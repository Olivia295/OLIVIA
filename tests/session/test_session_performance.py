"""G-3: the offline control loop (one ``Session.turn``) stays within P99 55 ms (SDD §10.1)."""

from __future__ import annotations

import os
import random
import time
from datetime import UTC, datetime

import pytest

from olivia.core.models import PersonaProfile, UserRegion
from olivia.core.session import Session
from olivia.core.taxonomy import load_taxonomy

TURNS = 200
# The 55 ms budget is for the single-core reference machine (ruling 32). CI runners vary
# by several times between instances, so there it only guards against a gross slowdown.
P99_BUDGET_S = 0.150 if os.environ.get("CI") else 0.055
NOW = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)
# One cycle walks explore, empower with a card, closing, haven, crisis and red-flag paths.
SCRIPT = (
    "最近工作压力很大，有点焦虑，晚上总睡不着",
    "被领导催进度，心慌得要命",
    "给我一个方法",
    "/done",
    "[5%] 好累，今天不想动脑，只想躺着",
    "[60%] 好一点了，想聊聊我和室友的事情，我觉得她根本不在乎我",
    "心慌得要命，喘不上气，直接给我一个方法",
    "/not-now",
    ("今天加班到很晚，领导又催进度，感觉活着好累，" * 20)[:500],
    "我是边缘型人格，确诊两年了，给我一个练习",
    "我不想活了",
    "我现在安全了",
    "嗯",
    "嗯",
)


def _coverage_is_tracing() -> bool:
    try:
        import coverage
    except ImportError:
        return False
    return coverage.Coverage.current() is not None


def _mixed_turns() -> list[float]:
    tax = load_taxonomy()
    profile = PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        region=UserRegion("CN", "Asia/Shanghai"),
    )
    samples: list[float] = []
    session = Session.open(tax, profile, rng=random.Random(3), now=lambda: NOW)
    for i in range(TURNS):
        if i % len(SCRIPT) == 0:
            session = Session.open(tax, profile, rng=random.Random(i), now=lambda: NOW)
        text = SCRIPT[i % len(SCRIPT)]
        t0 = time.perf_counter()
        session.turn(text)
        samples.append(time.perf_counter() - t0)
    return sorted(samples)


# Line tracing multiplies the cost of every Python line; scripts/check.sh runs this file
# again without coverage, where the budget applies.
@pytest.mark.skipif(_coverage_is_tracing(), reason="latency is not measurable under coverage")
def test_turn_p99_within_the_control_loop_budget():
    _mixed_turns()  # warm-up: loads and caches the shared data
    # Scheduler jitter on shared runners has nothing to do with this code, so the budget
    # applies to the best of three rounds: a real slowdown fails every round.
    p99s = []
    for _ in range(3):
        samples = _mixed_turns()
        p99s.append(samples[int(len(samples) * 0.99) - 1])
    assert min(p99s) <= P99_BUDGET_S, f"P99 per round (s): {p99s}, budget {P99_BUDGET_S}"
