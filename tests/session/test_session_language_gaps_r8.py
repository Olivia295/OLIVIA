"""Round 8 language gaps (2026-11-25; drafts pending G-0).

* Someone else stopping a psychiatric medicine on their own (owner's decision of
  2026-11-25): the reply suggests contacting the prescribing doctor or a pharmacist soon,
  says a sudden stop may bring reactions, and neither urges stopping nor taking it
  (``substance.withdrawal_classes.others_psychiatric``). The user's own stop keeps its
  reminder, and someone else's non-psychiatric medicine keeps the general line.
* A drink asked for without 喝 ("就一小杯行不行", "来一口没事吧") is a drink asked for when
  alcohol was spoken of this turn or the turn before (酒, 啤酒, 白酒, 红酒, 喝两杯): in the
  crisis flow it gets ``substance.ask_to_drink_crisis``, outside it ``ask_to_drink``. An
  amount of something else ("一小杯奶茶", "一口饭"), eating or smoking ("吃一口", "抽一口"),
  or alcohol spoken of only earlier is none.

Every example message is written here; none comes from an evaluation set or a re-test
report.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest

from olivia.core.language.data import load_language_data
from olivia.core.models import PersonaProfile, UserRegion
from olivia.core.session import Session
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
NOW = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)
DATA = load_language_data(TAX)
SAID = DATA.utterances
CLASSES = SAID.withdrawal_classes
REMINDERS = (
    SAID.substance_lines["withdrawal"],
    SAID.substance_lines["withdrawal_severe"],
    *CLASSES.values(),
)
CRISIS_OPENER = "我真的撑不下去了，不想活了"


def _open(seed: int = 7) -> Session:
    profile = PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        user_name="小禾",
        region=UserRegion("CN", "Asia/Shanghai"),
    )
    return Session.open(TAX, profile, rng=random.Random(seed), now=lambda: NOW)


# -- 1: someone else stopped a psychiatric medicine -------------------------------------------

OTHERS_LINE = CLASSES.get("others_psychiatric", "")

OTHERS_STOPPED = [
    "我妈自己把抗抑郁药停了",
    "我室友说她的抗抑郁药已经停了",
    "我爸最近偷偷把安眠药断了",
    "我姐把抗焦虑的药一下子全停了",
    "我男朋友自己把精神科的药停掉了",
    "我老公说他不想吃情绪稳定剂了，已经停了",
    "她把喹硫平停了好几天了",
]


def test_the_others_line_is_a_plain_drafted_line() -> None:
    assert OTHERS_LINE, "substance.withdrawal_classes.others_psychiatric is missing"
    assert not any(ch.isdigit() for ch in OTHERS_LINE)
    assert len(OTHERS_LINE) <= 80
    assert "开药的医生或药师" in OTHERS_LINE and "尽快" in OTHERS_LINE
    assert "反应" in OTHERS_LINE
    # No medicine is named (the ``psychiatric`` class holds only "精神科的药" and the like),
    # and it neither urges stopping nor taking it.
    medicine_names = {
        w for name, words in DATA.substance.classes.items() if name != "psychiatric" for w in words
    }
    assert not any(w in OTHERS_LINE for w in medicine_names)
    for urging in ("别停", "不要停", "继续吃", "接着吃吧", "停掉吧", "别吃了", "不要吃"):
        assert urging not in OTHERS_LINE


@pytest.mark.parametrize("text", OTHERS_STOPPED)
def test_someone_elses_psychiatric_medicine_stopped_gets_its_line(text: str) -> None:
    reply = _open().turn(text).reply
    assert OTHERS_LINE in reply, reply
    assert not any(line in reply for line in REMINDERS if line != OTHERS_LINE)


@pytest.mark.parametrize("text", OTHERS_STOPPED[:3])
def test_in_the_crisis_flow_too(text: str) -> None:
    session = _open()
    assert session.turn(CRISIS_OPENER).in_crisis
    reply = session.turn(text).reply
    assert OTHERS_LINE in reply, reply
    assert "12356" in reply


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("我自己把抗抑郁药停了", "antidepressant"),
        ("安眠药我昨天起自己停了", "sleep"),
        ("抗焦虑的药我一下子全停了", "benzo"),
        ("精神科的药我打算明天起不吃了", "psychiatric"),
    ],
)
def test_the_users_own_stop_keeps_its_reminder(text: str, kind: str) -> None:
    reply = _open().turn(text).reply
    assert CLASSES[kind] in reply, reply
    assert OTHERS_LINE not in reply


@pytest.mark.parametrize(
    "text", ["我公公自己把胰岛素停了", "我妈自己把降压药停了", "我爸把止痛药停了"]
)
def test_someone_elses_other_medicine_keeps_the_general_line(text: str) -> None:
    reply = _open().turn(text).reply
    assert CLASSES["general"] in reply, reply
    assert OTHERS_LINE not in reply


@pytest.mark.parametrize("text", ["我妈每天按时吃抗抑郁药", "我爸的安眠药是医生让慢慢减的"])
def test_no_line_without_a_stop(text: str) -> None:
    reply = _open().turn(text).reply
    assert OTHERS_LINE not in reply


# -- 4: a drink asked for without 喝 --------------------------------------------------------------

DRINK_LINE = SAID.substance_lines["ask_to_drink_crisis"]
ASK_LINE = SAID.substance_lines["ask_to_drink"]

BARE_ASKS = [
    ("家里还有半瓶白酒", "就一小杯行不行"),
    ("我想喝两杯", "来一口没事吧"),
    ("柜子里有瓶红酒", "就两口，应该没关系吧"),
    ("好想喝几杯", "一小杯总行吧"),
    ("我这周在戒酒", "就一小杯行不行"),
    ("想小酌一下", "半杯可以吗"),
    ("", "冰箱里有啤酒，就一小罐可以吗"),
]


@pytest.mark.parametrize(("before", "text"), BARE_ASKS)
def test_a_drink_asked_for_without_drinking_in_the_crisis(before: str, text: str) -> None:
    session = _open()
    assert session.turn(CRISIS_OPENER).in_crisis
    if before:
        session.turn(before)
    result = session.turn(text)
    assert result.in_crisis
    assert DRINK_LINE in result.reply, result.reply
    assert "12356" in result.reply


@pytest.mark.parametrize(("before", "text"), BARE_ASKS[:3])
def test_a_drink_asked_for_without_drinking_outside_the_crisis(before: str, text: str) -> None:
    session = _open()
    session.turn(before)
    result = session.turn(text)
    assert not result.in_crisis
    assert ASK_LINE in result.reply, result.reply


@pytest.mark.parametrize(
    ("before", "text"),
    [
        ("家里还有半瓶白酒", "一小杯奶茶行不行"),
        ("我想喝两杯", "来一口饭没事吧"),
        ("柜子里有瓶红酒", "吃一口蛋糕可以吗"),
        ("家里还有半瓶白酒", "就一小杯热水行不行"),
        ("我想喝两杯", "我能不能抽一口烟"),
        ("好想喝几杯", "一口气睡到天亮行不行"),
        ("家里还有半瓶白酒", "我一口都不碰了，可以吗"),
        ("好想喝几杯", "一口答应他行不行"),
        ("楼下奶茶店还开着", "就一小杯行不行"),
        ("酒店楼下有家奶茶店", "就一小杯行不行"),
        ("我想喝一杯热牛奶", "来一口没事吧"),
    ],
)
def test_no_drink_asked_for_without_drinking_in_the_crisis(before: str, text: str) -> None:
    session = _open()
    assert session.turn(CRISIS_OPENER).in_crisis
    session.turn(before)
    result = session.turn(text)
    assert DRINK_LINE not in result.reply, result.reply


def test_alcohol_said_only_earlier_is_not_enough() -> None:
    session = _open()
    assert session.turn(CRISIS_OPENER).in_crisis
    session.turn("我想喝两杯")
    session.turn("身边没有别人")
    result = session.turn("就一小杯行不行")
    assert DRINK_LINE not in result.reply, result.reply
