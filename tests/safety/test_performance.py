import os
import time

import pytest

from olivia.core.safety.crisis import SafetyScreen
from olivia.core.safety.lexicon import load_safety_lexicons
from olivia.core.taxonomy import load_taxonomy

ROUNDS = 5
SAMPLES_PER_ROUND = 2000
# The 1 ms budget (SDD §10.1) is for a single-core baseline machine. CI runners vary by
# several times between instances, so there it only guards against a gross slowdown.
P99_BUDGET_S = 0.003 if os.environ.get("CI") else 0.001
# A quadratic containment check would take far longer than either bound on 80,000 chars.
LONG_INPUT_BUDGET_S = 2.0 if os.environ.get("CI") else 0.5


def _coverage_is_tracing() -> bool:
    try:
        import coverage
    except ImportError:
        return False
    return coverage.Coverage.current() is not None


# Line tracing roughly multiplies the cost of every Python line, so a latency budget
# measured under coverage says nothing about the code. scripts/check.sh runs this file
# again without coverage, where the budget applies.
@pytest.mark.skipif(_coverage_is_tracing(), reason="latency is not measurable under coverage")
def test_assess_p99_under_one_millisecond():
    tax = load_taxonomy()
    screen = SafetyScreen(tax, load_safety_lexicons(tax))
    text = ("今天加班到很晚，领导又催进度，感觉活着好累，" * 20)[:500]
    for _ in range(200):
        screen.assess(text)
    # Shared CI runners add scheduler jitter that has nothing to do with this code, so the
    # budget applies to the best of several rounds: a real slowdown fails every round.
    p99s = []
    for _ in range(ROUNDS):
        samples = []
        for _ in range(SAMPLES_PER_ROUND):
            t0 = time.perf_counter()
            screen.assess(text)
            samples.append(time.perf_counter() - t0)
        samples.sort()
        p99s.append(samples[int(len(samples) * 0.99)])
    assert min(p99s) < P99_BUDGET_S, f"P99 per round (s): {p99s}, budget {P99_BUDGET_S}"


@pytest.mark.skipif(_coverage_is_tracing(), reason="latency is not measurable under coverage")
def test_long_input_with_many_masked_cues_stays_fast():
    # Every 想死 sits inside a 不想死 mask: the containment check must not be quadratic.
    tax = load_taxonomy()
    screen = SafetyScreen(tax, load_safety_lexicons(tax))
    text = "不想死，" * 20000
    t0 = time.perf_counter()
    assessment = screen.assess(text)
    elapsed = time.perf_counter() - t0
    assert assessment.cue_ids == ()
    assert elapsed < LONG_INPUT_BUDGET_S, f"{elapsed:.3f}s for {len(text)} chars"


@pytest.mark.skipif(_coverage_is_tracing(), reason="latency is not measurable under coverage")
def test_long_input_with_many_excepted_pair_anchors_stays_fast():
    # Every 自杀 sits inside a 预防自杀 exception next to a request word: the pair cue's
    # exception check must not be quadratic either.
    tax = load_taxonomy()
    screen = SafetyScreen(tax, load_safety_lexicons(tax))
    text = "预防自杀，最快，" * 10000
    t0 = time.perf_counter()
    assessment = screen.assess(text)
    elapsed = time.perf_counter() - t0
    assert assessment.cue_ids == ()
    assert elapsed < LONG_INPUT_BUDGET_S, f"{elapsed:.3f}s for {len(text)} chars"


@pytest.mark.skipif(_coverage_is_tracing(), reason="latency is not measurable under coverage")
def test_long_input_with_many_voided_compositions_stays_fast():
    # Thousands of composition candidates, each voided by a third person, a negator or an
    # everyday word in its clause (fix F1): the per-candidate checks must stay bounded.
    tax = load_taxonomy()
    screen = SafetyScreen(tax, load_safety_lexicons(tax))
    text = "她打算明天自杀，我不要自杀，感冒药准备好了，不想死，" * 3000
    t0 = time.perf_counter()
    assessment = screen.assess(text)
    elapsed = time.perf_counter() - t0
    assert assessment.cue_ids == ()
    assert elapsed < LONG_INPUT_BUDGET_S, f"{elapsed:.3f}s for {len(text)} chars"
