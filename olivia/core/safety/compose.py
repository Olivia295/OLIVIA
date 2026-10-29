"""Gap-tolerant compositional cues (fix F1).

The phrase lexicon matches closed, exact phrases, so one inserted word (已经, 都, 也, 真的)
or another verb of the same meaning breaks a match. A ``Composition`` (``risk.yaml``,
section ``compositions``) instead joins two phrase lists, an intent verb and an act of
ending one's life for example, across a short gap without clause punctuation. The checks
that keep it from firing on everyday text are generic: exceptions around a part, blocker
words in the gap, a negator in the gap or just before the first part, a third person as
the subject, a required context nearby, voiding words in the same clause (or nearby, with
``unless_across``), for an entry with ``trailing``, anything but a sentence particle after
it in its clause and, for an entry with ``leading``, anything but a filler before it in its
clause. Each is described on :class:`~olivia.core.safety.lexicon.Composition`.

Round 3 (2026-10-27): an entry may need more than one context (``also``: a plan word, a
time, a place, each within its own window across clauses and, unless marked negatable, not
right after a negator), so a frame of three or four parts can be said in any order over
several short clauses; with ``clause_negation`` a negator earlier in the clause voids the
match (我不打算这周末去楼顶跳下去) when only the words of the denied plan (``negation_reach``:
plan words, times, places, prepositions) stand between them. Any other word ends its reach
(2026-10-28): in 我再也不想忍了我打算今晚从楼顶跳下去, typed with no punctuation, the 不
belongs to 忍 and the plan after it stands.

All matching runs on :func:`~olivia.core.safety.normalize.normalize` output, one
Aho-Corasick scan over every phrase of the section, then a bounded search per entry. An
entry whose heads (or required context) do not occur costs one set lookup per phrase found
in the message, not per phrase of the entry (F6a: the entries keep growing).
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Iterable, Mapping, Sequence, Set
from dataclasses import dataclass
from itertools import accumulate
from typing import Final

from olivia.core.safety.lexicon import Composition, CompositionRules
from olivia.core.safety.matcher import Match, PhraseMatcher

# What may follow a name said alone to address someone (哥哥，妈啊，).
_VOCATIVE_TAILS: Final = frozenset({"", "啊", "呀", "哇", "哈", "喂", "呐", "嘛", "啦", "哦"})


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

    def inside(self, a: int, b: int) -> list[Match]:
        """The spans wholly inside [a, b)."""
        if a >= b:
            return []
        i = bisect_left(self._starts, a)
        j = bisect_left(self._starts, b, lo=i)
        return [m for m in self._spans[i:j] if m.end <= b]

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
    unless_negators: frozenset[str]
    selves: frozenset[str]
    others: frozenset[str]
    recipients: frozenset[str]
    listeners: frozenset[str]

    @classmethod
    def of(cls, rules: CompositionRules) -> _Lists:
        return cls(
            negators=frozenset(rules.negators),
            non_negators=frozenset(rules.non_negators),
            unless_negators=frozenset(rules.unless_negators),
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
    also: tuple[frozenset[str], ...]

    @classmethod
    def of(cls, entry: Composition, shared: dict[frozenset[str], frozenset[str]]) -> _EntrySets:
        """``shared`` keeps one set per distinct list: many entries name the same list
        (round 6, 2026-10-30: about half a megabyte of repeated sets)."""

        def once(phrases: Iterable[str]) -> frozenset[str]:
            found = frozenset(phrases)
            return shared.setdefault(found, found)

        return cls(
            heads=once(entry.heads),
            tails=once(entry.tails),
            exceptions=once(entry.exceptions),
            blockers=once(entry.blockers),
            context=once(entry.context),
            unless=once(entry.unless),
            also=tuple(once(group.phrases) for group in entry.also),
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
        real = self._real_negators(text, lists)
        self.negators = _Spans(real)
        self._unless_negator_ends = sorted(
            [m.end for m in real] + [m.end for m in self.spans(lists.unless_negators)]
        )
        self.persons = self._subjects(lists)
        self._person_starts = [p.start for p in self.persons]

    def denied(self, phrase: Match, gap: int, match: tuple[int, int]) -> bool:
        """A negator outside the ``match`` span ends at most ``gap`` characters before
        ``phrase``, in its clause (不是为了烧烤, 不是拿来烤肉): the ``unless`` phrase is
        denied, not given. A negator of the match itself (不用再醒那么早) does not count."""
        lo = bisect_left(self._unless_negator_ends, phrase.start - gap)
        hi = bisect_right(self._unless_negator_ends, phrase.start)
        return any(
            not match[0] < end <= match[1] and self.no_stop(end, phrase.start)
            for end in self._unless_negator_ends[lo:hi]
        )

    def negated(self, phrase: Match, lookback: int) -> bool:
        """A real negator ends within ``lookback`` characters before ``phrase``, in its
        clause (不打算, 没想好)."""
        look = max(self.clause_start[phrase.start], phrase.start - lookback)
        return self.negators.any_inside(look, phrase.start)

    def vocative(self, person: _Person) -> bool:
        """The person word is a clause of its own, a particle at most after it (哥哥，
        妈啊，): someone addressed, not a subject."""
        start = self.clause_start[person.start]
        rest = self.text[person.end : self.clause_end[person.start]]
        return start == person.start and rest in _VOCATIVE_TAILS

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
    also: tuple[_Spans, ...] = ()


class Composer:
    """Finds every composition entry that fires in a normalized text."""

    def __init__(self, rules: CompositionRules) -> None:
        self._rules = rules
        phrases: set[str] = {
            *rules.negators,
            *rules.non_negators,
            *rules.unless_negators,
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
                *(group.phrases for group in entry.also),
            )
        self._matcher = PhraseMatcher({phrase: phrase for phrase in phrases})
        # The reach phrases by first character, for the rare check of a far negator.
        reach: dict[str, list[str]] = {}
        for phrase in dict.fromkeys(rules.negation_reach):
            reach.setdefault(phrase[0], []).append(phrase)
        self._reach = {ch: tuple(sorted(ps, key=len, reverse=True)) for ch, ps in reach.items()}
        self._lists = _Lists.of(rules)
        shared: dict[frozenset[str], frozenset[str]] = {}
        self._sets = tuple((entry, _EntrySets.of(entry, shared)) for entry in rules.entries)
        # Which part of which entry a phrase is: a message only visits the entries whose
        # every required part occurs in it (round 3: the entries keep growing, most
        # messages hit none; 2026-10-28: a head as common as 去 or 多少 visits its entry
        # only when the tail, the context and each `also` group occur too). A part is a
        # bit of the entry's mask: heads 1, tails 2, context 4, the k-th `also` group 8 << k.
        by_part: dict[str, list[tuple[int, int]]] = {}
        needed: list[int] = []
        for index, entry in enumerate(rules.entries):
            parts = [entry.heads, entry.tails, entry.context, *(g.phrases for g in entry.also)]
            mask = 0
            for bit, part in enumerate(parts):
                if not part:
                    continue
                mask |= 1 << bit
                for phrase in dict.fromkeys(part):
                    by_part.setdefault(phrase, []).append((index, 1 << bit))
            needed.append(mask)
        self._by_part = {phrase: tuple(roles) for phrase, roles in by_part.items()}
        self._needed = tuple(needed)

    def find(self, text: str) -> list[CompositionHit]:
        """The first accepted match of each entry that fires, in entry order."""
        if not self._rules.entries or not text:
            return []
        found: dict[str, list[Match]] = {}
        for match in self._matcher.find_all(text):
            found.setdefault(match.key, []).append(match)
        seen: dict[int, int] = {}
        by_part = self._by_part
        for key in found:
            for index, bit in by_part.get(key, ()):
                seen[index] = seen.get(index, 0) | bit
        needed = self._needed
        candidates = sorted(i for i, mask in seen.items() if mask == needed[i])
        if not candidates:
            return []
        facts = _Text(text, self._rules, self._lists, found)
        hits: list[CompositionHit] = []
        for index in candidates:
            entry, sets = self._sets[index]
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
        also: list[_Spans] = []
        for group, phrases in zip(entry.also, sets.also, strict=True):
            found = facts.spans(phrases)
            if not group.negatable:
                found = [m for m in found if not facts.negated(m, self._rules.lookback)]
            if not found:
                return None
            also.append(_Spans(found))
        own = _EntryFacts(
            exceptions=_Spans(facts.spans(sets.exceptions)),
            blockers=_Spans(facts.spans(sets.blockers)),
            context=context,
            unless=_Spans(facts.spans(sets.unless)),
            also=tuple(also),
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
        if entry.clause_negation and any(
            _covered(facts.text, negator.end, first.start, self._reach)
            for negator in facts.negators.inside(clause, look)
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
                if person is not None and facts.vocative(person):
                    # A clause that is only a name (哥哥，等我死了…) addresses someone; it
                    # is no subject to carry over (round 3).
                    person = None
            if person is not None and not person.is_self:
                return False
        window = entry.context_window
        if (
            entry.context
            and window is not None
            and not own.context.overlaps(first.start - window, second.end + window)
        ):
            return False
        for group, spans in zip(entry.also, own.also, strict=True):
            if group.window is not None and not spans.overlaps(
                first.start - group.window, second.end + group.window
            ):
                return False
        if entry.unless:
            a = first.start - entry.unless_window
            b = second.end + entry.unless_window
            if entry.unless_across:
                a, b = max(0, a), min(len(facts.text), b)
            else:
                a, b = max(clause, a), min(facts.clause_end[second.end], b)
            gap = self._rules.unless_negation_gap
            span = (first.start, second.end)
            if any(not facts.denied(m, gap, span) for m in own.unless.inside(a, b)):
                return False
        text = facts.text
        if entry.leading is not None and not _only(text, clause, first.start, entry.leading):
            return False
        if entry.trailing is not None:
            return _only(text, second.end, facts.clause_end[second.end], entry.trailing)
        return True


def _covered(text: str, start: int, end: int, by_first: Mapping[str, tuple[str, ...]]) -> bool:
    """Is ``text[start:end]`` made of reach phrases alone (any split), so that a negator
    ending at ``start`` still denies what begins at ``end``? Phrases are indexed by their
    first character; a gap of a few dozen characters costs a few dozen lookups."""
    reachable = {start}
    for i in range(start, end):
        if i not in reachable:
            continue
        for phrase in by_first.get(text[i], ()):
            j = i + len(phrase)
            if j <= end and text.startswith(phrase, i):
                if j == end:
                    return True
                reachable.add(j)
    return start == end


def _only(text: str, start: int, end: int, phrases: tuple[str, ...]) -> bool:
    """Is ``text[start:end]`` made of ``phrases`` alone (any number, any order, possibly
    none)?

    Any split counts, not only the greedy one: with i and i'm listed, i'mgonna is read as
    i'm + gonna. Nothing is copied and the scan stops at the first position no split
    reaches, so a long clause costs only as much as its leading run of phrases."""
    reachable = {start}
    furthest = start
    for i in range(start, end):
        if i > furthest:
            return False
        if i in reachable:
            for phrase in phrases:
                j = i + len(phrase)
                if j <= end and text.startswith(phrase, i):
                    reachable.add(j)
                    furthest = max(furthest, j)
    return end in reachable
