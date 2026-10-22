"""Typed, read-only access to ``hotlines.yaml``, the crisis-card resource data (GEO-02..07).

Loading validates the file strictly: unknown or missing keys, wrong types, bad dates or
levels, duplicate ids and a missing ``ZZ`` fallback region all raise
:class:`ResourceDataError`. Nothing is defaulted.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from importlib import resources
from pathlib import Path
from types import MappingProxyType
from typing import Final, TypeVar

import yaml

from olivia.core.models import UNKNOWN_COUNTRY, CrisisLevel

SUPPORTED_VERSION: Final = 1
_REGION_RE: Final = re.compile(r"[A-Z]{2}")
_CARD_LEVELS: Final = {"L2": CrisisLevel.L2, "L3": CrisisLevel.L3}

_TOP_KEYS: Final = frozenset({"version", "compiled_on", "regions"})
_REGION_KEYS: Final = frozenset({"emergency", "lines"})
_EMERGENCY_KEYS: Final = frozenset({"number", "purpose", "source_url", "verified_on", "notes"})
_E = TypeVar("_E", bound=StrEnum)

_LINE_KEYS: Final = frozenset(
    {
        "id",
        "name_zh",
        "number",
        "kind",
        "levels",
        "hours",
        "scope",
        "adcode",
        "minors_only",
        "source_url",
        "verified_on",
        "notes",
    }
)


class ResourceDataError(Exception):
    """Raised when the hotline data is missing, malformed, or looked up wrongly."""


class LineKind(StrEnum):
    """Kinds of support lines; the declaration order is the BROWSING group order."""

    CRISIS_HOTLINE = "crisis_hotline"
    TEXT_LINE = "text_line"
    YOUTH_LINE = "youth_line"
    DIRECTORY_URL = "directory_url"


class EmergencyPurpose(StrEnum):
    POLICE = "police"
    AMBULANCE = "ambulance"
    FIRE_AMBULANCE = "fire_ambulance"
    POLICE_FIRE_AMBULANCE = "police_fire_ambulance"
    GENERIC_GSM_EMERGENCY = "generic_gsm_emergency"


@dataclass(frozen=True)
class EmergencyNumber:
    id: str
    """Derived as ``<region>_emergency_<number>`` (the data file carries no id)."""
    number: str
    purpose: EmergencyPurpose
    source_url: str
    verified_on: date
    notes: str


@dataclass(frozen=True)
class HotlineEntry:
    id: str
    name_zh: str
    number: str
    kind: LineKind
    levels: frozenset[CrisisLevel]
    hours: str
    scope: str
    adcode: str | None
    minors_only: bool
    source_url: str
    verified_on: date
    notes: str


@dataclass(frozen=True)
class RegionResources:
    code: str
    emergency: tuple[EmergencyNumber, ...]
    lines: tuple[HotlineEntry, ...]


@dataclass(frozen=True)
class ResourceStore:
    version: int
    compiled_on: date
    regions: Mapping[str, RegionResources]

    def has_region(self, code: str) -> bool:
        return code in self.regions

    def region(self, code: str) -> RegionResources:
        try:
            return self.regions[code]
        except KeyError:
            raise ResourceDataError(f"no resources for region {code!r}") from None


def load_store(path: Path | None = None) -> ResourceStore:
    """Load hotline data from ``path``, or the copy packaged at ``olivia/data/resources``."""
    try:
        if path is None:
            text = (
                resources.files("olivia")
                .joinpath("data/resources/hotlines.yaml")
                .read_text("utf-8")
            )
        else:
            text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ResourceDataError(f"cannot read hotline data: {exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ResourceDataError(f"invalid hotline YAML: {exc}") from exc
    return parse_store(data)


def parse_store(data: object) -> ResourceStore:
    """Validate already-parsed YAML data and build a :class:`ResourceStore`."""
    top = _mapping(data, "top level", _TOP_KEYS)
    version = top["version"]
    if type(version) is not int or version != SUPPORTED_VERSION:
        raise ResourceDataError(f"unsupported hotline data version: {version!r}")
    compiled_on = _date(top["compiled_on"], "compiled_on")
    regions_raw = top["regions"]
    if not isinstance(regions_raw, Mapping) or not regions_raw:
        raise ResourceDataError("regions must be a non-empty mapping")

    regions: dict[str, RegionResources] = {}
    seen_ids: set[str] = set()
    for code, raw in regions_raw.items():
        if not isinstance(code, str) or not _REGION_RE.fullmatch(code):
            raise ResourceDataError(f"region code must be two uppercase letters: {code!r}")
        region = _region(code, raw)
        for entry_id in [e.id for e in region.emergency] + [line.id for line in region.lines]:
            if entry_id in seen_ids:
                raise ResourceDataError(f"duplicate entry id: {entry_id}")
            seen_ids.add(entry_id)
        regions[code] = region
    if UNKNOWN_COUNTRY not in regions:
        raise ResourceDataError(f"fallback region {UNKNOWN_COUNTRY} is missing")
    return ResourceStore(
        version=version, compiled_on=compiled_on, regions=MappingProxyType(regions)
    )


def _region(code: str, raw: object) -> RegionResources:
    where = f"region {code}"
    body = _mapping(raw, where, _REGION_KEYS)
    emergency_raw = _list(body["emergency"], f"{where}.emergency")
    lines_raw = _list(body["lines"], f"{where}.lines")
    if not emergency_raw:
        raise ResourceDataError(f"{where} has no emergency number")
    if not lines_raw:
        raise ResourceDataError(f"{where} has no lines")
    emergency = tuple(_emergency(code, item) for item in emergency_raw)
    lines = tuple(_line(code, item) for item in lines_raw)
    return RegionResources(code=code, emergency=emergency, lines=lines)


def _emergency(region: str, raw: object) -> EmergencyNumber:
    where = f"region {region} emergency entry"
    item = _mapping(raw, where, _EMERGENCY_KEYS)
    number = _text(item["number"], f"{where}.number")
    return EmergencyNumber(
        id=f"{region.lower()}_emergency_{number.replace(' ', '')}",
        number=number,
        purpose=_enum(EmergencyPurpose, item["purpose"], f"{where}.purpose"),
        source_url=_url(item["source_url"], f"{where}.source_url"),
        verified_on=_date(item["verified_on"], f"{where}.verified_on"),
        notes=_str(item["notes"], f"{where}.notes"),
    )


def _line(region: str, raw: object) -> HotlineEntry:
    item = _mapping(raw, f"region {region} line", _LINE_KEYS)
    line_id = _text(item["id"], f"region {region} line id")
    where = f"line {line_id}"
    if not line_id.startswith(region.lower() + "_"):
        raise ResourceDataError(f"{where}: id must start with {region.lower()}_")
    levels_raw = _list(item["levels"], f"{where}.levels")
    if not levels_raw:
        raise ResourceDataError(f"{where}: levels must not be empty")
    levels: set[CrisisLevel] = set()
    for level in levels_raw:
        if not isinstance(level, str) or level not in _CARD_LEVELS:
            raise ResourceDataError(f"{where}: level must be L2 or L3, got {level!r}")
        levels.add(_CARD_LEVELS[level])
    adcode = item["adcode"]
    if adcode is not None and not isinstance(adcode, str):
        raise ResourceDataError(f"{where}: adcode must be a string or null")
    minors_only = item["minors_only"]
    if not isinstance(minors_only, bool):
        raise ResourceDataError(f"{where}: minors_only must be a boolean")
    return HotlineEntry(
        id=line_id,
        name_zh=_text(item["name_zh"], f"{where}.name_zh"),
        number=_text(item["number"], f"{where}.number"),
        kind=_enum(LineKind, item["kind"], f"{where}.kind"),
        levels=frozenset(levels),
        hours=_text(item["hours"], f"{where}.hours"),
        scope=_text(item["scope"], f"{where}.scope"),
        adcode=adcode,
        minors_only=minors_only,
        source_url=_url(item["source_url"], f"{where}.source_url"),
        verified_on=_date(item["verified_on"], f"{where}.verified_on"),
        notes=_str(item["notes"], f"{where}.notes"),
    )


def _mapping(raw: object, where: str, keys: frozenset[str]) -> Mapping[str, object]:
    if not isinstance(raw, Mapping):
        raise ResourceDataError(f"{where} must be a mapping")
    present = set(raw)
    if missing := keys - present:
        raise ResourceDataError(f"{where} is missing keys: {sorted(missing)}")
    if extra := present - keys:
        raise ResourceDataError(f"{where} has unknown keys: {sorted(map(str, extra))}")
    return raw


def _list(raw: object, where: str) -> list[object]:
    if not isinstance(raw, list):
        raise ResourceDataError(f"{where} must be a list")
    return raw


def _str(raw: object, where: str) -> str:
    if not isinstance(raw, str):
        raise ResourceDataError(f"{where} must be a string")
    return raw


def _text(raw: object, where: str) -> str:
    value = _str(raw, where)
    if not value.strip():
        raise ResourceDataError(f"{where} must not be empty")
    return value


def _url(raw: object, where: str) -> str:
    value = _text(raw, where)
    if not value.startswith("https://"):
        raise ResourceDataError(f"{where} must be an https:// URL")
    return value


def _date(raw: object, where: str) -> date:
    # Dates are quoted strings in the file; an unquoted YAML date is rejected so the
    # format stays uniform.
    value = _text(raw, where)
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ResourceDataError(f"{where} must be an ISO date, got {value!r}") from None


def _enum(enum: type[_E], raw: object, where: str) -> _E:
    value = _text(raw, where)
    try:
        return enum(value)
    except ValueError:
        raise ResourceDataError(f"{where}: unknown value {value!r}") from None
