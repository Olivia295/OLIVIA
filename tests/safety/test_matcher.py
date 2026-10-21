import pytest

from olivia.core.safety.matcher import Match, PhraseMatcher


def test_finds_overlapping_phrases():
    m = PhraseMatcher({"想死": "L2", "想死的心都有了": "HYP", "死": "X"})
    found = m.find_all("我想死的心都有了")
    assert Match("L2", 1, 3) in found
    assert Match("HYP", 1, 8) in found
    assert Match("X", 2, 3) in found
    assert found == sorted(found, key=lambda x: (x.start, x.end))


def test_repeated_occurrences():
    assert [x.start for x in PhraseMatcher({"累": "K"}).find_all("累累累")] == [0, 1, 2]


def test_no_match_returns_empty():
    assert PhraseMatcher({"想死": "K"}).find_all("今天天气不错") == []


def test_empty_phrase_rejected():
    with pytest.raises(ValueError):
        PhraseMatcher({"": "K"})


def test_suffix_phrase_found_via_failure_link():
    # "she" contains "he"; "hers" shares prefix with "he": classic failure-link case.
    m = PhraseMatcher({"he": "A", "she": "B", "his": "C", "hers": "D"})
    found = m.find_all("ushers")
    assert found == [Match("B", 1, 4), Match("A", 2, 4), Match("D", 2, 6)]


def test_failure_link_recovers_after_partial_prefix():
    m = PhraseMatcher({"abcd": "K", "bcx": "J"})
    assert m.find_all("abcbcx") == [Match("J", 3, 6)]


def test_different_phrases_may_share_key():
    m = PhraseMatcher({"想死": "K", "不想活": "K"})
    assert m.find_all("不想活想死") == [Match("K", 0, 3), Match("K", 3, 5)]


def test_empty_text_and_empty_matcher():
    assert PhraseMatcher({"想死": "K"}).find_all("") == []
    assert PhraseMatcher({}).find_all("想死") == []


def test_matches_are_not_confused_by_mixed_scripts():
    m = PhraseMatcher({"ptsd": "P", "好累": "T"})
    assert m.find_all("我有ptsd好累") == [Match("P", 2, 6), Match("T", 6, 8)]
