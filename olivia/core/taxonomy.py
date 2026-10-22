"""Typed, read-only access to ``taxonomy.yaml``, the single source of truth.

All thresholds and enums come from the YAML file. Looking up anything that is
absent raises :class:`TaxonomyError`; no accessor ever returns a default.
"""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from itertools import pairwise
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

import yaml

from olivia.core.models import ActionType, CrisisLevel, SafetyGrade

_ID_LIST_SECTIONS: frozenset[str] = frozenset(
    {
        "emotions",
        "cognitive_distortions",
        "schemas",
        "satir_yearnings",
        "communication_stances",
        "contraindication_enums",
    }
)

_LABEL_KINDS: dict[str, tuple[str, str]] = {
    # kind -> (canonical id section, alias section)
    "emotion": ("emotions", "emotion_aliases"),
    "distortion": ("cognitive_distortions", "distortion_aliases"),
    "schema": ("schemas", "schema_aliases"),
    "yearning": ("satir_yearnings", "yearning_aliases"),
}


class TaxonomyError(Exception):
    """Raised when taxonomy data is missing, malformed, or looked up wrongly."""


class UnknownActionError(KeyError):
    """Raised when an action identifier is neither a method id, an action id nor an alias."""


@dataclass(frozen=True)
class MethodEntry:
    id: str
    name_zh: str
    name_en: str
    file: str
    grade: SafetyGrade
    evidence_level: str | None
    duration_minutes: int | None
    stealth_workplace_compatible: bool | None
    clinical_rationale: str | None
    core_action_steps: tuple[str, ...]
    contraindications: tuple[str, ...]
    sub_actions: tuple[str, ...]


@dataclass(frozen=True)
class RegisteredAction:
    id: str
    aliases: tuple[str, ...]
    name_zh: str
    parent_method_id: str | None
    action_type: ActionType
    duration_minutes: int
    stealth_workplace_compatible: bool
    clinical_rationale: str
    core_action_steps: tuple[str, ...]
    contraindications: tuple[str, ...]


@dataclass(frozen=True)
class RedFlag:
    """A clinical red flag; ``banned_methods`` keeps the taxonomy's raw entries."""

    code: str
    name_zh: str
    allowed_actions: tuple[str, ...]
    banned_methods: tuple[str, ...]


@dataclass(frozen=True)
class _CrisisBand:
    level: CrisisLevel
    low: float
    high: float
    closed: bool


_TIER_GRADES: tuple[tuple[str, SafetyGrade], ...] = (
    ("grade_A", SafetyGrade.GRADE_A),
    ("grade_B", SafetyGrade.GRADE_B),
    ("grade_C", SafetyGrade.GRADE_C),
)


class _Views:
    """Strictly parsed clinical views; building one runs every integrity check."""

    def __init__(self, data: Mapping[str, Any], contraindication_ids: frozenset[str]) -> None:
        self.methods = self._parse_methods(data)
        self.actions = self._parse_actions(data)
        self.alias_to_action = self._check_aliases()
        self._check_action_links()
        self._check_contraindications(contraindication_ids)
        self.tags = self._parse_tags(data)
        self.red_flags = self._parse_red_flags(data)
        self.whitelist = self._parse_whitelist(data)
        self._check_red_flag_references()
        self._check_whitelist()
        self.crisis_bands = self._parse_crisis(data)
        self.exit_safe_turns = self._parse_exit_turns(data)
        self._check_duplicated_values(data)

    # -- parsing -----------------------------------------------------------------

    @staticmethod
    def _parse_methods(data: Mapping[str, Any]) -> dict[str, MethodEntry]:
        tiers = _mapping(data.get("method_safety_tiers"), "method_safety_tiers")
        methods: dict[str, MethodEntry] = {}
        for tier_name, grade in _TIER_GRADES:
            tier = _mapping(tiers.get(tier_name), f"method_safety_tiers.{tier_name}")
            entries = _list(tier.get("methods"), f"method_safety_tiers.{tier_name}.methods")
            for raw in entries:
                where = f"method_safety_tiers.{tier_name} entry"
                item = _mapping(raw, where)
                mid = _str(item.get("id"), f"{where} id")
                where = f"method {mid}"
                if mid in methods:
                    raise TaxonomyError(f"duplicate method id: {mid}")
                strict = grade is SafetyGrade.GRADE_A
                methods[mid] = MethodEntry(
                    id=mid,
                    name_zh=_str(item.get("name_zh"), f"{where} name_zh"),
                    name_en=_str(item.get("name_en"), f"{where} name_en"),
                    file=_str(item.get("file"), f"{where} file"),
                    grade=grade,
                    evidence_level=_opt_str(item, "evidence_level", where, strict),
                    duration_minutes=_opt_int(item, "duration_minutes", where, strict),
                    stealth_workplace_compatible=_opt_bool(
                        item, "stealth_workplace_compatible", where, strict
                    ),
                    clinical_rationale=_opt_str(item, "clinical_rationale", where, strict),
                    core_action_steps=_opt_str_tuple(item, "core_action_steps", where, strict),
                    contraindications=_opt_str_tuple(item, "contraindications", where, strict),
                    sub_actions=_opt_str_tuple(item, "sub_actions", where, False),
                )
        return methods

    def _parse_actions(self, data: Mapping[str, Any]) -> dict[str, RegisteredAction]:
        actions: dict[str, RegisteredAction] = {}
        for raw in _list(data.get("action_registry"), "action_registry"):
            item = _mapping(raw, "action_registry entry")
            aid = _str(item.get("id"), "action_registry entry id")
            where = f"action {aid}"
            if aid in actions:
                raise TaxonomyError(f"duplicate action id: {aid}")
            if aid in self.methods:
                raise TaxonomyError(f"action id collides with a method id: {aid}")
            parent = item.get("parent_method_id")
            if parent is not None and not isinstance(parent, str):
                raise TaxonomyError(f"{where}: parent_method_id must be a string or null")
            raw_type = _str(item.get("action_type"), f"{where} action_type")
            try:
                action_type = ActionType(raw_type)
            except ValueError as exc:
                raise TaxonomyError(f"{where}: unknown action_type {raw_type!r}") from exc
            actions[aid] = RegisteredAction(
                id=aid,
                aliases=_opt_str_tuple(item, "aliases", where, True),
                name_zh=_str(item.get("name_zh"), f"{where} name_zh"),
                parent_method_id=parent,
                action_type=action_type,
                duration_minutes=_req_int(item, "duration_minutes", where),
                stealth_workplace_compatible=_req_bool(item, "stealth_workplace_compatible", where),
                clinical_rationale=_str(item.get("clinical_rationale"), f"{where} rationale"),
                core_action_steps=_opt_str_tuple(item, "core_action_steps", where, True),
                contraindications=_opt_str_tuple(item, "contraindications", where, False),
            )
        return actions

    @staticmethod
    def _parse_tags(data: Mapping[str, Any]) -> dict[str, tuple[str, ...]]:
        section = _mapping(data.get("banned_tag_mappings"), "banned_tag_mappings")
        tags: dict[str, tuple[str, ...]] = {}
        for tag, raw in section.items():
            item = _mapping(raw, f"banned_tag_mappings.{tag}")
            tags[str(tag)] = _opt_str_tuple(item, "banned_method_ids", f"banned tag {tag}", True)
        return tags

    @staticmethod
    def _parse_red_flags(data: Mapping[str, Any]) -> dict[str, RedFlag]:
        section = _mapping(data.get("clinical_red_flags"), "clinical_red_flags")
        entries = _list(
            section.get("mandatory_referral_disorders"),
            "clinical_red_flags.mandatory_referral_disorders",
        )
        flags: dict[str, RedFlag] = {}
        for raw in entries:
            item = _mapping(raw, "red flag entry")
            code = _str(item.get("code"), "red flag entry code")
            where = f"red flag {code}"
            if code in flags:
                raise TaxonomyError(f"duplicate red flag code: {code}")
            flags[code] = RedFlag(
                code=code,
                name_zh=_str(item.get("name_zh"), f"{where} name_zh"),
                allowed_actions=_opt_str_tuple(item, "allowed_actions", where, True),
                banned_methods=_opt_str_tuple(item, "banned_methods", where, True),
            )
        return flags

    @staticmethod
    def _parse_whitelist(data: Mapping[str, Any]) -> tuple[str, ...]:
        colbo = _mapping(data.get("colbo"), "colbo")
        node = _mapping(
            colbo.get("explore_stabilization_whitelist"), "colbo.explore_stabilization_whitelist"
        )
        return _opt_str_tuple(node, "method_ids", "stabilization whitelist", True)

    @staticmethod
    def _parse_crisis(data: Mapping[str, Any]) -> tuple[_CrisisBand, ...]:
        section = _mapping(data.get("crisis_hierarchy"), "crisis_hierarchy")
        bands: list[_CrisisBand] = []
        for level in CrisisLevel:
            node = _mapping(section.get(level.name), f"crisis_hierarchy.{level.name}")
            rng = node.get("score_range")
            if (
                not isinstance(rng, list)
                or len(rng) != 2
                or not all(isinstance(v, int | float) and not isinstance(v, bool) for v in rng)
            ):
                raise TaxonomyError(f"crisis_hierarchy.{level.name}.score_range must be [lo, hi]")
            interval = node.get("interval_type")
            expected = "CLOSED" if level is CrisisLevel.L3 else "HALF_OPEN"
            if interval != expected:
                raise TaxonomyError(
                    f"crisis_hierarchy.{level.name}.interval_type must be {expected}, "
                    f"got {interval!r}"
                )
            low, high = float(rng[0]), float(rng[1])
            if not low < high:
                raise TaxonomyError(f"crisis_hierarchy.{level.name} score_range is empty")
            bands.append(_CrisisBand(level, low, high, interval == "CLOSED"))
        if bands[0].low != 0.0:
            raise TaxonomyError("crisis_hierarchy must start at 0.0")
        for prev, nxt in pairwise(bands):
            if prev.high != nxt.low:
                raise TaxonomyError(
                    f"crisis_hierarchy has a gap or overlap between {prev.level.name} "
                    f"and {nxt.level.name}"
                )
        if bands[-1].high != 1.0:
            raise TaxonomyError("crisis_hierarchy must end at 1.0")
        return tuple(bands)

    @staticmethod
    def _parse_exit_turns(data: Mapping[str, Any]) -> dict[CrisisLevel, int]:
        hierarchy = _mapping(data.get("crisis_hierarchy"), "crisis_hierarchy")
        exit_rule = _mapping(hierarchy.get("exit_rule"), "crisis_hierarchy.exit_rule")
        where = "crisis_hierarchy.exit_rule.safe_streak_required"
        streaks = _mapping(exit_rule.get("safe_streak_required"), where)
        turns: dict[CrisisLevel, int] = {}
        for level in (CrisisLevel.L2, CrisisLevel.L3):
            if level.name not in streaks:
                raise TaxonomyError(f"safe_streak_required has no entry for {level.name}")
            value = _int_value(streaks[level.name], level.name, where)
            if value < 1:
                raise TaxonomyError(f"{where}.{level.name} must be at least 1")
            turns[level] = value
        return turns

    # -- integrity checks ----------------------------------------------------------

    def _check_duplicated_values(self, data: Mapping[str, Any]) -> None:
        """Safety values the YAML states twice must agree (exact equality; literals)."""
        for band in self.crisis_bands:
            if band.level is CrisisLevel.L0:
                continue
            name = band.level.name
            _require_equal(
                data,
                f"risk.model_thresholds.{name}",
                (f"crisis_hierarchy.{name}.score_range[0]", band.low),
            )
        for level, turns in self.exit_safe_turns.items():
            _require_equal(
                data,
                f"risk.crisis_exit_safe_turns.{level.name}",
                (f"crisis_hierarchy.exit_rule.safe_streak_required.{level.name}", turns),
            )
        for key in ("haven_enter", "haven_exit", "empower_min"):
            _require_equal(data, f"battery.{key}", _lookup(data, f"battery.thresholds.{key}"))
        _require_equal(
            data,
            "arousal.thresholds.block_high_load",
            _lookup(data, "arousal.thresholds.somatic_priority"),
        )
        _require_equal(
            data,
            "arousal.thresholds.explore_eligible_max",
            _lookup(data, "arousal.thresholds.exploration_allow"),
        )
        _require_equal(data, "arousal.scale", _lookup(data, "arousal.range"))

    def _check_aliases(self) -> dict[str, str]:
        alias_to_action: dict[str, str] = {}
        for action in self.actions.values():
            for alias in action.aliases:
                if alias in self.actions:
                    raise TaxonomyError(
                        f"alias {alias!r} of {action.id} collides with an action id"
                    )
                if alias in self.methods:
                    raise TaxonomyError(f"alias {alias!r} of {action.id} collides with a method id")
                if alias in alias_to_action:
                    raise TaxonomyError(
                        f"alias {alias!r} of {action.id} is also an alias of "
                        f"{alias_to_action[alias]}"
                    )
                alias_to_action[alias] = action.id
        return alias_to_action

    def _check_action_links(self) -> None:
        for action in self.actions.values():
            if action.parent_method_id is not None and action.parent_method_id not in self.methods:
                raise TaxonomyError(
                    f"action {action.id}: unknown parent_method_id {action.parent_method_id!r}"
                )
        for method in self.methods.values():
            for sub in method.sub_actions:
                if sub not in self.actions:
                    raise TaxonomyError(f"method {method.id}: sub_action {sub!r} is not registered")

    def _check_contraindications(self, allowed: frozenset[str]) -> None:
        for method in self.methods.values():
            for item in method.contraindications:
                if item not in allowed:
                    raise TaxonomyError(f"method {method.id}: unknown contraindication {item!r}")
        for action in self.actions.values():
            for item in action.contraindications:
                if item not in allowed:
                    raise TaxonomyError(f"action {action.id}: unknown contraindication {item!r}")

    def _check_red_flag_references(self) -> None:
        for tag, ids in self.tags.items():
            for mid in ids:
                if mid not in self.methods:
                    raise TaxonomyError(f"banned tag {tag}: unknown method id {mid!r}")
        for flag in self.red_flags.values():
            for entry in flag.allowed_actions:
                if not self.is_action_id(entry):
                    raise TaxonomyError(
                        f"red flag {flag.code}: allowed action {entry!r} cannot be resolved"
                    )
            for entry in flag.banned_methods:
                if entry not in self.tags and not self.is_action_id(entry):
                    raise TaxonomyError(
                        f"red flag {flag.code}: banned entry {entry!r} is not a method id, "
                        "action id or banned tag"
                    )

    def _check_whitelist(self) -> None:
        for entry in self.whitelist:
            if not self.is_action_id(entry):
                raise TaxonomyError(f"stabilization whitelist entry {entry!r} cannot be resolved")

    def is_action_id(self, raw: str) -> bool:
        return raw in self.methods or raw in self.actions or raw in self.alias_to_action


def _lookup(data: Mapping[str, Any], dotted_path: str) -> tuple[str, Any]:
    """Return ``(dotted_path, value)``; raises if any path segment is absent."""
    node: Any = data
    for part in dotted_path.split("."):
        if not isinstance(node, Mapping) or part not in node:
            raise TaxonomyError(f"taxonomy key not found: {dotted_path}")
        node = node[part]
    return dotted_path, node


def _require_equal(data: Mapping[str, Any], path: str, other: tuple[str, Any]) -> None:
    """Raise unless the value at ``path`` equals ``other`` (a ``(path, value)`` pair)."""
    _, value = _lookup(data, path)
    other_path, other_value = other
    if isinstance(value, bool) != isinstance(other_value, bool) or value != other_value:
        raise TaxonomyError(
            f"taxonomy disagrees with itself: {path} = {value!r} but {other_path} = {other_value!r}"
        )


def _mapping(node: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(node, Mapping):
        raise TaxonomyError(f"taxonomy {where} is missing or not a mapping")
    return node


def _list(node: Any, where: str) -> list[Any]:
    if not isinstance(node, list):
        raise TaxonomyError(f"taxonomy {where} is missing or not a list")
    return node


def _str(node: Any, where: str) -> str:
    if not isinstance(node, str) or not node:
        raise TaxonomyError(f"taxonomy {where} is missing or not a non-empty string")
    return node


def _opt_str(item: Mapping[str, Any], key: str, where: str, required: bool) -> str | None:
    if key not in item:
        if required:
            raise TaxonomyError(f"{where}: missing {key}")
        return None
    return _str(item[key], f"{where} {key}")


def _int_value(value: Any, key: str, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TaxonomyError(f"{where}: {key} must be a non-negative integer, got {value!r}")
    return value


def _bool_value(value: Any, key: str, where: str) -> bool:
    if not isinstance(value, bool):
        raise TaxonomyError(f"{where}: {key} must be a bool, got {value!r}")
    return value


def _req_int(item: Mapping[str, Any], key: str, where: str) -> int:
    if key not in item:
        raise TaxonomyError(f"{where}: missing {key}")
    return _int_value(item[key], key, where)


def _opt_int(item: Mapping[str, Any], key: str, where: str, required: bool) -> int | None:
    if key not in item and not required:
        return None
    return _req_int(item, key, where)


def _req_bool(item: Mapping[str, Any], key: str, where: str) -> bool:
    if key not in item:
        raise TaxonomyError(f"{where}: missing {key}")
    return _bool_value(item[key], key, where)


def _opt_bool(item: Mapping[str, Any], key: str, where: str, required: bool) -> bool | None:
    if key not in item and not required:
        return None
    return _req_bool(item, key, where)


def _opt_str_tuple(
    item: Mapping[str, Any], key: str, where: str, required: bool
) -> tuple[str, ...]:
    if key not in item:
        if required:
            raise TaxonomyError(f"{where}: missing {key}")
        return ()
    value = item[key]
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise TaxonomyError(f"{where}: {key} must be a list of non-empty strings")
    return tuple(value)


class Taxonomy:
    """Read-only, validated view over the parsed taxonomy mapping.

    Construction deep-copies ``data`` and runs every integrity check, so no
    ``Taxonomy`` instance can exist unless its data is internally consistent.
    """

    def __init__(self, data: Mapping[str, Any]) -> None:
        self._data: Mapping[str, Any] = copy.deepcopy(dict(data))
        self._cached_views: _Views | None = None
        self._verify_integrity()

    @property
    def version(self) -> str:
        value = self._data.get("version")
        if not isinstance(value, str):
            raise TaxonomyError("taxonomy 'version' is missing or not a string")
        return value

    def threshold(self, dotted_path: str) -> float:
        node: Any = self._data
        for part in dotted_path.split("."):
            if not isinstance(node, Mapping) or part not in node:
                raise TaxonomyError(f"taxonomy key not found: {dotted_path}")
            node = node[part]
        if isinstance(node, bool) or not isinstance(node, int | float):
            raise TaxonomyError(f"taxonomy value at {dotted_path} is not numeric: {node!r}")
        if not math.isfinite(node):
            raise TaxonomyError(f"taxonomy value at {dotted_path} is not finite: {node!r}")
        return float(node)

    def values(self, name: str) -> tuple[str, ...]:
        if name == "distress_categories":
            return tuple(str(item) for item in self._section_list(name))
        if name not in _ID_LIST_SECTIONS:
            raise TaxonomyError(f"unknown taxonomy value set: {name}")
        return self._ids(name)

    def canonical_label(
        self, kind: Literal["emotion", "distortion", "schema", "yearning"], label: str
    ) -> str:
        if kind not in _LABEL_KINDS:
            raise TaxonomyError(f"unknown label kind: {kind}")
        section, alias_section = _LABEL_KINDS[kind]
        if label in self._ids(section):
            return label
        aliases = self._data.get(alias_section)
        if not isinstance(aliases, Mapping):
            raise TaxonomyError(f"taxonomy section missing or not a mapping: {alias_section}")
        if label in aliases:
            return str(aliases[label])
        raise TaxonomyError(f"unknown {kind} label: {label}")

    def spectrum_ids(self) -> tuple[str, ...]:
        """Two-digit spectrum ids ("01".."11"), the keys of ``distress_category_mapping``."""
        section = _mapping(self._data.get("distress_category_mapping"), "distress_category_mapping")
        return tuple(str(key) for key in section)

    # -- clinical views ------------------------------------------------------------

    def methods(self) -> Mapping[str, MethodEntry]:
        """All 75 methods keyed by their two-digit id."""
        return MappingProxyType(self._views().methods)

    def grade_a_ids(self) -> frozenset[str]:
        return frozenset(
            m.id for m in self._views().methods.values() if m.grade is SafetyGrade.GRADE_A
        )

    def action_registry(self) -> Mapping[str, RegisteredAction]:
        """Registered sub-actions keyed by canonical action id."""
        return MappingProxyType(self._views().actions)

    def canonical_action_id(self, action_id: str) -> str:
        """Return the canonical id for a method id, action id or action alias."""
        views = self._views()
        if action_id in views.methods or action_id in views.actions:
            return action_id
        if action_id in views.alias_to_action:
            return views.alias_to_action[action_id]
        raise UnknownActionError(f"unknown action id: {action_id}")

    def red_flags(self) -> Mapping[str, RedFlag]:
        return MappingProxyType(self._views().red_flags)

    def banned_tag_methods(self, tag: str) -> tuple[str, ...]:
        tags = self._views().tags
        if tag not in tags:
            raise TaxonomyError(f"unknown banned tag: {tag}")
        return tags[tag]

    def is_banned_tag(self, entry: str) -> bool:
        return entry in self._views().tags

    def stabilization_whitelist(self) -> tuple[str, ...]:
        return self._views().whitelist

    def crisis_level_for_score(self, score: float) -> CrisisLevel:
        if math.isnan(score) or not 0.0 <= score <= 1.0:
            raise ValueError(f"crisis score must be within [0, 1], got {score}")
        for band in self._views().crisis_bands:
            if band.low <= score < band.high or (band.closed and score == band.high):
                return band.level
        raise TaxonomyError(f"no crisis band covers score {score}")  # unreachable once validated

    def crisis_exit_safe_turns(self, level: CrisisLevel) -> int:
        if level not in (CrisisLevel.L2, CrisisLevel.L3):
            raise ValueError(f"crisis exit streak is only defined for L2 and L3, got {level.name}")
        return self._views().exit_safe_turns[level]

    def _views(self) -> _Views:
        if self._cached_views is None:
            ids = frozenset(self._ids("contraindication_enums"))
            self._cached_views = _Views(self._data, ids)
        return self._cached_views

    def _verify_integrity(self) -> None:
        """Run every load-time integrity check; raises :class:`TaxonomyError` on failure."""
        self._views()
        for kind, (section, alias_section) in _LABEL_KINDS.items():
            ids = set(self._ids(section))
            aliases = _mapping(self._data.get(alias_section), alias_section)
            for alias, target in aliases.items():
                if not isinstance(target, str) or target not in ids:
                    raise TaxonomyError(
                        f"{kind} alias {alias!r} maps to unknown canonical id {target!r}"
                    )

    def _section_list(self, name: str) -> list[Any]:
        section = self._data.get(name)
        if not isinstance(section, list):
            raise TaxonomyError(f"taxonomy section missing or not a list: {name}")
        return section

    def _ids(self, name: str) -> tuple[str, ...]:
        ids: list[str] = []
        for item in self._section_list(name):
            if not isinstance(item, Mapping) or "id" not in item:
                raise TaxonomyError(f"taxonomy section {name} has an entry without 'id'")
            ids.append(str(item["id"]))
        return tuple(ids)


def load_taxonomy(path: Path | None = None) -> Taxonomy:
    """Load taxonomy from ``path``, or the copy packaged at ``olivia/data``."""
    try:
        if path is None:
            text = resources.files("olivia").joinpath("data/taxonomy.yaml").read_text("utf-8")
        else:
            text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise TaxonomyError(f"cannot read taxonomy file: {exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise TaxonomyError(f"invalid taxonomy YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise TaxonomyError("taxonomy top level must be a mapping")
    return Taxonomy(data)
