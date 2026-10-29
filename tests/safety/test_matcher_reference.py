"""F5d: the compact PhraseMatcher finds exactly what the original automaton found.

``_ReferenceMatcher`` is the matcher as it was before F5d (a dict and a list per node),
kept here only as the reference for a randomized comparison.
"""

from __future__ import annotations

import random
from collections import deque
from collections.abc import Mapping

import pytest

from olivia.core.perception.lexicon import load_perception_lexicon
from olivia.core.perception.rule_stub import RuleStub
from olivia.core.safety import compose, crisis, reported
from olivia.core.safety.lexicon import load_safety_lexicons
from olivia.core.safety.matcher import Match, PhraseMatcher
from olivia.core.taxonomy import load_taxonomy


class _ReferenceMatcher:
    def __init__(self, phrases: Mapping[str, str]) -> None:
        children: list[dict[str, int]] = [{}]
        outputs: list[list[tuple[int, str]]] = [[]]
        for phrase, key in phrases.items():
            if not phrase:
                raise ValueError("phrase must not be empty")
            node = 0
            for ch in phrase:
                nxt = children[node].get(ch)
                if nxt is None:
                    nxt = len(children)
                    children[node][ch] = nxt
                    children.append({})
                    outputs.append([])
                node = nxt
            outputs[node].append((len(phrase), key))
        fail = [0] * len(children)
        queue: deque[int] = deque(children[0].values())
        while queue:
            node = queue.popleft()
            for ch, child in children[node].items():
                queue.append(child)
                state = fail[node]
                while state and ch not in children[state]:
                    state = fail[state]
                fail[child] = children[state].get(ch, 0)
                outputs[child].extend(outputs[fail[child]])
        self._children = children
        self._fail = fail
        self._outputs = outputs

    def find_all(self, text: str) -> list[Match]:
        children, fail, outputs = self._children, self._fail, self._outputs
        found: list[Match] = []
        node = 0
        for i, ch in enumerate(text):
            while node and ch not in children[node]:
                node = fail[node]
            node = children[node].get(ch, 0)
            for length, key in outputs[node]:
                found.append(Match(key, i + 1 - length, i + 1))
        found.sort(key=lambda m: (m.start, m.end))
        return found


ALPHABET = "我想死累不好今天就到这里睡了去吗？，ab😀\U0010ffff"


def _random_phrases(rng: random.Random) -> dict[str, str]:
    phrases: dict[str, str] = {}
    for n in range(rng.randint(1, 40)):
        phrase = "".join(rng.choice(ALPHABET) for _ in range(rng.randint(1, 6)))
        phrases[phrase] = f"K{n % 7}"
    return phrases


@pytest.mark.parametrize("seed", range(200))
def test_random_phrases_and_texts_match_the_reference(seed: int) -> None:
    rng = random.Random(seed)
    phrases = _random_phrases(rng)
    compact, reference = PhraseMatcher(phrases), _ReferenceMatcher(phrases)
    for _ in range(20):
        text = "".join(rng.choice(ALPHABET) for _ in range(rng.randint(0, 80)))
        assert compact.find_all(text) == reference.find_all(text), (phrases, text)


def test_the_rule_stub_phrases_match_the_reference() -> None:
    # The two largest phrase sets of a session: the rule stub's scan and feedback.
    tax = load_taxonomy()
    stub = RuleStub(tax, load_perception_lexicon(tax))
    rng = random.Random(7)
    for keys in (stub._tags, stub._feedback_labels):
        phrases = {phrase: phrase for phrase in keys}
        compact, reference = PhraseMatcher(phrases), _ReferenceMatcher(phrases)
        pool = "".join(phrases) + "，。？的了"
        for _ in range(300):
            text = "".join(rng.choice(pool) for _ in range(rng.randint(0, 120)))
            assert compact.find_all(text) == reference.find_all(text)
        for phrase in list(phrases)[:: max(1, len(phrases) // 200)]:
            text = f"今天{phrase}了，{phrase}"
            assert compact.find_all(text) == reference.find_all(text)


def test_the_safety_index_phrases_match_the_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    # Round 6 (2026-10-30, preorder numbering): every phrase set the screen's index builds
    # (cue phrases keyed by cue id, compositions, denial, reported speech ...), as built.
    built: list[dict[str, str]] = []

    class Recording(PhraseMatcher):
        def __init__(self, phrases: Mapping[str, str]) -> None:
            built.append(dict(phrases))
            super().__init__(phrases)

    for module in (crisis, compose, reported):
        monkeypatch.setattr(module, "PhraseMatcher", Recording)
    crisis._CueIndex(load_safety_lexicons(load_taxonomy()))
    assert len(built) >= 5
    rng = random.Random(11)
    for phrases in built:
        compact, reference = PhraseMatcher(phrases), _ReferenceMatcher(phrases)
        pool = "".join(phrases) + "，。？的了我你他"
        for _ in range(150):
            text = "".join(rng.choice(pool) for _ in range(rng.randint(0, 160)))
            assert compact.find_all(text) == reference.find_all(text)
        for phrase in list(phrases)[:: max(1, len(phrases) // 150)]:
            text = f"我{phrase}了，{phrase}吧"
            assert compact.find_all(text) == reference.find_all(text)


def test_an_empty_phrase_is_still_rejected() -> None:
    with pytest.raises(ValueError):
        PhraseMatcher({"a": "K", "": "K"})
