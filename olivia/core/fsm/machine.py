"""The seven-state help-stage machine (SDD section 4.2).

``step`` is a pure function: it takes the session state before a user turn plus everything
known about that turn, and returns a new state with the stage the reply should be written
in. The input state is never mutated.

Precedence, highest first:

1. Crisis. While the crisis tracker reports ``in_crisis`` the stage is S_crisis, whatever
   else the turn carries. S_crisis is left only on the turn the tracker reports
   ``just_exited``, and only to S_explore (SDD 8.2).
2. Direct request. Asking outright for a method moves any other non-crisis stage to
   S_empower (COLBO-03), for every persona, S_haven included (owner decision 2026-10-24),
   and also at L1 (ruling 5), where ``Transition.stabilization_only`` limits the card.
3. Haven. Outside crisis, an effective battery at or below the haven threshold puts the
   session in S_haven from any stage, except that S_empower re-enters the haven only on a
   new battery reading: a direct request out of the haven is not undone on the next turn
   by the stored low battery. Once S_empower is left the ordinary way, the stored battery
   applies again.
4. The per-stage rows of the transition table. In S_empower an arousal spike is judged
   first, then aversion, then the commands. In S_clarify an arousal at or above the
   somatic line retreats to S_explore (``CLARIFY_AROUSAL_RETREAT``) before any advance.

L1 guard (PRD 9.1, taxonomy L1, SDD 8.2: L1 stays in S_explore). On a turn whose
effective level is L1 the turn-count advances do not fire: no ``EXPLORE_TO_CLARIFY`` and
no ``CLARIFY_TO_EMPOWER``. A direct request still does. ``CLARIFY_CORE_BELIEF`` is not
held: the session sets ``core_belief_confirmed`` only on a turn the rule screen found
below L1, so an L1 level there can only be a risk model's score band (the same rule as
the D3 answer and the schema mirror).

Stabilization flags on the transition, for the session to act on:

* ``stabilization_only``: the turn's effective level is L1 (outside crisis), so any card
  shown on it must come from the stabilization whitelist (ruling 5), whatever the stage.
* ``offer_stabilization``: the turn retreated for safety (``CLARIFY_AROUSAL_RETREAT``,
  ``EMPOWER_AROUSAL_RETREAT``, ``EMPOWER_AVERSION``); the reply should carry stabilization
  presence, a stabilization card when the solver allows one (COLBO-04 "激活稳定化在场通道").

Aversion. A turn whose signals carry ``aversion`` ("表达反感", COLBO-04 "强烈排斥") in
S_empower goes back to S_explore, the same route as ``/unhelpful``. The machine only
routes: whether the rejected method also gets the ``UNHELPFUL`` soft decay (SDD 6.3) or
any other bandit feedback is decided by the caller, which sees ``Reason.EMPOWER_AVERSION``.

Implementation intention. A turn whose signals carry ``intent_confirmed`` ("实施意向确认
完成") in S_closing ends the session in S_ready, like :func:`close_session` but as a user
turn, so it is counted like any other turn. The caller writes the session summary and
ledger on that reason exactly as on ``Reason.CLOSING_TO_READY``.

Core belief. A turn whose signals carry ``core_belief_confirmed`` (the session's reading
of a yes to the schema mirror question, model mode only, decision D4) in S_clarify moves
to S_empower without waiting for the auto-advance count (PRD C_2 "核心信念识别"); the
lock, persona and battery gates are the same.

Turn counts follow SDD 4.2: ``stage_turn_count`` counts turns in the current stage, the
turn that enters a stage is its first turn, and the gates read the count from before the
turn (so "stage_turn_count >= 2" means two turns have already been spent in the stage).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from enum import StrEnum

from olivia.core.models import (
    CrisisLevel,
    HelpStage,
    PerceptionContext,
    PersonaSpectrum,
    SessionState,
)
from olivia.core.perception.signals import Command, TurnSignals
from olivia.core.safety.tracker import CrisisStatus
from olivia.core.taxonomy import Taxonomy, TaxonomyError

# Absolute tolerance for the ΔArousal boundary, so 0.25 reached through float subtraction
# (for example 0.85 - 0.60) still counts as ">= 0.25".
_DELTA_TOLERANCE = 1e-9


@dataclass(frozen=True)
class TurnInput:
    perception: PerceptionContext
    crisis: CrisisStatus
    signals: TurnSignals
    persona: PersonaSpectrum


class Reason(StrEnum):
    """Why a turn landed where it did: one member per SDD 4.2 trigger, plus STAY."""

    STAY = "STAY"
    SESSION_START = "SESSION_START"
    """S_ready -> S_explore: the first turn of a session (SDD 4.2, q0)."""
    CRISIS_ENTER = "CRISIS_ENTER"
    """Any non-crisis stage -> S_crisis: the tracker reports an active crisis."""
    HAVEN_ENTER = "HAVEN_ENTER"
    """Any non-crisis stage -> S_haven: crisis screen passed and battery <= haven_enter."""
    DIRECT_REQUEST = "DIRECT_REQUEST"
    """Any non-crisis stage -> S_empower: the user asks outright for a method (COLBO-03)."""
    EXPLORE_TO_CLARIFY = "EXPLORE_TO_CLARIFY"
    """S_explore -> S_clarify: enough turns, arousal below the somatic line, no lock, battery."""
    CLARIFY_TO_EMPOWER = "CLARIFY_TO_EMPOWER"
    """S_clarify -> S_empower: auto-advance after N clarify turns, no lock, not SILENT_ANCHOR."""
    CLARIFY_CORE_BELIEF = "CLARIFY_CORE_BELIEF"
    """S_clarify -> S_empower: the user affirmed the schema mirror question (PRD C_2
    "核心信念识别", decision D4), with the auto-advance's lock, persona and battery gates."""
    CLARIFY_AROUSAL_RETREAT = "CLARIFY_AROUSAL_RETREAT"
    """S_clarify -> S_explore: arousal at or above the somatic line, so the session can offer
    the stabilization channel of S_explore (COLBO-02) instead of reflective work."""
    EMPOWER_AROUSAL_RETREAT = "EMPOWER_AROUSAL_RETREAT"
    """S_empower -> S_explore: ΔArousal or absolute arousal spike (COLBO-04)."""
    EMPOWER_AVERSION = "EMPOWER_AVERSION"
    """S_empower -> S_explore: the user expresses aversion to the practice (SDD 4.2, COLBO-04).

    Routed like ``/unhelpful``; the caller decides any bandit feedback for the method."""
    EMPOWER_UNHELPFUL = "EMPOWER_UNHELPFUL"
    """S_empower -> S_explore: ``/unhelpful``; the caller applies the soft decay (SDD 6.3)."""
    EMPOWER_TO_CLOSING = "EMPOWER_TO_CLOSING"
    """S_empower -> S_closing: ``/done`` or ``/not-now``."""
    HAVEN_EXIT = "HAVEN_EXIT"
    """S_haven -> S_explore: battery recovered to haven_exit or above."""
    CLOSING_INTENT_CONFIRMED = "CLOSING_INTENT_CONFIRMED"
    """S_closing -> S_ready: the user confirms the implementation intention (SDD 4.2)."""
    CLOSING_TO_READY = "CLOSING_TO_READY"
    """S_closing -> S_ready: the session closes (see :func:`close_session`)."""
    CRISIS_EXIT = "CRISIS_EXIT"
    """S_crisis -> S_explore: confirmed safety plus the safe-turn streak (SDD 8.2)."""


# Safety retreats after which the reply should carry stabilization presence (COLBO-04).
_STABILIZING_RETREATS = frozenset(
    {Reason.CLARIFY_AROUSAL_RETREAT, Reason.EMPOWER_AROUSAL_RETREAT, Reason.EMPOWER_AVERSION}
)


@dataclass(frozen=True)
class Transition:
    previous: HelpStage
    state: SessionState
    reason: Reason
    stabilization_only: bool = False
    """An L1 turn outside crisis: a card shown on it comes from the stabilization whitelist."""
    offer_stabilization: bool = False
    """A safety retreat: the reply should carry stabilization presence (a card if allowed)."""


@dataclass(frozen=True)
class _Gates:
    haven_enter: float
    haven_exit: float
    clarify_battery: float
    empower_battery: float
    clarify_arousal_max: float
    retreat_arousal: float
    retreat_delta: float
    clarify_turns: int
    auto_advance_turns: int

    @classmethod
    def from_taxonomy(cls, tax: Taxonomy) -> _Gates:
        return cls(
            haven_enter=tax.threshold("battery.thresholds.haven_enter"),
            haven_exit=tax.threshold("battery.thresholds.haven_exit"),
            clarify_battery=tax.threshold("battery.thresholds.clarify_min"),
            empower_battery=tax.threshold("battery.thresholds.empower_min"),
            clarify_arousal_max=tax.threshold("arousal.thresholds.somatic_priority"),
            retreat_arousal=tax.threshold("arousal.thresholds.cognitive_block"),
            retreat_delta=tax.threshold("arousal.thresholds.empower_retreat_delta"),
            clarify_turns=_whole(tax, "colbo.fsm.clarify_min_stage_turns"),
            auto_advance_turns=_whole(tax, "colbo.fsm.empower_auto_advance_stage_turns"),
        )


def _whole(tax: Taxonomy, path: str) -> int:
    value = tax.threshold(path)
    if not value.is_integer() or value < 1:
        raise TaxonomyError(f"taxonomy threshold {path} must be a positive whole number")
    return int(value)


def step(tax: Taxonomy, state: SessionState, inp: TurnInput) -> Transition:
    """Advance ``state`` by one user turn; returns a new state and never mutates ``state``."""
    gates = _Gates.from_taxonomy(tax)
    signals = inp.signals
    battery = state.social_battery if signals.battery is None else signals.battery
    locked = state.pure_listening_locked
    if signals.listening_lock_on:
        locked = True
    elif signals.listening_lock_off or signals.direct_request:
        # PRD Q-4 releases the lock when the user asks for advice, which a direct request is.
        locked = False

    previous = state.current_stage
    stage, reason = _route(gates, state, inp, battery, locked)
    changed = stage is not previous
    l1_turn = inp.crisis.level is CrisisLevel.L1 and not inp.crisis.in_crisis
    new_state = replace(
        state,
        current_stage=stage,
        global_turn_count=state.global_turn_count + 1,
        stage_turn_count=1 if changed else state.stage_turn_count + 1,
        pure_listening_locked=locked,
        social_battery=battery,
        current_risk_level=inp.crisis.level,
        consecutive_l1_count=inp.crisis.consecutive_l1_count,
        stage_entry_arousal=inp.perception.arousal if changed else state.stage_entry_arousal,
        user_shelved_actions=list(state.user_shelved_actions),
    )
    return Transition(
        previous=previous,
        state=new_state,
        reason=reason,
        stabilization_only=l1_turn,
        offer_stabilization=reason in _STABILIZING_RETREATS,
    )


def close_session(state: SessionState) -> Transition:
    """End a session in S_closing (the "会话自然关闭" exit) and return to S_ready.

    This is a session event rather than a user turn, so no turn is counted. Any other stage
    is returned unchanged with ``Reason.STAY``.
    """
    previous = state.current_stage
    if previous is not HelpStage.S_CLOSING:
        return Transition(
            previous,
            replace(state, user_shelved_actions=list(state.user_shelved_actions)),
            Reason.STAY,
        )
    new_state = replace(
        state,
        current_stage=HelpStage.S_READY,
        stage_turn_count=0,
        stage_entry_arousal=None,
        user_shelved_actions=list(state.user_shelved_actions),
    )
    return Transition(previous=previous, state=new_state, reason=Reason.CLOSING_TO_READY)


def _route(
    gates: _Gates, state: SessionState, inp: TurnInput, battery: float, locked: bool
) -> tuple[HelpStage, Reason]:
    previous = state.current_stage
    crisis = inp.crisis

    if crisis.in_crisis:
        return HelpStage.S_CRISIS, _enter_or_stay(previous, HelpStage.S_CRISIS, Reason.CRISIS_ENTER)
    if previous is HelpStage.S_CRISIS:
        # The tracker is the only authority on leaving crisis; anything else stays put.
        if crisis.just_exited:
            return HelpStage.S_EXPLORE, Reason.CRISIS_EXIT
        return HelpStage.S_CRISIS, Reason.STAY

    if inp.signals.direct_request and previous is not HelpStage.S_EMPOWER:
        return HelpStage.S_EMPOWER, Reason.DIRECT_REQUEST
    fresh_reading = inp.signals.battery is not None
    if battery <= gates.haven_enter and (previous is not HelpStage.S_EMPOWER or fresh_reading):
        return HelpStage.S_HAVEN, _enter_or_stay(previous, HelpStage.S_HAVEN, Reason.HAVEN_ENTER)

    if previous is HelpStage.S_READY:
        return HelpStage.S_EXPLORE, Reason.SESSION_START
    if previous is HelpStage.S_EMPOWER:
        return _from_empower(gates, state, inp)
    if previous is HelpStage.S_CLARIFY and inp.perception.arousal >= gates.clarify_arousal_max:
        return HelpStage.S_EXPLORE, Reason.CLARIFY_AROUSAL_RETREAT
    # L1 stays in S_explore: no auto-advance on an L1 turn (a direct request still works).
    held = crisis.level is CrisisLevel.L1
    if previous is HelpStage.S_EXPLORE and (
        not held
        and state.stage_turn_count >= gates.clarify_turns
        and inp.perception.arousal < gates.clarify_arousal_max
        and not locked
        and battery >= gates.clarify_battery
    ):
        return HelpStage.S_CLARIFY, Reason.EXPLORE_TO_CLARIFY
    confirmed = inp.signals.core_belief_confirmed
    if previous is HelpStage.S_CLARIFY and (
        (confirmed or (not held and state.stage_turn_count >= gates.auto_advance_turns))
        and not locked
        and inp.persona is not PersonaSpectrum.SILENT_ANCHOR
        and battery >= gates.empower_battery
    ):
        reason = Reason.CLARIFY_CORE_BELIEF if confirmed else Reason.CLARIFY_TO_EMPOWER
        return HelpStage.S_EMPOWER, reason
    if previous is HelpStage.S_HAVEN and battery >= gates.haven_exit:
        return HelpStage.S_EXPLORE, Reason.HAVEN_EXIT
    if previous is HelpStage.S_CLOSING and inp.signals.intent_confirmed:
        return HelpStage.S_READY, Reason.CLOSING_INTENT_CONFIRMED
    return previous, Reason.STAY


def _from_empower(gates: _Gates, state: SessionState, inp: TurnInput) -> tuple[HelpStage, Reason]:
    arousal = inp.perception.arousal
    baseline = state.stage_entry_arousal
    # Safety first: an arousal spike wins over any command sent on the same turn.
    spiked = arousal >= gates.retreat_arousal or (
        baseline is not None and _at_least(arousal - baseline, gates.retreat_delta)
    )
    if spiked:
        return HelpStage.S_EXPLORE, Reason.EMPOWER_AROUSAL_RETREAT
    if inp.signals.aversion:
        return HelpStage.S_EXPLORE, Reason.EMPOWER_AVERSION
    command = inp.signals.command
    if command is Command.UNHELPFUL:
        return HelpStage.S_EXPLORE, Reason.EMPOWER_UNHELPFUL
    if command is Command.DONE or command is Command.NOT_NOW:
        return HelpStage.S_CLOSING, Reason.EMPOWER_TO_CLOSING
    return HelpStage.S_EMPOWER, Reason.STAY


def _enter_or_stay(previous: HelpStage, target: HelpStage, reason: Reason) -> Reason:
    return Reason.STAY if previous is target else reason


def _at_least(value: float, bound: float) -> bool:
    return value >= bound or math.isclose(value, bound, rel_tol=0.0, abs_tol=_DELTA_TOLERANCE)
