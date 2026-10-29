"""Round 6 (re-test 2026-10-29, q2 sections 5-6 and q3 section 3; drafts pending G-0).

* Asking for a number, by its grammar: a hotline told to come over, the police or
  ambulance number with a linking word, who a number is for, Cantonese giving and having
  words. In the crisis flow such a request is answered as one, not with the generic
  "I heard your question" line; asking how to talk once the call gets through gets what
  to say (where, what happened, how things are now), and in the crisis flow the card
  then puts the emergency numbers first.
* Stopping a drink or a medicine at once, by its grammar ("一粒也不吃", "再也不喝",
  "全都不吃", "下周起不喝"); "without telling the doctor" is no doctor-led taper. In the
  crisis flow the reminder comes before the numbers. A withdrawal sign in the body gets
  the reminder and no practice card after it.

Every example message is written here; none comes from an evaluation set or a re-test
report.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest

from olivia.core.language.data import load_language_data
from olivia.core.models import PersonaProfile, UserRegion
from olivia.core.session import ReplyKind, Session
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
NOW = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)
DATA = load_language_data(TAX)
RENDER = DATA.render
SAID = DATA.utterances
ZONES = {"CN": "Asia/Shanghai", "HK": "Asia/Hong_Kong"}
CRISIS = "我真的撑不下去了，不想活了"
WITHDRAWAL = SAID.substance_lines["withdrawal"]


def _open(region: str = "CN") -> Session:
    profile = PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        user_name="小周",
        region=UserRegion(region, ZONES[region]),
    )
    return Session.open(TAX, profile, rng=random.Random(11), now=lambda: NOW)


def _in_crisis(region: str = "CN") -> Session:
    session = _open(region)
    assert session.turn(CRISIS).reply_kind is ReplyKind.CRISIS
    return session


# -- 1: asking for a number -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "region"),
    [
        ("能不能把求助热线直接甩过来", "CN"),
        ("那个心理热线的号码赶紧告诉我", "CN"),
        ("叫急救车是什么号码", "CN"),
        ("报警的话该打哪个电话", "CN"),
        ("給條熱線我吖", "HK"),
        ("有冇啲號碼可以打去搵人傾", "HK"),
    ],
)
def test_more_grammar_for_asking_a_number(text: str, region: str) -> None:
    result = _open(region).turn(text)
    assert result.reply_kind is ReplyKind.RESOURCES, result.reply
    assert result.inspect.get("resources_reply") == "hotline"


@pytest.mark.parametrize(
    "text",
    [
        "我把热线发给我妈了",
        "别把热线发给我",
        "他把电话发给同事了",
        "救护车来的时候我都吓傻了",
        "这个快递是给谁的",
    ],
)
def test_these_ask_for_no_number(text: str) -> None:
    assert _open().turn(text).reply_kind is not ReplyKind.RESOURCES


def test_who_a_number_is_for_comes_from_the_hotline_data() -> None:
    reply = _open().turn("12356主要是给什么人用的").reply
    assert reply.startswith(RENDER.hotline_number_known)
    assert "12356：全国统一心理援助热线" in reply


def test_how_to_talk_on_the_call_outside_a_crisis() -> None:
    result = _open().turn("要是拨通110以后我该说什么")
    assert result.reply_kind is ReplyKind.RESOURCES
    assert result.reply.startswith(RENDER.hotline_call_script[0])


def test_a_number_asked_for_in_a_crisis_is_answered_as_such() -> None:
    session = _in_crisis()
    result = session.turn("你能先给我个号码吗")
    assert result.reply_kind is ReplyKind.CRISIS
    assert result.reply.startswith(RENDER.hotline_in_crisis[0])
    assert not any(line in result.reply for line in RENDER.question_heard)
    assert "12356" in result.reply


def test_how_to_talk_on_the_emergency_call_in_a_crisis() -> None:
    session = _in_crisis()
    result = session.turn("打110接通了我要讲什么")
    assert result.reply_kind is ReplyKind.CRISIS
    assert result.reply.startswith(RENDER.hotline_call_script[0])
    reply = result.reply
    assert "110" in reply and "120" in reply
    assert reply.index("110") < reply.index("12356")  # emergency numbers first


def test_a_hong_kong_request_in_a_crisis_gets_no_mainland_number() -> None:
    session = _in_crisis("HK")
    reply = session.turn("可唔可以俾個電話我").reply
    assert reply.startswith(RENDER.hotline_in_crisis[0])
    for number in ("12356", "110", "120"):
        assert number not in reply


# -- 2: stopping on one's own -----------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "那个安神的药我打算从今晚起一片也不吃",
        "每天半斤白酒，下礼拜起我再也不喝了",
        "医生开的那些药我准备全都不吃了",
        "情绪的药我想偷偷断掉，也不打算跟医生说",
    ],
)
def test_stopping_by_grammar_gets_the_reminder(text: str) -> None:
    assert WITHDRAWAL in _open().turn(text).reply


@pytest.mark.parametrize(
    "text",
    [
        "奶茶我决定一口也不喝了",
        "医生让我每两周减一点药，我照着做",
        "宵夜我从明天起再也不吃了",
    ],
)
def test_no_reminder_without_a_drink_or_medicine_or_with_a_taper(text: str) -> None:
    reply = _open().turn(text).reply
    assert WITHDRAWAL not in reply


def test_in_a_crisis_the_reminder_comes_before_the_numbers() -> None:
    session = _in_crisis()
    reply = session.turn("我每晚都喝白酒，从后天开始一滴也不碰了").reply
    assert WITHDRAWAL in reply
    assert reply.index(WITHDRAWAL) < reply.index("12356")


def test_a_withdrawal_sign_gets_no_practice_card() -> None:
    result = _open().turn("停了氯硝西泮四天，手抖得厉害，心跳很快，一整夜都没合眼")
    assert result.reply_kind is not ReplyKind.CARD
    assert "约 2 分钟" not in result.reply
    assert WITHDRAWAL in result.reply
