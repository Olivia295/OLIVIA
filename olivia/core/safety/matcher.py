"""Multi-pattern phrase matching (Aho-Corasick) in a single linear scan."""

from __future__ import annotations

import functools
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from operator import attrgetter
from sys import intern
from typing import Final, cast

_LEAF: Final[Mapping[str, int]] = {}  # shared by every node without children; never written
_NO_OUTPUTS: Final[tuple[tuple[int, str], ...]] = ()
_BY_SPAN: Final = attrgetter("start", "end")


@dataclass(frozen=True)
class Match:
    """One occurrence of a phrase; ``end`` is exclusive."""

    key: str
    start: int
    end: int


@functools.cache
def _only_child(ch: str) -> Mapping[str, int]:
    """The edges of a node whose one child is numbered next, shared by every such node
    (never written to, like ``_LEAF``: a node that gets a second child copies it)."""
    return {ch: 1}


class PhraseMatcher:
    """Aho-Corasick automaton mapping phrases to keys.

    ``find_all`` reports every occurrence, overlapping ones included, in one
    pass over the text regardless of how many phrases are registered.

    Once built, the automaton is kept compact (F5d; round 6, 2026-10-30: the session's
    matchers hold about 32,000 nodes, three in four of them with exactly one child). Nodes
    are numbered in depth-first preorder, first child first, so a node's first child is
    the next number, and each node's edges map a character (interned, one string per
    character for every matcher) to ``child - node``. Every node whose one child is the
    next number shares one mapping per character, every node without children one empty
    mapping, and the offsets are mostly small integers, which Python does not allocate.
    Each node's outputs are a shared tuple: a node without a phrase of its own shares its
    failure target's (one empty tuple for every node without any).
    """

    def __init__(self, phrases: Mapping[str, str]) -> None:
        # Phrases inserted in sorted order create their nodes in depth-first preorder: a
        # node's first child, when it gets one, is the very next node created (every
        # phrase between a prefix and its extensions starts with that prefix).
        links: list[Mapping[str, int]] = [{}]
        own: dict[int, tuple[int, str]] = {}  # node -> (phrase length, key)
        for phrase in sorted(phrases):
            if not phrase:
                raise ValueError("phrase must not be empty")
            node = 0
            for ch in phrase:
                edges = links[node]
                step = edges.get(ch)
                if step is None:
                    step = len(links) - node
                    if step == 1 and node:
                        links[node] = _only_child(intern(ch))
                    else:
                        if edges is _LEAF or (node and len(edges) == 1):
                            links[node] = edges = dict(edges)  # shared until now
                        cast(dict[str, int], edges)[intern(ch)] = step
                    links.append(_LEAF)
                node += step
            own[node] = (len(phrase), phrases[phrase])

        # Failure links and outputs breadth first: a node's failure target is shallower,
        # so its outputs are final when the node's are made (its own phrase, then the
        # target's). A node without a phrase of its own shares its target's tuple.
        fail = [0] * len(links)
        outputs: list[tuple[tuple[int, str], ...]] = [_NO_OUTPUTS] * len(links)
        ints: dict[int, int] = {}  # one int object per failure target
        tuples: dict[tuple[tuple[int, str], ...], tuple[tuple[int, str], ...]] = {}
        queue: deque[int] = deque(links[0].values())
        for child in queue:
            if child in own:
                outputs[child] = (own[child],)
        while queue:
            node = queue.popleft()
            for ch, step in links[node].items():
                child = node + step
                queue.append(child)
                state = fail[node]
                while state and ch not in links[state]:
                    state = fail[state]
                target = state + links[state].get(ch, -state)
                fail[child] = ints.setdefault(target, target)
                found = outputs[target]
                if child in own:
                    found = (own[child], *found)
                    found = tuples.setdefault(found, found)
                outputs[child] = found
        self._links = links
        self._fail = fail
        self._outputs = outputs

    def find_all(self, text: str) -> list[Match]:
        """Return all occurrences in ``text``, sorted by ``(start, end)``."""
        links = self._links
        fail = self._fail
        outputs = self._outputs
        found: list[Match] = []
        root = links[0]
        node = 0
        for i, ch in enumerate(text):
            while node:
                edges = links[node]
                if ch in edges:
                    node += edges[ch]  # edges hold child - node
                    break
                node = fail[node]
            else:
                node = root.get(ch, 0)
            for length, key in outputs[node]:
                found.append(Match(key, i + 1 - length, i + 1))
        found.sort(key=_BY_SPAN)
        return found
