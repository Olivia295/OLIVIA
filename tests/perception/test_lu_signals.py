"""Language understanding (dogfood I1, I2, I8): what the rule stub hears in a message.

Usage testing found explicit requests for a practice that the stub did not read as a
direct request (COLBO-03) because the words were not next to each other ("有什么五分钟
能做的放松方法吗", "教我一个睡前放松的方法", "给我一个不用动嘴的练习"); requests for a
practice that is masked for a heart or breathing condition ("憋气那种", "冷水敷脸"); a
"why not" right after; heart symptoms; and questions about what OLIVIA stores ("你会把我
说的话存下来吗"). Talk that only contains such words (a story, a negation, someone else's
words) must stay ordinary talk, so stage one never gets a card unasked (COLBO-02).
"""

from __future__ import annotations

import pytest

from olivia.core.models import CrisisLevel
from olivia.core.perception.lexicon import load_perception_lexicon
from olivia.core.perception.rule_stub import RuleStub
from olivia.core.perception.signals import TurnSignals
from olivia.core.safety.crisis import CrisisAssessment
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
STUB = RuleStub(TAX, load_perception_lexicon(TAX))
CARDIO = "CARDIORESPIRATORY_INSTABILITY"


def _signals(text: str) -> TurnSignals:
    return STUB.perceive(text, CrisisAssessment(CrisisLevel.L0, 0.0, "STAGE2", False, ()))[1]


@pytest.mark.parametrize(
    "text",
    [
        # dogfood p1-s2, p2-s2, p4-s2
        "有什么五分钟能做的放松方法吗",
        "算了，现在可以教我一个睡前放松的方法吗",
        "教我一个睡前放松的方法",
        "给我一个不用动嘴的练习",
        "你直接教我吧",
        "来个呼吸练习吧，憋气那种我听说很管用",
        "能不能让我放松一下",
        "有没有什么坐着就能做的小方法",
        "那有什么办法能让我睡得着吗",
        "可以给我一些睡前的练习吗",
    ],
)
def test_explicit_requests_are_direct_requests(text: str) -> None:
    assert _signals(text).direct_request, text


@pytest.mark.parametrize(
    "text",
    [
        "我试过很多方法都没用",
        "我妈问我有没有什么好方法",
        "他给我一个方法，说是能睡得好",
        "外婆总能教我很多东西",
        "老师教我一个记单词的方法",
        "我没有什么方法能让自己放松",
        "我不能放松，一放松就焦虑",
        "你能帮我想想怎么说吗",
        "我该怎么开口跟妈妈聊",
        "别老给我发热线电话",
    ],
)
def test_talk_with_the_words_is_no_request(text: str) -> None:
    assert not _signals(text).direct_request, text


@pytest.mark.parametrize(
    "text",
    [
        "来个呼吸练习吧，憋气那种我听说很管用",
        "我想试试那个4-7-8呼吸法，就是吸4秒憋7秒那个",
        "那用冷水敷脸呢，网上说能马上让心跳降下来",
        "冷水洗脸那个方法行不行",
    ],
)
def test_a_masked_practice_named(text: str) -> None:
    assert CARDIO in _signals(text).contraindicated_practice, text


@pytest.mark.parametrize(
    "text",
    ["我不想憋气", "刚才游泳憋气憋得好难受", "冷水敷脸我试过了，没用"],
)
def test_a_masked_practice_only_mentioned(text: str) -> None:
    signals = _signals(text)
    # Mentioned in a story or turned down: not asked for.
    assert CARDIO not in signals.contraindicated_practice or not signals.direct_request, text


def test_a_named_masked_practice_is_no_feedback() -> None:
    # "憋气那种我听说很管用" praises another practice; it is not a done for the waiting card.
    signals = _signals("来个呼吸练习吧，憋气那种我听说很管用")
    assert signals.feedback is None


@pytest.mark.parametrize("text", ["为什么不行，说清楚", "为什么不行，你说清楚一点", "为啥不能"])
def test_why_not(text: str) -> None:
    assert _signals(text).why_not, text


@pytest.mark.parametrize("text", ["为什么我总是这样", "我也想说清楚一点"])
def test_no_why_not(text: str) -> None:
    assert not _signals(text).why_not, text


@pytest.mark.parametrize(
    "text", ["一想到就胸口发紧，手心出汗", "不过今晚心又跳得很快，睡不着", "胸闷，喘不过气"]
)
def test_heart_symptoms(text: str) -> None:
    assert _signals(text).cardiac_symptom, text


@pytest.mark.parametrize("text", ["心里好闷", "跳得很快的舞我学不会"])
def test_no_heart_symptoms(text: str) -> None:
    assert not _signals(text).cardiac_symptom, text


@pytest.mark.parametrize(
    "text",
    [
        "先问一下，你会把我说的话存下来吗",
        "我说的东西会不会被上传",
        "你会把今天的话记下来吗",
        "我们的聊天记录会不会被别人看到",
        "你会联网吗",
    ],
)
def test_privacy_questions(text: str) -> None:
    assert _signals(text).privacy_question, text


@pytest.mark.parametrize(
    "text",
    ["我把照片上传到网上了", "他把我说的话都记下来了", "记住：周四要见王老师", "我不想被别人看到"],
)
def test_no_privacy_question(text: str) -> None:
    assert not _signals(text).privacy_question, text


@pytest.mark.parametrize(
    "text", ["我该怎么开口跟妈妈聊", "你能帮我想想怎么说吗", "要怎么拒绝他比较好"]
)
def test_advice_requests(text: str) -> None:
    signals = _signals(text)
    assert signals.advice_request and not signals.direct_request, text


@pytest.mark.parametrize(
    "text", ["我不知道该怎么说", "他怎么跟我说话的，太凶了吧", "教我一个放松的方法"]
)
def test_no_advice_request(text: str) -> None:
    assert not _signals(text).advice_request, text


@pytest.mark.parametrize("text", ["你能不能别老给我发热线电话", "怎么又是热线电话"])
def test_hotline_pushback(text: str) -> None:
    assert _signals(text).hotline_pushback, text
