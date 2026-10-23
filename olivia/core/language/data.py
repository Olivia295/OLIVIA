"""Strict loaders for the W.I.L.L.O.W. language data (SDD §5).

Ten files feed the language engine:

* ``language/willow.yaml``: didactic rewrites, diagnosis terms, depathologizing
  replacements, protected terms and per-filter exemptions;
* ``language/metaphors.yaml``: spectrum x yearning nature images, a fallback list and
  the dossier imagery per situation code (``by_situation``, plan D-2);
* ``language/needs.yaml``: need phrases per Satir yearning;
* ``language/render.yaml``: labels and fixed sentences around cards;
* ``templates/<persona>.yaml``: per-stage reply templates, one file per persona
  (``PERSONA_TEMPLATE_FILES``, PRD ONB-03); all four are loaded and checked, and
  ``LanguageData.templates`` is the chosen one;
* ``cards/grade_a.yaml``: Grade A follow-along cards;
* ``cards/grade_bc_info.yaml``: Grade B/C psychoeducation entries, the spectrum lenses and
  the Grade B methods each dossier names (``situation_lenses``, plan D-2).

Every file is checked against the taxonomy when loaded. A missing or unknown key, a wrong
type, an unknown slot or a coverage gap raises :class:`LanguageDataError`; nothing is
defaulted.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from importlib import resources
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, TypeVar

import yaml

from olivia.core.models import CrisisLevel, HelpStage, PersonaSpectrum, SafetyGrade
from olivia.core.resources.store import EmergencyPurpose
from olivia.core.taxonomy import Taxonomy

SUPPORTED_VERSION: Final = 1
_E = TypeVar("_E", bound=StrEnum)
SLOT_NAMES: Final = frozenset(
    {"user_name", "agent_name", "emotion", "mirror", "metaphor", "need", "card_title"}
)
FILTER_NAMES: Final = frozenset(
    {"didactic_rewrites", "depathologize", "diagnosis_terms", "word_window", "metaphor_weaving"}
)
_SLOT_RE: Final = re.compile(r"\{([^{}]*)\}")
_CARD_ACTION_TYPES: Final = frozenset({"STABILIZATION", "MICRO_EXERCISE"})
_PART_STAGES: Final = (HelpStage.S_EXPLORE, HelpStage.S_CLARIFY, HelpStage.S_EMPOWER)
PERSONA_TEMPLATE_FILES: Final[Mapping[PersonaSpectrum, str]] = MappingProxyType(
    {
        PersonaSpectrum.GENTLE_HOLDING: "templates/gentle_holding.yaml",
        PersonaSpectrum.ZEN_PHILOSOPHER: "templates/zen_philosopher.yaml",
        PersonaSpectrum.RATIONAL_PEER: "templates/rational_peer.yaml",
        PersonaSpectrum.SILENT_ANCHOR: "templates/silent_anchor.yaml",
    }
)
_PART_NAMES: Final = {
    HelpStage.S_EXPLORE: ("reflect", "image", "invite"),
    HelpStage.S_CLARIFY: ("reflect", "need", "invite"),
    HelpStage.S_EMPOWER: ("bridge", "card_intro"),
}
# SILENT_ANCHOR speaks in one short paragraph ([10, 30] 字, WILLOW-03): S_explore and
# S_clarify have a single ``reflect`` part and no required slots, since a 20-字 mirror
# plus a 16-字 image could not fit that window.
_COMPACT_PERSONAS: Final = frozenset({PersonaSpectrum.SILENT_ANCHOR})
_COMPACT_PART_NAMES: Final = {
    HelpStage.S_EXPLORE: ("reflect",),
    HelpStage.S_CLARIFY: ("reflect",),
    HelpStage.S_EMPOWER: ("bridge", "card_intro"),
}
# Short follow-up lines (roadmap R-7b) and the direct question about intent (decision D3);
# the session fills only the two name slots.
_FOLLOWUPS: Final = (
    "clarify_feedback",
    "kit_empty",
    "closing_declined",
    "safety_check",
    "health_hint",
)
# Anti-dependence prompts (next-phase B7, PRD NG-4 / RSK-07 / §11.1); same slot rules.
_WELLBEING: Final = (
    "break_reminder",
    "break_reminder_haven",
    "late_night",
    "late_night_haven",
    "real_support",
)
_PLAIN_SLOTS: Final = frozenset({"user_name", "agent_name"})
# Slots a part must carry in every variant (the template file's own contract).
_REQUIRED_SLOTS: Final = {
    (HelpStage.S_EXPLORE, "reflect"): frozenset({"mirror", "emotion"}),
    (HelpStage.S_EXPLORE, "image"): frozenset({"metaphor"}),
    (HelpStage.S_CLARIFY, "reflect"): frozenset({"mirror", "emotion"}),
    (HelpStage.S_CLARIFY, "need"): frozenset({"need"}),
    (HelpStage.S_EMPOWER, "card_intro"): frozenset({"card_title"}),
}
_COMPACT_REQUIRED_SLOTS: Final = {
    (HelpStage.S_EMPOWER, "card_intro"): frozenset({"card_title"}),
}


class LanguageDataError(Exception):
    """Raised when language data is missing, malformed or inconsistent with the taxonomy."""


class ContentKind(StrEnum):
    """What a piece of text is; ``willow.yaml`` exemptions are keyed by these names."""

    NORMAL = "NORMAL"
    """Ordinary conversation replies composed from templates."""
    CARD = "CARD"
    """A Grade A or registry follow-along card."""
    GRADE_B_INFO = "GRADE_B_INFO"
    GRADE_C_INFO = "GRADE_C_INFO"
    REFERRAL = "REFERRAL"
    """A Grade C / red-flag specialist referral card."""
    CRISIS = "CRISIS"
    """S_crisis wording and the crisis resource card."""


# -- data classes -------------------------------------------------------------------------


@dataclass(frozen=True)
class WillowData:
    didactic_rewrites: Mapping[str, str]
    diagnosis_terms: tuple[str, ...]
    """Casefolded, as matched."""
    depathologize: Mapping[str, str]
    protected_terms: tuple[str, ...]
    exemptions: Mapping[str, frozenset[ContentKind]]

    def exempt(self, filter_name: str, kind: ContentKind) -> bool:
        if filter_name not in self.exemptions:
            raise LanguageDataError(f"unknown filter: {filter_name}")
        return kind in self.exemptions[filter_name]


def _empty() -> Mapping[str, tuple[str, ...]]:
    return MappingProxyType({})


@dataclass(frozen=True)
class MetaphorData:
    by_spectrum_yearning: Mapping[str, Mapping[str, tuple[str, ...]]]
    fallback: tuple[str, ...]
    by_situation: Mapping[str, tuple[str, ...]] = field(default_factory=_empty)
    """Situation code -> images drawn from its dossier (plan D-2; ``language/dossiers.py``)."""


@dataclass(frozen=True)
class TemplatePart:
    name: str
    variants: tuple[str, ...]


@dataclass(frozen=True)
class Templates:
    persona: PersonaSpectrum
    normal_window: tuple[int, int]
    paragraph_max: int
    haven_window: tuple[int, int]
    empower_window: tuple[int, int]
    """S_empower framing without the card body: ``window.empower``, else the normal window."""
    parts: Mapping[HelpStage, tuple[TemplatePart, ...]]
    """S_explore, S_clarify and S_empower: one variant per part, one paragraph each."""
    after_card: tuple[str, ...]
    light_bridge: tuple[str, ...]
    """S_empower ``bridge`` replacement below the right-wing battery (COLBO-07)."""
    haven: tuple[str, ...]
    crisis: tuple[str, ...]
    closing: tuple[str, ...]
    greeting: tuple[str, ...]
    returning_after_crisis: tuple[str, ...]
    """S_ready, first session after a crisis (A3): a gentle check-in that asks about safety."""
    returning_after_check: tuple[str, ...]
    """S_ready, first session after a no to the D3 question: a lighter check-in."""
    clarify_feedback: tuple[str, ...]
    """One question after an unclear reply to a waiting card: shelve it? (roadmap R-7b)"""
    kit_empty: tuple[str, ...]
    """The kit has nothing to show again."""
    closing_declined: tuple[str, ...]
    """S_closing: the user says no to choosing when to come back to the practice."""
    safety_check: tuple[str, ...]
    """One gentle, direct question about suicidal intent (decision D3), persona-free."""
    break_reminder: tuple[str, ...]
    """A paragraph after an ordinary reply once the session has run 45 minutes (B7)."""
    break_reminder_haven: tuple[str, ...]
    """The same in S_haven, replacing the haven line (no question, haven window)."""
    late_night: tuple[str, ...]
    """Once per session between 00:00 and 05:00 local time: rest, and someone to reach."""
    late_night_haven: tuple[str, ...]
    """The late-night line in S_haven, replacing the haven line (rest only)."""
    real_support: tuple[str, ...]
    """Replaces the S_explore / S_clarify invite: one question about people in the user's
    life (PRD §11.1 real-support share)."""
    health_hint: tuple[str, ...]
    """A heart, breathing or home-safety disclosure heard in the conversation can be
    saved with ``olivia health`` (decision D2, step A1)."""


@dataclass(frozen=True)
class ExerciseCard:
    id: str
    title: str
    duration_minutes: int
    intro: str
    steps: tuple[str, ...]
    closing: str
    stealth_note: str | None
    safety_note: str | None


@dataclass(frozen=True)
class CardDeck:
    cards: Mapping[str, ExerciseCard]
    excluded: Mapping[str, str]
    """Action id -> reason; rendering one of these is refused."""


@dataclass(frozen=True)
class InfoEntry:
    id: str
    title: str
    grade: SafetyGrade
    what_it_is: str
    how_it_helps: str
    who_offers_it: str


@dataclass(frozen=True)
class RenderText:
    card_duration: str
    card_safety_label: str
    card_stealth_label: str
    info_what_label: str
    info_how_label: str
    info_who_label: str
    info_ask_intro: str
    """Leads an information card the user asked for by name."""
    info_lens_intro: str
    """Leads a Grade B card that S_clarify offers as a perspective."""
    info_b_closing: str
    info_c_closing: str
    """Ends a Grade C card: not for trying alone; see a professional."""
    referral_intro: str
    referral_destinations: Mapping[str, str]
    referral_closing: str
    crisis_emergency_heading: Mapping[CrisisLevel, str]
    crisis_lines_heading: str
    crisis_hours_label: str
    crisis_stale_mark: str
    crisis_contact_people: str
    crisis_unknown_region_l3: str
    crisis_minimal: str
    emergency_purposes: Mapping[EmergencyPurpose, str]


@dataclass(frozen=True)
class LanguageData:
    willow: WillowData
    metaphors: MetaphorData
    needs: Mapping[str, tuple[str, ...]]
    render: RenderText
    templates: Templates
    cards: CardDeck
    info: Mapping[str, InfoEntry]
    info_lenses: Mapping[str, tuple[str, ...]]
    """Spectrum id -> the Grade B explainers S_clarify may offer for it (draft, G-0)."""
    personas: Mapping[PersonaSpectrum, Templates]
    """Every persona's templates; ``templates`` is one of them."""
    situation_lenses: Mapping[str, tuple[str, ...]] = field(default_factory=_empty)
    """Situation code -> the Grade B methods its dossier names (plan D-2, draft, G-0)."""

    def for_persona(self, persona: PersonaSpectrum) -> LanguageData:
        """The same data speaking with ``persona``'s templates (PRD ONB-03, plan D-1)."""
        if persona is self.templates.persona:
            return self
        return replace(self, templates=self.personas[persona])


# -- entry point --------------------------------------------------------------------------


def load_language_data(
    tax: Taxonomy,
    root: Path | None = None,
    *,
    persona: PersonaSpectrum = PersonaSpectrum.GENTLE_HOLDING,
) -> LanguageData:
    """Load and validate every language file from ``root`` (default: packaged ``olivia/data``).

    All four persona template files are loaded and checked; ``persona`` picks the one
    ``templates`` holds (switch later with :meth:`LanguageData.for_persona`).
    """
    willow = _parse_willow(_read(root, "language/willow.yaml"))
    info_doc = _read(root, "cards/grade_bc_info.yaml")
    info = _parse_info(info_doc, tax)
    personas = {
        p: _parse_templates(_read(root, rel), p, rel.rsplit("/", 1)[-1])
        for p, rel in PERSONA_TEMPLATE_FILES.items()
    }
    # The direct question about intent (decision D3) is persona-free: one wording for all.
    reference = personas[PersonaSpectrum.GENTLE_HOLDING].safety_check
    for p, tpl in personas.items():
        if tpl.safety_check != reference:
            raise LanguageDataError(
                f"{PERSONA_TEMPLATE_FILES[p]}: followups.safety_check must match gentle_holding"
            )
    return LanguageData(
        willow=willow,
        metaphors=_parse_metaphors(_read(root, "language/metaphors.yaml"), tax),
        needs=_parse_needs(_read(root, "language/needs.yaml"), tax),
        render=_parse_render(_read(root, "language/render.yaml"), tax),
        templates=personas[persona],
        cards=_parse_cards(_read(root, "cards/grade_a.yaml"), tax),
        info=info,
        info_lenses=_parse_lenses(info_doc, info, tax),
        personas=MappingProxyType(personas),
        situation_lenses=_parse_situation_lenses(info_doc, info, tax),
    )


def load_willow(root: Path | None = None) -> WillowData:
    """Load only ``willow.yaml`` (it does not depend on the taxonomy)."""
    return _parse_willow(_read(root, "language/willow.yaml"))


def slots_of(text: str) -> frozenset[str]:
    return frozenset(_SLOT_RE.findall(text))


# -- willow.yaml --------------------------------------------------------------------------


def _parse_willow(data: Mapping[str, Any]) -> WillowData:
    where = "willow.yaml"
    _keys(
        data,
        {
            "version",
            "didactic_rewrites",
            "diagnosis_terms",
            "depathologize",
            "protected_terms",
            "exemptions",
        },
        where,
    )
    _version(data, where)
    rewrites = _pairs(data["didactic_rewrites"], "pattern", "rewrite", f"{where} didactic_rewrites")
    depath = _pairs(data["depathologize"], "term", "replacement", f"{where} depathologize")
    diagnosis = _unique(
        tuple(t.casefold() for t in _strs(data["diagnosis_terms"], f"{where} diagnosis_terms")),
        f"{where} diagnosis_terms",
    )
    protected = _unique(_strs(data["protected_terms"], f"{where} protected_terms"), where)
    raw_ex = _map(data["exemptions"], f"{where} exemptions")
    _keys(raw_ex, FILTER_NAMES, f"{where} exemptions")
    exemptions: dict[str, frozenset[ContentKind]] = {}
    for name in sorted(FILTER_NAMES):
        kinds = _strs(raw_ex[name], f"{where} exemptions.{name}", allow_empty=True)
        exemptions[name] = frozenset(_enum(ContentKind, k, f"{where} exemptions") for k in kinds)
    if exemptions["diagnosis_terms"]:
        raise LanguageDataError(f"{where}: the diagnosis gate must have no exemptions")
    return WillowData(
        didactic_rewrites=MappingProxyType(rewrites),
        diagnosis_terms=diagnosis,
        depathologize=MappingProxyType(depath),
        protected_terms=protected,
        exemptions=MappingProxyType(exemptions),
    )


# -- metaphors.yaml / needs.yaml ----------------------------------------------------------


def _parse_metaphors(data: Mapping[str, Any], tax: Taxonomy) -> MetaphorData:
    where = "metaphors.yaml"
    _keys(data, {"version", "by_spectrum_yearning", "fallback"}, where, optional={"by_situation"})
    _version(data, where)
    grid_raw = _map(data["by_spectrum_yearning"], f"{where} by_spectrum_yearning")
    spectra = set(tax.spectrum_ids())
    yearnings = set(tax.values("satir_yearnings"))
    _keys(grid_raw, spectra, f"{where} by_spectrum_yearning")
    grid: dict[str, Mapping[str, tuple[str, ...]]] = {}
    for sid in tax.spectrum_ids():
        cell = _map(grid_raw[sid], f"{where} spectrum {sid}")
        _keys(cell, yearnings, f"{where} spectrum {sid}")
        grid[sid] = MappingProxyType(
            {yid: _strs(cell[yid], f"{where} {sid}.{yid}") for yid in sorted(yearnings)}
        )
    return MetaphorData(
        MappingProxyType(grid),
        _strs(data["fallback"], f"{where} fallback"),
        _parse_situation_images(data.get("by_situation", {}), tax),
    )


def _situation_keys(raw: Mapping[str, Any], tax: Taxonomy, where: str) -> list[str]:
    """The keys of a per-situation table: taxonomy situation codes, none a red flag.

    The seven red-flag dossiers belong to the red-flag referral path, never to the
    dossier layer. Returned in taxonomy order.
    """
    codes = tax.situation_codes()
    _keys(raw, set(), where, optional=set(codes))
    flagged = sorted(code for code in raw if code in tax.red_flags())
    if flagged:
        raise LanguageDataError(f"{where}: {flagged} is a red-flag code")
    return [code for code in codes if code in raw]


def _parse_situation_images(node: Any, tax: Taxonomy) -> Mapping[str, tuple[str, ...]]:
    """``by_situation``: situation code -> distinct dossier images (plan D-2)."""
    where = "metaphors.yaml by_situation"
    raw = _map(node, where) if node else {}
    return MappingProxyType(
        {
            code: _unique(_strs(raw[code], f"{where}.{code}"), f"{where}.{code}")
            for code in _situation_keys(raw, tax, where)
        }
    )


def _parse_needs(data: Mapping[str, Any], tax: Taxonomy) -> Mapping[str, tuple[str, ...]]:
    where = "needs.yaml"
    _keys(data, {"version", "by_yearning"}, where)
    _version(data, where)
    raw = _map(data["by_yearning"], f"{where} by_yearning")
    yearnings = tax.values("satir_yearnings")
    _keys(raw, set(yearnings), f"{where} by_yearning")
    return MappingProxyType({yid: _strs(raw[yid], f"{where} {yid}") for yid in yearnings})


# -- render.yaml ---------------------------------------------------------------------------


def _parse_render(data: Mapping[str, Any], tax: Taxonomy) -> RenderText:
    where = "render.yaml"
    _keys(data, {"version", "card", "info", "referral", "crisis"}, where)
    _version(data, where)
    card = _map(data["card"], f"{where} card")
    _keys(card, {"duration", "safety_label", "stealth_label"}, f"{where} card")
    duration = _str(card["duration"], f"{where} card.duration")
    if slots_of(duration) != {"minutes"}:
        raise LanguageDataError(f"{where} card.duration must carry exactly the {{minutes}} slot")
    info = _map(data["info"], f"{where} info")
    _keys(
        info,
        {
            "what_label",
            "how_label",
            "who_label",
            "ask_intro",
            "lens_intro",
            "b_closing",
            "c_closing",
        },
        f"{where} info",
    )
    ref = _map(data["referral"], f"{where} referral")
    _keys(ref, {"intro", "destinations", "closing"}, f"{where} referral")
    dest_raw = _map(ref["destinations"], f"{where} referral.destinations")
    _keys(dest_raw, set(tax.red_flags()), f"{where} referral.destinations")
    crisis = _map(data["crisis"], f"{where} crisis")
    _keys(
        crisis,
        {
            "emergency_heading",
            "lines_heading",
            "hours_label",
            "stale_mark",
            "contact_people",
            "unknown_region_l3",
            "minimal",
            "emergency_purposes",
        },
        f"{where} crisis",
    )
    heading = _map(crisis["emergency_heading"], f"{where} crisis.emergency_heading")
    _keys(heading, {"L2", "L3"}, f"{where} crisis.emergency_heading")
    purposes = _map(crisis["emergency_purposes"], f"{where} crisis.emergency_purposes")
    _keys(purposes, {p.value for p in EmergencyPurpose}, f"{where} crisis.emergency_purposes")
    texts = {
        k: _str(crisis[k], f"{where} crisis.{k}")
        for k in (
            "lines_heading",
            "hours_label",
            "stale_mark",
            "contact_people",
            "unknown_region_l3",
            "minimal",
        )
    }
    render = RenderText(
        card_duration=duration,
        card_safety_label=_str(card["safety_label"], f"{where} card.safety_label"),
        card_stealth_label=_str(card["stealth_label"], f"{where} card.stealth_label"),
        info_what_label=_str(info["what_label"], f"{where} info.what_label"),
        info_how_label=_str(info["how_label"], f"{where} info.how_label"),
        info_who_label=_str(info["who_label"], f"{where} info.who_label"),
        info_ask_intro=_str(info["ask_intro"], f"{where} info.ask_intro"),
        info_lens_intro=_str(info["lens_intro"], f"{where} info.lens_intro"),
        info_b_closing=_str(info["b_closing"], f"{where} info.b_closing"),
        info_c_closing=_str(info["c_closing"], f"{where} info.c_closing"),
        referral_intro=_str(ref["intro"], f"{where} referral.intro"),
        referral_destinations=MappingProxyType(
            {code: _str(dest_raw[code], f"{where} {code}") for code in tax.red_flags()}
        ),
        referral_closing=_str(ref["closing"], f"{where} referral.closing"),
        crisis_emergency_heading=MappingProxyType(
            {
                CrisisLevel.L2: _str(heading["L2"], f"{where} emergency_heading.L2"),
                CrisisLevel.L3: _str(heading["L3"], f"{where} emergency_heading.L3"),
            }
        ),
        crisis_lines_heading=texts["lines_heading"],
        crisis_hours_label=texts["hours_label"],
        crisis_stale_mark=texts["stale_mark"],
        crisis_contact_people=texts["contact_people"],
        crisis_unknown_region_l3=texts["unknown_region_l3"],
        crisis_minimal=texts["minimal"],
        emergency_purposes=MappingProxyType(
            {p: _str(purposes[p.value], f"{where} purpose {p.value}") for p in EmergencyPurpose}
        ),
    )
    for field_name, value in vars(render).items():
        if isinstance(value, str) and field_name != "card_duration" and slots_of(value):
            raise LanguageDataError(f"{where}: {field_name} must not carry slots")
    return render


# -- templates -----------------------------------------------------------------------------


def _parse_templates(data: Mapping[str, Any], owner: PersonaSpectrum, where: str) -> Templates:
    _keys(data, {"persona", "window", "stages", "followups", "wellbeing"}, where)
    persona = _enum(PersonaSpectrum, data["persona"], f"{where} persona")
    if persona is not owner:
        raise LanguageDataError(f"{where}: persona must be {owner.value}")
    compact = persona in _COMPACT_PERSONAS
    part_names = _COMPACT_PART_NAMES if compact else _PART_NAMES
    required_slots = _COMPACT_REQUIRED_SLOTS if compact else _REQUIRED_SLOTS
    window = _map(data["window"], f"{where} window")
    _keys(window, {"normal", "paragraph_max", "haven"}, f"{where} window", optional={"empower"})
    normal_window = _int_pair(window["normal"], f"{where} window.normal")
    stages = _map(data["stages"], f"{where} stages")
    _keys(stages, {s.value for s in HelpStage}, f"{where} stages")

    parts: dict[HelpStage, tuple[TemplatePart, ...]] = {}
    for stage in _PART_STAGES:
        body = _map(stages[stage.value], f"{where} {stage}")
        expected = (
            {"parts", "after_card", "light_bridge"} if stage is HelpStage.S_EMPOWER else {"parts"}
        )
        _keys(body, expected, f"{where} {stage}")
        raw_parts = _list(body["parts"], f"{where} {stage}.parts")
        built: list[TemplatePart] = []
        for raw in raw_parts:
            part = _map(raw, f"{where} {stage} part")
            _keys(part, {"name", "variants"}, f"{where} {stage} part")
            name = _str(part["name"], f"{where} {stage} part name")
            variants = _templates(part["variants"], f"{where} {stage}.{name}")
            required = required_slots.get((stage, name), frozenset())
            for text in variants:
                if not required <= slots_of(text):
                    raise LanguageDataError(f"{where} {stage}.{name}: missing slots in {text!r}")
            built.append(TemplatePart(name, variants))
        if tuple(p.name for p in built) != part_names[stage]:
            raise LanguageDataError(f"{where} {stage}: parts must be {part_names[stage]}")
        parts[stage] = tuple(built)

    empower = _map(stages[HelpStage.S_EMPOWER.value], f"{where} S_empower")
    singles: dict[HelpStage, tuple[str, ...]] = {}
    for stage in (HelpStage.S_HAVEN, HelpStage.S_CRISIS, HelpStage.S_CLOSING):
        body = _map(stages[stage.value], f"{where} {stage}")
        _keys(body, {"variants"}, f"{where} {stage}")
        singles[stage] = _templates(body["variants"], f"{where} {stage}")
    for text in singles[HelpStage.S_CRISIS]:
        if "metaphor" in slots_of(text):
            raise LanguageDataError(f"{where} S_crisis must not weave metaphors: {text!r}")
    ready = _map(stages[HelpStage.S_READY.value], f"{where} S_ready")
    _keys(
        ready, {"greeting", "returning_after_crisis", "returning_after_check"}, f"{where} S_ready"
    )
    if not any(not slots_of(t) for t in singles[HelpStage.S_HAVEN]):
        raise LanguageDataError(f"{where} S_haven needs a slot-free variant for the gate fallback")
    lines = {
        **_plain_lines(data, "followups", _FOLLOWUPS, where),
        **_plain_lines(data, "wellbeing", _WELLBEING, where),
    }
    return Templates(
        persona=persona,
        normal_window=normal_window,
        paragraph_max=_int(window["paragraph_max"], f"{where} window.paragraph_max"),
        haven_window=_int_pair(window["haven"], f"{where} window.haven"),
        empower_window=(
            _int_pair(window["empower"], f"{where} window.empower")
            if "empower" in window
            else normal_window
        ),
        parts=MappingProxyType(parts),
        after_card=_templates(empower["after_card"], f"{where} S_empower.after_card"),
        light_bridge=_templates(empower["light_bridge"], f"{where} S_empower.light_bridge"),
        haven=singles[HelpStage.S_HAVEN],
        crisis=singles[HelpStage.S_CRISIS],
        closing=singles[HelpStage.S_CLOSING],
        greeting=_templates(ready["greeting"], f"{where} S_ready.greeting"),
        returning_after_crisis=_templates(
            ready["returning_after_crisis"], f"{where} S_ready.returning_after_crisis"
        ),
        returning_after_check=_templates(
            ready["returning_after_check"], f"{where} S_ready.returning_after_check"
        ),
        clarify_feedback=lines["clarify_feedback"],
        kit_empty=lines["kit_empty"],
        closing_declined=lines["closing_declined"],
        safety_check=lines["safety_check"],
        health_hint=lines["health_hint"],
        break_reminder=lines["break_reminder"],
        break_reminder_haven=lines["break_reminder_haven"],
        late_night=lines["late_night"],
        late_night_haven=lines["late_night_haven"],
        real_support=lines["real_support"],
    )


def _plain_lines(
    data: Mapping[str, Any], section: str, names: tuple[str, ...], where: str
) -> dict[str, tuple[str, ...]]:
    """Groups of short lines that fill only the name slots, each with a slot-free variant."""
    body = _map(data[section], f"{where} {section}")
    _keys(body, set(names), f"{where} {section}")
    lines: dict[str, tuple[str, ...]] = {}
    for name in names:
        lines[name] = _templates(body[name], f"{where} {section}.{name}")
        for text in lines[name]:
            if slots_of(text) - _PLAIN_SLOTS:
                raise LanguageDataError(
                    f"{where} {section}.{name}: only name slots are filled here: {text!r}"
                )
        if not any(not slots_of(t) for t in lines[name]):
            raise LanguageDataError(f"{where} {section}.{name} needs a slot-free variant")
    return lines


def _templates(node: Any, where: str) -> tuple[str, ...]:
    texts = _strs(node, where)
    for text in texts:
        unknown = slots_of(text) - SLOT_NAMES
        if unknown:
            raise LanguageDataError(f"{where}: unknown slots {sorted(unknown)} in {text!r}")
        if "{" in _SLOT_RE.sub("", text) or "}" in _SLOT_RE.sub("", text):
            raise LanguageDataError(f"{where}: stray brace in {text!r}")
    return texts


# -- cards ---------------------------------------------------------------------------------


def _parse_cards(data: Mapping[str, Any], tax: Taxonomy) -> CardDeck:
    where = "grade_a.yaml"
    _keys(data, {"version", "persona", "cards", "excluded"}, where)
    _version(data, where)
    if data["persona"] != "gentle_holding":
        raise LanguageDataError(f"{where}: persona must be gentle_holding")
    sources = _card_sources(tax)
    cards: dict[str, ExerciseCard] = {}
    for raw in _list(data["cards"], f"{where} cards"):
        item = _map(raw, f"{where} card")
        cid = _str(item.get("id"), f"{where} card id")
        here = f"{where} card {cid}"
        _keys(
            item,
            {"id", "title", "duration_minutes", "intro", "steps", "closing"},
            here,
            optional={"stealth_note", "safety_note"},
        )
        if cid in cards:
            raise LanguageDataError(f"{here}: duplicate id")
        if cid not in sources:
            raise LanguageDataError(f"{here}: not a Grade A method or card-type registry action")
        title, steps, minutes = sources[cid]
        card = ExerciseCard(
            id=cid,
            title=_str(item["title"], f"{here} title"),
            duration_minutes=_int(item["duration_minutes"], f"{here} duration_minutes"),
            intro=_str(item["intro"], f"{here} intro"),
            steps=_strs(item["steps"], f"{here} steps"),
            closing=_str(item["closing"], f"{here} closing"),
            stealth_note=_opt_str(item, "stealth_note", here),
            safety_note=_opt_str(item, "safety_note", here),
        )
        if card.title != title or len(card.steps) != steps or card.duration_minutes != minutes:
            raise LanguageDataError(f"{here}: title, step count or duration differs from taxonomy")
        cards[cid] = card
    excluded: dict[str, str] = {}
    for raw in _list(data["excluded"], f"{where} excluded"):
        item = _map(raw, f"{where} excluded entry")
        _keys(item, {"id", "reason"}, f"{where} excluded entry")
        eid = _str(item["id"], f"{where} excluded id")
        if eid not in sources or eid in cards:
            raise LanguageDataError(f"{where}: excluded id {eid} is unknown or also has a card")
        excluded[eid] = _str(item["reason"], f"{where} excluded {eid} reason")
    missing = set(sources) - set(cards) - set(excluded)
    if missing:
        raise LanguageDataError(f"{where}: no card or exclusion for {sorted(missing)}")
    return CardDeck(MappingProxyType(cards), MappingProxyType(excluded))


def _card_sources(tax: Taxonomy) -> dict[str, tuple[str, int, int]]:
    """Every id that should have a card: id -> (title, step count, minutes)."""
    sources: dict[str, tuple[str, int, int]] = {}
    for mid in tax.grade_a_ids():
        method = tax.methods()[mid]
        if method.duration_minutes is None:
            raise LanguageDataError(f"Grade A method {mid} has no duration in the taxonomy")
        sources[mid] = (method.name_zh, len(method.core_action_steps), method.duration_minutes)
    for aid, action in tax.action_registry().items():
        if action.action_type.value in _CARD_ACTION_TYPES:
            sources[aid] = (action.name_zh, len(action.core_action_steps), action.duration_minutes)
    return sources


def _parse_info(data: Mapping[str, Any], tax: Taxonomy) -> Mapping[str, InfoEntry]:
    where = "grade_bc_info.yaml"
    _keys(data, {"entries", "clarify_lenses"}, where, optional={"situation_lenses"})
    grades = {"B": SafetyGrade.GRADE_B, "C": SafetyGrade.GRADE_C}
    entries: dict[str, InfoEntry] = {}
    for raw in _list(data["entries"], f"{where} entries"):
        item = _map(raw, f"{where} entry")
        eid = str(item.get("id"))
        here = f"{where} entry {eid}"
        _keys(
            item,
            {"id", "title", "grade", "what_it_is", "how_it_helps", "who_offers_it", "try_alone"},
            here,
        )
        if eid in entries:
            raise LanguageDataError(f"{here}: duplicate id")
        method = tax.methods().get(eid)
        grade = grades.get(str(item["grade"]))
        if method is None or grade is None or method.grade is not grade:
            raise LanguageDataError(f"{here}: grade does not match the taxonomy")
        if item["try_alone"] is not False:
            raise LanguageDataError(f"{here}: try_alone must be false")
        entry = InfoEntry(
            id=eid,
            title=_str(item["title"], f"{here} title"),
            grade=grade,
            what_it_is=_str(item["what_it_is"], f"{here} what_it_is"),
            how_it_helps=_str(item["how_it_helps"], f"{here} how_it_helps"),
            who_offers_it=_str(item["who_offers_it"], f"{here} who_offers_it"),
        )
        if entry.title != method.name_zh:
            raise LanguageDataError(f"{here}: title differs from the taxonomy name")
        entries[eid] = entry
    expected = {m.id for m in tax.methods().values() if m.grade is not SafetyGrade.GRADE_A}
    if set(entries) != expected:
        raise LanguageDataError(f"{where}: entries must cover exactly the Grade B/C methods")
    return MappingProxyType(entries)


def _parse_lenses(
    data: Mapping[str, Any], info: Mapping[str, InfoEntry], tax: Taxonomy
) -> Mapping[str, tuple[str, ...]]:
    """``clarify_lenses``: spectrum id -> distinct Grade B ids that have an entry."""
    where = "grade_bc_info.yaml clarify_lenses"
    raw = _map(data["clarify_lenses"], where)
    _keys(raw, set(), where, optional=set(tax.spectrum_ids()))
    lenses: dict[str, tuple[str, ...]] = {}
    for spectrum in tax.spectrum_ids():
        if spectrum not in raw:
            continue
        ids = _unique(_strs(raw[spectrum], f"{where}.{spectrum}"), f"{where}.{spectrum}")
        for mid in ids:
            entry = info.get(mid)
            if entry is None or entry.grade is not SafetyGrade.GRADE_B:
                raise LanguageDataError(f"{where}.{spectrum}: {mid} is not a Grade B method")
        lenses[spectrum] = ids
    return MappingProxyType(lenses)


def _parse_situation_lenses(
    data: Mapping[str, Any], info: Mapping[str, InfoEntry], tax: Taxonomy
) -> Mapping[str, tuple[str, ...]]:
    """``situation_lenses``: situation code -> distinct Grade B ids the dossier names.

    Grade C stays out: it is shown only when the user asks about it by name.
    """
    where = "grade_bc_info.yaml situation_lenses"
    node = data.get("situation_lenses", {})
    raw = _map(node, where) if node else {}
    lenses: dict[str, tuple[str, ...]] = {}
    for code in _situation_keys(raw, tax, where):
        ids = _unique(_strs(raw[code], f"{where}.{code}"), f"{where}.{code}")
        for mid in ids:
            entry = info.get(mid)
            if entry is None or entry.grade is not SafetyGrade.GRADE_B:
                raise LanguageDataError(f"{where}.{code}: {mid} is not a Grade B method")
        lenses[code] = ids
    return MappingProxyType(lenses)


# -- primitives ----------------------------------------------------------------------------


def _read(root: Path | None, rel: str) -> Mapping[str, Any]:
    try:
        if root is None:
            text = resources.files("olivia").joinpath(f"data/{rel}").read_text("utf-8")
        else:
            text = (root / rel).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise LanguageDataError(f"cannot read {rel}: {exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise LanguageDataError(f"invalid YAML in {rel}: {exc}") from exc
    return _map(data, rel)


def _keys(
    node: Mapping[str, Any],
    required: set[str] | frozenset[str],
    where: str,
    optional: set[str] | frozenset[str] = frozenset(),
) -> None:
    keys = {str(k) for k in node}
    missing = set(required) - keys
    unknown = keys - set(required) - set(optional)
    if missing or unknown:
        raise LanguageDataError(
            f"{where}: missing keys {sorted(missing)}, unknown {sorted(unknown)}"
        )


def _version(data: Mapping[str, Any], where: str) -> None:
    version = data["version"]
    if type(version) is not int or version != SUPPORTED_VERSION:
        raise LanguageDataError(f"{where}: unsupported version {version!r}")


def _map(node: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(node, Mapping):
        raise LanguageDataError(f"{where} is missing or not a mapping")
    return {str(k): v for k, v in node.items()}


def _list(node: Any, where: str) -> list[Any]:
    if not isinstance(node, list) or not node:
        raise LanguageDataError(f"{where} is missing or not a non-empty list")
    return node


def _str(node: Any, where: str) -> str:
    if not isinstance(node, str) or not node.strip():
        raise LanguageDataError(f"{where} is missing or not a non-empty string")
    return node


def _opt_str(item: Mapping[str, Any], key: str, where: str) -> str | None:
    return _str(item[key], f"{where} {key}") if key in item else None


def _strs(node: Any, where: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if allow_empty and node == []:
        return ()
    return tuple(_str(item, where) for item in _list(node, where))


def _unique(items: tuple[str, ...], where: str) -> tuple[str, ...]:
    if len(set(items)) != len(items):
        raise LanguageDataError(f"{where}: duplicate entries")
    return items


def _pairs(node: Any, key: str, value: str, where: str) -> dict[str, str]:
    table: dict[str, str] = {}
    for raw in _list(node, where):
        item = _map(raw, where)
        _keys(item, {key, value}, where)
        k = _str(item[key], f"{where} {key}")
        if k in table:
            raise LanguageDataError(f"{where}: duplicate {key} {k!r}")
        table[k] = _str(item[value], f"{where} {value}")
    return table


def _int(node: Any, where: str) -> int:
    if type(node) is not int or node <= 0:
        raise LanguageDataError(f"{where} must be a positive integer")
    return node


def _int_pair(node: Any, where: str) -> tuple[int, int]:
    if not isinstance(node, list) or len(node) != 2:
        raise LanguageDataError(f"{where} must be a [low, high] pair")
    low, high = _int(node[0], where), _int(node[1], where)
    if low > high:
        raise LanguageDataError(f"{where}: low exceeds high")
    return low, high


def _enum(cls: type[_E], value: Any, where: str) -> _E:
    try:
        return cls(value)
    except ValueError:
        raise LanguageDataError(f"{where}: unknown value {value!r}") from None
