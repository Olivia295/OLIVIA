"""Round 8 language gaps (2026-11-25; drafts pending G-0), read by the language layer.

* Someone else stopping a psychiatric medicine is its own kind (``others_psychiatric``,
  owner's decision of 2026-11-25); someone else's other medicine stays ``general`` and the
  user's own stop keeps the class it names. The psychiatric classes are data
  (``substance.yaml`` ``stopping.others_classes``) and must be known classes.
* A drink asked for without 喝 ("就一小杯行不行", "来一口没事吧") asks to drink when this
  message or the turn before (``recent``) spoke of alcohol, never otherwise; an amount of
  something else, eating or smoking, or saying no ("一口都不碰") is none, for the amounts
  of ``drinking`` too. The engine moves "the turn before" on with each ``note_risk``.

Every example message is written here; none comes from an evaluation set or a re-test
report.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

import pytest
import yaml

from olivia.core.language.data import LanguageDataError, _parse_substance, load_language_data
from olivia.core.language.engine import LanguageEngine
from olivia.core.language.guard import read_substance
from olivia.core.models import CrisisLevel
from olivia.core.safety.lexicon import load_safety_lexicons
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
DATA = load_language_data(TAX)
LEX = load_safety_lexicons(TAX)
CUES = DATA.substance
SUBSTANCE = Path(__file__).resolve().parents[2] / "olivia" / "data" / "lexicons" / "substance.yaml"


def _doc() -> dict[str, Any]:
    doc: dict[str, Any] = yaml.safe_load(SUBSTANCE.read_text(encoding="utf-8"))
    return doc


# -- 1: someone else's psychiatric medicine ---------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "我妈自己把抗抑郁药停了",
        "我爸最近偷偷把安眠药断了",
        "我哥把医生开的抗焦虑药全停了",
        "我女朋友说她不想吃精神科的药了，已经停了",
        "她自己把喹硫平停掉了",
    ],
)
def test_someone_elses_psychiatric_medicine_is_its_own_kind(text: str) -> None:
    reading = read_substance(CUES, text, context=False)
    assert reading.stopping and reading.withdrawal, text
    assert reading.kind == "others_psychiatric", text


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("我妈自己把降压药停了", "general"),
        ("我爸把止痛药停了", "general"),
        ("我自己把抗抑郁药停了", "antidepressant"),
        ("安眠药我昨天起自己停了", "sleep"),
        ("我把药停了", ""),
    ],
)
def test_other_kinds_are_unchanged(text: str, kind: str) -> None:
    assert read_substance(CUES, text, context=False).kind == kind


def test_the_psychiatric_classes_are_known_classes() -> None:
    assert CUES.stop_others_classes
    assert CUES.stop_others_classes <= CUES.classes.keys()
    assert "other_medicine" not in CUES.stop_others_classes
    assert "painkiller" not in CUES.stop_others_classes
    assert "others_psychiatric" in DATA.utterances.withdrawal_classes


def test_an_unknown_psychiatric_class_is_refused() -> None:
    doc = _doc()
    doc["stopping"]["others_classes"] = ["antidepressant", "no_such_class"]
    with pytest.raises(LanguageDataError, match="no_such_class"):
        _parse_substance(doc)


def test_the_psychiatric_classes_are_optional() -> None:
    doc = _doc()
    del doc["stopping"]["others_classes"]
    cues = _parse_substance(doc)
    assert cues.stop_others_classes == frozenset()
    assert read_substance(cues, "我妈自己把抗抑郁药停了", context=False).kind == "general"


# -- 4: a drink asked for without 喝 --------------------------------------------------------------

BARE_ASKS = [
    "就一小杯行不行",
    "来一口没事吧",
    "就两口，应该没关系吧",
    "一小杯总行吧",
    "半杯可以吗",
    "再来一小罐好不好",
]


@pytest.mark.parametrize("text", BARE_ASKS)
def test_a_bare_amount_asked_for_after_alcohol_asks_to_drink(text: str) -> None:
    reading = read_substance(CUES, text, context=False, recent=True)
    assert reading.asks_to_drink and reading.talks, text
    assert not reading.craving


@pytest.mark.parametrize("text", ["就一小杯行不行", "半杯可以吗", "就两口，应该没关系吧"])
def test_without_alcohol_spoken_of_it_asks_nothing(text: str) -> None:
    assert not read_substance(CUES, text, context=False).asks_to_drink
    # A drinking context from earlier in the session is not enough for an amount alone.
    assert not read_substance(CUES, text, context=True).asks_to_drink


@pytest.mark.parametrize(
    "text",
    ["冰箱里有啤酒，就一小罐可以吗", "家里有白酒，就一小杯行不行", "红酒就两口，没事吧"],
)
def test_alcohol_in_the_same_message_is_enough(text: str) -> None:
    reading = read_substance(CUES, text, context=False)
    assert reading.alcohol and reading.asks_to_drink, text


@pytest.mark.parametrize(
    "text",
    [
        "一小杯奶茶行不行",
        "来一口饭没事吧",
        "吃一口蛋糕可以吗",
        "就一小杯热水行不行",
        "我能不能抽一口烟",
        "一口气睡到天亮行不行",
        "我一口都不碰了，可以吗",
        "一口答应他行不行",
        "来一口面没事吧",
        "松一口气可以吗",
        "不来一口也行吧",
    ],
)
def test_other_amounts_ask_nothing(text: str) -> None:
    for context in (False, True):
        assert not read_substance(CUES, text, context=context, recent=True).asks_to_drink, text


@pytest.mark.parametrize(
    ("text", "alcohol"),
    [
        ("家里还有半瓶白酒", True),
        ("我想喝两杯", True),
        ("昨晚喝了几杯", True),
        ("想小酌一下", True),
        ("同学聚会大家一起干杯", True),
        ("冰箱里有啤酒", True),
        ("我想喝一杯热牛奶", False),
        ("喝两口水", False),
        ("酒店楼下有家奶茶店", False),
        ("笑起来有两个酒窝", False),
        ("今天上班好累", False),
    ],
)
def test_what_speaks_of_alcohol(text: str, alcohol: bool) -> None:
    assert read_substance(CUES, text, context=False).alcohol is alcohol


def test_the_amounts_in_drinking_stay_asks_in_context() -> None:
    for text in ("就来一杯，应该没事吧？", "喝一点行不行", "来一口没事吧"):
        assert read_substance(CUES, text, context=True).asks_to_drink, text


@pytest.mark.parametrize(
    "text", ["第一口下去，整个人都放松了", "一杯下去整个人都舒坦了", "冰啤酒下肚太爽了"]
)
def test_relishing_a_drink_is_still_a_craving(text: str) -> None:
    reading = read_substance(CUES, text, context=True)
    assert reading.craving and not reading.asks_to_drink, text


def test_the_engine_counts_only_this_turn_and_the_one_before() -> None:
    engine = LanguageEngine(TAX, rng=random.Random(3), data=DATA, lexicons=LEX)
    engine.note_risk(CrisisLevel.L0)
    assert not engine.substance("就一小杯行不行").asks_to_drink
    engine.note_risk(CrisisLevel.L0)
    engine.substance("我想喝两杯")
    engine.note_risk(CrisisLevel.L0)
    assert engine.substance("就一小杯行不行").asks_to_drink
    # Read again on the same turn, the answer is the same.
    assert engine.substance("就一小杯行不行").asks_to_drink
    engine.note_risk(CrisisLevel.L0)
    assert not engine.substance("半杯可以吗").asks_to_drink


def test_without_bare_drinks_nothing_is_read_without_drinking() -> None:
    doc = _doc()
    del doc["bare_drinks"]
    cues = _parse_substance(doc)
    assert cues.bare_amounts == () and cues.bare_alcohol == ()
    assert not read_substance(cues, "就一小杯行不行", context=False, recent=True).asks_to_drink


def test_bare_drinks_must_have_every_list() -> None:
    doc = _doc()
    del doc["bare_drinks"]["refusals"]
    with pytest.raises(LanguageDataError, match="refusals"):
        _parse_substance(doc)
