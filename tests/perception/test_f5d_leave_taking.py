"""Fix F5d: the rule stub's ``leave_taking`` signal, read with no card waiting.

The signal is the rule stub's in both modes (``perception/model_heads.py`` refines scores
only). It uses the F5a ``leave_taking`` phrases with the feedback scan (outermost, not
negated), and a phrase asked as a question is no goodbye.
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


LEAVING = [
    "我想睡觉了",
    "我去睡了",
    "我想试着睡一下",
    "嗯，今天就到这里吧",
    "我先去睡了，晚安",
    "今天先聊到这儿吧。",
    "改天再聊！",
    "做完了，我去睡了",
    "[20%] 我先睡了",
]

NOT_LEAVING = [
    "孩子去睡了，我终于能歇会儿",
    "今天就到这里？我还没说完",
    "今天就到这里吗",
    "今天就到这里吧？",
    "昨天我很早就去睡了",
    "我不想去睡",
    "他想睡觉了",
    "睡不着，一直在想今天的事",
    "/not-now",
]


@pytest.mark.parametrize("text", LEAVING)
def test_leave_taking_is_signalled(text: str) -> None:
    assert _signals(text).leave_taking, text


@pytest.mark.parametrize("text", NOT_LEAVING)
def test_look_alikes_and_questions_are_not(text: str) -> None:
    assert not _signals(text).leave_taking, text


def test_the_waiting_card_reading_is_unchanged() -> None:
    # F5a: a leave-taking phrase still reads as not_now for a waiting card.
    assert _signals("我去睡了").feedback is Command.NOT_NOW
    assert _signals("做完了，我去睡了").feedback is Command.DONE
