"""Natural-language feedback, answers and kit recall in the rule stub (roadmap R-7b).

The stub reads every message on its own; whether a card waits is the session's call
(tests/session/test_session_nl_feedback.py), so these tables only check what the text says.
"""

from __future__ import annotations

import pytest

from olivia.core.models import CrisisLevel
from olivia.core.perception.lexicon import load_perception_lexicon, strip_marks
from olivia.core.perception.rule_stub import RuleStub
from olivia.core.perception.signals import Answer, Command, TurnSignals
from olivia.core.safety.crisis import CrisisAssessment
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
STUB = RuleStub(TAX, load_perception_lexicon(TAX))


def _signals(text: str) -> TurnSignals:
    return STUB.perceive(text, CrisisAssessment(CrisisLevel.L0, 0.0, "STAGE2", False, ()))[1]


POSITIVES: dict[Command, list[str]] = {
    Command.DONE: [
        "做完了",
        "做完了！",
        "做完了!",
        "试过了，好多了",
        "刚照着做了一遍，舒服多了",
        "练完了，感觉好多了",
        "试了一下，挺有用的",
        "試過了",  # Traditional folds to Simplified
    ],
    Command.NOT_NOW: [
        "今天先不做了",
        "我今天真的提不起劲做这个",
        "先存着吧",
        "先存着吧。。。",
        "改天再试吧",
        "今天不想做这个",
        "现在不想做，下次再说",
        "帮我收进锦囊",
    ],
    Command.UNHELPFUL: [
        "这个方法对我没用",
        "这个不适合我",
        "这个不适合我。",
        "试过了，没用",
        "试了也没用",
        "做完了，但没什么用",
        "刚才那个对我没什么帮助",
        "我不想做这个",  # aversion is unhelpful feedback too
        "這個不適合我",
    ],
}


@pytest.mark.parametrize(
    ("text", "expected"),
    [(text, command) for command, texts in POSITIVES.items() for text in texts],
)
def test_feedback_phrases(text: str, expected: Command) -> None:
    signals = _signals(text)
    assert signals.feedback is expected
    assert not signals.feedback_unclear
    assert signals.command is None


@pytest.mark.parametrize(
    "text",
    [
        "唉",
        "唉。",
        "哎……",
        "算了吧",
        "算了吧！",
        "再说吧",
        "再说吧~",
        "随便吧",
        "不知道",
        "还没想好",
    ],
)
def test_unclear_whole_messages(text: str) -> None:
    signals = _signals(text)
    assert signals.feedback_unclear and signals.feedback is None


def test_done_and_not_now_together_are_unclear() -> None:
    signals = _signals("做完了一半，先存着吧")
    assert signals.feedback_unclear and signals.feedback is None


@pytest.mark.parametrize(
    "text", ["唉，今天又被老板骂了", "算了吧，我们聊点别的", "再说吧，我现在想聊聊家里的事"]
)
def test_unclear_words_inside_a_longer_message_are_not_unclear_feedback(text: str) -> None:
    signals = _signals(text)
    assert not signals.feedback_unclear and signals.feedback is None


HARD_NEGATIVES = [
    # Self-criticism is never method feedback.
    "我真没用",
    "我就是个废物",
    "我什么都做不好",
    "我太没用了",
    "我根本没用",
    "我觉得自己一点用都没有",
    "我连这个都做不好",
    "我觉得自己没什么用",
    # Negation.
    "不是没用",
    "这个方法不是没用，只是我还没习惯",
    "没有不想做了",
    "我不是今天不想做，是现在走不开",
    "也不是不适合我",
    # Unrelated sentences and questions.
    "今天下雨了",
    "这个练习有用吗",
    "这份工作不适合我",
    "我昨天完成了报告",
    "给我一个方法",
]


@pytest.mark.parametrize("text", HARD_NEGATIVES)
def test_hard_negatives_are_not_feedback(text: str) -> None:
    signals = _signals(text)
    assert signals.feedback is None and not signals.feedback_unclear, text


@pytest.mark.parametrize("text", ["我真没用", "我就是个废物", "我什么都做不好", "我根本没用"])
def test_self_criticism_is_not_aversion_either(text: str) -> None:
    assert not _signals(text).aversion


@pytest.mark.parametrize(
    ("text", "answer"),
    [
        ("好", Answer.AFFIRM),
        ("好的！", Answer.AFFIRM),
        ("可以", Answer.AFFIRM),
        ("嗯嗯。", Answer.AFFIRM),
        ("ＯＫ", Answer.AFFIRM),
        ("收起来吧", Answer.AFFIRM),
        ("不用了", Answer.DECLINE),
        ("不用了，谢谢", Answer.DECLINE),
        ("不要", Answer.DECLINE),
        ("先不用", Answer.DECLINE),
    ],
)
def test_whole_message_answers(text: str, answer: Answer) -> None:
    assert _signals(text).answer is answer


@pytest.mark.parametrize("text", ["好累啊", "可以聊聊吗", "不用你管", "好的我明白了你的意思但是"])
def test_answers_need_the_whole_message(text: str) -> None:
    assert _signals(text).answer is None


@pytest.mark.parametrize(
    "text",
    [
        "上次存的那个方法再给我看看",
        "我想试试锦囊里的",
        "锦囊里那个再给我看看",
        "收进锦囊的那个再给我看看",
        "打开锦囊吧",
    ],
)
def test_kit_recall(text: str) -> None:
    signals = _signals(text)
    assert signals.kit_recall
    # A recall is not shelving, even when it names the kit.
    assert signals.feedback is None


@pytest.mark.parametrize("text", ["今天好累", "帮我收进锦囊", "给我一个方法"])
def test_no_kit_recall_without_a_phrase(text: str) -> None:
    assert not _signals(text).kit_recall


@pytest.mark.parametrize("command", list(Command))
def test_commands_carry_no_natural_language_fields(command: Command) -> None:
    signals = _signals(command.value)
    assert signals.command is command
    assert signals.feedback is None and not signals.feedback_unclear
    assert signals.answer is None and not signals.kit_recall


def test_strip_marks_drops_punctuation_and_symbols_only() -> None:
    assert strip_marks("试过了,没用!~") == "试过了没用"
    assert strip_marks("ok") == "ok"
