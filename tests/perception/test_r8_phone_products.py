"""Round 8 (2026-11-25; drafts pending G-0): a phone product, job or service is no line asked for.

The round-5 grammar for asking for a number ("给个电话", "推荐个靠谱的电话", "有没有电话能打")
also read "推荐个靠谱的电话销售" as a request for a hotline. A phone word followed by what
makes it something else (a phone card, a plan, a phone sales job, a conference call, an
interview) is none, as the round-8 finding grammar already said; a delivery, takeaway or
customer-service number never was one. Every way of asking for a number that was a
request stays one.

Every example message is written here; none comes from an evaluation set or a re-test
report.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest

from olivia.core.models import CrisisLevel, PersonaProfile, UserRegion
from olivia.core.perception.lexicon import load_perception_lexicon
from olivia.core.perception.rule_stub import RuleStub
from olivia.core.safety.crisis import CrisisAssessment
from olivia.core.session import ReplyKind, Session
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
STUB = RuleStub(TAX, load_perception_lexicon(TAX))
CALM = CrisisAssessment(CrisisLevel.L0, 0.0, "STAGE2", False, ())
NOW = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)

ASKS = [
    "给个电话",
    "方便给个电话吗",
    "推荐个靠谱的电话",
    "推荐一个能打的号码",
    "推荐几个靠谱的电话",
    "求个号码，我想找人说说话",
    "要个电话本地能打的就行",
    "给个电话号码吧",
    "俾個號碼我啦",
    "有没有电话能打，想找人说说话",
    "有冇號碼可以打俾人傾偈",
]

NOT_ASKS = [
    "推荐个靠谱的电话销售",
    "求个靠谱的电话销售",
    "给我个电话销售的岗位",
    "推荐个电话卡",
    "要个电话卡",
    "有没有电话卡可以打",
    "有冇電話卡可以打",
    "推荐个电话套餐",
    "给我推荐个话费套餐",
    "有没有什么电话套餐打电话便宜",
    "来个电话会议",
    "推荐一个电话会议软件",
    "有没有电话会议要打",
    "推荐个电话面试的技巧",
    "推荐个靠谱的电话客服",
    "给个快递电话",
    "求个外卖电话",
    "要一个外卖的电话",
    "给个快递员的电话",
    "告诉我客服电话",
    "给我个客服号码",
]


def _open() -> Session:
    profile = PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        user_name="小禾",
        region=UserRegion("CN", "Asia/Shanghai"),
    )
    return Session.open(TAX, profile, rng=random.Random(7), now=lambda: NOW)


@pytest.mark.parametrize("text", ASKS)
def test_asking_for_a_number_is_still_a_request(text: str) -> None:
    assert STUB.perceive(text, CALM)[1].hotline_request, text


@pytest.mark.parametrize("text", NOT_ASKS)
def test_a_phone_product_job_or_service_is_no_request(text: str) -> None:
    assert not STUB.perceive(text, CALM)[1].hotline_request, text


@pytest.mark.parametrize("text", ["推荐个靠谱的电话销售", "推荐个电话卡", "来个电话会议"])
def test_no_resource_card_for_them(text: str) -> None:
    assert _open().turn(text).reply_kind is not ReplyKind.RESOURCES


def test_a_phone_card_beside_a_real_ask_still_asks() -> None:
    text = "电话卡快没钱了，给个号码吧，想找人说说"
    assert STUB.perceive(text, CALM)[1].hotline_request
