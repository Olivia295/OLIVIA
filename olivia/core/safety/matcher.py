"""Multi-pattern phrase matching (Aho-Corasick) in a single linear scan."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Match:
    """One occurrence of a phrase; ``end`` is exclusive."""

    key: str
    start: int
    end: int


class PhraseMatcher:
    """Aho-Corasick automaton mapping phrases to keys.

    ``find_all`` reports every occurrence, overlapping ones included, in one
    pass over the text regardless of how many phrases are registered.
    """

    def __init__(self, phrases: Mapping[str, str]) -> None:
        children: list[dict[str, int]] = [{}]
        outputs: list[list[tuple[int, str]]] = [[]]  # (phrase length, key)
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
                # BFS order guarantees fail[child] is complete: merge its outputs.
                outputs[child].extend(outputs[fail[child]])

        self._children = children
        self._fail = fail
        self._outputs = outputs

    def find_all(self, text: str) -> list[Match]:
        """Return all occurrences in ``text``, sorted by ``(start, end)``."""
        children = self._children
        fail = self._fail
        outputs = self._outputs
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
