"""What the user's words this turn allow the reply to say back (round 3, B2a; draft, G-0).

Two readings, both about wording only; neither changes a crisis level, a card or a flow.

* :class:`MirrorGuard`: risk words in the message, read (never copied) from the crisis
  lexicon ``lexicons/risk.yaml``, in two strengths.

  - Plain risk (:meth:`MirrorGuard.risky`): a Stage 1 or Stage 2 phrase ("想死", "跳楼",
    "不想活"), a composition whose every part occurs anywhere in the message (its heads,
    tails and context, none inside one of its exceptions, and none of its ``unless`` words
    present: "打算 … 桥上 … 往下跳" without the screen's gap and person checks), or a
    ``guarded.extra_risk_words`` slang word. Hyperbole ("累死了", "想死你了") is masked first.
  - A risk word (:meth:`MirrorGuard.flagged`): a ``recall_cap.vetoes`` word (means, death,
    heights, jumping, farewell: "天台", "跳", "不在了", "再见") outside every everyday sense
    the lexicon lists (its hyperbole and negation phrases, its compositions' exceptions and
    ``unless`` words: "跳伞", "跳水").

  - Round 4 (复测 q3): a composition read on its heads and tails alone (its context words
    not asked for), and two kinds of risk component (:meth:`MirrorGuard.kinds`,
    ``utterances.yaml`` ``guarded.components``: means, preparation, time, an ending,
    something lasting, a wish) count as plain risk too.

  The engine answers either with a ``guarded.acks`` line that quotes nothing
  (``LanguageEngine.build_slots``); a risk word in one clause keeps the whole message from
  being said back ("你就叫送行人吧，我快不在了").
* :func:`read_substance`: drinking cues from ``lexicons/substance.yaml`` (that file's
  header says how its lists combine): a withdrawal sign, a question asking whether a
  little drink is all right (or whether to stop quitting), and a sentence that relishes
  drinking, which is reflected as a strong craving instead of being quoted. Round 4:
  sleeping pills, painkillers and sedatives too, a reason found for a drink, and a
  craving for more.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final

from olivia.core.language.data import RiskComponents, SubstanceCues
from olivia.core.safety.lexicon import Composition, SafetyLexicons
from olivia.core.safety.normalize import normalize

_RISK_SECTIONS: Final = frozenset({"stage1", "stage2"})
_FIGURATIVE: Final = "hyperbole"
_EVERYDAY_SECTIONS: Final = frozenset({"hyperbole", "negation"})
_MASK: Final = "\0"
# guarded.components kinds the soft endings join (round 4).
_LASTING: Final = "lasting"
_ENDING: Final = "ending"
# "要不要": the characters of a yes-or-no question before a drink.
_A_NOT_A: Final = 3
# Round 4: at most this many characters between a desire and the drink ("想再喝").
_WANT_GAP: Final = 2
_WANT_FILLERS: Final = "再要去来"
# Particles and punctuation that may end a sentence after a bare desire ("我真的很想啊").
_PARTICLES: Final = "啊呀了吧哦嘛啦呢哈,.!?~ "
# A sentence of the message (folded text): the craving reading is per sentence.
_SENTENCE_RE: Final = re.compile(r"[.!?;。！？；\n]+")


class _Index:
    """Phrases by their first two characters (one-character phrases on their own): every
    phrase in a short message, found in one pass (generation budget, SDD §10.1)."""

    def __init__(self, phrases: Iterable[str]) -> None:
        by_head: dict[str, list[str]] = {}
        singles: set[str] = set()
        for phrase in {p for p in phrases if p}:
            if len(phrase) == 1:
                singles.add(phrase)
            else:
                by_head.setdefault(phrase[:2], []).append(phrase)
        self._by_head = {head: tuple(group) for head, group in by_head.items()}
        self._singles = frozenset(singles)

    def found(self, text: str) -> set[str]:
        hits = {ch for ch in text if ch in self._singles}
        by_head = self._by_head
        for i in range(len(text) - 1):
            group = by_head.get(text[i : i + 2])
            if group is not None:
                hits.update(p for p in group if text.startswith(p, i))
        return hits

    def masked(self, text: str) -> str:
        """``text`` with every phrase of the index blanked out, longest first."""
        for phrase in sorted(self.found(text), key=len, reverse=True):
            text = text.replace(phrase, _MASK * len(phrase))
        return text


@dataclass(frozen=True)
class _Relaxed:
    """A composition read loosely: every part anywhere in the message."""

    heads: frozenset[str]
    tails: frozenset[str]
    context: frozenset[str]
    unless: frozenset[str]
    exceptions: tuple[str, ...]

    @classmethod
    def of(cls, entry: Composition) -> _Relaxed:
        return cls(
            frozenset(entry.heads),
            frozenset(entry.tails),
            frozenset(entry.context),
            frozenset(entry.unless),
            entry.exceptions,
        )

    def words(self) -> frozenset[str]:
        return self.heads | self.tails | self.context | self.unless

    def matches(self, folded: str, found: set[str]) -> bool:
        """``found``: this index's phrases in ``folded``. A part inside one of the
        entry's exceptions does not count. Round 4: an entry with tails needs its heads
        and tails only, its context is not asked for ("药我已经准备好了" without a death
        word); an entry without tails still needs its context."""
        if not self.unless.isdisjoint(found):
            return False
        parts = (self.heads, self.tails) if self.tails else (self.heads, self.context)
        if any(part and part.isdisjoint(found) for part in parts):
            return False
        if not any(e in folded for e in self.exceptions):
            return True
        text = _masked(folded, self.exceptions)
        return all(not part or any(p in text for p in part) for part in parts)


class MirrorGuard:
    """The crisis lexicon's risk words for the mirror (see the module docstring)."""

    def __init__(
        self,
        lexicons: SafetyLexicons | None,
        extra: Iterable[str] = (),
        components: RiskComponents | None = None,
    ) -> None:
        phrases: set[str] = {normalize(w) for w in extra}
        self._components = components
        self._kinds = (
            {name: _Index(words) for name, words in components.kinds.items()}
            if components is not None
            else {}
        )
        self._soft = _Index(components.soft_ending if components is not None else ())
        self._usual = _Index(components.everyday if components is not None else ())
        figurative: set[str] = set()
        everyday: set[str] = set()
        relaxed: list[_Relaxed] = []
        vetoes: tuple[str, ...] = ()
        if lexicons is not None:
            for cue in lexicons.risk.values():
                if cue.section in _RISK_SECTIONS:
                    phrases.update(cue.patterns)
                if cue.section == _FIGURATIVE:
                    figurative.update(cue.patterns)
                if cue.section in _EVERYDAY_SECTIONS:
                    everyday.update(cue.patterns)
            for entry in lexicons.compositions.entries:
                relaxed.append(_Relaxed.of(entry))
                everyday.update(entry.exceptions)
                everyday.update(entry.unless)
            vetoes = lexicons.recall_cap.vetoes
        self._phrases = _Index(phrases)
        self._figurative = _Index(figurative)
        self._everyday = _Index(everyday)
        # Each composition under the words of its first part: only those can match.
        self._by_word: dict[str, list[_Relaxed]] = {}
        for r in relaxed:
            for word in r.heads or r.tails or r.context:
                self._by_word.setdefault(word, []).append(r)
        self._parts = _Index(w for r in relaxed for w in r.words())
        self._vetoes = _Index(vetoes)

    def risky(self, text: str) -> bool:
        """``text`` holds a risk phrase or a loosely read composition, outside hyperbole."""
        folded = self._figurative.masked(normalize(text))
        if not folded.strip(_MASK):
            return False
        if self._phrases.found(folded):
            return True
        found = self._parts.found(folded)
        candidates = {id(r): r for w in found for r in self._by_word.get(w, ())}
        if any(r.matches(folded, found) for r in candidates.values()):
            return True
        components = self._components
        return components is not None and len(self.kinds(text)) >= components.min_kinds

    def kinds(self, text: str) -> set[str]:
        """Round 4: the kinds of risk component in ``text`` (``guarded.components``): a
        means, a preparation, a time, an ending, something lasting, a wish. A phrase
        inside an everyday word ("计划", "心跳") does not count; a soft ending ("休息",
        "晚安") is an ending only next to something lasting ("永远的那种")."""
        if self._components is None:
            return set()
        folded = self._usual.masked(normalize(text))
        kinds = {name for name, index in self._kinds.items() if index.found(folded)}
        if _LASTING in kinds and self._soft.found(folded):
            kinds.add(_ENDING)
        return kinds

    def flagged(self, text: str) -> bool:
        """``text`` holds a ``recall_cap`` risk word outside every everyday sense (round 4:
        nor inside a ``guarded.components.everyday`` word: "心跳很快")."""
        folded = self._usual.masked(normalize(text))
        return bool(self._vetoes.found(self._everyday.masked(folded)))


def _masked(folded: str, masks: Sequence[str]) -> str:
    for mask in masks:
        if mask in folded:
            folded = folded.replace(mask, _MASK * len(mask))
    return folded


@dataclass(frozen=True)
class SubstanceReading:
    """What one message says about drinking (``lexicons/substance.yaml``)."""

    mentioned: bool = False
    """The message is about drinking: the session's drinking context starts here."""
    withdrawal: bool = False
    severe: bool = False
    """A severe withdrawal sign (seeing or hearing what is not there, a seizure)."""
    asks_to_drink: bool = False
    """A question whether a little is all right, a wish to put quitting off, or (round 4)
    a reason found for a little ("度数那么低，应该不算破戒吧")."""
    craving: bool = False
    talks: bool = False
    """Round 4: the message itself is about drinking (a substance word or a drink): no
    "this matters to you" line after it."""

    @property
    def any(self) -> bool:
        return self.withdrawal or self.asks_to_drink or self.craving or self.talks


NOTHING: Final = SubstanceReading()


def read_substance(cues: SubstanceCues, text: str, *, context: bool) -> SubstanceReading:
    """Read ``text`` for drinking cues; ``context``: drinking came up earlier this session."""
    folded = normalize(text)
    if not folded or not cues.substances:
        return NOTHING
    # "突然不喝会出问题吗" is about drinking unless it names something else to drink.
    asked = _has(folded, cues.questions)
    # Cutting down on a drink that is no other beverage ("只是想少喝一点") is drinking too.
    mentioned = (
        _has(folded, cues.substances)
        or (asked and not _has(folded, cues.not_alcohol))
        or (_has(folded, cues.quitting) and _drinks(folded, cues))
    )
    if not (context or mentioned):
        return NOTHING
    severe = _free(folded, cues.severe, cues)
    withdrawal = severe or asked or _free(folded, cues.signs, cues)
    put_off = _has(folded, cues.later) and _has(folded, cues.put_off)
    drinks = _drinks(folded, cues)
    asks_to_drink = (
        (drinks and _has(folded, cues.asking))
        or _has(folded, cues.postpone)
        or put_off
        or _free(folded, cues.excuses, cues)
    )
    craving = not asks_to_drink and any(
        _relishes(sentence, cues, context=context)
        for sentence in _SENTENCE_RE.split(folded)
        if sentence
    )
    talks = _has(folded, cues.substances) or drinks
    return SubstanceReading(mentioned, withdrawal, severe, asks_to_drink, craving, talks)


def _relishes(sentence: str, cues: SubstanceCues, *, context: bool) -> bool:
    """One sentence relishes drinking: not a question, and an alcohol word with a wish or
    a pleasure, or (in context) a drink with a pleasure, with nothing about quitting in
    the sentence; or (round 4, in context) a desire for more (:func:`_wants_more`) with
    nothing about quitting before it ("特别想再喝一点，把这种难受压下去")."""
    if _has(sentence, cues.asking):
        return False
    if context and _wants_more(sentence, cues):
        return True
    if _has(sentence, cues.quitting):
        return False
    pleasure = _free(sentence, cues.pleasure, cues)
    if _has(sentence, cues.substances) and (pleasure or _free(sentence, cues.desire, cues)):
        return True
    return context and pleasure and _drinks(sentence, cues)


def _wants_more(sentence: str, cues: SubstanceCues) -> bool:
    """Round 4: a desire with no quitting word before it, right before a drink ("特别想再
    喝一点"; only 再, 要, 去 or 来 between), before the feeling once more ("我好想再有一
    次"), or ending the sentence ("但我真的很想")."""
    for word in cues.desire:
        start = sentence.find(word)
        while start >= 0:
            end = start + len(word)
            rest = sentence[end:]
            if (
                not _negated(sentence, start, cues)
                and not _has(sentence[:start], cues.quitting)
                and (
                    _has(rest, cues.again)
                    or not rest.strip(_PARTICLES)
                    or any(
                        _drink_at(sentence, end + gap, cues)
                        for gap in range(_WANT_GAP + 1)
                        if all(ch in _WANT_FILLERS for ch in rest[:gap])
                    )
                )
            ):
                return True
            start = sentence.find(word, start + 1)
    return False


def _drink_at(text: str, start: int, cues: SubstanceCues) -> bool:
    """A drink act begins at ``start`` and is of nothing in ``not_alcohol``."""
    for act in cues.drinking:
        if text.startswith(act, start):
            after = text[start + len(act) : start + len(act) + cues.object_window]
            if not _has(after, cues.not_alcohol):
                return True
    return False


def _has(text: str, phrases: Sequence[str]) -> bool:
    return any(p in text for p in phrases)


def _negated(text: str, start: int, cues: SubstanceCues) -> bool:
    """A negator stands right before ``start``; the 不 of a question "要不要喝" is none,
    nor (round 4) one inside a ``non_negators`` word ("要不我喝…", "忍不住")."""
    if start >= _A_NOT_A and _is_a_not_a(text[start - _A_NOT_A : start], cues):
        return False
    begin = max(0, start - cues.negation_window)
    plain = text
    for word in cues.non_negators:
        if word in plain:
            plain = plain.replace(word, _MASK * len(word))
    head = plain[begin:start]
    return any(n in head for n in cues.negators)


def _is_a_not_a(three: str, cues: SubstanceCues) -> bool:
    """ "要不要", "能不能", "有没有": a yes-or-no question, not a negation."""
    return three[0] == three[2] and three[1] in cues.negators


def _free(text: str, phrases: Sequence[str], cues: SubstanceCues) -> bool:
    """Some occurrence of a phrase is not right after a negator ("没有手抖" is none)."""
    for phrase in phrases:
        start = text.find(phrase)
        while start >= 0:
            if not _negated(text, start, cues):
                return True
            start = text.find(phrase, start + 1)
    return False


def _drinks(text: str, cues: SubstanceCues) -> bool:
    """A drink that is not negated ("不喝") and not of something else ("喝茶", "一大杯凉白开")."""
    for act in cues.drinking:
        start = text.find(act)
        while start >= 0:
            if not _negated(text, start, cues) and _drink_at(text, start, cues):
                return True
            start = text.find(act, start + 1)
    return False
