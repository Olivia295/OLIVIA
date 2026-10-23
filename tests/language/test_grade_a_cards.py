"""Structural and wording checks for the Grade A follow-along cards.

The cards are a clinical draft awaiting G-0 review; these tests only guard that each
card stays faithful to taxonomy.yaml (one card per method, one step per core step,
same duration) and inside the WILLOW length and wording limits.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CARDS_PATH = ROOT / "olivia/data/cards/grade_a.yaml"
TAX_PATH = ROOT / "olivia/data/taxonomy.yaml"

HEADER = (
    "# 草稿：待 G-0 两名注册心理师审核"
    "（docs/superpowers/plans/2026-10-22-remaining-roadmap.md R1-4）"
)
EXCLUDED_ID = "12:tipp_cold_water"
EXCLUDED_REASON = "冷水刺激仅保留在 taxonomy，产品不提供跟练脚本，待 G-0 决定"
CARD_ACTION_TYPES = {"STABILIZATION", "MICRO_EXERCISE"}
FORBIDDEN = ["抑郁症", "焦虑症", "症状", "病情", "确诊", "你应该", "必须", "冰水", "冷水"]
LIMITS = {"intro": 60, "closing": 40, "stealth_note": 40, "safety_note": 60}
STEP_LIMIT = 80
MAX_MINUTES = 5
TEXT_FIELDS = ["title", "intro", "closing", "stealth_note", "safety_note"]

DOC: dict[str, Any] = yaml.safe_load(CARDS_PATH.read_text(encoding="utf-8"))
TAX: dict[str, Any] = yaml.safe_load(TAX_PATH.read_text(encoding="utf-8"))
CARDS: list[dict[str, Any]] = DOC["cards"]


def _sources() -> dict[str, dict[str, Any]]:
    """Every taxonomy entry that should have a card, keyed by id."""
    entries = {m["id"]: m for m in TAX["method_safety_tiers"]["grade_A"]["methods"]}
    for action in TAX["action_registry"]:
        if action["action_type"] in CARD_ACTION_TYPES:
            entries[action["id"]] = action
    return entries


SOURCES = _sources()
EXPECTED_IDS = sorted(set(SOURCES) - {EXCLUDED_ID})
CARD_BY_ID = {card["id"]: card for card in CARDS}


def test_header_marks_draft_awaiting_g0() -> None:
    first_line = CARDS_PATH.read_text(encoding="utf-8").splitlines()[0]
    assert first_line == HEADER


def test_persona_is_gentle_holding() -> None:
    assert DOC["persona"] == "gentle_holding"


def test_grade_a_has_32_methods() -> None:
    assert len(TAX["method_safety_tiers"]["grade_A"]["methods"]) == 32


def test_exactly_one_card_per_expected_id() -> None:
    ids = [card["id"] for card in CARDS]
    assert len(ids) == len(set(ids)), "duplicate card ids"
    assert sorted(ids) == EXPECTED_IDS


def test_cold_water_is_excluded_with_reason() -> None:
    assert EXCLUDED_ID in SOURCES
    assert EXCLUDED_ID not in CARD_BY_ID
    assert DOC["excluded"] == [{"id": EXCLUDED_ID, "reason": EXCLUDED_REASON}]


@pytest.mark.parametrize("card_id", EXPECTED_IDS)
def test_card_matches_taxonomy(card_id: str) -> None:
    card, source = CARD_BY_ID[card_id], SOURCES[card_id]
    assert card["title"] == source["name_zh"]
    assert len(card["steps"]) == len(source["core_action_steps"])
    assert card["duration_minutes"] == source["duration_minutes"]
    assert card["duration_minutes"] <= MAX_MINUTES


@pytest.mark.parametrize("card_id", EXPECTED_IDS)
def test_card_lengths(card_id: str) -> None:
    card = CARD_BY_ID[card_id]
    for field, limit in LIMITS.items():
        if field in card:
            assert 0 < len(card[field]) <= limit, f"{card_id}.{field}: {len(card[field])}"
    for i, step in enumerate(card["steps"]):
        assert 0 < len(step) <= STEP_LIMIT, f"{card_id}.steps[{i}]: {len(step)}"


@pytest.mark.parametrize("card_id", EXPECTED_IDS)
def test_card_wording(card_id: str) -> None:
    card = CARD_BY_ID[card_id]
    texts = [card[f] for f in TEXT_FIELDS if f in card] + list(card["steps"])
    for text in texts:
        hits = [word for word in FORBIDDEN if word in text]
        assert not hits, f"{card_id}: {hits} in {text!r}"
    assert "0" in card["closing"] and "10" in card["closing"], "closing must ask for SUDS 0-10"


@pytest.mark.parametrize("card_id", EXPECTED_IDS)
def test_stealth_and_safety_notes_follow_taxonomy(card_id: str) -> None:
    card, source = CARD_BY_ID[card_id], SOURCES[card_id]
    assert ("stealth_note" in card) == bool(source["stealth_workplace_compatible"])
    assert ("safety_note" in card) == bool(source.get("contraindications"))


def test_cards_have_only_known_fields() -> None:
    allowed = {"id", "duration_minutes", "steps", "display_title", *TEXT_FIELDS}
    for card in CARDS:
        assert set(card) <= allowed, f"{card['id']}: {set(card) - allowed}"
