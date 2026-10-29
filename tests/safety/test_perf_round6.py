"""Round 6 performance (2026-10-30): the same results with less memory and less repeated work.

Round 6 added about fifty composition entries and their phrase lists; peak RSS in model
mode went past the 100 MB budget of ``scripts/bench_loop.py`` and the safety screen's P99
grew. Nothing here changes what any screen, matcher or fold returns:

* ``PhraseMatcher`` numbers its nodes in depth-first preorder, so the many nodes with one
  child share one edge mapping per character (``test_matcher_reference.py`` checks it
  against the original automaton);
* ``normalize`` remembers its last results: a turn folds the same message a dozen times
  (screen, red flags, reported speech, mirror, guard), and a long message costs about
  85 µs per fold;
* the phrase index shared by the rule screen and the model screen remembers its last
  scans, so the model screen's rule pass over the same message does not scan it again.
"""

from __future__ import annotations

import tracemalloc

from olivia.core.safety import crisis
from olivia.core.safety.crisis import SafetyScreen
from olivia.core.safety.lexicon import load_safety_lexicons
from olivia.core.safety.matcher import PhraseMatcher
from olivia.core.safety.normalize import normalize
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
LONG = ("今天加班到很晚，领导又催进度，感觉活着好累，" * 20)[:500]


def _composer_phrases() -> dict[str, str]:
    index = crisis._CueIndex(load_safety_lexicons(TAX))
    return {key: key for found in index.composer._matcher._outputs for _, key in found}


def test_the_matcher_keeps_its_nodes_compact() -> None:
    phrases = _composer_phrases()
    assert len(phrases) > 3000
    tracemalloc.start()
    try:
        before = tracemalloc.get_traced_memory()[0]
        matcher = PhraseMatcher(phrases)
        held = tracemalloc.get_traced_memory()[0] - before
    finally:
        tracemalloc.stop()
    nodes = len(matcher._links)
    assert nodes > 10_000
    # A dict per node, as before, held about 220 bytes a node.
    assert held / nodes < 130, (held, nodes)


def test_normalize_remembers_a_message_it_just_folded() -> None:
    first = normalize(LONG)
    assert normalize(LONG) is first
    assert first == normalize.__wrapped__(LONG)  # type: ignore[attr-defined]


def test_the_shared_index_scans_a_message_once_for_both_screens(monkeypatch) -> None:
    lexicons = load_safety_lexicons(TAX)
    rules = SafetyScreen(TAX, lexicons)
    index = rules._index
    expected_scan = index.scan(normalize("我不想活了"))
    expected_compose = index.compose(normalize("我不想活了"))
    calls: list[str] = []
    real_find = index.matcher.find_all
    real_compose = index.composer.find

    def counting_find(text: str):  # type: ignore[no-untyped-def]
        calls.append("scan")
        return real_find(text)

    def counting_compose(text: str):  # type: ignore[no-untyped-def]
        calls.append("compose")
        return real_compose(text)

    monkeypatch.setattr(index.matcher, "find_all", counting_find)
    monkeypatch.setattr(index.composer, "find", counting_compose)
    text = LONG + "我打算今晚从楼顶跳下去"
    first = rules.assess(text)
    scans = len(calls)
    assert scans >= 2
    assert rules.assess(text) == first
    assert len(calls) == scans  # nothing scanned again
    # Each caller gets its own list.
    got = index.scan(normalize("我不想活了"))
    got.clear()
    assert index.scan(normalize("我不想活了")) == expected_scan
    assert index.compose(normalize("我不想活了")) == expected_compose
