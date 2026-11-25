"""Where the user says they are now (owner decision 2026-11-25 B; draft, G-0).

"我在多伦多", "我人在悉尼读书", "我现在在香港", "I'm in Toronto": the user's own place now,
as a hotline region code (CN, HK, MO, TW, US, CA, GB, AU) or ``ZZ`` for a place without
verified numbers here, with the ISO code of a country whose official emergency numbers
``render.yaml`` ``crisis.local_emergency`` lists (JP, DE, ...). The place names are the
lexicon's ``hotline_places`` and ``local_emergency_places`` (``present_place.excluded``
left out: "国内" is Taiwan to a user from Taiwan, so mainland China is only ever named
outright); the grammar is ``present_place`` in ``perception.yaml``.

A message is read one clause at a time (split at punctuation); the last clause that says
where the user is now counts. A clause says it when the user is its subject, only fillers
stand between the subject and the verb, and the place follows the verb, with no marker of
the past, the future, a condition or a wish around it. Someone else's place ("我朋友在伦敦"),
the past ("我以前在多伦多", "我在东京读书的时候"), the future ("下个月去悉尼") and a condition
("如果我在美国") never count. Nothing here is written anywhere: the session keeps the place
in memory only.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from olivia.core.models import UNKNOWN_COUNTRY
from olivia.core.perception.lexicon import PerceptionLexicon, PresentPlaceGrammar
from olivia.core.safety.normalize import fold_words, normalize

# Clause marks on the folded text (whitespace is already gone) and on the raw English text
# (a full stop only before a space or the end, so "u.s." stays whole).
_CLAUSES: Final = re.compile(r"[，,。.！!？?；;、~～…:：]+")
_ENGLISH_CLAUSES: Final = re.compile(r"[，,。！!？?；;~～…:：]+|\.(?=\s|$)")
_ENGLISH_WORDS: Final = 3
# Every English pattern ends in "in" and a space: without one, no English is read.
_ENGLISH_HINT: Final = re.compile(r"(?<![a-z])in\s", re.IGNORECASE)
_WORD_EDGE: Final = re.compile(r"[^a-z]+$")


@dataclass(frozen=True)
class SaidPlace:
    """A place the user said they are in now."""

    region: str
    """A hotline region code, or ``ZZ`` for a place without verified numbers here."""
    country: str | None = None
    """For ``ZZ``: the country, when ``crisis.local_emergency`` may list its numbers."""


class PresentPlaceReader:
    """Reads :class:`SaidPlace` from a message with the lexicon's ``present_place``."""

    def __init__(self, lexicon: PerceptionLexicon) -> None:
        grammar = lexicon.present_place
        self._grammar = grammar
        if grammar is None:
            return
        countries = {
            name: code for code, names in lexicon.local_emergency_places.items() for name in names
        }
        places: dict[str, SaidPlace] = {}
        for code, names in lexicon.hotline_places.items():
            for name in names:
                if name not in grammar.excluded:
                    country = countries.get(name) if code == UNKNOWN_COUNTRY else None
                    places[name] = SaidPlace(code, country)
        for name, code in countries.items():
            places.setdefault(name, SaidPlace(UNKNOWN_COUNTRY, code))
        self._latin = {name: place for name, place in places.items() if name.isascii()}
        # Every name, the Latin ones too ("我现在在Toronto" folds to "我现在在toronto").
        everything = sorted(places)
        # Chinese names other words hold ("加国" in "参加国际"), as hotline_place_patterns has
        # them: read where a name would stand.
        self._held = tuple(
            (code, pattern)
            for code, patterns in lexicon.hotline_place_patterns.items()
            for pattern in patterns
            if not pattern.pattern.isascii()
        )
        self._english_held = tuple(
            (code, pattern)
            for code, patterns in lexicon.hotline_place_patterns.items()
            for pattern in patterns
            if pattern.pattern.isascii()
        )
        self._places = places
        held = "|".join(f"(?:{pattern.pattern})" for _, pattern in self._held)
        place = f"(?P<place>{_alternation(everything)}{'|' + held if held else ''})"
        verbs = _alternation(grammar.verbs)
        lead = f"(?:{_alternation(grammar.fillers)})*(?:{verbs})"
        subjects = _alternation(grammar.subjects)
        self._said = re.compile(f"(?:{subjects}){lead}{place}")
        # A verb right before a place, anywhere: most messages have none, and are not read
        # clause by clause.
        self._verb_place = re.compile(f"(?:{verbs}){place}")
        starts = _alternation(grammar.clause_subjects)
        self._clause_start = re.compile(f"^(?:{starts}){lead}{place}")
        self._continued = re.compile(f"^(?:{_alternation(grammar.continuations)}){lead}{place}")
        # Where the user was or will be ("我之前在多伦多"): a later clause with no subject
        # ("现在在悉尼") may then say where the user is now.
        was = _alternation((*grammar.fillers, *grammar.not_before))
        self._was = re.compile(f"(?:{subjects})(?:{was})*(?:{verbs}){place}")

    def read(self, text: str, *, folded: str | None = None) -> SaidPlace | None:
        """Where the message says the user is now (its last such clause), else None.
        ``folded`` is ``normalize(text)`` when the caller has it already."""
        grammar = self._grammar
        if grammar is None:
            return None
        folded = normalize(text) if folded is None else folded
        found: SaidPlace | None = None
        # Most messages name no place at all: one quick look before reading clause by clause.
        if self._verb_place.search(folded) is not None:
            found = self._read_han(grammar, folded)
        if found is None and _ENGLISH_HINT.search(text) is not None:
            found = self._read_english(grammar, fold_words(text))
        return found

    def _read_han(self, grammar: PresentPlaceGrammar, folded: str) -> SaidPlace | None:
        found: SaidPlace | None = None
        said_before = False
        for clause in _CLAUSES.split(folded):
            if not clause:
                continue
            matches = list(self._said.finditer(clause))
            starts = [m for m in (self._clause_start.match(clause),) if m is not None]
            if said_before:
                starts += [m for m in (self._continued.match(clause),) if m is not None]
            said_before = said_before or bool(matches or starts) or bool(self._was.search(clause))
            for match in sorted([*matches, *starts], key=lambda m: m.start()):
                before = clause[: match.start()]
                after = clause[match.end() :]
                if _has(before, grammar.not_before) or _has(after, grammar.not_after):
                    continue
                if after.startswith(grammar.attributes):
                    continue
                place = self._place(match.group("place"))
                if place is not None:
                    found = place
        return found

    def _read_english(self, grammar: PresentPlaceGrammar, spaced: str) -> SaidPlace | None:
        found: SaidPlace | None = None
        for clause in _ENGLISH_CLAUSES.split(spaced):
            if not clause.strip() or any(p.search(clause) for p in grammar.english_not_now):
                continue
            for pattern in grammar.english:
                for match in pattern.finditer(clause):
                    place = self._english_place(clause[match.end() :])
                    if place is not None:
                        found = place
        return found

    def _place(self, name: str) -> SaidPlace | None:
        place = self._places.get(name)
        if place is not None:
            return place
        for code, pattern in self._held:
            if pattern.fullmatch(name):
                return SaidPlace(code)
        return None

    def _english_place(self, rest: str) -> SaidPlace | None:
        """The place at the start of ``rest`` ("new york now" is New York): up to three
        words joined, longest first, with or without a leading "the"."""
        for code, pattern in self._english_held:
            if pattern.match(rest):
                return SaidPlace(code)
        words = [_WORD_EDGE.sub("", word) for word in rest.split()[:_ENGLISH_WORDS]]
        for start in (0, 1) if words[:1] == ["the"] else (0,):
            for end in range(len(words), start, -1):
                place = self._latin.get("".join(words[start:end]))
                if place is not None:
                    return place
        return None


def _alternation(phrases: Iterable[str]) -> str:
    return "|".join(re.escape(p) for p in sorted(set(phrases), key=len, reverse=True))


def _has(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)
