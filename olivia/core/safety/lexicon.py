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
from olivia.core.safety.normalize import normalize
from olivia.core.taxonomy import Taxonomy

RiskSection = Literal["stage1", "stage2", "hyperbole", "negation", "safety_confirm"]
RedFlagTier = Literal["SELF_REPORT", "FEATURE"]

_RISK_FILE: Final = "risk.yaml"
_RED_FLAG_FILE: Final = "red_flags.yaml"
_SECTIONS: Final[tuple[RiskSection, ...]] = get_args(RiskSection)
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
    red_flags, negations = _parse_red_flags(tax, flag_doc, seen_ids)
    return SafetyLexicons(
        risk=MappingProxyType(risk),
        red_flags=MappingProxyType(red_flags),
        self_report_negations=negations,
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
    if not isinstance(raw, str) or not raw.strip():
        raise LexiconError(f"{where}: 'id' must be a non-empty string")
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
    _check_keys(doc, {"version", *_SECTIONS}, _RISK_FILE)
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
    if section in ("negation", "safety_confirm"):
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
