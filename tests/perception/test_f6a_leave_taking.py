"""Fix F6a: reported goodbyes and whole-clause goodbyes in the rule stub.

Usage testing: "他跟我说今天就到这里吧，然后就把我拉黑了" and "老板说今天就到这里，明天再
改" got the goodbye on the first turn, while "拜拜", "好的，拜拜", "88", "下次聊" and
"先这样吧" got an ordinary reply. A ``leave_taking`` phrase after reported speech or
another person in its clause is no goodbye; the ``leave_taking_whole`` goodbyes count only
as a clause of their own.
"""

from __future__ import annotations

import pytest

from olivia.core.models import CrisisLevel
from olivia.core.perception.lexicon import load_perception_lexicon
from olivia.core.perception.rule_stub import RuleStub
from olivia.core.perception.signals import Command, TurnSignals
from olivia.core.safety.crisis import CrisisAssessment
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
STUB = RuleStub(TAX, load_perception_lexicon(TAX))


def _signals(text: str) -> TurnSignals:
    return STUB.perceive(text, CrisisAssessment(CrisisLevel.L0, 0.0, "STAGE2", False, ()))[1]


GOODBYES = [
    "拜拜",
    "好的，拜拜",
    "好的拜拜",
    "88",
    "886~",
    "下次聊",
    "那我们下次聊吧",
    "先这样吧",
    "嗯，今天先这样",
    "不说了，今天就到这里吧",
    "不说了今天就到这里吧",
    # I7 (2026-10-26, transcripts p1-s1 and p5-s2): sleep as a clause of its own.
    "[2%] 睡了",
    "晚安",
    "好，晚安",
    "嗯，睡了",
    "我睡了",
    "睡觉去了",
]

REPORTED_OR_NOT_A_GOODBYE = [
    "他跟我说今天就到这里吧，然后就把我拉黑了",
    "老板说今天就到这里，明天再改",
    "我妈说她去睡了，我还睡不着",
    "她告诉我今天就到这里",
    "拜拜那段感情",
    "跟过去说拜拜",
    "我考了88",
    "这个方案先这样吧",
    "下次聊聊你的工作",
    "拜拜？",
    "孩子终于睡了",
    "昨天睡了六个小时",
    "你睡了吗",
    "晚安？",
    "一想到这件事我就睡不着",
]


@pytest.mark.parametrize("text", GOODBYES)
def test_whole_clause_goodbyes_take_leave(text: str) -> None:
    signals = _signals(text)
    assert signals.leave_taking, text
    assert signals.feedback is Command.NOT_NOW, text


@pytest.mark.parametrize("text", REPORTED_OR_NOT_A_GOODBYE)
def test_reported_speech_and_look_alikes_do_not(text: str) -> None:
    assert not _signals(text).leave_taking, text


def test_reported_goodbye_is_not_a_not_now_for_a_waiting_card() -> None:
    assert _signals("他跟我说今天就到这里吧").feedback is None
    assert _signals("做完了，拜拜").feedback is Command.DONE
