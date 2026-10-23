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
   ``clinical_history`` codes are active from the start). In model mode the student's
   perception heads then refine the rule context (``perception/model_heads.py``, roadmap
   C1); the tracker has already read the rule valence, so crisis handling is the same in
   both modes.
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

Grade B/C information cards (PRD §8.1, roadmap next-phase A4), never on a crisis turn
(the tracker's crisis or an L1-L3 screen), with feedback for a waiting card, or with a
direct request; the solver's ``info_cards`` applies the red-flag closure, bans, arousal
gate and stage rules, so a red-flag user only ever gets the referral card:

* asked: a Grade B/C therapy named in a question (``TurnSignals.therapy_question``) gets
  ``render_info_reply(lens=False)`` as the whole reply, Grade C in any ordinary stage and
  Grade B in S_clarify only. A card waiting for feedback keeps waiting.
* lens: once per session, an S_clarify turn without the listening lock appends one Grade
  B explainer (``render_info_reply(lens=True)``) to the S_clarify reply, drawn from the
  ``clarify_lenses`` entry of the most recent spectrum the conversation showed.

A card whose text names one of the profile's taboo topics, or that the gate blocks, is
not shown and the turn is handled as if nothing had been asked.

Reply kinds: CRISIS for the crisis path; CARD when an exercise card is shown; REFERRAL
when a referral card is shown and no exercise card; INFO when a Grade B/C information
card is shown; HAVEN for S_haven and for any reply the gate or the taboo filter replaced
with the haven line; NORMAL otherwise.

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

Natural-language follow-ups (roadmap R-7b), read before the state machine runs and
never on a crisis turn (the tracker's crisis or an L2/L3 screen) or an L1 screen:

* While a card waits in the current stage, a feedback phrase ("做完了", "今天先不做了",
  "这个不适合我") is passed to the state machine as the command it stands for, so it has
  exactly the command's effects; a slash command wins. Aversion keeps its own route.
* An unclear reply ("唉", "再说吧") to a waiting card that is still waiting after the
  turn gets one clarification question (``followups.clarify_feedback``). On the next
  turn only, a yes records NOT_NOW as if ``/not-now`` had been sent; a no, or anything
  else, is handled as it would be without the question (the card keeps waiting).
* A kit recall ("锦囊里那个再给我看看") outside a crisis acts as a direct request and
  re-offers the most recently shelved action the solver allows now, which leaves the
  kit until it is shelved again; with an empty kit the reply is ``followups.kit_empty``
  (not in S_haven). The kit is the session's ``user_shelved_actions``; keeping it across
  sessions waits for P5.
* In S_closing a whole-message yes ("好", "可以") confirms the implementation intention
  like an ``intent_confirmed`` phrase; a no ("不用了") gets ``followups.closing_declined``
  and the session stays in S_closing.

Anti-dependence prompts (next-phase B7, decision D5; ``chang/wellbeing.py``): the 45-minute
break reminder, the once-per-session late-night line and real-world support guidance go
only on an ordinary composed reply on a calm turn (no crisis, no L1-L3 screen), never on a
card, information, referral, safety-question or follow-up reply. ``inspect["reminder"]`` is
``none``, ``break`` or ``late_night``; ``inspect["real_support_share"]`` is the share of
this session's replies that carried real-support guidance (PRD §11.1).

``inspect["feedback_source"]`` says where recorded feedback came from: ``command``,
``phrase`` (a feedback or aversion phrase) or ``confirmed`` (a yes to the question).

Direct question about intent (decision D3, step A7): a turn whose screen reports an
``ASK_INTENT`` cue (a euphemistic request for a way to end a life: 想走了 + 不痛, end it
without pain) while the turn stays below L2 and outside a crisis gets one gentle, direct
question about suicidal intent plus the region's L2 resource lines (SAFETY_CHECK), and
nothing else: no card, referral, method or advice, and the request is not passed on as a
direct request. The next turn is read as the answer (``safety/intent_check.py``): a clear
no returns to the ordinary flow and sets the in-session gentle-care flag (``snapshot``);
a yes, an unclear answer, no answer or a new crisis cue is read as L2 before the tracker
runs, so the crisis flow follows. A turn that screens L2/L3 itself never waits for the
question. ``inspect["safety_check"]`` is ``asked``, ``affirmed``, ``denied``, ``unclear``
or None.

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

from olivia.core.chang.wellbeing import Wellbeing
from olivia.core.fsm.machine import Reason, Transition, TurnInput, step
from olivia.core.language.data import ContentKind, LanguageData, load_language_data, slots_of
from olivia.core.language.engine import LanguageEngine, Slots
from olivia.core.language.filters import apply_willow
from olivia.core.language.mirror import FALLBACK_MIRROR
from olivia.core.methods.bandit import Feedback, ThompsonSampler
from olivia.core.methods.solver import (
    M0_ACTION_ID,
    AllowedSet,
    SolverInput,
    allowed_actions,
    build_plan,
    info_cards,
)
from olivia.core.models import (
    CrisisLevel,
    HelpStage,
    PerceptionContext,
    PersonaProfile,
    SessionState,
)
from olivia.core.perception.lexicon import load_perception_lexicon
from olivia.core.perception.model_heads import ModelHeads
from olivia.core.perception.rule_stub import RuleStub, dominant_spectrum
from olivia.core.perception.signals import Answer, Command, TurnSignals
from olivia.core.perception.student import RiskChoice, choose_risk_model
from olivia.core.resources.bundle import load_hotlines_bytes
from olivia.core.resources.card import CardMode, ResourceCard
from olivia.core.resources.resolver import resolve
from olivia.core.resources.store import ResourceStore, parse_store
from olivia.core.safety.crisis import CrisisAssessment, RiskModel, SafetyScreen
from olivia.core.safety.intent_check import IntentAnswer, read_intent_answer
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


_NO_FOLLOWUP_STAGES: Final = frozenset({HelpStage.S_CRISIS, HelpStage.S_HAVEN})
# Cue id added to an answer turn the session reads as L2 after the D3 question.
SAFETY_CHECK_CUE: Final = "SAFETY_CHECK_L2"


class FeedbackSource(StrEnum):
    """Where this turn's feedback came from (``inspect["feedback_source"]``)."""

    COMMAND = "command"
    """A slash command."""
    PHRASE = "phrase"
    """A natural-language feedback or aversion phrase."""
    CONFIRMED = "confirmed"
    """A yes to the clarification question asked on the turn before."""


class AgeGateRefusedError(Exception):
    """The profile is a minor's refusal record or does not confirm 18+ (NG-3)."""


class ReplyKind(StrEnum):
    CRISIS = "CRISIS"
    REFERRAL = "REFERRAL"
    HAVEN = "HAVEN"
    NORMAL = "NORMAL"
    CARD = "CARD"
    INFO = "INFO"
    SAFETY_CHECK = "SAFETY_CHECK"
    """The direct question about intent with the region's resource lines (decision D3)."""


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
    hotline_reason: str | None
    """Why the built-in hotline data was used instead of an override (``None``: override)."""


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
        hotline_reason=bundle.reason,
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
    info_id: str | None = None


@dataclass(frozen=True)
class _FollowUp:
    """What the session made of a turn's follow-up signals before the state machine ran."""

    signals: TurnSignals
    """The signals the state machine sees: an accepted phrase or answer becomes the
    command (or ``intent_confirmed`` / ``direct_request``) it stands for."""
    source: FeedbackSource | None = None
    """The source if the waiting card gets feedback on this turn."""
    clarify: bool = False
    """An unclear reply to the waiting card: ask once whether to shelve it."""
    recall: bool = False
    """Show a shelved card again."""
    kit_empty: bool = False
    """A recall request with nothing in the kit."""
    closing_declined: bool = False
    """A no to the S_closing question."""


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
        risk: RiskChoice | None = None,
        started_at: datetime | None = None,
    ) -> None:
        self._tax = tax
        self._profile = profile
        self._shared = shared
        self._screen = screen
        self._risk = risk if risk is not None else choose_risk_model()
        self._heads = None if self._risk.student is None else ModelHeads(tax, self._risk.student)
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
        self._clarifying = False
        # The last turn asked the D3 question, so the next turn is its answer.
        self._asking = False
        # The user said no to the D3 question this session (kept across sessions by A3/B3).
        self._gentle_care = False
        self._referred: set[str] = set()
        self._gate_notes: list[str] = []
        self._last_spectrum: str | None = None
        self._lens_shown = False
        start = started_at if started_at is not None else now()
        zone = profile.region.timezone if profile.region is not None else None
        self._wellbeing = Wellbeing(tax, zone, start)

    @classmethod
    def open(
        cls,
        tax: Taxonomy,
        profile: PersonaProfile,
        *,
        rng: random.Random,
        now: Callable[[], datetime],
        model: RiskModel | None = None,
        student: bool = False,
    ) -> Session:
        """Start a session; ``now`` is the clock (timezone-aware) for cards and the bandit.

        The crisis screen's Stage 2 uses ``model`` when given; ``student=True`` uses the
        packaged perception student (``perception/student.py``); otherwise, or when the
        student fails to load, the rule model runs alone. An injected model or the student
        can only raise the rule level and stays capped at L2. ``inspect`` reports which one
        ran. With the student on, its other heads also refine perception
        (``perception/model_heads.py``); an injected model leaves perception to the rules.

        Raises :class:`AgeGateRefusedError` for a refusal record or any profile that does
        not confirm 18+, and lets every data-loading error through.
        """
        if profile.is_age_gate_refusal or profile.age_confirmed_18_plus is not True:
            raise AgeGateRefusedError("no session without a confirmed adult profile")
        moment = now()
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise ValueError("now() must return a timezone-aware datetime")
        shared = _shared(tax, moment.date().isoformat())
        risk = choose_risk_model(model, student=student)
        screen = (
            shared.screen
            if risk.model is None
            else SafetyScreen(tax, shared.lexicons, risk.model, model_plan_evidence=False)
        )
        return cls(tax, profile, shared, screen, rng=rng, now=now, risk=risk, started_at=moment)

    @property
    def state(self) -> SessionState:
        return replace(self._state, user_shelved_actions=list(self._state.user_shelved_actions))

    def turn(self, text: str) -> TurnResult:
        now = self._now()
        self._gate_notes = []

        assessment = self._screen.assess(text)
        assessment, answer = self._answer_safety_check(text, assessment)
        model_level, model_score = self._risk.take_turn()
        perception, signals = self._shared.stub.perceive(text, assessment)
        status = self._tracker.observe(assessment, text, perception.valence)
        self._last_status = status
        if self._heads is not None:
            perception = self._heads.refine(text, perception)
        flags = self._red_flags.observe(text)
        ask = answer is None and assessment.asks_intent and not status.in_crisis
        # The request on an ask turn is not a request for an exercise, and the answer to the
        # question is not an answer to any other question.
        if ask:
            signals = replace(signals, direct_request=False, answer=None)
        elif answer is not None:
            signals = replace(signals, answer=None)
        self._asking = ask
        pending = self._pending
        follow = self._follow_up(signals, status, assessment.level, pending)
        signals = follow.signals
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
        feedback = self._feedback_for(pending, transition, signals)
        if spectrum is not None:
            self._last_spectrum = spectrum
        info = self._info_choice(
            stage, perception, flags, signals, status, assessment.level, feedback, transition
        )
        # The waiting card is still on screen, in the stage it was shown in.
        still_waiting = (
            pending is not None
            and feedback is None
            and transition.previous is pending.stage
            and stage is pending.stage
        )

        templates = self._engine.data.templates
        # Only the plain composed reply of the current stage carries a wellbeing prompt.
        ordinary = False
        if stage is HelpStage.S_CRISIS:
            rendered = self._crisis(status, now)
        elif ask:
            rendered = self._safety_check(stage, now)
        elif follow.clarify and still_waiting:
            rendered = self._followup(templates.clarify_feedback, stage)
            self._clarifying = True
        elif follow.kit_empty and stage not in _NO_FOLLOWUP_STAGES:
            rendered = self._followup(templates.kit_empty, stage)
        elif follow.closing_declined and stage is HelpStage.S_CLOSING:
            rendered = self._followup(templates.closing_declined, stage)
        elif follow.recall and stage is HelpStage.S_EMPOWER:
            rendered = self._offer(
                stage, perception, flags, spectrum, mirror_text, now, recall=True
            )
        elif info is not None:
            rendered = self._info(info, stage, perception, spectrum, mirror_text)
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
            ordinary = True

        calm = not status.in_crisis and assessment.level < CrisisLevel.L1
        plain = rendered.kind is ReplyKind.NORMAL or stage is HelpStage.S_HAVEN
        prompted = self._wellbeing.prompt(
            rendered.reply,
            now=now,
            stage=stage,
            eligible=ordinary and calm and plain,
            locked=transition.state.pure_listening_locked,
            templates=templates,
            render=lambda variant: self._wellbeing_line(variant, stage),
        )
        rendered.reply = prompted.reply

        if stage is not HelpStage.S_CRISIS and not ask:
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
            "valence": perception.valence,
            "emotion": perception.fine_grained_emotion,
            "intent": perception.empathy_intent,
            "stance": perception.communication_stance,
            "readiness": perception.readiness_to_change,
            "battery": transition.state.social_battery,
            "lock": transition.state.pure_listening_locked,
            "spectrum": spectrum,
            "red_flags": sorted(flags),
            "candidates": list(rendered.candidates),
            "chosen": rendered.chosen,
            "info": rendered.info_id,
            "feedback": feedback.value if feedback is not None else None,
            "feedback_source": (
                follow.source.value if feedback is not None and follow.source is not None else None
            ),
            "gate": list(dict.fromkeys(self._gate_notes)),
            "hotline_source": self._shared.hotline_source,
            "hotline_reason": self._shared.hotline_reason,
            "risk_model": self._risk.label,
            "risk_model_reason": self._risk.reason,
            "model_level": model_level,
            "model_score": model_score,
            "safety_check": "asked" if ask else (answer.value if answer is not None else None),
            "reminder": prompted.reminder.value,
            "real_support_share": round(self._wellbeing.real_support_share, 4),
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
            "awaiting_clarification": self._clarifying,
            "awaiting_safety_check": self._asking,
            "gentle_care": self._gentle_care,
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

    def _safety_check(self, stage: HelpStage, now: datetime) -> _Rendered:
        """The D3 question with the region's L2 resource lines (never the minors' lines)."""
        card = resolve(
            self._shared.store,
            self._profile.region,
            CrisisLevel.L2,
            mode=CardMode.CRISIS,
            today=now.date(),
            is_minor=False,
        )
        self._engine.last_gate = None
        reply = self._engine.render_safety_check(card, self._plain_slots(), stage)
        self._note_gate()
        return _Rendered(reply, ReplyKind.SAFETY_CHECK, card=card)

    def _answer_safety_check(
        self, text: str, assessment: CrisisAssessment
    ) -> tuple[CrisisAssessment, IntentAnswer | None]:
        """Read this turn as the answer to the D3 question asked on the turn before.

        Anything but a clear no is read as L2 (the screen's own L2/L3 is kept as it is);
        a no sets the gentle-care flag. Whether a no carries a new crisis cue is the rule
        screen's call: an injected model's score band alone (L1) does not void it, while
        its L2 still enters crisis through ``assessment``. Returns the assessment
        unchanged and None when no question was asked.
        """
        if not self._asking:
            return assessment, None
        shared = self._shared.screen
        rules = assessment if self._screen is shared else shared.assess(text)
        answer = read_intent_answer(self._shared.lexicons.intent_answers, text, rules)
        if answer is IntentAnswer.DENIED:
            self._gentle_care = True
            return assessment, answer
        if assessment.level >= CrisisLevel.L2:
            return assessment, answer
        l2 = replace(
            assessment,
            level=CrisisLevel.L2,
            score=max(assessment.score, self._tax.threshold("risk.lexicon_scores.L2")),
            cue_ids=(*assessment.cue_ids, SAFETY_CHECK_CUE),
        )
        return l2, answer

    def _offer(
        self,
        stage: HelpStage,
        perception: PerceptionContext,
        flags: frozenset[str],
        spectrum: str | None,
        mirror_text: str,
        now: datetime,
        *,
        recall: bool = False,
    ) -> _Rendered:
        """Sample and show a card in S_empower, or a stabilization card in S_explore.

        With ``recall``, the most recently shelved action that the solver allows right now
        is shown instead of a sampled one, and it leaves the kit (``/not-now`` puts it
        back). When no shelved action is allowed now, a card is sampled as usual.
        """
        tax = self._tax
        shelved = self._state.user_shelved_actions
        deck = self._engine.data.cards.cards
        chosen: str | None = None
        bucket = spectrum if spectrum is not None else FALLBACK_SPECTRUM
        allowed = self._allowed(stage, perception, flags, frozenset(shelved))
        if recall:
            unmasked = self._allowed(stage, perception, flags, frozenset())
            kit = [a for a in reversed(shelved) if a in unmasked.candidates and a in deck]
            if kit:
                chosen = kit[0]
                remaining = [a for a in shelved if a != chosen]
                self._state = replace(self._state, user_shelved_actions=remaining)
                allowed = self._allowed(stage, perception, flags, frozenset(remaining))
        renderable = [aid for aid in allowed.candidates if aid in deck]
        if chosen is None and renderable:
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
                        stage,
                        perception,
                        spectrum,
                        mirror_text,
                        card_title=title,
                        card=body,
                        light=allowed.battery_gated,
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
        if chosen is not None and chosen in shelved and rendered.action_id != chosen:
            # A recalled card that could not be shown stays in the kit.
            self._state = replace(self._state, user_shelved_actions=list(shelved))

        rendered.candidates = allowed.candidates
        rendered.chosen = chosen
        # The solver requires the referral card with every S_empower plan and with every
        # stabilization card it backs; S_explore companionship relies on the new-flag rule.
        if stage is HelpStage.S_EMPOWER or rendered.action_id is not None:
            rendered.referral_flags = plan.referral_flags
        return rendered

    def _info_choice(
        self,
        stage: HelpStage,
        perception: PerceptionContext,
        flags: frozenset[str],
        signals: TurnSignals,
        status: CrisisStatus,
        assessed: CrisisLevel,
        feedback: Feedback | None,
        transition: Transition,
    ) -> tuple[str, str, bool] | None:
        """(method id, card text, lens) for a Grade B/C card to show, or None."""
        if (
            status.in_crisis
            or assessed >= CrisisLevel.L1
            or feedback is not None
            or signals.direct_request
        ):
            return None
        inp = SolverInput(
            stage=stage,
            arousal=perception.arousal,
            battery=transition.state.social_battery,
            active_red_flags=flags,
            active_contraindications=frozenset(),
            situation_codes=frozenset(),
            shelved_actions=frozenset(),
        )
        asked = signals.therapy_question
        if asked is not None:
            chosen, lens = (asked if info_cards(self._tax, inp, asked) else None), False
        elif (
            stage is HelpStage.S_CLARIFY
            and not self._lens_shown
            and not transition.state.pure_listening_locked
        ):
            fits = self._engine.data.info_lenses.get(self._last_spectrum or "", ())
            pool = [mid for mid in info_cards(self._tax, inp) if mid in fits]
            chosen, lens = (self._rng.choice(pool) if pool else None), True
        else:
            return None
        if chosen is None:
            return None
        self._engine.last_gate = None
        text = self._engine.render_info_reply(chosen, lens=lens)
        if not self._note_gate() or self._has_taboo(text, ""):
            return None
        return chosen, text, lens

    def _info(
        self,
        info: tuple[str, str, bool],
        stage: HelpStage,
        perception: PerceptionContext,
        spectrum: str | None,
        mirror_text: str,
    ) -> _Rendered:
        """The information card alone, or after the S_clarify reply for a lens."""
        method_id, text, lens = info
        if not lens:
            return _Rendered(text, ReplyKind.INFO, info_id=method_id)
        rendered = self._with_taboo_filter(
            lambda: self._compose(stage, perception, spectrum, mirror_text), stage
        )
        if rendered.kind is ReplyKind.NORMAL:
            rendered.reply = f"{rendered.reply}\n\n{text}"
            rendered.kind = ReplyKind.INFO
            rendered.info_id = method_id
            self._lens_shown = True
        return rendered

    def _allowed(
        self,
        stage: HelpStage,
        perception: PerceptionContext,
        flags: frozenset[str],
        shelved: frozenset[str],
    ) -> AllowedSet:
        return allowed_actions(
            self._tax,
            SolverInput(
                stage=stage,
                arousal=perception.arousal,
                active_red_flags=flags,
                active_contraindications=frozenset(),
                situation_codes=frozenset(),
                shelved_actions=shelved,
                battery=self._state.social_battery,
            ),
        )

    def _compose(
        self,
        stage: HelpStage,
        perception: PerceptionContext,
        spectrum: str | None,
        mirror_text: str,
        *,
        card_title: str = "",
        card: str = "",
        light: bool = False,
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
        text = self._engine.compose(stage, slots, card=card, light=light)
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
        return self._plain_line(self._engine.data.templates.after_card, HelpStage.S_EMPOWER)

    def _followup(self, variants: tuple[str, ...], stage: HelpStage) -> _Rendered:
        """A short follow-up line (roadmap R-7b), through the taboo filter and the gate."""
        return self._with_taboo_filter(lambda: self._plain_line(variants, stage), stage)

    def _plain_line(self, variants: tuple[str, ...], stage: HelpStage) -> tuple[str, str] | None:
        """One variant with only the name slots filled, after WILLOW and the output gate."""
        values = self._plain_slots().values()
        usable = [v for v in variants if all(values[s] for s in slots_of(v))]
        text = self._rng.choice(usable)
        for name, value in values.items():
            text = text.replace("{" + name + "}", value)
        text = apply_willow(text, ContentKind.NORMAL, self._engine.data.willow)
        result = self._engine.gate.check(text, kind=ContentKind.NORMAL, stage=stage)
        self._engine.last_gate = result
        if not self._note_gate():
            return None
        return text, ""

    def _wellbeing_line(self, variant: str, stage: HelpStage) -> str | None:
        """One wellbeing variant with the name slots filled, or None when the gate or a
        taboo topic rules it out (B7)."""
        values = self._plain_slots().values()
        if not all(values[s] for s in slots_of(variant)):
            return None
        text = variant
        for name, value in values.items():
            text = text.replace("{" + name + "}", value)
        text = apply_willow(text, ContentKind.NORMAL, self._engine.data.willow)
        self._engine.last_gate = self._engine.gate.check(text, kind=ContentKind.NORMAL, stage=stage)
        if not self._note_gate() or self._has_taboo(text, ""):
            return None
        return text

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

    def _follow_up(
        self,
        signals: TurnSignals,
        status: CrisisStatus,
        assessed: CrisisLevel,
        pending: _Pending | None,
    ) -> _FollowUp:
        """Read natural-language feedback, answers and kit recall (roadmap R-7b).

        Nothing is read on a crisis turn (the tracker's crisis, or an L2/L3 screen): the
        signals pass through unchanged and the state machine routes to S_crisis. Feedback
        phrases count only while a card waits in the current stage, and a slash command
        wins. A clarification question waits for exactly one turn.
        """
        clarifying, self._clarifying = self._clarifying, False
        if status.in_crisis or assessed >= CrisisLevel.L2:
            return _FollowUp(signals)
        # An L1 screen ("我想消失") may hide distress the rules under-rate, so its everyday
        # phrases are not read as feedback, answers or kit recall; commands still count.
        phrases = assessed < CrisisLevel.L1
        current = self._state.current_stage
        source: FeedbackSource | None = None
        clarify = False
        if pending is not None and pending.stage is current:
            if signals.command is not None:
                source = FeedbackSource.COMMAND
            elif signals.aversion and signals.feedback in (None, Command.UNHELPFUL):
                # Aversion keeps its own route (EMPOWER_AVERSION), with the same feedback.
                source = FeedbackSource.PHRASE
            elif not phrases:
                pass
            elif signals.feedback is not None:
                # Read exactly as the command, so the state machine routes it the same way.
                signals = replace(signals, command=signals.feedback, aversion=False)
                source = FeedbackSource.PHRASE
            elif clarifying and signals.answer is Answer.AFFIRM:
                signals = replace(signals, command=Command.NOT_NOW, aversion=False)
                source = FeedbackSource.CONFIRMED
            elif signals.feedback_unclear and not clarifying:
                clarify = True
        recall = kit_empty = False
        if phrases and signals.kit_recall and source is None and not clarify:
            if self._state.user_shelved_actions:
                signals = replace(signals, direct_request=True)
                recall = True
            else:
                kit_empty = True
        declined = False
        if phrases and current is HelpStage.S_CLOSING and signals.command is None:
            if signals.answer is Answer.AFFIRM:
                signals = replace(signals, intent_confirmed=True)
            elif signals.answer is Answer.DECLINE:
                declined = True
        return _FollowUp(signals, source, clarify, recall, kit_empty, declined)

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
