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
    answers = _parse_answers(risk_doc, required=bool(ask_pairs))
    red_flags, negations = _parse_red_flags(tax, flag_doc, seen_ids)
    return SafetyLexicons(
        risk=MappingProxyType(risk),
        red_flags=MappingProxyType(red_flags),
        self_report_negations=negations,
        pairs=pairs,
        ask_pairs=ask_pairs,
        intent_answers=answers,
    )


# -- file access -------------------------------------------------------------------


def _read_yaml(base: Traversable | Path, name: str) -> dict[str, Any]:
    try:
        text = base.joinpath(name).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise LexiconError(f"{name}: cannot read lexicon file: {exc}") from exc
    try:
        doc = yaml.safe_load(text)
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
    allowed = {"version", *_SECTIONS, _PAIR_SECTION, _ASK_SECTION, _ANSWER_SECTION}
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
