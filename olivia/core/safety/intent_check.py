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

Round 3 (2026-10-27, re-test r2 第 1 节):

* Interjections and laughter before the answer are dropped first, however many and with
  whatever punctuation between them (哈哈, 嗯, 呃, 啊？, 诶, 害, 想啥呢, 当然, lol, haha,
  hmm): "嗯不是，没那回事" is a no (it read as the yes 嗯), "哈哈，没有啦" and "啊？当然不是啦"
  are noes. A message that is nothing but interjections ("嗯", "当然") is read as it was
  typed, so a bare 嗯 stays a yes and a bare 当然 stays unclear.
* A no said twice ("没有没有，你想多了") is the same no.
* "不是才怪" is no no (``_SARCASM``), and neither is a first clause about living on or
  waking up ("我没想过要活下去": ``_NEGATED_VETOES``).
* :func:`read_answer` also reads a first clause that negates the intent in the first person
  ("我绝对没有想结束生命，只是项目做不下去"): the rules see a risk phrase in it, which is
  under the negation. It is a no only when the whole message carries no plan evidence (L3),
  the rest of the message, screened on its own (``rest_screen``), is L0 with no ask cue and
  no unsure phrase occurs anywhere;
  ``IntentReading.negated`` then tells the session that the no carries the only cue.

2026-10-28 (SDD retrace): a no is read only up to where a new statement starts, and what
follows it must carry no risk. "我没有想自杀 今晚就把药全吃了" was a no: the first clause
ran to the end (no punctuation, only a space) and the denial's own negation voided the
plan after it. Now the first clause also ends at a space next to a Han character and
before a time word, a plan word or a new 我 (``_SOFT_BREAK``); with ``rest_screen`` given,
everything after that point is screened on its own and any risk cue there (L1 or above,
an ask cue, plan evidence) makes the answer UNCLEAR, for a plain no and a negated intent
alike.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
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
# Round 3: interjections, laughter and "what are you thinking" before the answer, each
# optionally followed by punctuation or a space. Dropped from the front again and again.
_INTERJECTION: Final = re.compile(
    r"(?:(?:哈|呵|嘿|嘻|嗨|hh)+|[嗯恩呃额哦噢喔诶欸哎啊害咦哇呀]+|哎呀|唉|哎哟|天哪|天啊|拜托|"
    r"你?想啥呢|你?想什么呢|你?在想啥|怎么可能|当然|肯定|"
    r"(?:lol|lmao|haha\w*|hah|ha|hmm+|um+|uh+|oh|ah|well|lmfao)\b)"
    r"[\s,.!?;:。、~…\"“”]*"
)
# A no said twice or more ("没有没有", "不是不是"; r2 u1b) is the same no.
_REPEATED: Final = re.compile(r"(.+?)\1+")
# A no that means yes.
_SARCASM: Final = ("才怪", "就怪了")
# Round 3: a first clause that negates an intent in the first person (我绝对没有想……). Only
# 没(有) and 不是 negate the intent itself; 不想 often is the risk ("我不想活了"), so it is
# no part of this reading, nor is a clause about living on or waking up.
_NEGATED_INTENT: Final = re.compile(
    r"^(?:我|俺)?(?:绝对|真的|根本|从来|完全|并|确实|压根儿?|一点也|一点都)*"
    r"(?:没有|没|不是)(?:在|有)?(?:想|想过|要|打算|准备|是想|是要)"
)
_NEGATED_VETOES: Final = ("活", "醒", "继续", "存在", "下去", "坚持", "撑")
# 2026-10-28: where a new statement starts inside a first clause typed without punctuation
# (fold_words keeps spaces): a space next to a Han character, or, after the first
# character, a time, a plan word or a new 我. Only what follows is screened for risk, so a
# break found too early makes the reading stricter, never looser.
_HAN: Final = "\u3400-\u4dbf\u4e00-\u9fff"
_SOFT_BREAK: Final = re.compile(
    rf"\s(?=[{_HAN}])|(?<=[{_HAN}])\s|(?<=.)(?=今晚|今夜|今天|明天|明早|明晚|后天|这周|本周|周末|下周|"
    r"下个月|月底|周[一二三四五六日天]|星期|礼拜|过两天|过几天|这几天|凌晨|半夜|一会儿|待会|等会|"
    r"马上|现在|立刻|晚上|早上|一早|我|俺|打算|准备|决定|计划|已经|还是|干脆)"
)


class IntentAnswer(StrEnum):
    """How the turn after the question answered it (``inspect["safety_check"]``)."""

    AFFIRMED = "affirmed"
    DENIED = "denied"
    UNCLEAR = "unclear"


@dataclass(frozen=True)
class IntentReading:
    """:func:`read_answer`'s result."""

    answer: IntentAnswer
    negated: bool = False
    """The no is a first-person negated intent clause whose risk phrase is the message's
    only rule cue (round 3); only with ``answer`` DENIED."""


def read_intent_answer(
    answers: IntentAnswers, text: str, assessment: CrisisAssessment
) -> IntentAnswer:
    """Read one turn as the answer to the question asked on the turn before."""
    return read_answer(answers, text, assessment).answer


def read_answer(
    answers: IntentAnswers,
    text: str,
    assessment: CrisisAssessment,
    rest_screen: Callable[[str], CrisisAssessment] | None = None,
) -> IntentReading:
    """:func:`read_intent_answer`, with the negated first clause read too when
    ``rest_screen`` (the rule screen) is given."""
    folded = fold_words(text)
    body = _drop_interjections(folded)
    parts = _CLAUSE_END.split(body, maxsplit=1)
    clause = parts[0].strip().lstrip(_FILLERS).strip()
    rest = parts[1] if len(parts) > 1 else ""
    sarcastic = any(word in folded for word in _SARCASM)
    living = any(word in clause for word in _NEGATED_VETOES)
    plain = clause.rstrip(_PARTICLES)
    repeated = _REPEATED.fullmatch(plain)
    base = repeated.group(1) if repeated is not None else plain
    denies = (
        not sarcastic
        and not living
        and (base in answers.deny_whole or _starts(clause, answers.deny_start))
    )
    unsure = any(_contains(folded, phrase) for phrase in answers.unsure)
    negated = (
        not sarcastic
        and rest_screen is not None
        and not living
        and _NEGATED_INTENT.match(clause) is not None
    )
    if not denies and not negated:
        yes = _starts(clause, answers.affirm_start)
        return IntentReading(IntentAnswer.AFFIRMED if yes else IntentAnswer.UNCLEAR)
    if rest_screen is not None:
        following = _following(clause, rest)
        if following and _risky(rest_screen(following)):
            return IntentReading(IntentAnswer.UNCLEAR)
    calm = assessment.level is CrisisLevel.L0 and not assessment.asks_intent
    if calm and not unsure:
        return IntentReading(IntentAnswer.DENIED)
    plan = assessment.has_plan_evidence or assessment.level is CrisisLevel.L3
    if negated and not unsure and not plan and rest_screen is not None:
        return IntentReading(IntentAnswer.DENIED, negated=True)
    return IntentReading(IntentAnswer.UNCLEAR)


def _following(clause: str, rest: str) -> str:
    """What follows the no: the first clause after its first soft break, then the rest."""
    soft = _SOFT_BREAK.search(clause)
    tail = clause[soft.end() :].strip() if soft is not None else ""
    return ",".join(part for part in (tail, rest.strip()) if part)


def _risky(screened: CrisisAssessment) -> bool:
    """Any risk cue: L1 or above, an ask cue or plan evidence."""
    return (
        screened.level is not CrisisLevel.L0 or screened.asks_intent or screened.has_plan_evidence
    )


def _drop_interjections(folded: str) -> str:
    """``folded`` without its leading interjections; as typed when nothing else is left."""
    body = folded.strip()
    while True:
        match = _INTERJECTION.match(body)
        if match is None or not match.group(0):
            break
        body = body[match.end() :].lstrip()
    return body if body else folded


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
