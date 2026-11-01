"""Round 7 (re-test 2026-10-31, q2 section 6, q3 sections 3-4, q4 B5; drafts pending G-0).

* Asking for a number, by its grammar: wanting to call or find a line to talk, the
  police or the ambulance (Hong Kong 白车) then the number, a support line and "which
  number", which line to call, what the numbers are for. Someone else's call or a
  nuisance call is no request. Traditional 專 folds to 专.
* In the crisis flow such questions get a real answer before the card: a police call is
  for help, not an arrest; what each number is (from the signed hotline data only);
  which line is for what (the emergency numbers then lead the card); the first words on
  a hotline call. "我想打电话，打哪个" is no reaching out to someone nearby.
* Withdrawal: the reminder names only the kind of medicine or drink spoken of, missed
  doses and tapering on one's own count, English too; someone else's or a non-psychiatric
  medicine gets the general "ask the doctor" line; a clinic word naming where a medicine
  came from is no wish to see a doctor; nothing after the reminder says it can wait.
* A city the user says they are in counts for its country, now and later in the session.

Every example message is written here; none comes from an evaluation set or a re-test
report.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest

from olivia.core.language.data import load_language_data
from olivia.core.models import CrisisLevel, PersonaProfile, UserRegion
from olivia.core.perception.lexicon import load_perception_lexicon
from olivia.core.perception.rule_stub import RuleStub
from olivia.core.safety.crisis import CrisisAssessment
from olivia.core.safety.normalize import normalize
from olivia.core.session import ReplyKind, Session
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
NOW = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)
DATA = load_language_data(TAX)
RENDER = DATA.render
SAID = DATA.utterances
CLASSES = SAID.withdrawal_classes
STUB = RuleStub(TAX, load_perception_lexicon(TAX))
CALM = CrisisAssessment(CrisisLevel.L0, 0.0, "STAGE2", False, ())
ZONES = {"CN": "Asia/Shanghai", "HK": "Asia/Hong_Kong", "TW": "Asia/Taipei", "US": "UTC"}
CRISIS = {"US": "I want to end my life tonight"}
REMINDERS = (
    SAID.substance_lines["withdrawal"],
    SAID.substance_lines["withdrawal_severe"],
    *CLASSES.values(),
)


def _open(region: str = "CN", seed: int = 7) -> Session:
    profile = PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        user_name="小禾",
        region=UserRegion(region, ZONES[region]),
    )
    return Session.open(TAX, profile, rng=random.Random(seed), now=lambda: NOW)


def _in_crisis(region: str = "CN") -> Session:
    session = _open(region)
    result = session.turn(CRISIS.get(region, "我撑不下去了，真的不想活了"))
    assert result.reply_kind is ReplyKind.CRISIS
    return session


def _signals(text: str):  # type: ignore[no-untyped-def]
    return STUB.perceive(text, CALM)[1]


# -- 1: asking for a number -------------------------------------------------------------------


def test_traditional_zhuan_folds() -> None:
    assert normalize("專線") == "专线"


@pytest.mark.parametrize(
    ("text", "region"),
    [
        ("我想拨个电话找人倾诉一下", "CN"),
        ("要叫救护车，号码多少来着", "CN"),
        ("我要搵白車，電話係咩", "HK"),
        ("情緒支持專線幾號呢", "TW"),
        ("现在该拨哪支号码", "CN"),
        ("12356和120有啥差别", "CN"),
    ],
)
def test_more_grammar_for_asking_a_number(text: str, region: str) -> None:
    result = _open(region).turn(text)
    assert result.reply_kind is ReplyKind.RESOURCES, result.reply
    assert result.inspect.get("resources_reply") == "hotline"


@pytest.mark.parametrize(
    "text",
    [
        "邻居天天大半夜煲电话，我快崩溃了",
        "怎么让楼上别半夜打电话",
        "推销电话又来了，烦",
        "想给我爸打个电话聊聊近况",
        "他想找个电话聊聊，可是不好意思",
    ],
)
def test_someone_elses_call_asks_for_no_number(text: str) -> None:
    assert _open().turn(text).reply_kind is not ReplyKind.RESOURCES


def test_what_two_numbers_are_comes_from_the_data() -> None:
    reply = _open().turn("12356和120有啥差别").reply
    assert reply.startswith(RENDER.hotline_purposes_known)
    assert "· 120：医疗急救" in reply and "· 12356：全国统一心理援助热线" in reply
    assert "· 110：" not in reply.split("\n\n")[0]  # only the named ones


def test_first_words_outside_a_crisis() -> None:
    reply = _open().turn("拨热线的话第一句讲什么好").reply
    assert reply.startswith(RENDER.hotline_first_words[0])


# -- 2: in the crisis flow ---------------------------------------------------------------------


def test_a_police_call_is_for_help() -> None:
    reply = _in_crisis().turn("要是报警了，我会不会被抓起来").reply
    assert reply.startswith(RENDER.hotline_police_fear[0])
    assert "110" in reply and "120" in reply


@pytest.mark.parametrize(
    ("text", "region"),
    [
        ("我是该打急救还是打心理热线", "CN"),
        ("那我现在该拨哪个", "CN"),
        ("我應該搵邊個熱線", "HK"),
        ("who should I ring now", "US"),
    ],
)
def test_which_line_is_answered_and_the_emergency_numbers_lead(text: str, region: str) -> None:
    result = _in_crisis(region).turn(text)
    assert result.reply_kind is ReplyKind.CRISIS
    assert result.reply.startswith(RENDER.hotline_which[0]), result.reply
    assert not result.reply.startswith(RENDER.crisis_reach_out[0])
    emergency = {"CN": "110", "HK": "999", "US": "911"}[region]
    assert emergency in result.reply


def test_what_the_numbers_are_for_in_a_crisis() -> None:
    reply = _in_crisis().turn("卡上这几个号码各自是干嘛的").reply
    assert reply.startswith(RENDER.hotline_purposes_known)
    assert "· 120：医疗急救" in reply and "· 12356：全国统一心理援助热线" in reply


def test_a_number_asked_about_in_a_crisis() -> None:
    reply = _in_crisis("TW").turn("1980是做什麼的").reply
    assert reply.startswith(RENDER.hotline_number_known)
    assert "1980：张老师" in reply


def test_first_words_on_a_hotline_in_a_crisis() -> None:
    reply = _in_crisis().turn("电话接通了，我开口第一句讲啥").reply
    assert reply.startswith(RENDER.hotline_first_words[0]), reply


# -- 3: withdrawal -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("舍曲林我漏了三天没吃，现在头一阵阵发晕", "antidepressant"),
        ("劳拉西泮我想从这周起自己停", "benzo"),
        ("碳酸锂我打算慢慢自己减掉", "mood_stabilizer"),
        ("奥氮平断了五天，整晚睡不着", "antipsychotic"),
        ("安眠药我现在隔天才吃一次，自己在减", "sleep"),
        ("I quit my Lexapro cold turkey and keep feeling dizzy", "antidepressant"),
        ("戒酒以后浑身冒冷汗，手抖个不停", "alcohol"),
    ],
)
def test_the_reminder_names_the_kind_spoken_of(text: str, kind: str) -> None:
    result = _open().turn(text)
    assert CLASSES[kind] in result.reply, result.reply
    others = [line for line in REMINDERS if line != CLASSES[kind]]
    assert not any(line in result.reply for line in others)
    assert result.reply_kind is not ReplyKind.CARD


@pytest.mark.parametrize(
    "text", ["我公公自己把胰岛素停了", "我室友说她的抗抑郁药已经停了", "降压药我这周没吃"]
)
def test_someone_elses_or_a_non_psychiatric_medicine_gets_the_general_line(text: str) -> None:
    reply = _open().turn(text).reply
    assert CLASSES["general"] in reply, reply
    assert not any(line in reply for line in REMINDERS if line != CLASSES["general"])


@pytest.mark.parametrize(
    "text",
    ["医生让我隔天吃一次舍曲林，慢慢减", "我按时吃喹硫平，睡得好多了", "手机锂电池鼓包了"],
)
def test_no_reminder_without_a_stop_on_ones_own(text: str) -> None:
    reply = _open().turn(text).reply
    assert not any(line in reply for line in REMINDERS)


def test_a_clinic_word_naming_a_medicine_is_no_wish_to_go() -> None:
    assert not _signals("心理科开的那些药我今晚起不吃了").help_seeking
    assert _signals("我想去精神科看看").help_seeking


def test_the_stop_in_a_crisis_is_no_wish_to_see_a_doctor() -> None:
    reply = _in_crisis().turn("精神科医生给的药我打算明天起不吃了").reply
    assert not any(line in reply for line in RENDER.help_seeking)
    assert CLASSES["psychiatric"] in reply or SAID.substance_lines["withdrawal"] in reply


@pytest.mark.parametrize("seed", range(12))
def test_nothing_says_it_can_wait_after_the_emergency_reminder(seed: int) -> None:
    session = _open(seed=seed)
    first = session.turn("停酒第三天，夜里看见窗帘上有人影在晃").reply
    assert SAID.substance_lines["withdrawal_severe"] in first
    after = session.turn("嗯，我知道了")
    for phrase in SAID.urgent_conflicts:
        assert phrase not in first and phrase not in after.reply


# -- 4: places ---------------------------------------------------------------------------------


def test_a_city_names_its_country() -> None:
    result = _open().turn("我在名古屋读研，能给个求助热线吗")
    assert result.reply.startswith(RENDER.hotline_elsewhere[0])
    assert "12356" not in result.reply and "110（报警）" not in result.reply
    assert "日本：报警 110" in result.reply


def test_a_city_said_earlier_counts_for_a_later_request() -> None:
    session = _open()
    session.turn("我现在人在釜山，一个人住")
    reply = session.turn("有没有求助热线").reply
    assert reply.startswith(RENDER.hotline_elsewhere[0])
    assert "12356" not in reply and "韩国：报警 112" in reply


def test_a_supported_city_gets_that_regions_card() -> None:
    reply = _open().turn("我在蒙特利尔读书，有没有热线").reply
    assert reply.startswith(RENDER.hotline_other_region[0])
    assert "12356" not in reply


def test_a_place_in_the_past_is_not_kept() -> None:
    session = _open()
    session.turn("我在东京读书的时候特别孤单")
    reply = session.turn("有没有求助热线").reply
    assert "12356" in reply
