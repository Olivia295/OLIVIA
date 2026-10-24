"""Fix F5a: requests, the listening lock and leave-taking in the rule stub.

Usage testing found method requests read as ordinary talk ("有没有什么办法能让我先缓一缓",
"再给我一个", "能教我一下正念吗"), a refusal of methods that did not set the listening lock
("我不需要什么方法，你就陪我说说话吧") and going to sleep or ending the talk not read at all
("我去睡了", "今天就到这里吧"). The lexicon now has general forms for each; every positive
table here has a table of look-alikes that must not fire (everyday talk, negation, someone
else, the past). Signals are the rule stub's in both modes (``perception/model_heads.py``
refines scores only), so these tables hold for model mode too.
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


# -- direct requests (issue 6) -----------------------------------------------------------

REQUESTS = [
    "有没有什么办法能让我先缓一缓",
    "有没有什么好办法让我睡着",
    "有没有好方法能让我不那么紧张",
    "再给我一个别的方法吧",
    "再给我一个练习",
    "换个方法吧",
    "换一个练习试试",
    "还有别的办法吗？",
    "有没有其他方法",
    "能不能教我怎么放松",
    "可不可以教我一下",
    "你能教我深呼吸吗",
    "教我几招吧",
    # whole messages
    "再给我一个",
    "再给我一个吧！",
    "再来一个",
    "换一个",
    "还有别的吗",
]

NOT_REQUESTS = [
    "老板说再给我一个机会",
    "我试过别的方法都没用",
    "我真的没有什么办法了",
    "外婆以前总能教我很多东西",
    "不用教我了",
    "他换了一个工作",
    "我们换个话题吧",
    "我还有别的事要忙",
    "妈妈再给我一个月时间",
    "再给我一个拥抱就好了",
]


@pytest.mark.parametrize("text", REQUESTS)
def test_requests_for_a_method(text: str) -> None:
    assert _signals(text).direct_request, text


@pytest.mark.parametrize("text", NOT_REQUESTS)
def test_look_alikes_ask_for_nothing(text: str) -> None:
    assert not _signals(text).direct_request, text


def test_a_not_a_question_is_not_a_negation() -> None:
    # 有没有 / 能不能 ask; a plain 没有 / 不能 before the same words still negates.
    assert _signals("有没有什么技巧").direct_request
    assert not _signals("我没有什么技巧").direct_request
    assert _signals("能不能教我").direct_request
    assert not _signals("你不能教我").direct_request


def test_asking_to_be_taught_a_named_practice_is_a_therapy_request() -> None:
    signals = _signals("能教我一下正念吗")
    assert signals.therapy_request == "15" and signals.direct_request
    assert _signals("CBT是什么").therapy_question == "01"
    assert _signals("CBT是什么").therapy_request is None
    assert _signals("不用教我正念").therapy_request is None


# -- the listening lock (issue 8) --------------------------------------------------------

LOCKS = [
    "我不需要什么方法，你就陪我说说话吧",
    "不需要方法，陪我聊聊天就好",
    "你能陪我说会儿话吗",
    "别给我方法，我就想有人听",
    "我不要什么方法",
]

NOT_LOCKS = [
    "我需要一个方法",
    "给我一个方法吧",
    "他陪我说了很久的话",
    "我不是不需要方法",
]


def test_known_limit_the_stub_does_not_read_tense() -> None:
    # A past "不需要什么方法" still sets the lock: phrase matching cannot see tense. The cost
    # is small (the lock only keeps the session listening; any request releases it).
    assert _signals("以前我不需要什么方法也能睡着").listening_lock_on


@pytest.mark.parametrize("text", LOCKS)
def test_turning_down_methods_sets_the_lock(text: str) -> None:
    signals = _signals(text)
    assert signals.listening_lock_on and not signals.direct_request, text


@pytest.mark.parametrize("text", NOT_LOCKS)
def test_look_alikes_set_no_lock(text: str) -> None:
    assert not _signals(text).listening_lock_on, text


# -- leave-taking (issue 10) -------------------------------------------------------------

LEAVING = [
    "我去睡了",
    "我想睡觉了",
    "我想试着睡一下",
    "我先去睡了，晚安",
    "嗯，今天就到这里吧",
    "今天先聊到这儿吧",
    "改天再聊",
    "我先撤了",
]

NOT_LEAVING = [
    "孩子去睡了，我终于能歇会儿",
    "昨天我很早就去睡了",
    "我不想去睡",
    "他想睡觉了",
    "睡不着，一直在想今天的事",
]


@pytest.mark.parametrize("text", LEAVING)
def test_leave_taking_reads_as_not_now(text: str) -> None:
    signals = _signals(text)
    assert signals.feedback is Command.NOT_NOW and not signals.feedback_unclear, text


@pytest.mark.parametrize("text", NOT_LEAVING)
def test_look_alikes_are_not_leave_taking(text: str) -> None:
    assert _signals(text).feedback is None, text


def test_other_feedback_in_the_same_message_wins_over_leave_taking() -> None:
    assert _signals("做完了，我去睡了").feedback is Command.DONE
    assert _signals("这个没用，我去睡了").feedback is Command.UNHELPFUL
    assert _signals("先存着，我去睡了").feedback is Command.NOT_NOW
    # done and not_now together stay unclear, leave-taking or not
    signals = _signals("做完了，先存着，我去睡了")
    assert signals.feedback is None and signals.feedback_unclear
