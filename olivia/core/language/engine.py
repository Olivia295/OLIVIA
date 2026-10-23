"""The offline W.I.L.L.O.W. language engine (SDD §5, R1 rule mode).

Every public render method assembles text from the reviewed data files, runs
:func:`~olivia.core.language.filters.apply_willow` for the content kind, then passes the
result through the :class:`~olivia.core.language.gate.OutputGate`. A gate block never
raises; the method returns the gate's safe line instead (for crisis cards, a minimal card
that still lists every number, see :meth:`LanguageEngine.render_crisis`). The last gate
verdict is kept in :attr:`LanguageEngine.last_gate` for telemetry.

Template choice is seeded through the injected ``random.Random``. For the composed stages
the engine walks the variant combinations in an rng-shuffled order and takes the first one
whose filtered text fits the stage's word window (WILLOW-03, SDD §5.3); if none fits, it
takes the one with the smallest cadence penalty. Templates and windows are the persona's
(``LanguageData.for_persona``).

Quality fixes (F3):

* The ``{emotion}`` slot names a feeling only when there is one to name
  (:meth:`LanguageEngine.feeling_word`): the user's own words first ("好累" -> 疲惫), never
  an emotion in ``feelings.yaml`` ``never_named`` (the rule stub's fallback ``calm``).
  Without a feeling the parts that need one use their ``unnamed`` variants.
* A message that is not a statement gets a short acknowledgement in the ``{mirror}`` slot
  instead of a mirror (:meth:`LanguageEngine.safe_mirror`).
* A composed reply never repeats a paragraph of the replies composed just before it
  (``RECENT_REPLIES``): combinations that would are taken only when nothing else is left.
  The crisis opening likewise differs from the one before when there is another variant.
* After a very short message (``is_short_input``) S_explore and S_clarify answer in two
  paragraphs (the middle one left out) inside the persona's ``window.short``.
* Personas with their own images (``metaphors.yaml`` ``by_persona``) never get the
  nature images.
"""

from __future__ import annotations

import itertools
import random
import re
from collections import deque
from collections.abc import Iterable, Mapping, Sequence, Set
from dataclasses import dataclass, fields
from datetime import datetime
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from olivia.core.language.data import (
    ContentKind,
    ExerciseCard,
    FeelingWord,
    InfoEntry,
    LanguageData,
    load_language_data,
    slots_of,
)
from olivia.core.language.dossiers import situation_images
from olivia.core.language.filters import apply_willow
from olivia.core.language.gate import GateResult, OutputGate, phone_like_runs
from olivia.core.language.mirror import FALLBACK_MIRROR, Utterance, mirror, utterance_kind
from olivia.core.models import ActionSkeleton, CrisisLevel, HelpStage, SafetyGrade
from olivia.core.resources.card import CardMode, ResourceCard
from olivia.core.resources.store import LineKind
from olivia.core.safety.normalize import normalize
from olivia.core.taxonomy import Taxonomy

_SLOT_RE: Final = re.compile(r"\{([^{}]*)\}")
_CJK_RE: Final = re.compile(r"[一-鿿]")
_WS_RE: Final = re.compile(r"\s")
_NORMAL_STAGES: Final = frozenset(
    {HelpStage.S_EXPLORE, HelpStage.S_CLARIFY, HelpStage.S_EMPOWER, HelpStage.S_CLOSING}
)
_UNKNOWN_HOURS: Final = "unknown"
_UNKNOWN_REGION: Final = "ZZ"
_SHORT_STAGES: Final = frozenset({HelpStage.S_EXPLORE, HelpStage.S_CLARIFY})
SHORT_INPUT_MAX: Final = 2
"""A message with at most this many Chinese characters, letters or digits is very short,
like any one-word answer, emoji or punctuation (``Utterance.BRIEF``)."""
RECENT_REPLIES: Final = 3
"""Composed replies whose paragraphs the next one does not repeat (one turn may compose
two: the S_explore reflection and the card framing of a stabilization card)."""
_MEANINGFUL_RE: Final = re.compile(r"[一-鿿A-Za-z0-9]")
_CLAUSE_ENDS: Final = frozenset("，,。.！!？?；;：:、\n…")
# Working hours for the card's context line (F3): Monday-Friday, 09:00-18:00 local time.
_WORK_DAYS: Final = range(0, 5)
_WORK_HOURS: Final = range(9, 18)


@dataclass(frozen=True)
class Slots:
    """Values for the seven template slots; unused ones may stay empty."""

    user_name: str
    agent_name: str
    emotion: str = ""
    mirror: str = ""
    metaphor: str = ""
    need: str = ""
    card_title: str = ""

    def values(self) -> dict[str, str]:
        return {f.name: getattr(self, f.name) for f in fields(self)}


def count_all(text: str) -> int:
    """Characters excluding whitespace (the reading used for upper bounds)."""
    return len(_WS_RE.sub("", text))


def count_cjk(text: str) -> int:
    """Chinese characters only (the reading used for lower bounds)."""
    return len(_CJK_RE.findall(text))


def paragraphs(text: str) -> list[str]:
    return [p for p in text.split("\n\n") if p.strip()]


def is_short_input(text: str) -> bool:
    """A very short message: a one-word answer ("嗯", "好吧", "不知道"), an emoji or
    punctuation, or at most ``SHORT_INPUT_MAX`` Chinese characters, letters or digits."""
    if len(_MEANINGFUL_RE.findall(text)) <= SHORT_INPUT_MAX:
        return True
    return utterance_kind(text) is Utterance.BRIEF


def at_work(now: datetime, timezone: str | None) -> bool:
    """Whether ``now`` falls in working hours where the user lives (Mon-Fri 9-18)."""
    local = now
    if timezone:
        try:
            local = now.astimezone(ZoneInfo(timezone))
        except (ZoneInfoNotFoundError, ValueError):
            local = now
    return local.weekday() in _WORK_DAYS and local.hour in _WORK_HOURS


class LanguageEngine:
    def __init__(
        self, tax: Taxonomy, *, rng: random.Random, data: LanguageData | None = None
    ) -> None:
        self._tax = tax
        self._rng = rng
        self._data = data if data is not None else load_language_data(tax)
        self._gate = OutputGate(tax, self._data)
        self.last_gate: GateResult | None = None
        # The verdict on the last crisis reply with the user's safety plan in it (B10);
        # None when no plan block was offered.
        self.last_plan_gate: GateResult | None = None
        # Paragraphs of the last few composed replies, never repeated verbatim (F3).
        self._recent: deque[frozenset[str]] = deque(maxlen=RECENT_REPLIES)
        self._last_crisis_opening: str | None = None

    @property
    def data(self) -> LanguageData:
        return self._data

    @property
    def gate(self) -> OutputGate:
        return self._gate

    # -- slots -----------------------------------------------------------------------------

    def emotion_word(self, emotion_id: str) -> str:
        """The taxonomy's Chinese name for a canonical emotion id or alias."""
        return self._tax.emotion_name(self._tax.canonical_label("emotion", emotion_id))

    def feeling_word(self, emotion_id: str | None, user_text: str = "") -> str:
        """What the ``{emotion}`` slot says this turn; "" when no feeling is named.

        The user's own word comes first ("今天上班好累" -> 疲惫) when it may stand in for
        the perceived emotion; an emotion in ``never_named`` (the rule stub's fallback
        ``calm``, so also every turn without an emotion cue) names nothing; otherwise the
        everyday ``display`` word or the taxonomy name (``language/feelings.yaml``).
        """
        feelings = self._data.feelings
        canonical = (
            self._tax.canonical_label("emotion", emotion_id) if emotion_id is not None else None
        )
        text = normalize(user_text)
        for word in feelings.words:
            open_to = canonical is None or canonical in word.replaces
            if open_to and _feeling_hit(text, word, feelings.negations):
                return word.word
        if canonical is None or canonical in feelings.never_named:
            return ""
        return feelings.display.get(canonical) or self._tax.emotion_name(canonical)

    def need_phrase(self, yearning_id: str) -> str:
        canonical = self._tax.canonical_label("yearning", yearning_id)
        return self._rng.choice(self._data.needs[canonical])

    def metaphor_phrase(
        self,
        spectrum_id: str | None,
        yearning_id: str | None,
        situations: Set[str] = frozenset(),
    ) -> str:
        """An image for the persona.

        A persona with its own images (``by_persona``: everyday images for GENTLE_HOLDING
        and RATIONAL_PEER, F3) draws from the spectrum's list, else its fallback. The
        others get a nature image: the active situations' dossier imagery, else the
        spectrum x yearning cell, else a fallback image (precedence:
        ``language/dossiers.py``).
        """
        own = self._data.metaphors.by_persona.get(self._data.templates.persona)
        if own is not None:
            listed = own.by_spectrum.get(spectrum_id or "")
            return self._rng.choice(listed if listed else own.fallback)
        dossier = situation_images(self._data.metaphors.by_situation, situations)
        if dossier:
            return self._rng.choice(dossier)
        grid = self._data.metaphors.by_spectrum_yearning
        if spectrum_id is not None and spectrum_id in grid and yearning_id is not None:
            cell = grid[spectrum_id]
            canonical = self._tax.canonical_label("yearning", yearning_id)
            return self._rng.choice(cell[canonical])
        return self._rng.choice(self._data.metaphors.fallback)

    def safe_mirror(self, user_text: str) -> str:
        """:func:`mirror` for a statement, an acknowledgement for anything else, replaced
        by a neutral line if it would trip the gate.

        A question, request, greeting, thanks, note, one-word answer or message without
        Chinese is not mirrored (F3): its kind's ``utterances.yaml`` acknowledgement is
        used, picked from the text itself so it draws no random number.
        """
        kind = utterance_kind(user_text)
        acks = self._data.utterances.acks.get(kind.value, ())
        if kind is not Utterance.STATEMENT and acks:
            raw = acks[sum(map(ord, user_text)) % len(acks)]
        else:
            raw = mirror(user_text)
        text = apply_willow(raw, ContentKind.NORMAL, self._data.willow)
        if not text or self._gate.reasons(text, kind=ContentKind.NORMAL, stage=HelpStage.S_EXPLORE):
            return FALLBACK_MIRROR
        return text

    def boundary_line(self, user_text: str) -> str:
        """The plain line for a medication or diagnosis question, "" for anything else.

        Dose, add, cut or stop questions about a medicine point to the prescribing doctor
        or a pharmacist; "am I X?" says no diagnosis can be given here and where to get an
        assessment (``utterances.yaml`` ``boundaries``, F3). The session puts it before
        the reply it would give anyway.
        """
        text = normalize(user_text)
        lines = [
            b.line
            for b in self._data.utterances.boundaries.values()
            if any(c in text for c in b.cues)
            and (not b.needs_any or any(n in text for n in b.needs_any))
        ]
        if not lines:
            return ""
        line = apply_willow("".join(lines), ContentKind.NORMAL, self._data.willow)
        if self._gate.reasons(line, kind=ContentKind.NORMAL, stage=HelpStage.S_EXPLORE):
            return ""
        return line

    def build_slots(
        self,
        *,
        user_name: str,
        agent_name: str,
        user_text: str = "",
        emotion_id: str | None = None,
        yearning_id: str | None = None,
        spectrum_id: str | None = None,
        card_title: str = "",
        situations: Set[str] = frozenset(),
    ) -> Slots:
        return Slots(
            user_name=user_name,
            agent_name=agent_name,
            emotion=self.feeling_word(emotion_id, user_text),
            mirror=self.safe_mirror(user_text) if user_text.strip() else "",
            metaphor=self.metaphor_phrase(spectrum_id, yearning_id, situations),
            need=self.need_phrase(yearning_id) if yearning_id is not None else "",
            card_title=card_title,
        )

    def pick_line(self, variants: Sequence[str], values: Mapping[str, str] | None = None) -> str:
        """One variant for a single-line reply (a follow-up or the feedback prompt).

        Drawn like ``rng.choice``, but a variant whose text (slots filled from ``values``)
        is a paragraph of one of the last replies is passed over for the next one in
        order (F3: no verbatim repeats; never one of the reply just before); no extra draw.
        """
        picked = self._rng.choice(variants)
        start = variants.index(picked)
        ordered = [variants[(start + k) % len(variants)] for k in range(len(variants))]

        def text(variant: str) -> str:
            return _fill(variant, dict(values)) if values is not None else variant

        last = self._recent[-1] if self._recent else frozenset()
        older = frozenset().union(*list(self._recent)[:-1])
        picked = next(
            (v for v in ordered if text(v) not in last and text(v) not in older),
            next((v for v in ordered if text(v) not in last), picked),
        )
        self._recent.append(frozenset({text(picked)}))
        return picked

    # -- normal stages ---------------------------------------------------------------------

    def compose(
        self,
        stage: HelpStage,
        slots: Slots,
        *,
        card: str = "",
        light: bool = False,
        returning_after_crisis: bool = False,
        short: bool = False,
    ) -> str:
        """A reply for a non-crisis stage.

        ``card`` is the rendered card body (:meth:`render_card`) that S_empower inserts
        between ``card_intro`` and ``after_card``; it is required there and not counted in
        the word window. ``light`` swaps the S_empower ``bridge`` for ``light_bridge``
        ("today we start with something light"), used when the solver cut the pool to the
        stabilization whitelist for low battery (COLBO-07). ``returning_after_crisis`` picks
        the S_ready greeting variant used for the first session after a crisis. Raises
        ``ValueError`` for S_crisis (use :meth:`render_crisis`), for ``light`` outside
        S_empower, or when a needed slot is empty.

        ``short`` (the user's message was very short, :func:`is_short_input`) makes
        S_explore and S_clarify two paragraphs, the first and last part, in the persona's
        ``window.short``; a persona without one, and every other stage, ignore it. A
        combination that repeats a paragraph of a recent reply is taken only when every
        combination does (then the best-fitting one).
        """
        if stage is HelpStage.S_CRISIS:
            raise ValueError("S_crisis replies are rendered by render_crisis")
        if stage is HelpStage.S_EMPOWER and not card.strip():
            raise ValueError("S_empower needs the rendered card body")
        if light and stage is not HelpStage.S_EMPOWER:
            raise ValueError("only S_empower has a light bridge")
        values = slots.values()
        short = short and stage in _SHORT_STAGES and self._data.templates.short_window is not None
        pools = self._pools(stage, returning_after_crisis, named=bool(slots.emotion))
        if light:
            pools[0] = self._data.templates.light_bridge
        usable = [[v for v in pool if all(values[s] for s in slots_of(v))] for pool in pools]
        if short and len(usable) == 3:
            dropped = set().union(*(slots_of(v) for v in usable[1])) - slots_of("".join(usable[0]))
            closing = [v for v in usable[2] if not slots_of(v) & dropped] or usable[2]
            usable = [usable[0], closing]
        if any(not pool for pool in usable):
            raise ValueError(f"{stage}: no template variant can be filled from these slots")
        combos = list(itertools.product(*usable))
        self._rng.shuffle(combos)
        # Never a paragraph of the reply just before; avoid the older recent ones too.
        last: frozenset[str] = self._recent[-1] if self._recent else frozenset()
        older: frozenset[str] = frozenset().union(*list(self._recent)[:-1])
        best: tuple[tuple[bool, bool, float], str] | None = None
        for combo in combos:
            text = apply_willow(
                "\n\n".join(_fill(part, values) for part in combo),
                ContentKind.NORMAL,
                self._data.willow,
            )
            shown = paragraphs(text)
            key = (
                bool(last.intersection(shown)),
                bool(older.intersection(shown)),
                self.window_penalty(stage, text, short=short),
            )
            if best is None or key < best[0]:
                best = (key, text)
            if key == (False, False, 0.0):
                break
        assert best is not None
        text = best[1]
        self._recent.append(frozenset(paragraphs(text)))
        if stage is HelpStage.S_EMPOWER:
            head, sep, tail = text.rpartition("\n\n")
            text = f"{head}{sep}{card.strip()}\n\n{tail}"
        return self._checked(text, ContentKind.NORMAL, stage)

    def window_penalty(self, stage: HelpStage, text: str, *, short: bool = False) -> float:
        """SDD §5.3 cadence penalty (κ = 1) plus paragraph overflow; 0 means it fits.

        The windows are the persona's (``window`` in its template file): GENTLE_HOLDING,
        ZEN_PHILOSOPHER and RATIONAL_PEER use [140, 260] and S_haven [15, 40];
        SILENT_ANCHOR uses [10, 30] (WILLOW-03). S_empower uses ``empower_window``;
        ``short`` S_explore / S_clarify replies use ``short_window`` (F3).
        """
        tpl = self._data.templates
        if short and stage in _SHORT_STAGES and tpl.short_window is not None:
            low, high = tpl.short_window
            penalty = 0.0
        elif stage is HelpStage.S_HAVEN:
            low, high = tpl.haven_window
            penalty = 0.0 if "\n" not in text else float(high) ** 2
        elif stage is HelpStage.S_EMPOWER:
            low, high = tpl.empower_window
            penalty = 0.0
        elif stage in _NORMAL_STAGES:
            low, high = tpl.normal_window
            penalty = 0.0
        else:  # S_ready: one short paragraph, no total window
            low, high = 0, tpl.paragraph_max
            penalty = 0.0
        cjk, total = count_cjk(text), count_all(text)
        if cjk < low:
            penalty += float(low - cjk) ** 2
        if total > high:
            penalty += float(total - high) ** 2
        for para in paragraphs(text):
            over = count_all(para) - tpl.paragraph_max
            if over > 0:
                penalty += float(over) ** 2
        return penalty

    def _pools(self, stage: HelpStage, returning: bool, *, named: bool) -> list[Sequence[str]]:
        tpl = self._data.templates
        if stage in tpl.parts:
            pools: list[Sequence[str]] = [
                part.variants if named or not part.unnamed else part.unnamed
                for part in tpl.parts[stage]
            ]
            if stage is HelpStage.S_EMPOWER:
                pools.append(tpl.after_card)
            return pools
        if stage is HelpStage.S_HAVEN:
            return [tpl.haven]
        if stage is HelpStage.S_CLOSING:
            return [tpl.closing]
        if stage is HelpStage.S_READY:
            return [tpl.returning_after_crisis if returning else tpl.greeting]
        raise ValueError(f"no templates for {stage}")

    # -- cards -----------------------------------------------------------------------------

    def card_for(self, method_id: str) -> ExerciseCard:
        """The follow-along card for a Grade A method or card-type registry action.

        Raises ``ValueError`` for an excluded action (``12:tipp_cold_water``) and for
        actions that are not rendered as cards (m0, psychoeducation, referral).
        """
        deck = self._data.cards
        canonical = self._tax.canonical_action_id(method_id)
        if canonical in deck.excluded:
            raise ValueError(f"{canonical} has no follow-along card: {deck.excluded[canonical]}")
        if canonical not in deck.cards:
            raise ValueError(f"{canonical} is not rendered as a follow-along card")
        return deck.cards[canonical]

    def render_card(self, skeleton: ActionSkeleton, *, at_work: bool = True) -> str:
        """The card body for an exercise skeleton (title, intro, safety, steps, closing).

        The title is the card's everyday name (an exercise, F3). The closing line about
        doing it unnoticed at a desk appears only ``at_work`` (:func:`at_work`); outside
        working hours the card ends with ``card.home_line`` instead.
        """
        card = self.card_for(skeleton.method_id)
        if len(card.steps) != len(skeleton.core_action_steps):
            raise ValueError(f"{card.id}: card steps do not match the skeleton")
        r = self._data.render
        duration = r.card_duration.replace("{minutes}", str(card.duration_minutes))
        blocks = [f"「{card.title}」· {duration}\n{card.intro}"]
        if card.safety_note is not None:
            blocks.append(f"{r.card_safety_label}{card.safety_note}")
        blocks.append("\n".join(f"{i}. {step}" for i, step in enumerate(card.steps, start=1)))
        tail = card.closing
        if not at_work:
            tail += f"\n{r.card_home_line}"
        elif card.stealth_note is not None:
            tail += f"\n{r.card_stealth_label}{card.stealth_note}"
        blocks.append(tail)
        text = apply_willow("\n\n".join(blocks), ContentKind.CARD, self._data.willow)
        return self._checked(text, ContentKind.CARD, HelpStage.S_EMPOWER)

    def render_info(self, method_id: str) -> str:
        """The Grade B/C psychoeducation card; raises ``ValueError`` for other ids."""
        entry = self._data.info.get(method_id)
        if entry is None:
            raise ValueError(f"{method_id} has no Grade B/C information card")
        kind = _info_kind(entry)
        text = apply_willow(self._info_body(entry), kind, self._data.willow)
        return self._checked(text, kind, HelpStage.S_CLARIFY)

    def render_info_reply(self, method_id: str, *, lens: bool) -> str:
        """The framed information card (roadmap next-phase A4).

        The lead is ``info.lens_intro`` when S_clarify offers a Grade B perspective
        (``lens``) and ``info.ask_intro`` when the user asked; the closing is
        ``info.b_closing`` for Grade B (a way of seeing, nothing to do),
        ``info.c_closing`` for Grade C (not for trying alone; see a professional) or
        ``info.a_closing`` for a Grade A practice asked about by name (it can be done here;
        F3). The whole reply goes through WILLOW and the gate as the card's grade (a Grade A
        explainer as Grade B text). Raises ``ValueError`` for an id with no card.
        """
        entry = self._data.info.get(method_id) or self._data.exercise_info.get(method_id)
        if entry is None:
            raise ValueError(f"{method_id} has no information card")
        kind = _info_kind(entry)
        r = self._data.render
        lead = r.info_lens_intro if lens else r.info_ask_intro
        if entry.grade is SafetyGrade.GRADE_A:
            closing = r.info_a_closing
        elif kind is ContentKind.GRADE_B_INFO:
            closing = r.info_b_closing
        else:
            closing = r.info_c_closing
        text = f"{lead}\n\n{self._info_body(entry)}\n\n{closing}"
        text = apply_willow(text, kind, self._data.willow)
        return self._checked(text, kind, HelpStage.S_CLARIFY)

    def _info_body(self, entry: InfoEntry) -> str:
        r = self._data.render
        return "\n".join(
            [
                f"「{entry.title}」",
                f"{r.info_what_label}{entry.what_it_is}",
                f"{r.info_how_label}{entry.how_it_helps}",
                f"{r.info_who_label}{entry.who_offers_it}",
            ]
        )

    def render_referral(self, flags: Iterable[str]) -> str:
        """The specialist referral card for active red-flag codes (taxonomy order)."""
        active = set(flags)
        destinations = self._data.render.referral_destinations
        unknown = active - set(destinations)
        if unknown:
            raise ValueError(f"unknown red flags: {sorted(unknown)}")
        if not active:
            raise ValueError("a referral card needs at least one red flag")
        places = list(dict.fromkeys(destinations[c] for c in self._tax.red_flags() if c in active))
        r = self._data.render
        lines = [r.referral_intro, *(f"· {p}" for p in places), "", r.referral_closing]
        text = apply_willow("\n".join(lines), ContentKind.REFERRAL, self._data.willow)
        # Any non-S_empower stage keeps the Grade A title check on for referral text.
        return self._checked(text, ContentKind.REFERRAL, HelpStage.S_EXPLORE)

    # -- crisis ----------------------------------------------------------------------------

    def render_crisis(
        self, card: ResourceCard, slots: Slots, *, plan_block: str = "", urgent: bool = False
    ) -> str:
        """S_crisis wording plus the card's numbers: emergency first, stale entries marked.

        Exempt from word windows and metaphors. If the gate ever blocks the full card, the
        reply falls back to a minimal card that still lists every number, never to a line
        without numbers.

        ``plan_block`` is the user's own safety plan (B10, ``chang/safety_plan.py``). It
        skips WILLOW and goes after the opening sentence when the card carries no
        emergency numbers (an L2 card with a regional line), otherwise after the card, so
        emergency numbers come before any other number. The whole reply passes the gate
        with the plan's own digit runs allowed for this reply only; if it is blocked, the
        plan block is dropped and the reply is the one without it (minimal-card fallback
        included). :attr:`last_plan_gate` keeps the verdict on the reply with the plan.

        ``urgent`` frames the card's emergency numbers the way an L3 card does (the L3
        heading, then the line about calling someone close) on a card below L3. The
        session passes it, with the region's emergency numbers added to its L2 card, when
        the risk model scored L3 but its L3 does not count as plan evidence (owner decision
        2026-10-24): the emergency numbers lead, every L2 line stays, the flow stays L2.
        """
        if card.mode is not CardMode.CRISIS or card.level < CrisisLevel.L2:
            raise ValueError("render_crisis needs a CRISIS-mode card at L2 or L3")
        values = slots.values()
        usable = [t for t in self._data.templates.crisis if all(values[s] for s in slots_of(t))]
        if not usable:
            raise ValueError("no S_crisis variant can be filled from these slots")
        picked = self._rng.choice(usable)
        if picked == self._last_crisis_opening and len(usable) > 1:
            # Never the same opening twice in a row (F3); no extra random draw.
            picked = usable[(usable.index(picked) + 1) % len(usable)]
        self._last_crisis_opening = picked
        opening = _fill(picked, values)
        resources = self._resource_blocks(card, urgent=urgent)
        numbers = _numbers(card)
        self.last_plan_gate = None
        if plan_block.strip():
            willow = self._data.willow
            head = apply_willow(opening, ContentKind.CRISIS, willow)
            card_text = apply_willow("\n\n".join(resources), ContentKind.CRISIS, willow)
            if card.emergency:
                blocks = [head, card_text, plan_block]
            else:
                blocks = [head, plan_block, card_text]
            planned = self._gate.check(
                "\n\n".join(blocks),
                kind=ContentKind.CRISIS,
                stage=HelpStage.S_CRISIS,
                allowed_numbers=[*numbers, *phone_like_runs(plan_block)],
            )
            self.last_plan_gate = planned
            if planned.ok:
                self.last_gate = planned
                return planned.text
        joined = "\n\n".join([opening, *resources])
        text = apply_willow(joined, ContentKind.CRISIS, self._data.willow)
        result = self._gate.check(
            text, kind=ContentKind.CRISIS, stage=HelpStage.S_CRISIS, allowed_numbers=numbers
        )
        self.last_gate = result
        if result.ok:
            return result.text
        return self._minimal_card(numbers)

    def render_safety_check(self, card: ResourceCard, slots: Slots, stage: HelpStage) -> str:
        """The direct question about intent (decision D3) plus the card's resource lines.

        The question is one ``followups.safety_check`` variant (name slots only) under the
        NORMAL filters; the resource lines are the crisis card's, from ``card`` (the
        region's L2 CRISIS card), under the CRISIS filters. The whole reply passes the gate
        as NORMAL content in ``stage`` with the card's numbers allowed, the way crisis
        cards pass it. A block falls back to the minimal card, never to a reply without
        numbers.
        """
        if card.mode is not CardMode.CRISIS or card.level < CrisisLevel.L2:
            raise ValueError("render_safety_check needs a CRISIS-mode card at L2 or L3")
        values = slots.values()
        tpl = self._data.templates.safety_check
        usable = [t for t in tpl if all(values[s] for s in slots_of(t))]
        if not usable:
            raise ValueError("no safety_check variant can be filled from these slots")
        willow = self._data.willow
        question = apply_willow(_fill(self._rng.choice(usable), values), ContentKind.NORMAL, willow)
        resources = apply_willow(
            "\n\n".join(self._resource_blocks(card)), ContentKind.CRISIS, willow
        )
        numbers = _numbers(card)
        result = self._gate.check(
            f"{question}\n\n{resources}",
            kind=ContentKind.NORMAL,
            stage=stage,
            allowed_numbers=numbers,
        )
        self.last_gate = result
        if result.ok:
            return result.text
        return self._minimal_card(numbers)

    def _resource_blocks(self, card: ResourceCard, *, urgent: bool = False) -> list[str]:
        """The card's numbers: emergency first, then lines, stale entries marked.

        ``urgent`` frames the emergency numbers as an L3 card does (:meth:`render_crisis`).
        """
        r = self._data.render
        stale = set(card.stale_entries)
        mark = r.crisis_stale_mark
        blocks: list[str] = []
        if card.emergency:
            framing = CrisisLevel.L3 if urgent else card.level
            lines = [r.crisis_emergency_heading[framing]]
            for em in card.emergency:
                purpose = r.emergency_purposes[em.purpose]
                lines.append(f"· {em.number}（{purpose}）{mark if em.id in stale else ''}")
            if framing is CrisisLevel.L3:
                lines.append(r.crisis_contact_people)
                if card.region_used == _UNKNOWN_REGION:
                    lines.append(r.crisis_unknown_region_l3)
            blocks.append("\n".join(lines))
        if card.lines:
            lines = [r.crisis_lines_heading]
            for ln in card.lines:
                lines.append(f"· {ln.name_zh}：{ln.number}{mark if ln.id in stale else ''}")
                if ln.hours != _UNKNOWN_HOURS and ln.kind is not LineKind.DIRECTORY_URL:
                    lines.append(f"  {r.crisis_hours_label}{ln.hours}")
            blocks.append("\n".join(lines))
        return blocks

    def _minimal_card(self, numbers: Sequence[str]) -> str:
        return "\n".join([self._data.render.crisis_minimal, *(f"· {n}" for n in numbers)])

    # -- helpers ---------------------------------------------------------------------------

    def _checked(self, text: str, kind: ContentKind, stage: HelpStage) -> str:
        result = self._gate.check(text, kind=kind, stage=stage)
        self.last_gate = result
        return result.text


def _numbers(card: ResourceCard) -> list[str]:
    return [e.number for e in card.emergency] + [ln.number for ln in card.lines]


def _info_kind(entry: InfoEntry) -> ContentKind:
    if entry.grade in (SafetyGrade.GRADE_A, SafetyGrade.GRADE_B):
        return ContentKind.GRADE_B_INFO
    return ContentKind.GRADE_C_INFO


def _feeling_hit(text: str, word: FeelingWord, negations: Sequence[str]) -> bool:
    """A non-negated cue of ``word`` in folded ``text``, outside its exception words.

    Scanned left to right, longest cue first, so "不是很累" is one negated hit, not a
    negated "很累" plus a bare "累". A cue whose nearest pronoun before it in the same
    clause is someone else's ("他说他累了") describes that person, not the user.
    """
    masked = text
    for exception in word.exceptions:
        masked = masked.replace(normalize(exception), "\0" * len(normalize(exception)))
    cues = sorted({normalize(c) for c in word.cues}, key=len, reverse=True)
    i = 0
    while i < len(masked):
        cue = next((c for c in cues if masked.startswith(c, i)), None)
        if cue is None:
            i += 1
            continue
        if not any(masked.endswith(n, 0, i) for n in negations) and not _about_others(masked, i):
            return True
        i += len(cue)
    return False


def _about_others(text: str, end: int) -> bool:
    """The nearest pronoun before ``end`` in its clause is 他/她/它 (not 我/你)."""
    for ch in reversed(text[:end]):
        if ch in _CLAUSE_ENDS:
            return False
        if ch in "我你您咱":
            return False
        if ch in "他她它":
            return True
    return False


def _fill(template: str, values: dict[str, str]) -> str:
    return _SLOT_RE.sub(lambda m: values[m.group(1)], template)
