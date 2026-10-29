"""The answer to the question whether the user is under 18 (round 6, re-test q2 第 4 节).

The minors' reply asks ``crisis.minor_confirm`` ("你现在还不满十八岁，对吗？"); the next
message is its answer. Spoken yeses were missed ("嗯是", "嗯呐，是"): the shared
whole-message answer list (``perception.yaml`` ``answers``) is the answer to other
questions too, so this question has its own closed grammar here instead of more entries
there, and the crisis tracker's own reading of a short yes to its safety question
(``tracker.py``) is a different reader again; neither is widened by this one.

:func:`reads_yes` is a whole-message yes: one or more yes words and fillers (嗯, 对, 是的,
係呀 folded to 系呀, "yes", "yeah I am", ...), optionally with sentence particles, and
nothing else: no negation, no question, no other word. Anything with 不 / 没 / 唔 / 冇 / no /
not, a question mark or a trailing question particle is never a yes. Matching is on the
folded text (``normalize``: Traditional to Simplified, no spaces, casefolded).
"""

from __future__ import annotations

import re
from typing import Final

from olivia.core.safety.normalize import normalize

# Yes words, longest first so the alternation never stops early. Cantonese 系 / 啱 (after
# folding 係), Mandarin 是 / 对 / 没错, "我是" ("嗯，我是"), and fillers that are only
# acceptance (嗯, 嗯呐, 嗯哼).
_YES_WORDS: Final = (
    "没错",
    "冇错",
    "对头",
    "我是",
    "我系",
    "是的",
    "是滴",
    "是嘅",
    "系嘅",
    "系的",
    "对的",
    "对滴",
    "嗯呐",
    "嗯呢",
    "嗯哼",
    "嗯",
    "恩",
    "是",
    "系",
    "对",
    "啱",
)
_PARTICLES: Final = "啊呀呢哦喔嘞啦哈吧咯呐哒捏"
_ZH_YES: Final = re.compile("(?:(?:" + "|".join(_YES_WORDS) + f")[{_PARTICLES}]*)+")
_EN_YES: Final = re.compile(
    r"(?:(?:yes|yeah|yep|yup|ya|yah|sure|correct|right|true|exactly|uhhuh|mhm|mm)+"
    r"(?:that'sright|thatsright|iam|i'm|im)?)+"
)
# Dropped before matching: punctuation, symbols, ellipses and tildes.
_MARKS: Final = re.compile(r"[\s,.!~、。！，…·:：;；'\"“”‘’()（）\-—]+")
_NEGATION: Final = re.compile(r"不|没(?!错)|唔|冇(?!错)|未|别|no|not|n't")
_QUESTION: Final = re.compile(r"[?？]|[吗么]$|吗[啊呀]?$")


def reads_yes(text: str) -> bool:
    """A whole-message yes to the question whether the user is under 18."""
    folded = normalize(text)
    if not folded or _QUESTION.search(folded.rstrip(".。!！~～…")) is not None:
        return False
    bare = _MARKS.sub("", folded)
    if not bare or _NEGATION.search(bare) is not None:
        return False
    return _ZH_YES.fullmatch(bare) is not None or _EN_YES.fullmatch(bare) is not None


# A no: a negation or a correction at the start, or an adult age or "grown up" anywhere.
_NO_START: Final = re.compile(r"(?:嗯+|呃+|额+)?(?:不|没|唔|冇|别|no|nah|nope|not)")
_NO_ANYWHERE: Final = re.compile(
    r"打错|说错|写错|手滑|口误|搞错|早就?成年|已经成年|成年了|i'mnot|imnot|iamnot"
    r"|(?:我|i'm|im|iam)(?:今年|已经|都|早就|其实)*(?:(?:1[89]|[2-9][0-9])(?![0-9])|二十|三十|四十|五十)"
)


def reads_no(text: str) -> bool:
    """A no to the question whether the user is under 18: a negation or a correction
    ("不是，我打错了"), or an adult age ("我都三十了")."""
    bare = _MARKS.sub("", normalize(text))
    return bool(bare) and (
        _NO_START.match(bare) is not None or _NO_ANYWHERE.search(bare) is not None
    )
