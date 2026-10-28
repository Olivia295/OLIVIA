"""Round 5 (re-test 2026-10-29, q2 section 5 and q3 section 3; drafts pending G-0).

* More ways to ask for a number: a phone with no word for support, an imperative, the
  police or ambulance number, Cantonese; what a given number is (from the signed hotline
  data only, never a guess); what to do when a call does not get through.
* A place named in English ("the US") gets that region's card; a place not known here
  gets a line on how to see another region's numbers.
* A slash word that is no chat command is never mirrored: one about resources gets them,
  any other one says it is unknown and lists the commands.
* Stopping a drink or a medicine on one's own gets the withdrawal reminder, in the crisis
  flow too, and the plan is not said back.

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
ZONES = {"CN": "Asia/Shanghai", "US": "America/New_York", "HK": "Asia/Hong_Kong"}


def _open(region: str = "CN") -> Session:
    profile = PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        user_name="小林",
        region=UserRegion(region, ZONES[region]),
    )
    return Session.open(TAX, profile, rng=random.Random(5), now=lambda: NOW)


# -- 1: asking for a number -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "region"),
    [
        ("方便给个电话吗", "CN"),
        ("有没有电话能打，想找人说说话", "CN"),
        ("麻烦把热线号码发我", "CN"),
        ("号码直接发过来吧", "CN"),
        ("报警打几号", "CN"),
        ("叫救护车要拨哪个", "CN"),
        ("俾個號碼我啦", "HK"),
        ("有冇號碼可以打俾人傾偈", "HK"),
    ],
)
def test_more_ways_to_ask_for_a_number(text: str, region: str) -> None:
    result = _open(region).turn(text)
    assert result.reply_kind is ReplyKind.RESOURCES, result.reply
    assert result.inspect.get("resources_reply") == "hotline"


@pytest.mark.parametrize(
    "text",
    [
        "有空给我打个电话",
        "我昨天给我妈打了电话",
        "他的号码我存着",
        "520是什么意思",
        "我考了130分是什么水平",
        "客服热线打了半天打不通",
    ],
)
def test_a_phone_or_a_number_in_passing_is_no_request(text: str) -> None:
    assert _open().turn(text).reply_kind is not ReplyKind.RESOURCES


def test_the_emergency_number_asked_for_leads_with_it() -> None:
    reply = _open().turn("急救号码是多少").reply
    assert reply.startswith(RENDER.hotline_emergency[0])
    assert "110" in reply and "120" in reply


def test_what_a_number_is_comes_from_the_hotline_data() -> None:
    reply = _open().turn("12356这个号码是做啥的").reply
    assert reply.startswith(RENDER.hotline_number_known)
    assert "12356：全国统一心理援助热线（中国大陆" in reply


def test_a_number_in_other_regions_names_each_region() -> None:
    reply = _open().turn("999是做什么的").reply
    assert "999：报警、消防与急救（中国香港）" in reply
    assert "999：报警、消防与急救（英国）" in reply


def test_a_number_not_in_the_data_is_not_guessed() -> None:
    result = _open().turn("95588是干嘛的")
    assert result.reply.startswith(RENDER.hotline_number_unknown[0])
    assert result.reply_kind is ReplyKind.RESOURCES


@pytest.mark.parametrize("text", ["电话老是占线，咋办", "打了几次都没人接怎么办"])
def test_a_call_that_does_not_get_through(text: str) -> None:
    reply = _open().turn(text).reply
    assert reply.startswith(RENDER.hotline_unreachable[0])
    assert "紧急电话" in reply and "身边" in reply


def test_a_call_that_does_not_get_through_after_the_card() -> None:
    session = _open()
    session.turn("有什么热线可以打")
    reply = session.turn("还是打唔通").reply
    assert reply.startswith(RENDER.hotline_unreachable[0])


def test_a_call_that_does_not_get_through_in_the_crisis_flow() -> None:
    session = _open()
    assert session.turn("我真的不想活了").in_crisis
    reply = session.turn("那个电话一直占线").reply
    assert RENDER.hotline_unreachable[0] in reply


def test_cantonese_hours_question_after_the_card() -> None:
    session = _open("HK")
    session.turn("有冇熱線可以打")
    result = session.turn("係咪通宵都有人聽㗎")
    assert result.reply_kind is ReplyKind.RESOURCES
    assert "你把" not in result.reply


# -- 2: another region -------------------------------------------------------------------------


def test_a_place_in_english_with_word_edges() -> None:
    result = _open().turn("is there a crisis line in the U.S.?")
    assert result.reply.startswith(RENDER.hotline_other_region[0])
    assert "988" in result.reply and "12356" not in result.reply


def test_an_unknown_place_in_english_gets_a_hint() -> None:
    reply = _open().turn("any suicide hotline for Brazil").reply
    assert RENDER.hotline_place_hint[0] in reply


def test_us_inside_a_word_is_no_place() -> None:
    reply = _open().turn("what hotline number should I use?").reply
    assert "988" not in reply


# -- 3: unknown slash words ------------------------------------------------------------------


@pytest.mark.parametrize("text", ["/求助", "/hotline", "/电话"])
def test_a_slash_word_about_resources_gets_them(text: str) -> None:
    result = _open().turn(text)
    assert result.reply_kind is ReplyKind.RESOURCES
    assert text not in result.reply


@pytest.mark.parametrize("text", ["/abc", "/聊天", "/start"])
def test_an_unknown_slash_word_is_not_mirrored(text: str) -> None:
    reply = _open().turn(text).reply
    assert reply.startswith(RENDER.unknown_command)
    assert "/exit" in reply and text not in reply.replace(RENDER.chat_help, "")


def test_help_and_feedback_commands_still_work() -> None:
    assert _open().turn("/help").reply.startswith(RENDER.chat_help.split("\n")[0])
    assert RENDER.unknown_command not in _open().turn("/done").reply


# -- 4: stopping on one's own ------------------------------------------------------------------

WITHDRAWAL = SAID.substance_lines["withdrawal"]


@pytest.mark.parametrize(
    "text",
    [
        "今晚开始酒我一滴都不碰了，彻底戒",
        "劳拉西泮我打算自己停掉",
        "文拉法辛我上周就停了",
        "停咗啲瞓觉药，好辛苦",
        "酒停了两天，身上难受得很",
    ],
)
def test_stopping_on_ones_own_gets_the_reminder(text: str) -> None:
    reply = _open().turn(text).reply
    assert WITHDRAWAL in reply
    assert "医生" in WITHDRAWAL and "急救" in WITHDRAWAL


@pytest.mark.parametrize(
    "text", ["今晚开始酒我一滴都不碰了，彻底戒", "下周开始我滴酒不沾了，直接戒"]
)
def test_the_abrupt_plan_is_not_said_back(text: str) -> None:
    reply = _open().turn(text).reply
    assert "戒" not in reply.replace(WITHDRAWAL, "")


def test_the_stopping_mirror_line() -> None:
    reply = _open().turn("下周开始我滴酒不沾了，直接戒").reply
    assert any(line in reply for line in SAID.stopping_acks)


def test_stopping_in_the_crisis_flow_keeps_the_reminder() -> None:
    result = _open().turn("我真的不想活了，安眠药我这两天全停了")
    assert result.in_crisis
    assert WITHDRAWAL in result.reply


def test_a_sip_to_ease_it_is_sent_to_the_doctor() -> None:
    session = _open()
    session.turn("停酒第二天了")
    reply = session.turn("要不先抿一口压一压")
    assert "医生" in reply.reply and SAID.substance_lines["ask_to_drink"] in reply.reply


@pytest.mark.parametrize(
    "text",
    [
        "医生让我慢慢减药，我在照做",
        "我按时吃抗抑郁药，最近舒服多了",
        "雨停了，我出去走走",
        "我戒了奶茶",
        "我在戒酒，第三天",
    ],
)
def test_no_stop_reminder_without_a_stop_on_ones_own(text: str) -> None:
    assert WITHDRAWAL not in _open().turn(text).reply
