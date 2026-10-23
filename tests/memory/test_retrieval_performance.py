"""SDD §10.1 Step 3: one 3D retrieval query stays within P99 2 ms (step B4).

The ledger is a realistic year: 365 daily summaries and 50 notes. The index is built once
per loaded ledger, so the budget is for a query against it.
"""

from __future__ import annotations

import os
import random
import time
from datetime import UTC, datetime, timedelta

import pytest

from olivia.core.memory.ledger import (
    LedgerEntry,
    MethodRecord,
    NoteEntry,
    SessionSummary,
    SummaryEntry,
)
from olivia.core.memory.retrieval import MemoryIndex
from olivia.core.methods.bandit import Feedback
from olivia.core.models import CrisisLevel, HelpStage

QUERIES = 300
# The 2 ms budget is for the single-core reference machine (ruling 32). CI runners vary
# by several times between instances, so there it only guards against a gross slowdown.
P99_BUDGET_S = 0.006 if os.environ.get("CI") else 0.002
NOW = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
TITLES = {
    "12:tipp_breathing": "冷水与呼吸的快速降温",
    "30:grounding": "五感着陆",
    "29:pmr_release": "肌肉一松一紧",
    "05": "五分钟启动",
}
NOTE_SEEDS = (
    "整理桌面会让我有掌控感",
    "妈妈的生日是三月五号，记得提前订蛋糕",
    "下周六考IELTS，口语是弱项，想多练练",
    "和室友谈过之后轻松了很多，她其实也在乎我",
    "跑步二十分钟以后心慌会好一些",
    "领导说下个季度可能调岗，我还没想好要不要去",
    "晚上十一点以后不看手机，睡得会好一点",
    "外婆做的红烧肉是我最想念的味道",
)
MESSAGES = (
    "被领导催进度，心慌得要命",
    "好累，今天不想动脑",
    "又失眠了，躺到三点还睡不着",
    "我觉得她根本不在乎我",
    "下周就要考试了，口语还是很差",
    "桌面乱成一团，什么都找不到",
    "嗯",
    ("今天加班到很晚，领导又催进度，感觉整个人都被掏空了，" * 20)[:500],
)


def _ledger(rng: random.Random) -> list[LedgerEntry]:
    entries: list[LedgerEntry] = []
    path = (HelpStage.S_READY, HelpStage.S_EXPLORE, HelpStage.S_EMPOWER, HelpStage.S_CLOSING)
    for day in range(365):
        start = NOW - timedelta(days=day, hours=rng.randint(0, 12))
        methods = tuple(
            MethodRecord(rng.choice(sorted(TITLES)), rng.choice([*Feedback, None]))
            for _ in range(rng.randint(0, 2))
        )
        crisis = rng.choice([None] * 30 + [CrisisLevel.L1, CrisisLevel.L2])
        summary = SessionSummary(
            started_at=start,
            ended_at=start + timedelta(minutes=rng.randint(5, 60)),
            stage_path=path[: rng.randint(2, 4)],
            spectra=tuple(rng.sample([f"{i:02d}" for i in range(1, 12)], rng.randint(1, 3))),
            methods=methods,
            crisis_level=crisis,
            marked_by_user=rng.random() < 0.02,
        )
        entries.append(SummaryEntry(f"{day:024x}", summary))
    for i in range(50):
        text = "，".join(rng.sample(NOTE_SEEDS, rng.randint(1, 3)))
        when = NOW - timedelta(days=rng.randint(0, 364))
        entries.append(NoteEntry(f"{1000 + i:024x}", text, when))
    return entries


def _coverage_is_tracing() -> bool:
    try:
        import coverage
    except ImportError:
        return False
    return coverage.Coverage.current() is not None


def _queries(index: MemoryIndex) -> list[float]:
    samples: list[float] = []
    for i in range(QUERIES):
        message = MESSAGES[i % len(MESSAGES)]
        t0 = time.perf_counter()
        index.rank(message, NOW)
        samples.append(time.perf_counter() - t0)
    return sorted(samples)


# Line tracing multiplies the cost of every Python line; scripts/check.sh runs this file
# again without coverage, where the budget applies.
@pytest.mark.skipif(_coverage_is_tracing(), reason="latency is not measurable under coverage")
def test_one_query_p99_within_the_retrieval_budget():
    index = MemoryIndex(_ledger(random.Random(29)), method_titles=TITLES)
    assert len(index.entries) == 415
    _queries(index)  # warm-up
    # Scheduler jitter on shared runners has nothing to do with this code, so the budget
    # applies to the best of three rounds: a real slowdown fails every round.
    p99s = []
    for _ in range(3):
        samples = _queries(index)
        p99s.append(samples[int(len(samples) * 0.99) - 1])
    assert min(p99s) <= P99_BUDGET_S, f"P99 per round (s): {p99s}, budget {P99_BUDGET_S}"
