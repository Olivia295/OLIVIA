"""The seven-state help-stage machine (SDD section 4.2).

``step`` is a pure function: it takes the session state before a user turn plus everything
known about that turn, and returns a new state with the stage the reply should be written
in. The input state is never mutated.

Precedence, highest first:

1. Crisis. While the crisis tracker reports ``in_crisis`` the stage is S_crisis, whatever
   else the turn carries. S_crisis is left only on the turn the tracker reports
   ``just_exited``, and only to S_explore (SDD 8.2).
2. Haven. Outside crisis, an effective battery at or below the haven threshold puts the
   session in S_haven from any stage.
3. Direct request. Asking outright for a method moves any other non-crisis stage to
   S_empower (COLBO-03), for every persona.
4. The per-stage rows of the transition table. In S_empower an arousal spike is judged
   first, then aversion, then the commands.

Aversion. A turn whose signals carry ``aversion`` ("表达反感", COLBO-04 "强烈排斥") in
S_empower goes back to S_explore, the same route as ``/unhelpful``. The machine only
routes: whether the rejected method also gets the ``UNHELPFUL`` soft decay (SDD 6.3) or
any other bandit feedback is decided by the caller, which sees ``Reason.EMPOWER_AVERSION``.

Implementation intention. A turn whose signals carry ``intent_confirmed`` ("实施意向确认
完成") in S_closing ends the session in S_ready, like :func:`close_session` but as a user
turn, so it is counted like any other turn. The caller writes the session summary and
ledger on that reason exactly as on ``Reason.CLOSING_TO_READY``.

Turn counts follow SDD 4.2: ``stage_turn_count`` counts turns in the current stage, the
turn that enters a stage is its first turn, and the gates read the count from before the
turn (so "stage_turn_count >= 2" means two turns have already been spent in the stage).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from enum import StrEnum

from olivia.core.models import HelpStage, PerceptionContext, PersonaSpectrum, SessionState
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


@dataclass(frozen=True)
class Transition:
    previous: HelpStage
    state: SessionState
    reason: Reason


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
    return Transition(previous=previous, state=new_state, reason=reason)


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

    if battery <= gates.haven_enter:
        return HelpStage.S_HAVEN, _enter_or_stay(previous, HelpStage.S_HAVEN, Reason.HAVEN_ENTER)
    if inp.signals.direct_request and previous is not HelpStage.S_EMPOWER:
        return HelpStage.S_EMPOWER, Reason.DIRECT_REQUEST

    if previous is HelpStage.S_READY:
        return HelpStage.S_EXPLORE, Reason.SESSION_START
    if previous is HelpStage.S_EMPOWER:
        return _from_empower(gates, state, inp)
    if previous is HelpStage.S_EXPLORE and (
        state.stage_turn_count >= gates.clarify_turns
        and inp.perception.arousal < gates.clarify_arousal_max
        and not locked
        and battery >= gates.clarify_battery
    ):
        return HelpStage.S_CLARIFY, Reason.EXPLORE_TO_CLARIFY
    if previous is HelpStage.S_CLARIFY and (
        state.stage_turn_count >= gates.auto_advance_turns
        and not locked
        and inp.persona is not PersonaSpectrum.SILENT_ANCHOR
        and battery >= gates.empower_battery
    ):
        return HelpStage.S_EMPOWER, Reason.CLARIFY_TO_EMPOWER
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
