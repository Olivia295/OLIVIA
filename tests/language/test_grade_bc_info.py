"""Grade B/C psychoeducation cards: coverage, length limits and safety wording."""

from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
TAXONOMY_PATH = ROOT / "olivia" / "data" / "taxonomy.yaml"
CARDS_PATH = ROOT / "olivia" / "data" / "cards" / "grade_bc_info.yaml"
REVIEW_HEADER = (
    "# 草稿：待 G-0 两名注册心理师审核"
    "（docs/superpowers/plans/2026-10-22-remaining-roadmap.md R1-4）"
)

FIELDS = {"id", "title", "grade", "what_it_is", "how_it_helps", "who_offers_it", "try_alone"}
LIMITS = {"what_it_is": 80, "how_it_helps": 80, "who_offers_it": 60}
TEXT_FIELDS = ("title", "what_it_is", "how_it_helps", "who_offers_it")
FORBIDDEN = ("练习步骤", "第一步", "跟着我", "你应该", "必须", "治愈", "根治")


def _tier(grade: str) -> dict[str, dict[str, Any]]:
    data = yaml.safe_load(TAXONOMY_PATH.read_text(encoding="utf-8"))
    methods = data["method_safety_tiers"][f"grade_{grade}"]["methods"]
    return {str(m["id"]): m for m in methods}


TIER_B = _tier("B")
TIER_C = _tier("C")
TIER_A = _tier("A")


def _entries() -> list[dict[str, Any]]:
    data = yaml.safe_load(CARDS_PATH.read_text(encoding="utf-8"))
    entries = data["entries"]
    assert isinstance(entries, list)
    return entries


ENTRIES = _entries()


def _entry_id(entry: dict[str, Any]) -> str:
    return str(entry["id"])


def test_file_starts_with_review_header() -> None:
    first_line = CARDS_PATH.read_text(encoding="utf-8").splitlines()[0]
    assert first_line == REVIEW_HEADER


def test_every_grade_b_and_c_id_has_exactly_one_entry() -> None:
    ids = [_entry_id(e) for e in ENTRIES]
    assert len(ids) == len(set(ids)), "duplicate entry ids"
    assert set(ids) == set(TIER_B) | set(TIER_C)


def test_no_grade_a_id_appears() -> None:
    assert not {_entry_id(e) for e in ENTRIES} & set(TIER_A)


@pytest.mark.parametrize("entry", ENTRIES, ids=_entry_id)
def test_entry_shape_matches_taxonomy(entry: dict[str, Any]) -> None:
    assert set(entry) == FIELDS
    method_id = _entry_id(entry)
    expected_grade = "B" if method_id in TIER_B else "C"
    assert entry["grade"] == expected_grade
    tier = TIER_B if expected_grade == "B" else TIER_C
    assert entry["title"] == tier[method_id]["name_zh"]
    for field in TEXT_FIELDS:
        assert isinstance(entry[field], str) and entry[field].strip()


@pytest.mark.parametrize("entry", ENTRIES, ids=_entry_id)
def test_length_limits(entry: dict[str, Any]) -> None:
    for field, limit in LIMITS.items():
        assert len(entry[field]) <= limit, f"{field} is {len(entry[field])} chars (> {limit})"


@pytest.mark.parametrize("entry", ENTRIES, ids=_entry_id)
def test_try_alone_is_false(entry: dict[str, Any]) -> None:
    # PRD: Grade C forbids any self-help guidance; Grade B is psychoeducation only and
    # "不作为指令动作", so no Grade B method currently carries a self-help part either.
    assert entry["try_alone"] is False


@pytest.mark.parametrize("entry", [e for e in ENTRIES if e["grade"] == "C"], ids=_entry_id)
def test_grade_c_says_not_to_try_alone(entry: dict[str, Any]) -> None:
    assert "不建议独自尝试" in entry["who_offers_it"]


@pytest.mark.parametrize("entry", ENTRIES, ids=_entry_id)
def test_no_forbidden_wording(entry: dict[str, Any]) -> None:
    for field in TEXT_FIELDS:
        text = entry[field]
        for word in FORBIDDEN:
            assert word not in text, f"{field} contains {word!r}"
        assert "%" not in text and "％" not in text, f"{field} contains a percentage"
