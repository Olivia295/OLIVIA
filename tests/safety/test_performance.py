import time

from olivia.core.safety.crisis import SafetyScreen
from olivia.core.safety.lexicon import load_safety_lexicons
from olivia.core.taxonomy import load_taxonomy

ROUNDS = 5
SAMPLES_PER_ROUND = 2000


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
    assert min(p99s) < 0.001, f"P99 per round (s): {p99s}"


def test_long_input_with_many_masked_cues_stays_fast():
    # Every 想死 sits inside a 不想死 mask: the containment check must not be quadratic.
    tax = load_taxonomy()
    screen = SafetyScreen(tax, load_safety_lexicons(tax))
    text = "不想死，" * 20000
    t0 = time.perf_counter()
    assessment = screen.assess(text)
    elapsed = time.perf_counter() - t0
    assert assessment.cue_ids == ()
    assert elapsed < 0.5, f"{elapsed:.3f}s for {len(text)} chars"
