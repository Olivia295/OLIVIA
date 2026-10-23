"""Rules mode is the default and must not drift when model-mode perception changes (C1).

``rules_mode_golden.json`` holds every turn of two scripted rules-only sessions (reply,
kind, stage, levels, action, flags and the ``inspect`` panel data) as recorded before
the student's other heads were wired in (roadmap C1). The perception keys added to
``inspect`` then (``PERCEPTION_KEYS``) are left out of the comparison; their rules-mode
values are checked against the rule stub in ``test_session_model_heads.py``.

Regenerate only for an intended rules-mode change, by calling ``write_golden()``.
"""

from __future__ import annotations

import json
import random
from datetime import UTC, datetime
from pathlib import Path

from olivia.core.models import PersonaProfile, UserRegion
from olivia.core.session import Session
from olivia.core.taxonomy import load_taxonomy

GOLDEN = Path(__file__).with_name("rules_mode_golden.json")
PERCEPTION_KEYS = ("valence", "emotion", "intent", "stance", "readiness")
NOW = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)
SEEDS = (3, 11)
# Explore, empower with a card, feedback, haven, lock, stabilization, a long message,
# a red flag, a crisis and its exit.
SCRIPT = (
    "最近工作压力很大，有点焦虑，晚上总睡不着",
    "被领导催进度，心慌得要命",
    "给我一个方法",
    "/done",
    "[5%] 好累，今天不想动脑，只想躺着",
    "[60%] 好一点了，想聊聊我和室友的事情，我觉得她根本不在乎我",
    "你听我说就好，不用给建议",
    "心慌得要命，喘不上气，直接给我一个方法",
    "/not-now",
    "锦囊里那个再给我看看",
    ("今天加班到很晚，领导又催进度，感觉活着好累，" * 20)[:500],
    "我是边缘型人格，确诊两年了，给我一个练习",
    "我不想活了",
    "我现在安全了",
    "嗯",
    "嗯",
)


def transcript() -> list[dict[str, object]]:
    tax = load_taxonomy()
    profile = PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        region=UserRegion("CN", "Asia/Shanghai"),
    )
    turns: list[dict[str, object]] = []
    for seed in SEEDS:
        session = Session.open(tax, profile, rng=random.Random(seed), now=lambda: NOW)
        for text in SCRIPT:
            result = session.turn(text)
            card = result.resource_card
            turns.append(
                {
                    "reply": result.reply,
                    "kind": result.reply_kind.value,
                    "stage": result.stage.value,
                    "crisis_level": result.crisis_level.name,
                    "in_crisis": result.in_crisis,
                    "card": None if card is None else card.level.name,
                    "action_id": result.action_id,
                    "referral_flags": sorted(result.referral_flags),
                    "inspect": dict(result.inspect),
                }
            )
    return turns


def write_golden() -> None:
    GOLDEN.write_text(
        json.dumps(transcript(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )


def test_rules_mode_matches_the_recorded_golden():
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    current = json.loads(json.dumps(transcript(), ensure_ascii=False))
    for turn in current:
        for key in PERCEPTION_KEYS:
            turn["inspect"].pop(key, None)
    assert len(current) == len(golden)
    for i, (got, want) in enumerate(zip(current, golden, strict=True)):
        assert got == want, f"turn {i}"
