import os
import time

import pytest

from olivia.core.models import CrisisLevel
from olivia.core.perception.lexicon import load_perception_lexicon
from olivia.core.perception.rule_stub import RuleStub
from olivia.core.safety.crisis import CrisisAssessment
from olivia.core.taxonomy import load_taxonomy

ROUNDS = 3
SAMPLES_PER_ROUND = 2000
# A 2 ms budget for the stub on a 500-character message; CI runners vary by several
# times between instances, so there it only guards against a gross slowdown.
P99_BUDGET_S = 0.006 if os.environ.get("CI") else 0.002


def _coverage_is_tracing() -> bool:
    try:
        import coverage
    except ImportError:
        return False
    return coverage.Coverage.current() is not None


# Line tracing multiplies the cost of every Python line, so the budget is meaningless
# under coverage. scripts/check.sh runs this file again without coverage.
@pytest.mark.skipif(_coverage_is_tracing(), reason="latency is not measurable under coverage")
def test_perceive_p99_under_two_milliseconds():
    tax = load_taxonomy()
    stub = RuleStub(tax, load_perception_lexicon(tax))
    assessment = CrisisAssessment(CrisisLevel.L0, 0.0, "STAGE2", False, ())
    # Cue-dense text: emotions, modifiers, spectra, negations and signal phrases.
    text = ("[40%] 最近特别焦虑，睡不着，工作压力好大，有点想哭，不是不难过，只想说说。" * 20)[:500]
    assert len(text) == 500
    for _ in range(200):
        stub.perceive(text, assessment)
    # The budget applies to the best round: a real slowdown fails every round, while
    # scheduler jitter on a shared runner does not.
    p99s = []
    for _ in range(ROUNDS):
        samples = []
        for _ in range(SAMPLES_PER_ROUND):
            t0 = time.perf_counter()
            stub.perceive(text, assessment)
            samples.append(time.perf_counter() - t0)
        samples.sort()
        p99s.append(samples[int(len(samples) * 0.99)])
    assert min(p99s) < P99_BUDGET_S, f"P99 per round (s): {p99s}, budget {P99_BUDGET_S}"
