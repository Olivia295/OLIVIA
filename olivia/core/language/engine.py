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
takes the one with the smallest cadence penalty.
"""

from __future__ import annotations

import itertools
import random
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, fields
from typing import Final

from olivia.core.language.data import (
    ContentKind,
    ExerciseCard,
    LanguageData,
    load_language_data,
    slots_of,
)
from olivia.core.language.filters import apply_willow
from olivia.core.language.gate import GateResult, OutputGate
from olivia.core.language.mirror import FALLBACK_MIRROR, mirror
from olivia.core.models import ActionSkeleton, CrisisLevel, HelpStage, SafetyGrade
from olivia.core.resources.card import CardMode, ResourceCard
from olivia.core.resources.store import LineKind
from olivia.core.taxonomy import Taxonomy

_SLOT_RE: Final = re.compile(r"\{([^{}]*)\}")
_CJK_RE: Final = re.compile(r"[一-鿿]")
_WS_RE: Final = re.compile(r"\s")
_NORMAL_STAGES: Final = frozenset(
    {HelpStage.S_EXPLORE, HelpStage.S_CLARIFY, HelpStage.S_EMPOWER, HelpStage.S_CLOSING}
)
_UNKNOWN_HOURS: Final = "unknown"
_UNKNOWN_REGION: Final = "ZZ"


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


class LanguageEngine:
    def __init__(
        self, tax: Taxonomy, *, rng: random.Random, data: LanguageData | None = None
    ) -> None:
        self._tax = tax
        self._rng = rng
        self._data = data if data is not None else load_language_data(tax)
        self._gate = OutputGate(tax, self._data)
        self.last_gate: GateResult | None = None

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

    def need_phrase(self, yearning_id: str) -> str:
        canonical = self._tax.canonical_label("yearning", yearning_id)
        return self._rng.choice(self._data.needs[canonical])

    def metaphor_phrase(self, spectrum_id: str | None, yearning_id: str | None) -> str:
        """A nature image for the spectrum x yearning cell, or a fallback image."""
        grid = self._data.metaphors.by_spectrum_yearning
        if spectrum_id is not None and spectrum_id in grid and yearning_id is not None:
            cell = grid[spectrum_id]
            canonical = self._tax.canonical_label("yearning", yearning_id)
            return self._rng.choice(cell[canonical])
        return self._rng.choice(self._data.metaphors.fallback)

    def safe_mirror(self, user_text: str) -> str:
        """:func:`mirror`, replaced by a neutral line if it would trip the gate."""
        text = apply_willow(mirror(user_text), ContentKind.NORMAL, self._data.willow)
        if not text or self._gate.reasons(text, kind=ContentKind.NORMAL, stage=HelpStage.S_EXPLORE):
            return FALLBACK_MIRROR
        return text

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
    ) -> Slots:
        return Slots(
            user_name=user_name,
            agent_name=agent_name,
            emotion=self.emotion_word(emotion_id) if emotion_id is not None else "",
            mirror=self.safe_mirror(user_text) if user_text.strip() else "",
            metaphor=self.metaphor_phrase(spectrum_id, yearning_id),
            need=self.need_phrase(yearning_id) if yearning_id is not None else "",
            card_title=card_title,
        )

    # -- normal stages ---------------------------------------------------------------------

    def compose(
        self,
        stage: HelpStage,
        slots: Slots,
        *,
        card: str = "",
        light: bool = False,
        returning_after_crisis: bool = False,
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
        """
        if stage is HelpStage.S_CRISIS:
            raise ValueError("S_crisis replies are rendered by render_crisis")
        if stage is HelpStage.S_EMPOWER and not card.strip():
            raise ValueError("S_empower needs the rendered card body")
        if light and stage is not HelpStage.S_EMPOWER:
            raise ValueError("only S_empower has a light bridge")
        values = slots.values()
        pools = self._pools(stage, returning_after_crisis)
        if light:
            pools[0] = self._data.templates.light_bridge
        usable = [[v for v in pool if all(values[s] for s in slots_of(v))] for pool in pools]
        if any(not pool for pool in usable):
            raise ValueError(f"{stage}: no template variant can be filled from these slots")
        combos = list(itertools.product(*usable))
        self._rng.shuffle(combos)
        best: tuple[float, str] | None = None
        for combo in combos:
            text = apply_willow(
                "\n\n".join(_fill(part, values) for part in combo),
                ContentKind.NORMAL,
                self._data.willow,
            )
            penalty = self.window_penalty(stage, text)
            if penalty == 0:
                best = (0.0, text)
                break
            if best is None or penalty < best[0]:
                best = (penalty, text)
        assert best is not None
        text = best[1]
        if stage is HelpStage.S_EMPOWER:
            head, sep, tail = text.rpartition("\n\n")
            text = f"{head}{sep}{card.strip()}\n\n{tail}"
        return self._checked(text, ContentKind.NORMAL, stage)

    def window_penalty(self, stage: HelpStage, text: str) -> float:
        """SDD §5.3 cadence penalty (κ = 1) plus paragraph overflow; 0 means it fits."""
        tpl = self._data.templates
        if stage is HelpStage.S_HAVEN:
            low, high = tpl.haven_window
            penalty = 0.0 if "\n" not in text else float(high) ** 2
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

    def _pools(self, stage: HelpStage, returning: bool) -> list[Sequence[str]]:
        tpl = self._data.templates
        if stage in tpl.parts:
            pools: list[Sequence[str]] = [part.variants for part in tpl.parts[stage]]
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

    def render_card(self, skeleton: ActionSkeleton) -> str:
        """The card body for an exercise skeleton (title, intro, safety, steps, closing)."""
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
        if card.stealth_note is not None:
            tail += f"\n{r.card_stealth_label}{card.stealth_note}"
        blocks.append(tail)
        text = apply_willow("\n\n".join(blocks), ContentKind.CARD, self._data.willow)
        return self._checked(text, ContentKind.CARD, HelpStage.S_EMPOWER)

    def render_info(self, method_id: str) -> str:
        """The Grade B/C psychoeducation card; raises ``ValueError`` for other ids."""
        entry = self._data.info.get(method_id)
        if entry is None:
            raise ValueError(f"{method_id} has no Grade B/C information card")
        kind = (
            ContentKind.GRADE_B_INFO
            if entry.grade is SafetyGrade.GRADE_B
            else ContentKind.GRADE_C_INFO
        )
        r = self._data.render
        text = "\n".join(
            [
                f"「{entry.title}」",
                f"{r.info_what_label}{entry.what_it_is}",
                f"{r.info_how_label}{entry.how_it_helps}",
                f"{r.info_who_label}{entry.who_offers_it}",
            ]
        )
        text = apply_willow(text, kind, self._data.willow)
        return self._checked(text, kind, HelpStage.S_CLARIFY)

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

    def render_crisis(self, card: ResourceCard, slots: Slots) -> str:
        """S_crisis wording plus the card's numbers: emergency first, stale entries marked.

        Exempt from word windows and metaphors. If the gate ever blocks the full card, the
        reply falls back to a minimal card that still lists every number, never to a line
        without numbers.
        """
        if card.mode is not CardMode.CRISIS or card.level < CrisisLevel.L2:
            raise ValueError("render_crisis needs a CRISIS-mode card at L2 or L3")
        values = slots.values()
        usable = [t for t in self._data.templates.crisis if all(values[s] for s in slots_of(t))]
        if not usable:
            raise ValueError("no S_crisis variant can be filled from these slots")
        blocks = [_fill(self._rng.choice(usable), values), *self._resource_blocks(card)]
        text = apply_willow("\n\n".join(blocks), ContentKind.CRISIS, self._data.willow)
        numbers = _numbers(card)
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

    def _resource_blocks(self, card: ResourceCard) -> list[str]:
        """The card's numbers: emergency first, then lines, stale entries marked."""
        r = self._data.render
        stale = set(card.stale_entries)
        mark = r.crisis_stale_mark
        blocks: list[str] = []
        if card.emergency:
            lines = [r.crisis_emergency_heading[card.level]]
            for em in card.emergency:
                purpose = r.emergency_purposes[em.purpose]
                lines.append(f"· {em.number}（{purpose}）{mark if em.id in stale else ''}")
            if card.level is CrisisLevel.L3:
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


def _fill(template: str, values: dict[str, str]) -> str:
    return _SLOT_RE.sub(lambda m: values[m.group(1)], template)
