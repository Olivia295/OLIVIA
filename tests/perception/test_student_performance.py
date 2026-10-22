"""P6-6a: ``StudentRiskModel.predict`` stays within P99 45 ms (SDD §10.1)."""

from __future__ import annotations

import os
import random
import time

import pytest

from olivia.core.perception.student import StudentRiskModel, default_student

STRINGS = 200
ROUNDS = 3
# The 45 ms budget is for the single-core reference machine (ruling 32). CI runners vary
# by several times between instances, so there it only guards against a gross slowdown.
P99_BUDGET_S = 0.120 if os.environ.get("CI") else 0.045
PIECES = ("今天", "上班", "好累", "周末", "想去", "公园", "散步", "，", "。", "我", "有点", "压力")


def _coverage_is_tracing() -> bool:
    try:
        import coverage
    except ImportError:
        return False
    return coverage.Coverage.current() is not None


def _texts() -> list[str]:
    rng = random.Random(6)
    texts = []
    for i in range(STRINGS):
        length = (1, 8, 30, 120, 600)[i % 5]  # up to well past max_len
        texts.append("".join(rng.choice(PIECES) for _ in range(length)))
    return texts


@pytest.mark.skipif(_coverage_is_tracing(), reason="latency is not measurable under coverage")
def test_predict_p99_within_budget():
    loaded = default_student()
    assert loaded.model is not None, loaded.reason
    model = StudentRiskModel(loaded.model)
    texts = _texts()
    for text in texts[:20]:  # warm-up
        model.predict(text)
    # The budget applies to the best of several rounds: a real slowdown fails every round.
    p99s = []
    for _ in range(ROUNDS):
        samples = []
        for text in texts:
            t0 = time.perf_counter()
            model.predict(text)
            samples.append(time.perf_counter() - t0)
        samples.sort()
        p99s.append(samples[int(len(samples) * 0.99) - 1])
    assert min(p99s) <= P99_BUDGET_S, f"P99 per round (s): {p99s}, budget {P99_BUDGET_S}"
