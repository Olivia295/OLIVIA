"""Crisis and red-flag lexicons with strict load-time validation.

A later task builds one Aho-Corasick matcher over every risk phrase keyed by cue
id, so any ambiguity (shared ids, shared phrases, out-of-band scores) must be
rejected here rather than resolved at match time.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Literal, get_args

import yaml

from olivia.core.models import CrisisLevel
from olivia.core.safety.normalize import fold_words, normalize
from olivia.core.taxonomy import Taxonomy
from olivia.core.yaml_load import safe_load

RiskSection = Literal["stage1", "stage2", "hyperbole", "negation", "safety_confirm", "confirm_veto"]
RedFlagTier = Literal["SELF_REPORT", "FEATURE"]

_RISK_FILE: Final = "risk.yaml"
_RED_FLAG_FILE: Final = "red_flags.yaml"
_SECTIONS: Final[tuple[RiskSection, ...]] = get_args(RiskSection)
_PAIR_SECTION: Final = "stage2_pairs"
_ASK_SECTION: Final = "stage2_ask"
_ASK_ID_PREFIX: Final = "ASK_INTENT"
_ANSWER_SECTION: Final = "intent_answers"
_ANSWER_LISTS: Final = ("deny_whole", "deny_start", "affirm_start", "unsure")
_PAIR_ROLES: Final = ("anchors", "requests", "exceptions")
_COMP_SECTION: Final = "compositions"
_DENIAL_SECTION: Final = "denial"
_DENIAL_LISTS: Final = ("phrases", "negators", "contrasts", "vetoes")
_RECALL_SECTION: Final = "recall_cap"
_PERCEPTION_FILE: Final = "perception.yaml"
# perception.yaml's note recall sections (F15), the one source of these phrases.
_RECALL_QUESTION_SECTIONS: Final = ("note_recall", "note_recall_questions")
_COMP_GLOBAL_LISTS: Final = (
    "negators",
    "non_negators",
    "selves",
    "others",
    "recipients",
    "listeners",
)
_COMP_KEYS: Final = frozenset(
    {"stops", "lookback", "subject_window", "lists", "entries", *_COMP_GLOBAL_LISTS}
)
_COMP_PHRASE_KEYS: Final = (
    "heads",
    "tails",
    "context",
    "unless",
    "exceptions",
    "blockers",
    "trailing",
)
_COMP_ENTRY_KEYS: Final = frozenset(
    {
        "id",
        "level",
        "max_gap",
        "order",
        "context_window",
        "unless_window",
        "persons",
        *_COMP_PHRASE_KEYS,
    }
)
_COMP_LEVELS: Final = ("L1", "L2", "L3", "ASK")
_COMP_ORDERS: Final = ("head_first", "either")
_STAGE1_ID_PREFIX: Final = "S1_"
# Upper bounds that keep a composition local: a gap or window wider than a short clause
# would join words that have nothing to do with each other.
_MAX_GAP: Final = 12
_MAX_WINDOW: Final = 24
_TIERS: Final[tuple[RedFlagTier, ...]] = get_args(RedFlagTier)
_SCORE_KEY_BY_SECTION: Final[Mapping[str, str]] = MappingProxyType(
    {"stage1": "L3", "hyperbole": "HYPERBOLE"}
)
_STAGE2_LEVELS: Final = (CrisisLevel.L1, CrisisLevel.L2)


class LexiconError(Exception):
    """Raised when a lexicon file is missing, malformed, or internally inconsistent."""


@dataclass(frozen=True)
class RiskCue:
    id: str
    section: RiskSection
    level: CrisisLevel | None
    score: float | None
    patterns: tuple[str, ...]


@dataclass(frozen=True)
class PairCue:
    """Stage 2 cue that needs two phrases in one message: a request and an anchor.

    It fires when some ``requests`` phrase and some ``anchors`` phrase both occur, except
    that an anchor occurrence lying wholly inside one of the entry's own ``exceptions``
    (a benign sense such as 预防自杀) does not count. Negation and hyperbole masks never
    apply to pair cues, so they cannot hide a method request.
    """

    id: str
    level: CrisisLevel
    score: float
    anchors: tuple[str, ...]
    requests: tuple[str, ...]
    exceptions: tuple[str, ...]


@dataclass(frozen=True)
class Composition:
    """A cue built from two phrase lists joined across a short gap (fix F1).

    It matches a ``heads`` occurrence followed, within ``max_gap`` characters and with no
    clause punctuation in between, by a ``tails`` occurrence (either order with
    ``either_order``); with no ``tails`` a head occurrence alone is the match. A match is
    rejected when a part lies wholly inside one of ``exceptions``, a ``blockers`` phrase
    lies in the gap, a negator sits in the gap or just before the first part, the last
    person word before the second part names someone else (``persons``), no ``context``
    phrase lies within ``context_window`` characters of it (anywhere when the window is
    None), or an ``unless`` phrase lies within ``unless_window`` characters of it in the
    same clause. With ``trailing``, the match must also end its clause: only ``trailing``
    phrases (sentence particles such as 了, 吧) may stand between it and the next clause
    punctuation or the end of the message. ``ask`` marks a D3 cue (L1); a level of L3 is
    Stage 1 plan evidence.
    """

    id: str
    level: CrisisLevel
    score: float
    ask: bool
    heads: tuple[str, ...]
    tails: tuple[str, ...] = ()
    max_gap: int = 0
    either_order: bool = False
    context: tuple[str, ...] = ()
    context_window: int | None = None
    unless: tuple[str, ...] = ()
    unless_window: int = 0
    exceptions: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    persons: bool = True
    trailing: tuple[str, ...] | None = None
    """None: anything may follow the match. Otherwise the match ends its clause: only
    these phrases may follow it before the clause punctuation or the end of the text."""


@dataclass(frozen=True)
class CompositionRules:
    """The ``compositions`` section: shared word lists and the entries that use them."""

    stops: frozenset[str] = frozenset()
    """Clause punctuation (folded). A gap never crosses it; the person, negation and
    ``unless`` windows stop at it."""
    lookback: int = 0
    """How many characters before the first part a negator still negates it."""
    subject_window: int = 0
    """How many characters before the second part a person word can be its subject."""
    negators: tuple[str, ...] = ()
    non_negators: tuple[str, ...] = ()
    """Words that contain a negator without negating anything (忍不住, 要不, 差不多)."""
    selves: tuple[str, ...] = ()
    others: tuple[str, ...] = ()
    recipients: tuple[str, ...] = ()
    """A person word right after one of these (跟她说, 给我妈) is an object, not a subject."""
    listeners: tuple[str, ...] = ()
    """The person spoken to (你): never carried over as the subject of a later clause."""
    entries: tuple[Composition, ...] = ()


@dataclass(frozen=True)
class IntentAnswers:
    """Phrases for reading the answer to the D3 question (``safety/intent_check.py``).

    Folded with :func:`~olivia.core.safety.normalize.fold_words` (spaces kept). No phrase
    is both a yes and a no; ``unsure`` may repeat a yes phrase (有一点).
    """

    deny_whole: tuple[str, ...] = ()
    """The first clause is exactly one of these (trailing particles aside): a plain no."""
    deny_start: tuple[str, ...] = ()
    """The first clause starts with one of these: a no in its own words."""
    affirm_start: tuple[str, ...] = ()
    """The first clause starts with one of these: a yes."""
    unsure: tuple[str, ...] = ()
    """Anywhere in the message, these void a no (但是, 有一点, 不知道, maybe ...)."""


@dataclass(frozen=True)
class DenialRules:
    """The ``denial`` section (F10): a first-person denial or all-clear outside a crisis.

    Where every Stage 2 phrase of a message lies inside a ``phrases`` hit and the rules
    rate the message L0, an injected model's level counts at most as L1 (``crisis.py``),
    unless a ``negators`` word stands right before the denial (a double negation), a
    ``contrasts`` word follows it, or a ``vetoes`` phrase (means, plan, time, farewell,
    preparation, hedge or retraction) lies anywhere in the message. Folded with
    :func:`~olivia.core.safety.normalize.normalize`; no phrase contains a contrast or a
    veto, since it could then never apply. Empty when the section is absent: no cap.
    """

    phrases: tuple[str, ...] = ()
    negators: tuple[str, ...] = ()
    contrasts: tuple[str, ...] = ()
    vetoes: tuple[str, ...] = ()


@dataclass(frozen=True)
class RecallCapRules:
    """The ``recall_cap`` section (F16a): a question about a note, and nothing else.

    Where the rules rate a message L0, no phrase of the risk, pair, composition or denial
    sections occurs in it, a ``questions`` phrase does and no ``vetoes`` phrase does, an
    injected model's level counts at most as L1 (``crisis.py``). ``questions`` are
    perception.yaml's ``note_recall`` and ``note_recall_questions`` phrases (F15), read
    from the same directory; ``vetoes`` are means, death and farewell words that keep the
    model's level. Folded with :func:`~olivia.core.safety.normalize.normalize`; no question
    contains a veto. Empty when the section (or perception.yaml) is absent: no cap.
    """

    questions: tuple[str, ...] = ()
    vetoes: tuple[str, ...] = ()


@dataclass(frozen=True)
class RedFlagCue:
    id: str
    code: str
    tier: RedFlagTier
    patterns: tuple[str, ...]


@dataclass(frozen=True)
class SafetyLexicons:
    risk: Mapping[str, RiskCue]
    red_flags: Mapping[str, RedFlagCue]
    self_report_negations: tuple[str, ...]
    pairs: tuple[PairCue, ...] = ()
    ask_pairs: tuple[PairCue, ...] = ()
    """L1 ``ASK_INTENT`` cues (decision D3), matched like ``pairs``: the session asks about
    intent when one fires on a turn below L2."""
    intent_answers: IntentAnswers = IntentAnswers()
    compositions: CompositionRules = CompositionRules()
    denial: DenialRules = DenialRules()
    recall_cap: RecallCapRules = RecallCapRules()

    def cues(self, section: RiskSection) -> tuple[RiskCue, ...]:
        return tuple(cue for cue in self.risk.values() if cue.section == section)


def load_safety_lexicons(tax: Taxonomy, directory: Path | None = None) -> SafetyLexicons:
    """Load and validate both lexicon files; ``None`` reads the packaged copies."""
    base: Traversable | Path = (
        resources.files("olivia").joinpath("data/lexicons") if directory is None else directory
    )
    risk_doc = _read_yaml(base, _RISK_FILE)
    flag_doc = _read_yaml(base, _RED_FLAG_FILE)
    seen_ids: dict[str, str] = {}
    risk = _parse_risk(tax, risk_doc, seen_ids)
    pairs = _parse_pairs(tax, risk_doc, seen_ids, risk, _PAIR_SECTION)
    ask_pairs = _parse_pairs(tax, risk_doc, seen_ids, risk, _ASK_SECTION)
    compositions = _parse_compositions(tax, risk_doc, seen_ids)
    # Composition ask cues do not make the answers required: without them every answer
    # reads as unclear, which the session treats as L2 (fail-safe).
    answers = _parse_answers(risk_doc, required=bool(ask_pairs))
    denial = _parse_denial(risk_doc)
    recall_cap = _parse_recall_cap(base, risk_doc)
    red_flags, negations = _parse_red_flags(tax, flag_doc, seen_ids)
    return SafetyLexicons(
        risk=MappingProxyType(risk),
        red_flags=MappingProxyType(red_flags),
        self_report_negations=negations,
        pairs=pairs,
        ask_pairs=ask_pairs,
        intent_answers=answers,
        compositions=compositions,
        denial=denial,
        recall_cap=recall_cap,
    )


# -- file access -------------------------------------------------------------------


def _read_yaml(base: Traversable | Path, name: str) -> dict[str, Any]:
    try:
        text = base.joinpath(name).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise LexiconError(f"{name}: cannot read lexicon file: {exc}") from exc
    try:
        doc = safe_load(text)
    except yaml.YAMLError as exc:
        raise LexiconError(f"{name}: invalid YAML: {exc}") from exc
    if not isinstance(doc, dict):
        raise LexiconError(f"{name}: top level must be a mapping")
    version = doc.get("version")
    if type(version) is not int or version != 1:
        raise LexiconError(f"{name}: top-level 'version' must be 1, got {version!r}")
    return doc


# -- shared helpers ----------------------------------------------------------------


def _check_keys(item: Mapping[str, Any], allowed: set[str], where: str) -> None:
    extra = sorted(str(key) for key in item if key not in allowed)
    if extra:
        raise LexiconError(f"{where}: unknown keys {extra}")


def _entry_list(doc: Mapping[str, Any], key: str, file: str) -> list[Mapping[str, Any]]:
    node = doc.get(key)
    if not isinstance(node, list):
        raise LexiconError(f"{file}: '{key}' must be a list")
    entries: list[Mapping[str, Any]] = []
    for index, item in enumerate(node):
        if not isinstance(item, dict):
            raise LexiconError(f"{file}: {key}[{index}] must be a mapping")
        entries.append(item)
    return entries


def _entry_id(item: Mapping[str, Any], where: str, seen_ids: dict[str, str]) -> str:
    raw = item.get("id")
    if not isinstance(raw, str) or not raw.strip() or not raw.isprintable():
        raise LexiconError(f"{where}: 'id' must be a non-empty printable string")
    if raw in seen_ids:
        raise LexiconError(f"duplicate id {raw}: used in {seen_ids[raw]} and {where}")
    seen_ids[raw] = where
    return raw


def _normalized_list(node: Any, where: str) -> tuple[str, ...]:
    if not isinstance(node, list) or not node:
        raise LexiconError(f"{where}: 'patterns' must be a non-empty list")
    out: list[str] = []
    for raw in node:
        if not isinstance(raw, str):
            raise LexiconError(f"{where}: pattern {raw!r} is not a string")
        folded = normalize(raw)
        if not folded:
            raise LexiconError(f"{where}: pattern {raw!r} is empty after normalization")
        out.append(folded)
    return tuple(out)


def _claim_patterns(
    patterns: tuple[str, ...], cue_id: str, owners: dict[str, str], file: str
) -> None:
    """Reject a normalized phrase that two entries (or one entry twice) both own."""
    for phrase in patterns:
        owner = owners.setdefault(phrase, cue_id)
        if owner == cue_id and patterns.count(phrase) == 1:
            continue
        raise LexiconError(
            f"{file}: phrase {phrase!r} appears in both {owner} and {cue_id}"
            if owner != cue_id
            else f"{file}: phrase {phrase!r} is repeated within {cue_id}"
        )


# -- risk.yaml ---------------------------------------------------------------------


def _parse_risk(
    tax: Taxonomy, doc: Mapping[str, Any], seen_ids: dict[str, str]
) -> dict[str, RiskCue]:
    allowed = {
        "version",
        *_SECTIONS,
        _PAIR_SECTION,
        _ASK_SECTION,
        _ANSWER_SECTION,
        _COMP_SECTION,
        _DENIAL_SECTION,
        _RECALL_SECTION,
    }
    _check_keys(doc, allowed, _RISK_FILE)
    owners: dict[str, str] = {}
    cues: dict[str, RiskCue] = {}
    for section in _SECTIONS:
        for item in _entry_list(doc, section, _RISK_FILE):
            where = f"{_RISK_FILE} {section} entry {item.get('id')!r}"
            cue_id = _entry_id(item, where, seen_ids)
            where = f"{_RISK_FILE} {section} entry {cue_id}"
            _check_keys(item, {"id", "level", "score", "patterns"}, where)
            patterns = _normalized_list(item.get("patterns"), where)
            _claim_patterns(patterns, cue_id, owners, _RISK_FILE)
            level, score = _level_and_score(tax, section, item, where)
            cues[cue_id] = RiskCue(cue_id, section, level, score, patterns)
    return cues


def _level_and_score(
    tax: Taxonomy, section: RiskSection, item: Mapping[str, Any], where: str
) -> tuple[CrisisLevel | None, float | None]:
    if section == "stage2":
        return _stage2_level_and_score(tax, item, where)
    if "level" in item or "score" in item:
        raise LexiconError(f"{where}: 'level' and 'score' are only allowed in stage2")
    if section in ("negation", "safety_confirm", "confirm_veto"):
        return None, None
    key = _SCORE_KEY_BY_SECTION[section]
    level = CrisisLevel.L3 if section == "stage1" else CrisisLevel.L0
    return level, tax.threshold(f"risk.lexicon_scores.{key}")


def _stage2_level_and_score(
    tax: Taxonomy, item: Mapping[str, Any], where: str
) -> tuple[CrisisLevel, float]:
    raw = item.get("level")
    level = next((lv for lv in _STAGE2_LEVELS if lv.name == raw), None)
    if level is None:
        raise LexiconError(f"{where}: stage2 level must be L1 or L2, got {raw!r}")
    if "score" not in item:
        return level, tax.threshold(f"risk.lexicon_scores.{level.name}")
    raw_score = item["score"]
    if isinstance(raw_score, bool) or not isinstance(raw_score, int | float):
        raise LexiconError(f"{where}: score must be a number, got {raw_score!r}")
    score = float(raw_score)
    if not math.isfinite(score) or not 0.0 <= score <= 1.0:
        raise LexiconError(f"{where}: score {raw_score!r} is outside [0, 1]")
    if tax.crisis_level_for_score(score) != level:
        raise LexiconError(f"{where}: score {score} does not fall in the {level.name} band")
    return level, score


def _parse_pairs(
    tax: Taxonomy,
    doc: Mapping[str, Any],
    seen_ids: dict[str, str],
    risk: Mapping[str, RiskCue],
    section: str,
) -> tuple[PairCue, ...]:
    """Parse an optional pair section (``stage2_pairs`` or ``stage2_ask``).

    Pair phrases share the screen's one matcher with the risk cues, so none may repeat a
    risk phrase; across pair entries (of either section) a phrase may repeat, within one
    entry it may not. ``stage2_ask`` entries carry no level or score: they are always L1
    at the taxonomy's L1 score, and their ids start with ``ASK_INTENT``.
    """
    if section not in doc:
        return ()
    ask = section == _ASK_SECTION
    keys = {"id", *_PAIR_ROLES} if ask else {"id", "level", "score", *_PAIR_ROLES}
    risk_owner = {phrase: cue.id for cue in risk.values() for phrase in cue.patterns}
    pairs: list[PairCue] = []
    for item in _entry_list(doc, section, _RISK_FILE):
        where = f"{_RISK_FILE} {section} entry {item.get('id')!r}"
        cue_id = _entry_id(item, where, seen_ids)
        where = f"{_RISK_FILE} {section} entry {cue_id}"
        _check_keys(item, keys, where)
        if ask and not cue_id.startswith(_ASK_ID_PREFIX):
            raise LexiconError(f"{where}: an ask cue id must start with {_ASK_ID_PREFIX}")
        lists = {
            role: _normalized_list(item[role], f"{where} {role}") if role in item else ()
            for role in _PAIR_ROLES
        }
        for role in ("anchors", "requests"):
            if not lists[role]:
                raise LexiconError(f"{where}: '{role}' must be a non-empty list")
        role_of: dict[str, str] = {}
        for role, phrases in lists.items():
            for phrase in phrases:
                if phrase in risk_owner:
                    raise LexiconError(
                        f"{where}: phrase {phrase!r} is already a {risk_owner[phrase]} pattern"
                    )
                if phrase in role_of:
                    raise LexiconError(
                        f"{where}: phrase {phrase!r} is repeated in {role_of[phrase]} and {role}"
                    )
                role_of[phrase] = role
        anchors, requests, exceptions = (lists[role] for role in _PAIR_ROLES)
        for phrase in exceptions:
            if not any(anchor in phrase for anchor in anchors):
                raise LexiconError(f"{where}: exception {phrase!r} contains none of the anchors")
        if ask:
            level, score = CrisisLevel.L1, tax.threshold("risk.lexicon_scores.L1")
        else:
            level, score = _stage2_level_and_score(tax, item, where)
        pairs.append(PairCue(cue_id, level, score, anchors, requests, exceptions))
    return tuple(pairs)


def _parse_compositions(
    tax: Taxonomy, doc: Mapping[str, Any], seen_ids: dict[str, str]
) -> CompositionRules:
    """Parse the optional ``compositions`` section (fix F1).

    Its phrases go to a matcher of their own, so they may repeat a phrase of any other
    section. ``lists`` holds named phrase lists that entries refer to by name; an entry
    may also give a list inline.
    """
    if _COMP_SECTION not in doc:
        return CompositionRules()
    where = f"{_RISK_FILE} {_COMP_SECTION}"
    node = doc[_COMP_SECTION]
    if not isinstance(node, dict):
        raise LexiconError(f"{where}: must be a mapping")
    _check_keys(node, set(_COMP_KEYS), where)
    raw_stops = node.get("stops")
    stops = frozenset(normalize(raw_stops)) if isinstance(raw_stops, str) else frozenset()
    if not stops:
        raise LexiconError(f"{where}: 'stops' must be a non-empty string of punctuation")
    lookback = _bounded_int(node.get("lookback"), 0, 8, f"{where} lookback")
    subject_window = _bounded_int(node.get("subject_window"), 0, 16, f"{where} subject_window")
    shared = {
        name: _normalized_list(node.get(name), f"{where} {name}") for name in _COMP_GLOBAL_LISTS
    }
    raw_lists = node.get("lists", {})
    if not isinstance(raw_lists, dict):
        raise LexiconError(f"{where}: 'lists' must be a mapping")
    lists = {
        str(name): _normalized_list(value, f"{where} lists.{name}")
        for name, value in raw_lists.items()
    }
    entries = tuple(
        _parse_composition(tax, item, lists, seen_ids)
        for item in _entry_list(node, "entries", where)
    )
    return CompositionRules(
        stops=stops,
        lookback=lookback,
        subject_window=subject_window,
        negators=shared["negators"],
        non_negators=shared["non_negators"],
        selves=shared["selves"],
        others=shared["others"],
        recipients=shared["recipients"],
        listeners=shared["listeners"],
        entries=entries,
    )


def _bounded_int(raw: Any, low: int, high: int, where: str) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int) or not low <= raw <= high:
        raise LexiconError(f"{where}: must be an integer in [{low}, {high}], got {raw!r}")
    return raw


def _composition_list(
    item: Mapping[str, Any], key: str, lists: Mapping[str, tuple[str, ...]], where: str
) -> tuple[str, ...]:
    """An entry's phrase list: a name from ``lists`` or an inline list; () when absent."""
    if key not in item:
        return ()
    raw = item[key]
    if isinstance(raw, str):
        if raw not in lists:
            raise LexiconError(f"{where}: '{key}' names an unknown list {raw!r}")
        return lists[raw]
    return _normalized_list(raw, f"{where} {key}")


def _parse_composition(
    tax: Taxonomy,
    item: Mapping[str, Any],
    lists: Mapping[str, tuple[str, ...]],
    seen_ids: dict[str, str],
) -> Composition:
    where = f"{_RISK_FILE} {_COMP_SECTION} entry {item.get('id')!r}"
    cue_id = _entry_id(item, where, seen_ids)
    where = f"{_RISK_FILE} {_COMP_SECTION} entry {cue_id}"
    _check_keys(item, set(_COMP_ENTRY_KEYS), where)
    raw_level = item.get("level")
    if raw_level not in _COMP_LEVELS:
        raise LexiconError(f"{where}: level must be one of {list(_COMP_LEVELS)}, got {raw_level!r}")
    ask = raw_level == "ASK"
    if ask != cue_id.startswith(_ASK_ID_PREFIX):
        raise LexiconError(
            f"{where}: the id starts with {_ASK_ID_PREFIX} exactly when level is ASK"
        )
    if (raw_level == "L3") != cue_id.startswith(_STAGE1_ID_PREFIX):
        raise LexiconError(
            f"{where}: the id starts with {_STAGE1_ID_PREFIX} exactly when level is L3"
        )
    level = CrisisLevel.L1 if ask else CrisisLevel[raw_level]
    phrases = {key: _composition_list(item, key, lists, where) for key in _COMP_PHRASE_KEYS}
    if not phrases["heads"]:
        raise LexiconError(f"{where}: 'heads' must be a non-empty list or list name")
    max_gap, order = 0, "head_first"
    if phrases["tails"]:
        max_gap = _bounded_int(item.get("max_gap"), 0, _MAX_GAP, f"{where} max_gap")
        order = item.get("order", order)
        if order not in _COMP_ORDERS:
            raise LexiconError(f"{where}: order must be one of {list(_COMP_ORDERS)}")
    elif "max_gap" in item or "order" in item:
        raise LexiconError(f"{where}: 'max_gap' and 'order' need 'tails'")
    context_window: int | None = None
    if "context_window" in item:
        if not phrases["context"]:
            raise LexiconError(f"{where}: 'context_window' needs 'context'")
        context_window = _bounded_int(
            item["context_window"], 0, _MAX_WINDOW, f"{where} context_window"
        )
    unless_window = 0
    if phrases["unless"]:
        unless_window = _bounded_int(
            item.get("unless_window"), 1, _MAX_WINDOW, f"{where} unless_window"
        )
    elif "unless_window" in item:
        raise LexiconError(f"{where}: 'unless_window' needs 'unless'")
    parts = (*phrases["heads"], *phrases["tails"])
    for phrase in phrases["exceptions"]:
        if not any(part in phrase for part in parts):
            raise LexiconError(f"{where}: exception {phrase!r} contains no head or tail")
    persons = item.get("persons", True)
    if not isinstance(persons, bool):
        raise LexiconError(f"{where}: 'persons' must be true or false")
    return Composition(
        id=cue_id,
        level=level,
        score=tax.threshold(f"risk.lexicon_scores.{level.name}"),
        ask=ask,
        heads=phrases["heads"],
        tails=phrases["tails"],
        max_gap=max_gap,
        either_order=order == "either",
        context=phrases["context"],
        context_window=context_window,
        unless=phrases["unless"],
        unless_window=unless_window,
        exceptions=phrases["exceptions"],
        blockers=phrases["blockers"],
        persons=persons,
        trailing=phrases["trailing"] if "trailing" in item else None,
    )


def _parse_answers(doc: Mapping[str, Any], *, required: bool) -> IntentAnswers:
    """The answer phrases. Required whenever an ask cue exists: the session must be able
    to read the answer to the question it asks."""
    where = f"{_RISK_FILE} {_ANSWER_SECTION}"
    if _ANSWER_SECTION not in doc:
        if required:
            raise LexiconError(f"{where}: required when {_ASK_SECTION} has entries")
        return IntentAnswers()
    node = doc[_ANSWER_SECTION]
    if not isinstance(node, dict):
        raise LexiconError(f"{where}: must be a mapping")
    _check_keys(node, set(_ANSWER_LISTS), where)
    owner: dict[str, str] = {}
    lists: dict[str, tuple[str, ...]] = {}
    for name in _ANSWER_LISTS:
        raw = node.get(name)
        if not isinstance(raw, list) or not raw:
            raise LexiconError(f"{where}: '{name}' must be a non-empty list")
        folded: list[str] = []
        for entry in raw:
            phrase = fold_words(entry) if isinstance(entry, str) else ""
            if not phrase:
                raise LexiconError(f"{where} {name}: entry {entry!r} is empty or not a string")
            if phrase in folded:
                raise LexiconError(f"{where} {name}: phrase {phrase!r} is repeated")
            # A yes and a no never share a phrase; unsure words may also read as a yes.
            if name != "unsure":
                if phrase in owner:
                    raise LexiconError(f"{where}: {phrase!r} is in {owner[phrase]} and {name}")
                owner[phrase] = name
            folded.append(phrase)
        lists[name] = tuple(folded)
    return IntentAnswers(**lists)


def _parse_denial(doc: Mapping[str, Any]) -> DenialRules:
    """Parse the optional ``denial`` section (F10). Its phrases go to a matcher of their
    own, so they may repeat a phrase of any other section."""
    if _DENIAL_SECTION not in doc:
        return DenialRules()
    where = f"{_RISK_FILE} {_DENIAL_SECTION}"
    node = doc[_DENIAL_SECTION]
    if not isinstance(node, dict):
        raise LexiconError(f"{where}: must be a mapping")
    _check_keys(node, set(_DENIAL_LISTS), where)
    lists: dict[str, tuple[str, ...]] = {}
    for name in _DENIAL_LISTS:
        phrases = _normalized_list(node.get(name), f"{where} {name}")
        repeated = sorted({p for p in phrases if phrases.count(p) > 1})
        if repeated:
            raise LexiconError(f"{where} {name}: phrases {repeated} are repeated")
        lists[name] = phrases
    for phrase in lists["phrases"]:
        for name in ("contrasts", "vetoes"):
            inside = [word for word in lists[name] if word in phrase]
            if inside:
                raise LexiconError(
                    f"{where}: phrase {phrase!r} contains {name} {inside}, so it never applies"
                )
    return DenialRules(**lists)


def _parse_recall_cap(base: Traversable | Path, doc: Mapping[str, Any]) -> RecallCapRules:
    """Parse the optional ``recall_cap`` section (F16a) and read its questions from
    perception.yaml next to risk.yaml (absent there: no questions, so no cap)."""
    if _RECALL_SECTION not in doc:
        return RecallCapRules()
    where = f"{_RISK_FILE} {_RECALL_SECTION}"
    node = doc[_RECALL_SECTION]
    if not isinstance(node, dict):
        raise LexiconError(f"{where}: must be a mapping")
    _check_keys(node, {"vetoes"}, where)
    vetoes = _normalized_list(node.get("vetoes"), f"{where} vetoes")
    repeated = sorted({p for p in vetoes if vetoes.count(p) > 1})
    if repeated:
        raise LexiconError(f"{where} vetoes: phrases {repeated} are repeated")
    if not base.joinpath(_PERCEPTION_FILE).is_file():
        return RecallCapRules(vetoes=vetoes)
    perception = _read_yaml(base, _PERCEPTION_FILE)
    questions: list[str] = []
    for section in _RECALL_QUESTION_SECTIONS:
        if section in perception:
            questions.extend(_normalized_list(perception[section], f"{_PERCEPTION_FILE} {section}"))
    for question in questions:
        inside = [word for word in vetoes if word in question]
        if inside:
            raise LexiconError(
                f"{where}: question {question!r} contains vetoes {inside}, so it never applies"
            )
    return RecallCapRules(questions=tuple(dict.fromkeys(questions)), vetoes=vetoes)


# -- red_flags.yaml ----------------------------------------------------------------


def _parse_red_flags(
    tax: Taxonomy, doc: Mapping[str, Any], seen_ids: dict[str, str]
) -> tuple[dict[str, RedFlagCue], tuple[str, ...]]:
    _check_keys(doc, {"version", "self_report_negations", "entries"}, _RED_FLAG_FILE)
    negations = _parse_negations(doc.get("self_report_negations"))
    known_codes = set(tax.red_flags())
    owners: dict[str, str] = {}
    cues: dict[str, RedFlagCue] = {}
    tiers_by_code: dict[str, set[str]] = {code: set() for code in known_codes}
    for item in _entry_list(doc, "entries", _RED_FLAG_FILE):
        where = f"{_RED_FLAG_FILE} entry {item.get('id')!r}"
        cue_id = _entry_id(item, where, seen_ids)
        where = f"{_RED_FLAG_FILE} entry {cue_id}"
        _check_keys(item, {"id", "code", "tier", "patterns"}, where)
        code = item.get("code")
        if not isinstance(code, str) or code not in known_codes:
            raise LexiconError(f"{where}: red flag code {code!r} is not in the taxonomy")
        tier = next((t for t in _TIERS if t == item.get("tier")), None)
        if tier is None:
            raise LexiconError(
                f"{where}: tier must be one of {list(_TIERS)}, got {item.get('tier')!r}"
            )
        patterns = _normalized_list(item.get("patterns"), where)
        _claim_patterns(patterns, cue_id, owners, _RED_FLAG_FILE)
        tiers_by_code[code].add(tier)
        cues[cue_id] = RedFlagCue(cue_id, code, tier, patterns)
    for code in sorted(known_codes):
        for tier in _TIERS:
            if tier not in tiers_by_code[code]:
                raise LexiconError(f"{_RED_FLAG_FILE}: red flag {code} has no {tier} entry")
    return cues, negations


def _parse_negations(node: Any) -> tuple[str, ...]:
    where = f"{_RED_FLAG_FILE} self_report_negations"
    if not isinstance(node, list) or not node:
        raise LexiconError(f"{where}: must be a non-empty list")
    out: list[str] = []
    for raw in node:
        if not isinstance(raw, str) or not normalize(raw):
            raise LexiconError(f"{where}: entry {raw!r} is empty or not a string")
        out.append(normalize(raw))
    return tuple(out)
