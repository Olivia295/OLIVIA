import time

from olivia.core.safety.crisis import SafetyScreen
from olivia.core.safety.lexicon import load_safety_lexicons
from olivia.core.taxonomy import load_taxonomy


def test_assess_p99_under_one_millisecond():
    tax = load_taxonomy()
    screen = SafetyScreen(tax, load_safety_lexicons(tax))
    text = ("今天加班到很晚，领导又催进度，感觉活着好累，" * 20)[:500]
    for _ in range(200):
        screen.assess(text)
    samples = []
    for _ in range(2000):
        t0 = time.perf_counter()
        screen.assess(text)
        samples.append(time.perf_counter() - t0)
    samples.sort()
    assert samples[int(len(samples) * 0.99)] < 0.001
