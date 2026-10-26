"""Gap-tolerant compositional cues (fix F1).

The phrase lexicon matches closed, exact phrases, so one inserted word (已经, 都, 也, 真的)
or another verb of the same meaning breaks a match. A ``Composition`` (``risk.yaml``,
section ``compositions``) instead joins two phrase lists, an intent verb and an act of
ending one's life for example, across a short gap without clause punctuation. The checks
that keep it from firing on everyday text are generic: exceptions around a part, blocker
words in the gap, a negator in the gap or just before the first part, a third person as
the subject, a required context nearby, voiding words in the same clause (or nearby, with
``unless_across``) and, for an
entry with ``trailing``, anything but a sentence particle after it in its clause. Each is
described on :class:`~olivia.core.safety.lexicon.Composition`.

All matching runs on :func:`~olivia.core.safety.normalize.normalize` output, one
Aho-Corasick scan over every phrase of the section, then a bounded search per entry. An
entry whose heads (or required context) do not occur costs one set lookup per phrase found
in the message, not per phrase of the entry (F6a: the entries keep growing).
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Iterable, Sequence, Set
from dataclasses import dataclass
from itertools import accumulate

from olivia.core.safety.lexicon import Composition, CompositionRules
from olivia.core.safety.matcher import Match, PhraseMatcher


@dataclass(frozen=True)
class CompositionHit:
    """One accepted match of an entry; ``end`` is exclusive."""

    entry: Composition
    start: int
    end: int


class _Spans:
    """Occurrences sorted by start, answering containment and overlap queries in
    O(log n) plus the size of the answer."""

    def __init__(self, spans: Iterable[Match]) -> None:
        self._spans = sorted(spans, key=lambda m: (m.start, m.end))
        self._starts = [m.start for m in self._spans]
        # _max_ends[i]: the furthest end among the first i + 1 spans.
        self._max_ends = list(accumulate((m.end for m in self._spans), max))

    def __bool__(self) -> bool:
        return bool(self._spans)

    def any_inside(self, a: int, b: int) -> bool:
        """Is some span wholly inside [a, b)?"""
        if a >= b:
            return False
        i = bisect_left(self._starts, a)
        j = bisect_left(self._starts, b, lo=i)
        return any(m.end <= b for m in self._spans[i:j])

    def overlaps(self, a: int, b: int) -> bool:
        """Does some span share a character with [a, b)?"""
        j = bisect_left(self._starts, b)
        return j > 0 and self._max_ends[j - 1] > a

    def covers(self, span: Match) -> bool:
        """Does some span wholly contain ``span``?"""
        i = bisect_right(self._starts, span.start)
        return i > 0 and self._max_ends[i - 1] >= span.end


@dataclass(frozen=True)
class _Person:
    start: int
    end: int
    is_self: bool
    listener: bool


@dataclass(frozen=True)
class _Lists:
    """The section's shared phrase lists as sets, built once per composer."""

    negators: frozenset[str]
    non_negators: frozenset[str]
    selves: frozenset[str]
    others: frozenset[str]
    recipients: frozenset[str]
    listeners: frozenset[str]

    @classmethod
    def of(cls, rules: CompositionRules) -> _Lists:
        return cls(
            negators=frozenset(rules.negators),
            non_negators=frozenset(rules.non_negators),
            selves=frozenset(rules.selves),
            others=frozenset(rules.others),
            recipients=frozenset(rules.recipients),
            listeners=frozenset(rules.listeners),
        )


@dataclass(frozen=True)
class _EntrySets:
    """One entry's phrase lists as sets, built once per composer."""

    heads: frozenset[str]
    tails: frozenset[str]
    exceptions: frozenset[str]
    blockers: frozenset[str]
    context: frozenset[str]
    unless: frozenset[str]

    @classmethod
    def of(cls, entry: Composition) -> _EntrySets:
        return cls(
            heads=frozenset(entry.heads),
            tails=frozenset(entry.tails),
            exceptions=frozenset(entry.exceptions),
            blockers=frozenset(entry.blockers),
            context=frozenset(entry.context),
            unless=frozenset(entry.unless),
        )


class _Text:
    """Per-message facts shared by every entry: clauses, negators and person words."""

    def __init__(
        self, text: str, rules: CompositionRules, lists: _Lists, found: dict[str, list[Match]]
    ) -> None:
        n = len(text)
        self.text = text
        self.found = found
        # clause_start[i]: first index of the clause holding position i; clause_end[i]: the
        # index of the first stop at or after i (n when none).
        self.clause_start = [0] * (n + 1)
        self.clause_end = [n] * (n + 1)
        self._stops_before = [0] * (n + 1)
        start = 0
        for i, ch in enumerate(text):
            self.clause_start[i] = start
            stop = ch in rules.stops
            self._stops_before[i + 1] = self._stops_before[i] + stop
            if stop:
                start = i + 1
        self.clause_start[n] = start
        end = n
        for i in range(n - 1, -1, -1):
            if text[i] in rules.stops:
                end = i
            self.clause_end[i] = end
        self.negators = _Spans(self._real_negators(text, lists))
        self.persons = self._subjects(lists)
        self._person_starts = [p.start for p in self.persons]

    def no_stop(self, a: int, b: int) -> bool:
        return self._stops_before[b] == self._stops_before[a]

    def spans(self, phrases: Set[str]) -> list[Match]:
        """Every occurrence of ``phrases``, in no particular order."""
        found = self.found
        if len(phrases) < len(found):
            return [m for phrase in phrases for m in found.get(phrase, ())]
        return [m for phrase, ms in found.items() if phrase in phrases for m in ms]

    def _real_negators(self, text: str, lists: _Lists) -> list[Match]:
        """Negator occurrences that negate: not inside a non-negating word (忍不住) and not
        the middle of an A-not-A question (要不要, 是不是, 有没有)."""
        neutral = _Spans(self.spans(lists.non_negators))
        real: list[Match] = []
        for m in self.spans(lists.negators):
            if neutral.covers(m):
                continue
            if m.start > 0 and m.end < len(text) and text[m.start - 1] == text[m.end]:
                continue
            real.append(m)
        return real

    def _subjects(self, lists: _Lists) -> list[_Person]:
        """Person words that can be a subject, sorted by start. One right after a recipient
        word (跟她说, 给我妈, 告诉妹妹) is an object and is left out."""
        recipient_ends = {m.end for m in self.spans(lists.recipients)}
        listeners = _Spans(self.spans(lists.listeners))
        people = [
            _Person(m.start, m.end, is_self, not is_self and listeners.covers(m))
            for phrases, is_self in ((lists.selves, True), (lists.others, False))
            for m in self.spans(phrases)
        ]
        subjects = [
            p for p in people if p.start not in recipient_ends and p.start - 1 not in recipient_ends
        ]
        subjects.sort(key=lambda p: (p.start, -p.end))
        return subjects

    def last_person(
        self, a: int, b: int, parts: Sequence[Match], *, carried: bool = False
    ) -> _Person | None:
        """The last person word wholly inside [a, b) and outside the parts. With ``carried``
        (a subject carried over from an earlier clause), listeners (你) do not count."""
        lo = bisect_left(self._person_starts, a)
        hi = bisect_left(self._person_starts, b, lo=lo)
        for person in reversed(self.persons[lo:hi]):
            if person.end > b or any(person.start < p.end and p.start < person.end for p in parts):
                continue
            if carried and person.listener:
                continue
            return person
        return None


@dataclass(frozen=True)
class _EntryFacts:
    """One entry's own phrase occurrences in one message."""

    exceptions: _Spans
    blockers: _Spans
    context: _Spans
    unless: _Spans


class Composer:
    """Finds every composition entry that fires in a normalized text."""

    def __init__(self, rules: CompositionRules) -> None:
        self._rules = rules
        phrases: set[str] = {
            *rules.negators,
            *rules.non_negators,
            *rules.selves,
            *rules.others,
            *rules.recipients,
        }
        for entry in rules.entries:
            phrases.update(
                entry.heads,
                entry.tails,
                entry.context,
                entry.unless,
                entry.exceptions,
                entry.blockers,
            )
        self._matcher = PhraseMatcher({phrase: phrase for phrase in phrases})
        self._lists = _Lists.of(rules)
        self._sets = tuple((entry, _EntrySets.of(entry)) for entry in rules.entries)

    def find(self, text: str) -> list[CompositionHit]:
        """The first accepted match of each entry that fires, in entry order."""
        if not self._rules.entries or not text:
            return []
        found: dict[str, list[Match]] = {}
        for match in self._matcher.find_all(text):
            found.setdefault(match.key, []).append(match)
        facts = _Text(text, self._rules, self._lists, found)
        hits: list[CompositionHit] = []
        for entry, sets in self._sets:
            hit = self._first_hit(entry, sets, facts)
            if hit is not None:
                hits.append(hit)
        return hits

    def _first_hit(
        self, entry: Composition, sets: _EntrySets, facts: _Text
    ) -> CompositionHit | None:
        found_heads = facts.spans(sets.heads)
        if not found_heads:
            return None
        context = _Spans(facts.spans(sets.context))
        if entry.context and not context:
            return None
        own = _EntryFacts(
            exceptions=_Spans(facts.spans(sets.exceptions)),
            blockers=_Spans(facts.spans(sets.blockers)),
            context=context,
            unless=_Spans(facts.spans(sets.unless)),
        )
        heads = sorted(
            (m for m in found_heads if not own.exceptions.covers(m)),
            key=lambda m: (m.start, m.end),
        )
        if not heads:
            return None
        if not entry.tails:
            for head in heads:
                if self._accept(entry, own, facts, head, head):
                    return CompositionHit(entry, head.start, head.end)
            return None
        tails = sorted(
            (m for m in facts.spans(sets.tails) if not own.exceptions.covers(m)),
            key=lambda m: (m.start, m.end),
        )
        by_end = sorted(heads, key=lambda m: (m.end, m.start))
        ends = [m.end for m in by_end]
        starts = [m.start for m in heads]
        gap = entry.max_gap
        for tail in tails:
            low, high = bisect_left(ends, tail.start - gap), bisect_right(ends, tail.start)
            pairs = [(head, tail) for head in by_end[low:high]]
            if entry.either_order:
                low, high = bisect_left(starts, tail.end), bisect_right(starts, tail.end + gap)
                pairs += [(tail, head) for head in heads[low:high]]
            for first, second in pairs:
                if facts.no_stop(first.end, second.start) and self._accept(
                    entry, own, facts, first, second
                ):
                    return CompositionHit(entry, first.start, second.end)
        return None

    def _accept(
        self, entry: Composition, own: _EntryFacts, facts: _Text, first: Match, second: Match
    ) -> bool:
        rules = self._rules
        if own.blockers.any_inside(first.end, second.start):
            return False
        clause = facts.clause_start[first.start]
        look = max(clause, first.start - rules.lookback)
        if facts.negators.any_inside(look, first.start) or facts.negators.any_inside(
            first.end, second.start
        ):
            return False
        if entry.persons:
            subject_from = max(clause, second.start - rules.subject_window)
            person = facts.last_person(subject_from, second.start, (first, second))
            if person is None and subject_from == clause > 0:
                # A clause that names nobody keeps the subject of the clause before it
                # (我朋友最近很难过，总说要自杀); a listener (谢谢你，) is not carried over.
                earlier = max(0, clause - 2 * rules.subject_window)
                person = facts.last_person(earlier, clause, (), carried=True)
            if person is not None and not person.is_self:
                return False
        window = entry.context_window
        if (
            entry.context
            and window is not None
            and not own.context.overlaps(first.start - window, second.end + window)
        ):
            return False
        if entry.unless:
            a = first.start - entry.unless_window
            b = second.end + entry.unless_window
            if entry.unless_across:
                a, b = max(0, a), min(len(facts.text), b)
            else:
                a, b = max(clause, a), min(facts.clause_end[second.end], b)
            if own.unless.any_inside(a, b):
                return False
        if entry.trailing is not None:
            return _only(facts.text[second.end : facts.clause_end[second.end]], entry.trailing)
        return True


def _only(rest: str, phrases: tuple[str, ...]) -> bool:
    """Is ``rest`` made of ``phrases`` alone (any number, any order, possibly none)?"""
    while rest:
        phrase = next((p for p in phrases if rest.startswith(p)), None)
        if phrase is None:
            return False
        rest = rest[len(phrase) :]
    return True
