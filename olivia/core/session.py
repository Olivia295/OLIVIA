"""The single conversation entry point (DEVELOPMENT_PLAN P4, roadmap P4-3).

``Session.open`` checks the age gate and loads everything a conversation needs; a lexicon,
template or hotline file that fails to load or verify raises there, so no conversation
starts without its safety data. ``Session.turn`` then runs one user turn through the whole
pipeline in a fixed order (SDD §8.1), and no caller can skip or reorder a step:

1. ``SafetyScreen.assess`` on the raw text.
2. ``RuleStub.perceive`` with that assessment. It is a pure function of the text and the
   assessment and touches no session state; it runs here so the tracker gets the turn's
   valence for its "L1 with worsening valence" escalation (PRD §9.1).
3. ``CrisisTracker.observe``, then ``SessionRedFlags.observe`` (profile
   ``clinical_history`` codes are active from the start).
4. ``fsm.step`` with the perception, the crisis status and the turn's signals.
5. Stage handling and language rendering; the engine's output gate checks every
   rendered text.
6. Bandit feedback on the card that was waiting for it.

Stage handling:

* ``S_crisis``: a CRISIS card at ``max(L2, this turn's level, the crisis entry level)``
  for the profile region (never the minors-only lines), rendered by ``render_crisis``.
  Using the entry level keeps an L3 card's emergency numbers on screen for every turn of
  an L3 crisis, not only the turns that repeat the plan (ruling 14).
* ``S_empower``: the solver's available set, minus actions that have no follow-along card
  (``12:tipp_cold_water`` is excluded from the deck pending G-0), is sampled by Thompson
  sampling in the dominant spectrum. A turn with no spectrum cue uses ``"02"`` (the
  low-mood spectrum, the commonest presentation) so the posterior still has one place
  to live. No candidate -> m0, a companionship reply from the S_explore templates; any
  red flag in the plan appends the referral card. While a shown card still waits for
  feedback, an S_empower turn re-sends the ``after_card`` prompt instead of sampling a
  new card. That covers a direct request straight after an S_explore stabilization
  card too: the rule stub reads each turn on its own, so "能给我一个练习试试吗" one turn
  after "喘不上气" looks calm and would otherwise open the full cognitive pool
  (red-team rt084-rt086 with the probe turn). The card then waits in S_empower.
* ``S_explore`` at or above ``arousal.thresholds.somatic_priority`` (COLBO-02, SOP 3):
  the solver's stabilization whitelist, sampled the same way, shown as a card framed by
  the S_explore reflection (reflect paragraph, then card intro, card and ``after_card``).
  Not while the pure-listening lock is on, not while an S_explore card still waits for
  feedback and not on a turn that gives feedback. No candidate -> the plain S_explore
  reply.
* Every other stage: ``compose(stage, slots)``.

Red-flag referral (SDD §8.4): the first non-crisis turn on which a flag is active (from
the profile, or newly detected in the text) appends ``render_referral`` for it, once per
flag per session. A plan in S_empower or a stabilization card also appends the referral
for its plan's flags every time, since the solver requires the card with every plan.

Reply kinds: CRISIS for the crisis path; CARD when an exercise card is shown; REFERRAL
when a referral card is shown and no exercise card; HAVEN for S_haven and for any reply
the gate or the taboo filter replaced with the haven line; NORMAL otherwise. INFO is
reserved for the Grade B/C information path, which no R1 stage uses yet.

Taboo topics (ruling 21) are a hard filter on every non-CRISIS, non-REFERRAL text: a hit
outside the mirrored user words recomposes the reply with fresh template draws, up to
``TABOO_RETRIES`` times, and otherwise replaces it with the haven line. Crisis and
referral wording is exempt so a taboo never hides safety resources.

Feedback (SDD §6.3) only ever lands on a card that was shown and is still waiting:
``/done`` -> HELPFUL; ``/not-now`` -> NOT_NOW and the action is shelved for the session;
``/unhelpful`` or aversion -> UNHELPFUL. For an S_empower card the state machine's
reason decides (an arousal retreat wins over a command on the same turn and gives no
feedback); for an S_explore stabilization card the next S_explore turn's command or
aversion does, unless that turn enters a crisis. Leaving the stage the card was shown
in ends the wait.

The session keeps no user text: ``inspect`` and ``snapshot`` hold ids, levels and numbers
only, and gate reasons are reduced to their check names.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from functools import lru_cache
from typing import Final
from uuid import uuid4

import yaml

from olivia.core.fsm.machine import Reason, Transition, TurnInput, step
from olivia.core.language.data import ContentKind, LanguageData, load_language_data, slots_of
from olivia.core.language.engine import LanguageEngine, Slots
from olivia.core.language.filters import apply_willow
from olivia.core.language.mirror import FALLBACK_MIRROR
from olivia.core.methods.bandit import Feedback, ThompsonSampler
from olivia.core.methods.solver import M0_ACTION_ID, SolverInput, allowed_actions, build_plan
from olivia.core.models import (
    CrisisLevel,
    HelpStage,
    PerceptionContext,
    PersonaProfile,
    SessionState,
)
from olivia.core.perception.lexicon import load_perception_lexicon
from olivia.core.perception.rule_stub import RuleStub, dominant_spectrum
from olivia.core.perception.signals import Command, TurnSignals
from olivia.core.resources.bundle import load_hotlines_bytes
from olivia.core.resources.card import CardMode, ResourceCard
from olivia.core.resources.resolver import resolve
from olivia.core.resources.store import ResourceStore, parse_store
from olivia.core.safety.crisis import RiskModel, SafetyScreen
from olivia.core.safety.lexicon import SafetyLexicons, load_safety_lexicons
from olivia.core.safety.red_flags import RedFlagDetector, SessionRedFlags
from olivia.core.safety.tracker import CrisisStatus, CrisisTracker
from olivia.core.taxonomy import Taxonomy

FALLBACK_SPECTRUM: Final = "02"
TABOO_RETRIES: Final = 5
_SOMATIC_KEY: Final = "arousal.thresholds.somatic_priority"
_EMPOWER_EXITS: Final = frozenset(
    {Reason.EMPOWER_TO_CLOSING, Reason.EMPOWER_UNHELPFUL, Reason.EMPOWER_AVERSION}
)
_COMMAND_FEEDBACK: Final = {
    Command.DONE: Feedback.HELPFUL,
    Command.NOT_NOW: Feedback.NOT_NOW,
    Command.UNHELPFUL: Feedback.UNHELPFUL,
}


class AgeGateRefusedError(Exception):
    """The profile is a minor's refusal record or does not confirm 18+ (NG-3)."""


class ReplyKind(StrEnum):
    CRISIS = "CRISIS"
    REFERRAL = "REFERRAL"
    HAVEN = "HAVEN"
    NORMAL = "NORMAL"
    CARD = "CARD"
    INFO = "INFO"


@dataclass(frozen=True)
class TurnResult:
    reply: str
    reply_kind: ReplyKind
    stage: HelpStage
    crisis_level: CrisisLevel
    in_crisis: bool
    resource_card: ResourceCard | None
    action_id: str | None
    """The newly shown exercise or m0 (``EMOTIONAL_HOLDING_PRESENCE``); None otherwise."""
    referral_flags: tuple[str, ...]
    """Red-flag codes whose referral card is in this reply."""
    inspect: dict[str, object]
    """The ``--inspect`` panel data (ruling 27): ids, levels and numbers, never user text."""


@dataclass(frozen=True)
class _Shared:
    """Stateless, read-only parts shared by every session over one taxonomy."""

    lexicons: SafetyLexicons
    screen: SafetyScreen
    stub: RuleStub
    detector: RedFlagDetector
    language: LanguageData
    store: ResourceStore
    hotline_source: str


@lru_cache(maxsize=4)
def _shared(tax: Taxonomy, today_iso: str) -> _Shared:
    lexicons = load_safety_lexicons(tax)
    bundle = load_hotlines_bytes(None, today=datetime.fromisoformat(today_iso).date())
    return _Shared(
        lexicons=lexicons,
        screen=SafetyScreen(tax, lexicons),
        stub=RuleStub(tax, load_perception_lexicon(tax)),
        detector=RedFlagDetector(tax, lexicons),
        language=load_language_data(tax),
        store=parse_store(yaml.safe_load(bundle.data)),
        hotline_source=bundle.source,
    )


@dataclass(frozen=True)
class _Pending:
    """A shown card waiting for feedback."""

    action_id: str
    spectrum: str
    stage: HelpStage


@dataclass
class _Rendered:
    reply: str
    kind: ReplyKind
    action_id: str | None = None
    referral_flags: tuple[str, ...] = ()
    card: ResourceCard | None = None
    candidates: tuple[str, ...] = ()
    chosen: str | None = None
    pending: _Pending | None = None


# A composer returns (text, mirror it used) or None when the output gate blocked it.
_Composer = Callable[[], tuple[str, str] | None]


class Session:
    """One conversation. Build it with :meth:`open`; call :meth:`turn` once per message."""

    def __init__(
        self,
        tax: Taxonomy,
        profile: PersonaProfile,
        shared: _Shared,
        screen: SafetyScreen,
        *,
        rng: random.Random,
        now: Callable[[], datetime],
    ) -> None:
        self._tax = tax
        self._profile = profile
        self._shared = shared
        self._screen = screen
        self._rng = rng
        self._now = now
        self._somatic = tax.threshold(_SOMATIC_KEY)
        self._tracker = CrisisTracker(tax, shared.lexicons)
        self._red_flags = SessionRedFlags(shared.detector, profile.clinical_history)
        self._sampler = ThompsonSampler(tax)
        self._engine = LanguageEngine(tax, rng=rng, data=shared.language)
        self._state = SessionState(session_id=uuid4())
        self._last_status: CrisisStatus | None = None
        self._pending: _Pending | None = None
        self._referred: set[str] = set()
        self._gate_notes: list[str] = []

    @classmethod
    def open(
        cls,
        tax: Taxonomy,
        profile: PersonaProfile,
        *,
        rng: random.Random,
        now: Callable[[], datetime],
        model: RiskModel | None = None,
    ) -> Session:
        """Start a session; ``now`` is the clock (timezone-aware) for cards and the bandit.

        Raises :class:`AgeGateRefusedError` for a refusal record or any profile that does
        not confirm 18+, and lets every data-loading error through.
        """
        if profile.is_age_gate_refusal or profile.age_confirmed_18_plus is not True:
            raise AgeGateRefusedError("no session without a confirmed adult profile")
        moment = now()
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise ValueError("now() must return a timezone-aware datetime")
        shared = _shared(tax, moment.date().isoformat())
        screen = shared.screen if model is None else SafetyScreen(tax, shared.lexicons, model)
        return cls(tax, profile, shared, screen, rng=rng, now=now)

    @property
    def state(self) -> SessionState:
        return replace(self._state, user_shelved_actions=list(self._state.user_shelved_actions))

    def turn(self, text: str) -> TurnResult:
        now = self._now()
        self._gate_notes = []

        assessment = self._screen.assess(text)
        perception, signals = self._shared.stub.perceive(text, assessment)
        status = self._tracker.observe(assessment, text, perception.valence)
        self._last_status = status
        flags = self._red_flags.observe(text)
        transition = step(
            self._tax,
            self._state,
            TurnInput(perception, status, signals, self._profile.persona_spectrum),
        )
        self._state = transition.state
        stage = transition.state.current_stage
        spectrum = dominant_spectrum(perception.distress_vector)
        # A command is not something to mirror back.
        mirror_text = "" if signals.command is not None else text
        pending = self._pending
        feedback = self._feedback_for(pending, transition, signals)

        if stage is HelpStage.S_CRISIS:
            rendered = self._crisis(status, now)
        elif stage is HelpStage.S_EMPOWER:
            # A card still waiting for feedback is not replaced: staying in S_empower, or
            # asking for a method right after an S_explore stabilization card, gets the
            # feedback prompt for the card already on screen.
            awaiting = (
                pending is not None
                and feedback is None
                and transition.previous is pending.stage
                and transition.reason in (Reason.STAY, Reason.DIRECT_REQUEST)
            )
            if pending is not None and awaiting:
                rendered = self._with_taboo_filter(self._after_card_prompt, stage)
                rendered.pending = replace(pending, stage=HelpStage.S_EMPOWER)
            else:
                rendered = self._offer(stage, perception, flags, spectrum, mirror_text, now)
        elif (
            stage is HelpStage.S_EXPLORE
            and perception.arousal >= self._somatic
            and not transition.state.pure_listening_locked
            and feedback is None
            and not (pending is not None and pending.stage is HelpStage.S_EXPLORE)
        ):
            rendered = self._offer(stage, perception, flags, spectrum, mirror_text, now)
        else:
            rendered = self._with_taboo_filter(
                lambda: self._compose(stage, perception, spectrum, mirror_text), stage
            )

        if stage is not HelpStage.S_CRISIS:
            self._append_referral(rendered, flags)

        if pending is not None and feedback is not None:
            self._apply_feedback(pending, feedback, now)
        # A card waits only while the session stays in the stage it was shown in.
        if rendered.pending is not None:
            self._pending = rendered.pending
        elif feedback is not None or (pending is not None and pending.stage is not stage):
            self._pending = None

        inspect: dict[str, object] = {
            "turn": transition.state.global_turn_count,
            "level": status.level.name,
            "assessed_level": assessment.level.name,
            "in_crisis": status.in_crisis,
            "cue_ids": list(assessment.cue_ids),
            "stage": stage.value,
            "previous_stage": transition.previous.value,
            "reason": transition.reason.value,
            "arousal": perception.arousal,
            "battery": transition.state.social_battery,
            "lock": transition.state.pure_listening_locked,
            "spectrum": spectrum,
            "red_flags": sorted(flags),
            "candidates": list(rendered.candidates),
            "chosen": rendered.chosen,
            "feedback": feedback.value if feedback is not None else None,
            "gate": list(dict.fromkeys(self._gate_notes)),
            "hotline_source": self._shared.hotline_source,
        }
        return TurnResult(
            reply=rendered.reply,
            reply_kind=rendered.kind,
            stage=stage,
            crisis_level=status.level,
            in_crisis=status.in_crisis,
            resource_card=rendered.card,
            action_id=rendered.action_id,
            referral_flags=rendered.referral_flags,
            inspect=inspect,
        )

    def snapshot(self) -> dict[str, object]:
        """JSON-safe session state for later persistence (P5); holds no user text."""
        state = self._state
        status = self._last_status
        pending = self._pending
        return {
            "session_id": str(state.session_id),
            "stage": state.current_stage.value,
            "global_turn_count": state.global_turn_count,
            "stage_turn_count": state.stage_turn_count,
            "pure_listening_locked": state.pure_listening_locked,
            "social_battery": state.social_battery,
            "current_risk_level": state.current_risk_level.name,
            "stage_entry_arousal": state.stage_entry_arousal,
            "user_shelved_actions": list(state.user_shelved_actions),
            "in_crisis": status.in_crisis if status is not None else False,
            "crisis_entry_level": (
                status.entry_level.name
                if status is not None and status.entry_level is not None
                else None
            ),
            "red_flags": sorted(self._red_flags.active),
            "referred_flags": sorted(self._referred),
            "pending_action": pending.action_id if pending else None,
            "pending_spectrum": pending.spectrum if pending else None,
            "pending_stage": pending.stage.value if pending else None,
            "bandit": self._sampler.to_dict(),
        }

    # -- stages ---------------------------------------------------------------------------

    def _crisis(self, status: CrisisStatus, now: datetime) -> _Rendered:
        level = max(CrisisLevel.L2, status.level, status.entry_level or CrisisLevel.L0)
        card = resolve(
            self._shared.store,
            self._profile.region,
            level,
            mode=CardMode.CRISIS,
            today=now.date(),
            is_minor=False,
        )
        self._engine.last_gate = None
        reply = self._engine.render_crisis(card, self._plain_slots())
        self._note_gate()
        return _Rendered(reply, ReplyKind.CRISIS, card=card)

    def _offer(
        self,
        stage: HelpStage,
        perception: PerceptionContext,
        flags: frozenset[str],
        spectrum: str | None,
        mirror_text: str,
        now: datetime,
    ) -> _Rendered:
        """Sample and show a card in S_empower, or a stabilization card in S_explore."""
        tax = self._tax
        allowed = allowed_actions(
            tax,
            SolverInput(
                stage=stage,
                arousal=perception.arousal,
                active_red_flags=flags,
                active_contraindications=frozenset(),
                situation_codes=frozenset(),
                shelved_actions=frozenset(self._state.user_shelved_actions),
            ),
        )
        deck = self._engine.data.cards.cards
        renderable = [aid for aid in allowed.candidates if aid in deck]
        chosen: str | None = None
        bucket = spectrum if spectrum is not None else FALLBACK_SPECTRUM
        if renderable:
            chosen = self._sampler.choose(renderable, bucket, perception.arousal, self._rng, now)
        plan = build_plan(tax, chosen, allowed)
        primary = plan.primary

        card_text: str | None = None
        if primary.method_id != M0_ACTION_ID:
            self._engine.last_gate = None
            card_text = self._engine.render_card(primary)
            if not self._note_gate():
                card_text = None

        if card_text is not None:
            title = self._engine.card_for(primary.method_id).title
            body = card_text
            if stage is HelpStage.S_EMPOWER:
                rendered = self._with_taboo_filter(
                    lambda: self._compose(
                        stage, perception, spectrum, mirror_text, card_title=title, card=body
                    ),
                    stage,
                )
            else:
                rendered = self._with_taboo_filter(
                    lambda: self._compose_stabilization(
                        perception, spectrum, mirror_text, title, body
                    ),
                    stage,
                )
            if rendered.kind is ReplyKind.NORMAL:
                rendered.kind = ReplyKind.CARD
                rendered.action_id = primary.method_id
                rendered.pending = _Pending(primary.method_id, bucket, stage)
        elif primary.method_id == M0_ACTION_ID:
            rendered = self._with_taboo_filter(
                lambda: self._compose(HelpStage.S_EXPLORE, perception, spectrum, mirror_text),
                HelpStage.S_EXPLORE,
            )
            if stage is HelpStage.S_EMPOWER:
                rendered.action_id = M0_ACTION_ID
        else:  # the gate blocked the card: show nothing rather than a broken card
            rendered = _Rendered(self._engine.gate.fallback, ReplyKind.HAVEN)

        rendered.candidates = allowed.candidates
        rendered.chosen = chosen
        # The solver requires the referral card with every S_empower plan and with every
        # stabilization card it backs; S_explore companionship relies on the new-flag rule.
        if stage is HelpStage.S_EMPOWER or rendered.action_id is not None:
            rendered.referral_flags = plan.referral_flags
        return rendered

    def _compose(
        self,
        stage: HelpStage,
        perception: PerceptionContext,
        spectrum: str | None,
        mirror_text: str,
        *,
        card_title: str = "",
        card: str = "",
    ) -> tuple[str, str] | None:
        """One composed reply and the mirror it used (taboo hits inside it are allowed)."""
        slots = self._engine.build_slots(
            user_name=self._profile.user_name,
            agent_name=self._profile.agent_name,
            user_text=mirror_text,
            emotion_id=perception.fine_grained_emotion,
            yearning_id=perception.deep_yearning,
            spectrum_id=spectrum,
            card_title=card_title,
        )
        if not slots.mirror:
            slots = replace(slots, mirror=FALLBACK_MIRROR)
        self._engine.last_gate = None
        text = self._engine.compose(stage, slots, card=card)
        if not self._note_gate():
            return None
        return text, slots.mirror

    def _compose_stabilization(
        self,
        perception: PerceptionContext,
        spectrum: str | None,
        mirror_text: str,
        title: str,
        card: str,
    ) -> tuple[str, str] | None:
        """S_explore reflection, then the card intro, the card and the feedback prompt.

        Both halves come out of ``compose`` and so passed the gate on their own; the
        S_empower ``bridge`` paragraph is dropped so the framing stays the S_explore one.
        """
        explore = self._compose(HelpStage.S_EXPLORE, perception, spectrum, mirror_text)
        if explore is None:
            return None
        empower = self._compose(
            HelpStage.S_EMPOWER, perception, spectrum, mirror_text, card_title=title, card=card
        )
        if empower is None:
            return None
        reflect = explore[0].split("\n\n", 1)[0]
        tail = empower[0].split("\n\n", 1)[1]
        return f"{reflect}\n\n{tail}", explore[1]

    def _after_card_prompt(self) -> tuple[str, str] | None:
        """The S_empower ``after_card`` line alone, for a card still waiting for feedback."""
        values = self._plain_slots().values()
        variants = self._engine.data.templates.after_card
        usable = [v for v in variants if all(values[s] for s in slots_of(v))]
        text = self._rng.choice(usable)
        for name, value in values.items():
            text = text.replace("{" + name + "}", value)
        text = apply_willow(text, ContentKind.NORMAL, self._engine.data.willow)
        result = self._engine.gate.check(text, kind=ContentKind.NORMAL, stage=HelpStage.S_EMPOWER)
        self._engine.last_gate = result
        if not self._note_gate():
            return None
        return text, ""

    def _with_taboo_filter(self, compose: _Composer, stage: HelpStage) -> _Rendered:
        kind = ReplyKind.HAVEN if stage is HelpStage.S_HAVEN else ReplyKind.NORMAL
        for _ in range(1 + TABOO_RETRIES):
            composed = compose()
            if composed is None:
                return _Rendered(self._engine.gate.fallback, ReplyKind.HAVEN)
            reply, mirrored = composed
            if not self._has_taboo(reply, mirrored):
                return _Rendered(reply, kind)
        self._gate_notes.append("taboo")
        return _Rendered(self._engine.gate.fallback, ReplyKind.HAVEN)

    def _append_referral(self, rendered: _Rendered, flags: frozenset[str]) -> None:
        """Add the referral card for the plan's flags and for flags not yet referred."""
        wanted = set(rendered.referral_flags) | (flags - self._referred)
        if not wanted:
            return
        codes = tuple(code for code in self._tax.red_flags() if code in wanted)
        self._engine.last_gate = None
        referral = self._engine.render_referral(codes)
        self._note_gate()
        self._referred |= wanted
        rendered.reply = f"{rendered.reply}\n\n{referral}"
        rendered.referral_flags = codes
        if rendered.kind is not ReplyKind.CARD:
            rendered.kind = ReplyKind.REFERRAL

    # -- feedback -------------------------------------------------------------------------

    @staticmethod
    def _feedback_for(
        pending: _Pending | None, transition: Transition, signals: TurnSignals
    ) -> Feedback | None:
        """The feedback this turn gives the waiting card, if any (no side effects)."""
        if pending is None or transition.previous is not pending.stage:
            return None
        if pending.stage is HelpStage.S_EMPOWER:
            reason = transition.reason
            if reason not in _EMPOWER_EXITS:
                return None
            if reason is Reason.EMPOWER_TO_CLOSING:
                return Feedback.NOT_NOW if signals.command is Command.NOT_NOW else Feedback.HELPFUL
            return Feedback.UNHELPFUL
        # The answer still counts when the same turn moves on (S_explore -> S_clarify),
        # but never inside a crisis.
        if transition.state.current_stage is HelpStage.S_CRISIS:
            return None
        if signals.command is not None:
            return _COMMAND_FEEDBACK[signals.command]
        return Feedback.UNHELPFUL if signals.aversion else None

    def _apply_feedback(self, pending: _Pending, feedback: Feedback, now: datetime) -> None:
        if feedback is Feedback.NOT_NOW:
            shelved = self._state.user_shelved_actions
            if pending.action_id not in shelved:
                self._state = replace(
                    self._state, user_shelved_actions=[*shelved, pending.action_id]
                )
        self._sampler.update(pending.action_id, pending.spectrum, feedback, now)

    # -- helpers --------------------------------------------------------------------------

    def _plain_slots(self) -> Slots:
        return Slots(user_name=self._profile.user_name, agent_name=self._profile.agent_name)

    def _has_taboo(self, reply: str, mirrored: str) -> bool:
        topics = [t.casefold() for t in self._profile.taboo_topics if t.strip()]
        if not topics:
            return False
        own = reply.replace(mirrored, "") if mirrored else reply
        folded = own.casefold()
        return any(topic in folded for topic in topics)

    def _note_gate(self) -> bool:
        """Record the last gate verdict's check names; True when it passed."""
        result = self._engine.last_gate
        if result is None or result.ok:
            return True
        self._gate_notes.extend(reason.split(":", 1)[0] for reason in result.reasons)
        return False
