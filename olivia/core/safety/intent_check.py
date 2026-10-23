"""Reading the answer to the direct question about intent (decision D3, step A7).

After an ``ASK_INTENT`` cue the session asks once whether the user is thinking of ending
their life, and reads the next turn with :func:`read_intent_answer`:

* ``DENIED`` only for a clear no: the first clause (up to the first punctuation mark,
  leading fillers such as 啊 or 哦 dropped) is a ``deny_whole`` phrase, possibly followed
  by particles such as 啦 or 的, or starts with a ``deny_start`` phrase; no ``unsure``
  phrase occurs anywhere in the message; and the turn's own screen is L0 with no ask cue.
* ``AFFIRMED`` when the first clause starts with an ``affirm_start`` phrase and is not a
  no.
* ``UNCLEAR`` for everything else, an empty message or a slash command included.

Only a denial returns to the ordinary flow; the session reads affirmed and unclear alike
as L2, so the two only differ in ``--inspect``. An English phrase counts only as whole
words ("no" is not the start of "nobody").
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from enum import StrEnum
from typing import Final

from olivia.core.models import CrisisLevel
from olivia.core.safety.crisis import CrisisAssessment
from olivia.core.safety.lexicon import IntentAnswers
from olivia.core.safety.normalize import fold_words

# Clause ends after fold_words (NFKC already maps ，！？；： to , ! ? ; :).
_CLAUSE_END: Final = re.compile(r"[,.!?;:。、~…\n\"“”]")
_FILLERS: Final = "啊呃额哦噢喔诶欸哎"
_PARTICLES: Final = "啦啊呀哦喔的呢嘛哈噢"


class IntentAnswer(StrEnum):
    """How the turn after the question answered it (``inspect["safety_check"]``)."""

    AFFIRMED = "affirmed"
    DENIED = "denied"
    UNCLEAR = "unclear"


def read_intent_answer(
    answers: IntentAnswers, text: str, assessment: CrisisAssessment
) -> IntentAnswer:
    """Read one turn as the answer to the question asked on the turn before."""
    folded = fold_words(text)
    clause = _CLAUSE_END.split(folded, maxsplit=1)[0].strip().lstrip(_FILLERS).strip()
    denies = clause.rstrip(_PARTICLES) in answers.deny_whole or _starts(clause, answers.deny_start)
    if not denies:
        yes = _starts(clause, answers.affirm_start)
        return IntentAnswer.AFFIRMED if yes else IntentAnswer.UNCLEAR
    calm = assessment.level is CrisisLevel.L0 and not assessment.asks_intent
    if calm and not any(_contains(folded, phrase) for phrase in answers.unsure):
        return IntentAnswer.DENIED
    return IntentAnswer.UNCLEAR


def _starts(clause: str, phrases: Iterable[str]) -> bool:
    return any(clause.startswith(p) and _word_end(clause, len(p), p) for p in phrases)


def _contains(text: str, phrase: str) -> bool:
    start = text.find(phrase)
    while start >= 0:
        before_ok = start == 0 or not (_is_word(phrase[0]) and _is_word(text[start - 1]))
        if before_ok and _word_end(text, start + len(phrase), phrase):
            return True
        start = text.find(phrase, start + 1)
    return False


def _word_end(text: str, end: int, phrase: str) -> bool:
    """A phrase ending in an ASCII letter or digit must not run into the next word."""
    return end >= len(text) or not (_is_word(phrase[-1]) and _is_word(text[end]))


def _is_word(ch: str) -> bool:
    return ch.isascii() and (ch.isalnum() or ch == "'")
