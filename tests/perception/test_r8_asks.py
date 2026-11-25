"""Round 8 (re-test r8, 2026-11-25; drafts pending G-0): asks for a line, and 安定.

* Asking for a line, by its grammar: finding or having a line said by what it is for
  ("帮我找个能打的电话"), when someone answers asked at the start of a clause ("几点有人听",
  a first message counts), a call to talk and then a recommendation asked for ("通个电话
  聊一下有推荐吗"), and 报警 with a word inside it ("报个警电话多少"). Everyday talk with the
  same words (a game, a call to a friend, a parcel's number, being picked up) is none.
* Canada and Australia by their common names, Traditional spellings included, land on CA
  and AU; words that hold 加国 ("参加国际") do not.
* 安定 is the benzodiazepine only next to stopping, cutting down or going without it
  ("安定停了三天", "不吃安定以后手抖"), never in "情绪安定", "安定下来", "生活安定" or the
  name of Beijing Anding Hospital.

Every example message is written here; none comes from an evaluation set or a re-test
report.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from olivia.core.language.data import LanguageDataError, _parse_substance, load_language_data
from olivia.core.language.guard import read_substance
from olivia.core.models import CrisisLevel, PersonaProfile, UserRegion
from olivia.core.perception.lexicon import load_perception_lexicon
from olivia.core.perception.rule_stub import RuleStub
from olivia.core.perception.signals import TurnSignals
from olivia.core.safety.crisis import CrisisAssessment
from olivia.core.session import ReplyKind, Session
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
STUB = RuleStub(TAX, load_perception_lexicon(TAX))
CALM = CrisisAssessment(CrisisLevel.L0, 0.0, "STAGE2", False, ())
DATA = load_language_data(TAX)
CUES = DATA.substance
NOW = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)
ZONES = {"CN": "Asia/Shanghai", "CA": "America/Toronto"}
SUBSTANCE = Path(__file__).resolve().parents[2] / "olivia" / "data" / "lexicons" / "substance.yaml"


def _signals(text: str) -> TurnSignals:
    return STUB.perceive(text, CALM)[1]


def _open(region: str = "CN") -> Session:
    profile = PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        user_name="小禾",
        region=UserRegion(region, ZONES[region]),
    )
    return Session.open(TAX, profile, rng=random.Random(7), now=lambda: NOW)


# -- 1a: finding or having a line, said by what it is for -------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "帮我找个能打的电话",
        "你帮我找一个打得通的号码",
        "能帮我搜个有人接的电话吗",
        "麻烦帮我查个能打的号码",
        "給我找個能打的電話",
        "有没有能打的电话",
        "想找个能打的电话说说话",
        "有没有可以倾诉的电话",
        "需要一个能说话的号码",
    ],
)
def test_finding_a_line_to_call_is_a_request(text: str) -> None:
    assert _signals(text).hotline_request, text


@pytest.mark.parametrize(
    "text",
    [
        "这游戏里帮我找个能打的队友",
        "帮我找个能打的角色",
        "这个英雄很能打，有没有推荐的出装",
        "帮我查一下快递电话",
        "帮我找一下我妈的电话",
        "帮我找个能打电话的地方",
        "帮我找个能打的电话卡",
        "帮我找个能打的电话手表",
        "家里有没有能打的电话",
        "附近有没有能打的电话",
        "不用帮我找能打的电话",
    ],
)
def test_other_numbers_phones_and_games_are_no_request(text: str) -> None:
    assert not _signals(text).hotline_request, text


# -- 1b: when someone answers, at the start of a clause ------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "几点有人听",
        "幾點有人聽",
        "什么时候有人接电话",
        "请问几点到几点有人接",
        "那什么时候才有人接",
        "我想知道几点有人接",
        "电话一般几点有人接？",
        "晚上有人接吗",
        "半夜有没有人听",
        "凌晨还有人接听吗",
        "周末也有人值班吗",
    ],
)
def test_asking_when_someone_answers_is_a_request_about_hours(text: str) -> None:
    signals = _signals(text)
    assert signals.hotline_request, text
    assert signals.hotline_hours, text
    assert signals.hotline_words, text


@pytest.mark.parametrize(
    "text",
    [
        "快递几点有人接收",
        "几点有人在家收快递",
        "食堂几点有人",
        "客服几点有人接",
        "明天几点有人来接我",
        "几点有人接我放学",
        "那几点有人接孩子",
        "几点有人接班",
        "这个直播几点有人看",
        "几点有人上线打游戏",
        "晚上有人陪我吃饭吗",
        "什么时候才有人听我说话",
        "周末有人值班",
    ],
)
def test_other_hours_and_laments_are_no_request(text: str) -> None:
    signals = _signals(text)
    assert not signals.hotline_request, text
    assert not signals.hotline_words, text


def test_a_first_message_asking_when_someone_listens_gets_the_card() -> None:
    result = _open().turn("几点有人听")
    assert result.reply_kind is ReplyKind.RESOURCES
    assert "12356" in result.reply
    assert DATA.render.hotline_hours[0] in result.reply


def test_asking_when_someone_listens_in_a_crisis_gets_the_hours_from_the_data() -> None:
    session = _open()
    assert session.turn("我撑不下去了，真的不想活了").reply_kind is ReplyKind.CRISIS
    result = session.turn("几点有人听")
    assert result.reply_kind is ReplyKind.CRISIS
    assert result.reply.startswith(DATA.render.hotline_hours_from_data)


# -- 1c: a call to talk, then a recommendation asked for -------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "通个电话聊一下有推荐吗",
        "通個電話聊一下有推薦嗎",
        "想通个电话找人聊聊",
        "想找人通个电话说说话",
        "打个电话倾诉一下，有推荐的吗",
        "打电话聊一聊，有什么推荐",
        "想打通电话聊聊天，求推荐",
    ],
)
def test_a_call_to_talk_asked_for_is_a_request(text: str) -> None:
    assert _signals(text).hotline_request, text


@pytest.mark.parametrize(
    "text",
    [
        "我想跟我妈通个电话聊一下，有推荐的话题吗",
        "跟我妈通个电话聊聊，有什么好聊的",
        "跟朋友打个电话聊聊天，好开心",
        "昨天和老同学通了电话聊了很久",
        "跟导师通个电话聊一下论文，有什么建议",
        "给客户打个电话聊方案，有推荐的话术吗",
        "打电话聊天有推荐的套餐吗",
        "打个电话聊聊，有没有空",
        "我想通了，电话里跟他聊聊",
    ],
)
def test_a_call_to_someone_named_or_a_phone_plan_is_no_request(text: str) -> None:
    assert not _signals(text).hotline_request, text


# -- 1d: 报警 with a word inside it ----------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "报个警电话多少",
        "報個警電話幾號",
        "报个警打几号",
        "要报一下警，号码是多少",
        "报下警要拨什么号码",
        "报一次警该打哪个",
    ],
)
def test_the_police_number_asked_with_a_split_verb_is_an_emergency_request(text: str) -> None:
    signals = _signals(text)
    assert signals.hotline_request, text
    assert signals.hotline_emergency, text


@pytest.mark.parametrize(
    "text",
    [
        "他说要报警，我好怕",
        "报个警吓唬他？不至于吧",
        "我昨天报了个警，警察来得挺快",
        "报警没用的",
        "救护车的声音好吵",
    ],
)
def test_the_police_in_a_story_is_no_request(text: str) -> None:
    assert not _signals(text).hotline_request, text


def test_the_police_number_asked_leads_with_the_emergency_numbers() -> None:
    result = _open().turn("报个警电话多少")
    assert result.reply_kind is ReplyKind.RESOURCES
    assert result.reply.startswith(DATA.render.hotline_emergency[0])
    assert "110" in result.reply


def test_the_police_number_asked_in_a_crisis_puts_the_emergency_numbers_first() -> None:
    session = _open()
    assert session.turn("我撑不下去了，真的不想活了").reply_kind is ReplyKind.CRISIS
    reply = session.turn("报个警电话多少").reply
    assert 0 <= reply.find("110") < reply.find("12356")


# -- 2: Canada and Australia by their common names ----------------------------------------------


@pytest.mark.parametrize(
    ("text", "place"),
    [
        ("加拿大有什么心理热线", "CA"),
        ("我在加国，有热线吗", "CA"),
        ("我在加國，有熱線嗎", "CA"),
        ("人在温哥华，想找个心理援助电话", "CA"),
        ("溫哥華有沒有心理熱線", "CA"),
        ("多倫多有冇熱線", "CA"),
        ("在满地可有什么求助电话", "CA"),
        ("卡加利有心理热线吗", "CA"),
        ("我在澳洲能打哪个电话", "AU"),
        ("澳大利亞有冇心理熱線", "AU"),
        ("我在悉尼读书，有没有能打的求助电话", "AU"),
        ("墨爾本有心理熱線嗎", "AU"),
        ("我在土澳，有没有心理热线", "AU"),
        ("坎培拉有心理热线吗", "AU"),
        ("布里斯本有心理熱線嗎", "AU"),
    ],
)
def test_canada_and_australia_by_any_common_name(text: str, place: str) -> None:
    signals = _signals(text)
    assert signals.hotline_request, text
    assert signals.hotline_place == place, text


@pytest.mark.parametrize(
    ("text", "place"),
    [
        ("我在参加国际交流项目", None),
        ("参加国庆的活动", None),
        ("加国籍要多久", None),
        ("增加国内的供给", "CN"),
        ("澳门有心理热线吗", "MO"),
        ("我在吃雪梨", None),
    ],
)
def test_words_that_hold_a_place_name_are_not_that_place(text: str, place: str | None) -> None:
    assert _signals(text).hotline_place == place, text


def test_a_place_without_a_question_is_no_request() -> None:
    for text in ("多伦多的冬天好冷", "我在澳洲玩得很开心", "墨尔本的咖啡真好喝"):
        assert not _signals(text).hotline_request, text


def test_a_mainland_user_asking_about_canada_gets_the_canadian_card() -> None:
    result = _open("CN").turn("加拿大有什么心理热线")
    assert result.reply_kind is ReplyKind.RESOURCES
    assert result.reply.startswith(DATA.render.hotline_other_region[0])
    assert "988" in result.reply
    assert "12356" not in result.reply


def test_a_canadian_user_naming_canada_is_not_told_they_are_abroad() -> None:
    signals = _signals("加拿大有什么心理热线")
    assert not signals.hotline_abroad
    result = _open("CA").turn("加拿大有什么心理热线")
    assert result.reply_kind is ReplyKind.RESOURCES
    assert DATA.render.hotline_abroad[0] not in result.reply


# -- 3: 安定 only next to stopping it ---------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "安定停了三天",
        "不吃安定以后手抖",
        "安定我自己停了",
        "我把安定断了，这几天睡不着",
        "停了安定以后心慌",
        "安定突然不吃了会怎么样",
        "安定已经减到半片了",
        "上周开始没再吃安定",
        "安定吃了两年，上个月突然不吃了",
        "戒安定好难受",
        "安定这两天没吃",
    ],
)
def test_anding_next_to_stopping_is_a_benzodiazepine_stop(text: str) -> None:
    reading = read_substance(CUES, text, context=False)
    assert reading.stopping, text
    assert reading.withdrawal, text
    assert reading.kind == "benzo", text


@pytest.mark.parametrize(
    "text",
    [
        "最近情绪安定多了",
        "总算安定下来了，不想再折腾",
        "生活安定以后我把兼职停了",
        "工作安定了，不吃外卖了",
        "我在北京安定医院看过病",
        "安定门地铁站停运了",
        "断了安定的生活",
        "局势安定，停火了",
        "内心安定不少",
        "社会安定减少了犯罪",
        "他们家很安定，从不吵架",
        "我想要安定的日子，不想再漂了",
    ],
)
def test_anding_in_everyday_words_is_no_medicine(text: str) -> None:
    for context in (False, True):
        reading = read_substance(CUES, text, context=context)
        assert not reading.stopping, text
        assert reading.kind == "", text


@pytest.mark.parametrize(
    "text",
    [
        "医生让我把安定减到半片",
        "我没停安定，还在吃",
        "不想停安定",
        "不吃安定就睡不着",
        "我从来不吃安定",
    ],
)
def test_anding_kept_taken_or_tapered_by_the_doctor_is_no_stop(text: str) -> None:
    assert not read_substance(CUES, text, context=False).stopping, text


def test_anding_stopped_gets_the_benzodiazepine_reminder() -> None:
    reminder = DATA.utterances.withdrawal_classes["benzo"]
    assert _open().turn("安定停了三天，手一直抖").reply.startswith(reminder)
    assert reminder not in _open().turn("最近情绪安定多了，我把兼职停了").reply


def _with_short_names(short_names: dict[str, list[str]]) -> dict[str, Any]:
    doc: dict[str, Any] = yaml.safe_load(SUBSTANCE.read_text(encoding="utf-8"))
    doc["stopping"]["short_names"] = short_names
    return doc


def test_a_short_name_must_be_of_a_known_class() -> None:
    with pytest.raises(LanguageDataError, match="no_such_class"):
        _parse_substance(_with_short_names({"no_such_class": ["安定停"]}))


def test_a_short_name_pattern_must_compile() -> None:
    with pytest.raises(LanguageDataError, match="short_names.benzo"):
        _parse_substance(_with_short_names({"benzo": ["安定("]}))


def test_a_short_name_pattern_must_not_match_empty_text() -> None:
    with pytest.raises(LanguageDataError, match="matches empty"):
        _parse_substance(_with_short_names({"benzo": ["(?:安定)?"]}))
