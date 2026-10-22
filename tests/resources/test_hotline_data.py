"""Integrity checks for the hotline data shown on crisis cards (GEO-02..07, R8)."""

from datetime import date
from pathlib import Path

import pytest
import yaml

DATA = Path(__file__).resolve().parents[2] / "olivia" / "data" / "resources" / "hotlines.yaml"
REGIONS = {"CN", "HK", "MO", "TW", "US", "CA", "GB", "AU", "ZZ"}
LEVELS = {"L2", "L3"}
KINDS = {"crisis_hotline", "text_line", "youth_line", "directory_url"}


def _load():
    with open(DATA, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _entries(region):
    data = _load()["regions"][region]
    return [*data.get("emergency", []), *data.get("lines", [])]


def test_supported_regions_are_present():
    assert set(_load()["regions"]) == REGIONS


@pytest.mark.parametrize("region", sorted(REGIONS))
def test_every_entry_has_an_official_source_and_date(region):
    for entry in _entries(region):
        assert entry["source_url"].startswith("https://"), entry
        date.fromisoformat(entry["verified_on"])
        assert isinstance(entry["number"], str) and entry["number"].strip(), entry


@pytest.mark.parametrize("region", sorted(REGIONS))
def test_lines_use_known_kinds_and_levels(region):
    for line in _load()["regions"][region].get("lines", []):
        assert line["kind"] in KINDS, line
        assert set(line["levels"]) <= LEVELS and line["levels"], line


def test_line_ids_are_unique_and_region_prefixed():
    ids = []
    for region, data in _load()["regions"].items():
        for line in data.get("lines", []):
            assert line["id"].startswith(region.lower() + "_"), line["id"]
            ids.append(line["id"])
    assert len(ids) == len(set(ids))


def test_mainland_only_numbers_stay_in_cn():
    # R8 / GEO-03: 12356, 120 and 12355 are mainland services. 110 is also the local
    # emergency number in Macau and Taiwan, so it is checked by region, not by digits.
    for region in REGIONS - {"CN"}:
        numbers = {entry["number"] for entry in _entries(region)}
        assert not numbers & {"12356", "120", "12355"}, region


def test_every_region_except_zz_has_an_l3_line_and_emergency_number():
    for region in REGIONS - {"ZZ"}:
        data = _load()["regions"][region]
        assert data.get("emergency"), region
        assert any("L3" in line["levels"] for line in data["lines"]), region


def test_741741_is_us_only():
    for region in REGIONS - {"US"}:
        assert "741741" not in {entry["number"] for entry in _entries(region)}, region
