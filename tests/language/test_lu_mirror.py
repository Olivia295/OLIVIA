"""Mirror fixes from usage testing (dogfood I3, 2026-10-26).

The usage run mirrored requests, questions, remarks about the companion and spoken
fragments as if they were statements about the user: "你感到对方直接教你吧", "你提到对方
钓过鱼吗哈哈", "你感到上次对方一直问你安不安全", "你提到行 试试", "你感到明天是你爸的忌
日", and Cantonese came back word for word ("你今晚可能去行下海旁"). When the mirror cannot
tell, it now leaves the words alone: the reply gets a short acknowledgement instead.
"""

from __future__ import annotations

import pytest

from olivia.core.language import LanguageEngine, mirror
from olivia.core.language.mirror import Utterance, utterance_kind
from olivia.core.taxonomy import load_taxonomy

# What is no statement to mirror, and what it is instead.
KINDS = [
    ("你直接教我吧", Utterance.REQUEST),
    ("你钓过鱼吗哈哈", Utterance.QUESTION),
    ("你钓过鱼吗？哈哈", Utterance.QUESTION),
    ("我该怎么开口跟妈妈聊", Utterance.QUESTION),
    ("你能帮我想想怎么说吗", Utterance.REQUEST),
    ("那用冷水敷脸呢", Utterance.QUESTION),
    ("为什么不行", Utterance.QUESTION),
    ("[40%] 行 试试", Utterance.BRIEF),
    ("好，试试", Utterance.BRIEF),
    ("上次你一直问我安不安全，吓我一跳", Utterance.COMPANION),
    ("你刚才说的那个我没听懂", Utterance.COMPANION),
    ("说点别的", Utterance.TOPIC),
    ("行吧，换个话题", Utterance.TOPIC),
    ("份工搵钱少，租金又贵到离谱", Utterance.DIALECT),
    ("今晚可能去行下海旁", Utterance.DIALECT),
]


@pytest.mark.parametrize(("text", "kind"), KINDS)
def test_not_a_statement(text: str, kind: Utterance) -> None:
    assert utterance_kind(text) is kind


MIRRORS = [
    # A possessed relative names no feeling of the user's: reported, not "你感到".
    ("明天是我爸的忌日", "你提到明天是你爸的忌日"),
    # A trailing fragment ("肺癌") is not run on after a comma.
    ("他走了两年了，肺癌", "你提到他走了两年了"),
    # A topic change is no part of the mirror; the rest is.
    ("行吧，说点别的，周末想去钓鱼", "你周末想去钓鱼"),
    # Words split by a space are two clauses.
    ("加班到十点 好累", "你加班到十点，好累"),
    # COLBO-01 stays as it is: a view of the companion is the user's view.
    ("我觉得你根本不在乎我", "你感到对方根本不在乎你"),
    ("您根本不在乎我的感受", "你感到对方根本不在乎你的感受"),
]


@pytest.mark.parametrize(("text", "expected"), MIRRORS)
def test_mirror(text: str, expected: str) -> None:
    assert mirror(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "上次你一直问我安不安全，吓我一跳",
        "你钓过鱼吗哈哈",
        "你直接教我吧",
        "为什么不行，你说清楚一点",
        "今晚可能去行下海旁",
    ],
)
def test_the_reply_never_echoes_these(text: str) -> None:
    engine = LanguageEngine(load_taxonomy(), rng=__import__("random").Random(1))
    said = engine.safe_mirror(text)
    assert "对方" not in said and "哈哈" not in said and "行下" not in said, said
