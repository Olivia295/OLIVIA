"""Strict loading of hotlines.yaml into typed, frozen entries."""

import copy
import dataclasses
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml

from olivia.core.models import CrisisLevel
from olivia.core.resources.store import (
    EmergencyPurpose,
    LineKind,
    ResourceDataError,
    load_store,
    parse_store,
)

DATA = Path(__file__).resolve().parents[2] / "olivia" / "data" / "resources" / "hotlines.yaml"


def _raw() -> dict[str, Any]:
    with open(DATA, encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f)
    return data


def test_packaged_and_path_loads_agree() -> None:
    assert load_store() == load_store(DATA)


def test_store_is_typed_and_frozen() -> None:
    store = load_store()
    cn = store.region("CN")
    line = cn.lines[0]
    assert line.id == "cn_12356"
    assert line.kind is LineKind.CRISIS_HOTLINE
    assert line.levels == frozenset({CrisisLevel.L2, CrisisLevel.L3})
    assert line.verified_on == date(2026, 10, 22)
    assert [e.id for e in cn.emergency] == ["cn_emergency_110", "cn_emergency_120"]
    assert cn.emergency[1].purpose is EmergencyPurpose.AMBULANCE
    assert store.compiled_on == date(2026, 10, 22) and store.version == 1
    with pytest.raises(dataclasses.FrozenInstanceError):
        line.number = "0"  # type: ignore[misc]
    with pytest.raises(TypeError):
        store.regions["XX"] = cn  # type: ignore[index]


def test_emergency_ids_drop_spaces() -> None:
    raw = _raw()
    raw["regions"]["ZZ"]["emergency"][0]["number"] = "1 12"
    assert parse_store(raw).region("ZZ").emergency[0].id == "zz_emergency_112"


def test_unknown_region_lookup_raises() -> None:
    with pytest.raises(ResourceDataError, match="XX"):
        load_store().region("XX")


def test_unreadable_and_invalid_files(tmp_path: Path) -> None:
    with pytest.raises(ResourceDataError, match="cannot read"):
        load_store(tmp_path / "missing.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("regions: [unclosed", encoding="utf-8")
    with pytest.raises(ResourceDataError, match="invalid hotline YAML"):
        load_store(bad)


def _zz_line(raw: dict[str, Any]) -> dict[str, Any]:
    line: dict[str, Any] = raw["regions"]["ZZ"]["lines"][0]
    return line


def _zz_emergency(raw: dict[str, Any]) -> dict[str, Any]:
    entry: dict[str, Any] = raw["regions"]["ZZ"]["emergency"][0]
    return entry


Mutation = Callable[[dict[str, Any]], object]

BROKEN: dict[str, tuple[Mutation, str]] = {
    "top level not a mapping": (lambda r: r.clear() or r.update({"x": 1}), "missing keys"),
    "unknown top key": (lambda r: r.update({"extra": 1}), "unknown keys"),
    "wrong version": (lambda r: r.update({"version": 2}), "version"),
    "bool version": (lambda r: r.update({"version": True}), "version"),
    "unquoted date": (lambda r: r.update({"compiled_on": date(2026, 1, 1)}), "string"),
    "bad date": (lambda r: r.update({"compiled_on": "2026-13-01"}), "ISO date"),
    "regions empty": (lambda r: r.update({"regions": {}}), "non-empty"),
    "bad region code": (lambda r: r["regions"].update({"uk": r["regions"]["GB"]}), "uppercase"),
    "zz missing": (lambda r: r["regions"].pop("ZZ"), "ZZ"),
    "region not mapping": (lambda r: r["regions"].update({"GB": []}), "mapping"),
    "no emergency": (lambda r: r["regions"]["GB"].update({"emergency": []}), "emergency"),
    "no lines": (lambda r: r["regions"]["GB"].update({"lines": []}), "no lines"),
    "lines not list": (lambda r: r["regions"]["GB"].update({"lines": {}}), "list"),
    "missing line key": (lambda r: _zz_line(r).pop("hours"), "missing keys"),
    "unknown line key": (lambda r: _zz_line(r).update({"city": "x"}), "unknown keys"),
    "id prefix": (lambda r: _zz_line(r).update({"id": "cn_x"}), "zz_"),
    "duplicate id": (
        lambda r: r["regions"]["ZZ"]["lines"][1].update({"id": _zz_line(r)["id"]}),
        "duplicate",
    ),
    "empty levels": (lambda r: _zz_line(r).update({"levels": []}), "not be empty"),
    "level L1": (lambda r: _zz_line(r).update({"levels": ["L1"]}), "L2 or L3"),
    "unknown kind": (lambda r: _zz_line(r).update({"kind": "chat"}), "unknown value"),
    "adcode int": (lambda r: _zz_line(r).update({"adcode": 110000}), "adcode"),
    "minors_only str": (lambda r: _zz_line(r).update({"minors_only": "no"}), "boolean"),
    "http url": (lambda r: _zz_line(r).update({"source_url": "http://x"}), "https"),
    "empty name": (lambda r: _zz_line(r).update({"name_zh": " "}), "not be empty"),
    "notes not str": (lambda r: _zz_line(r).update({"notes": None}), "string"),
    "unknown purpose": (lambda r: _zz_emergency(r).update({"purpose": "fire"}), "unknown"),
    "emergency number int": (lambda r: _zz_emergency(r).update({"number": 112}), "string"),
}


@pytest.mark.parametrize("name", sorted(BROKEN))
def test_malformed_data_is_rejected(name: str) -> None:
    mutate, message = BROKEN[name]
    raw = copy.deepcopy(_raw())
    mutate(raw)
    with pytest.raises(ResourceDataError, match=message):
        parse_store(raw)


def test_non_mapping_top_level_is_rejected() -> None:
    with pytest.raises(ResourceDataError, match="mapping"):
        parse_store(["not", "a", "mapping"])
