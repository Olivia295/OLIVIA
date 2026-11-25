"""Where the user says they are now (owner decision 2026-11-25 B; ``perception/location.py``).

The user's own place now, by grammar: the user is the subject, only fillers stand between
the subject and the verb, the place follows the verb, and nothing around it speaks of the
past, the future, a condition, a wish or someone else. The places are the lexicon's
``hotline_places`` and ``local_emergency_places``; "国内" never names mainland China.

Every example message is written here; none comes from an evaluation set.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from olivia.core.models import CrisisLevel
from olivia.core.perception.lexicon import PerceptionLexiconError, load_perception_lexicon
from olivia.core.perception.location import PresentPlaceReader, SaidPlace
from olivia.core.perception.rule_stub import RuleStub
from olivia.core.safety.crisis import CrisisAssessment
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
LEXICON = load_perception_lexicon(TAX)
READER = PresentPlaceReader(LEXICON)
STUB = RuleStub(TAX, LEXICON)
CALM = CrisisAssessment(CrisisLevel.L0, 0.0, "STAGE2", False, ())
PACKAGED = Path(__file__).resolve().parents[2] / "olivia" / "data" / "lexicons" / "perception.yaml"

# (message, region, country): the user's own place now.
SAID_NOW = [
    ("我在多伦多", "CA", None),
    ("我人在悉尼读书", "AU", None),
    ("我现在在香港", "HK", None),
    ("I'm in Toronto", "CA", None),
    ("我现在人在釜山，一个人住", "ZZ", "KR"),
    ("其实我现在在Toronto，这边已经很晚了", "CA", None),
    ("i am currently in new york", "US", None),
    ("I live in London now", "GB", None),
    ("我住在温哥华", "CA", None),
    ("人在伦敦，刚下飞机", "GB", None),
    ("我之前在多伦多，现在在悉尼", "AU", None),
    ("我刚到墨尔本", "AU", None),
    ("我们现在都在澳门", "MO", None),
    ("我到了台湾", "TW", None),
    ("我在加国读书", "CA", None),
    ("I'm in the US right now", "US", None),
    ("我在大陆读书", "CN", None),
    ("我现在在内地", "CN", None),
    ("我在日本留学", "ZZ", "JP"),
    ("现在我在法国", "ZZ", "FR"),
    ("I'm studying in Melbourne", "AU", None),
    ("我在 Hong Kong 工作", "HK", None),
    ("im in sydney rn", "AU", None),
    ("我現在在多倫多", "CA", None),
    ("我在泰国", "ZZ", None),
    ("我在多伦多，下个月去悉尼", "CA", None),
]

# Not the user's own place now: the past, the future, a condition or wish, someone else, a
# place name that is only an attribute, or "国内".
NOT_NOW = [
    "我以前在多伦多",
    "下个月去悉尼",
    "我朋友在伦敦",
    "如果我在美国",
    "我在东京读书的时候特别孤单",
    "我在多伦多待过两年",
    "要是我现在在多伦多就好了",
    "我妈在悉尼",
    "我在美国公司上班",
    "我在香港路",
    "I was in Toronto",
    "If I'm in Toronto next month",
    "My friend is in London",
    "I'm going to London",
    "When I'm in Toronto I feel lonely",
    "I'll be in Sydney next week",
    "我在国内",
    "跟国内有时差",
    "我只知道他在美国",
    "给我大陆的心理热线，我只信那个",
    "我明年在悉尼读书",
    "我不在多伦多",
    "我打算在温哥华定居",
    "我梦见我在伦敦",
    "他以为我在多伦多",
    "我是在香港出生的",
    "我朋友之前在多伦多，现在在悉尼",
    "下个月我就在悉尼了",
    "我在去多伦多的路上",
    "我在多伦多的朋友说那边冷",
]


@pytest.mark.parametrize(("text", "region", "country"), SAID_NOW)
def test_the_users_own_place_now_is_read(text: str, region: str, country: str | None) -> None:
    assert READER.read(text) == SaidPlace(region, country)


@pytest.mark.parametrize("text", NOT_NOW)
def test_the_past_the_future_a_condition_or_someone_else_is_not(text: str) -> None:
    assert READER.read(text) is None


def test_at_least_ten_of_each() -> None:
    assert len(SAID_NOW) >= 10 and len(NOT_NOW) >= 10


def test_the_last_place_said_in_a_message_counts() -> None:
    assert READER.read("我在多伦多待了一年，现在人在温哥华") == SaidPlace("CA")
    assert READER.read("我住在悉尼，这周我在墨尔本") == SaidPlace("AU")
    assert READER.read("我在香港，不对，我现在在澳门") == SaidPlace("MO")


def test_guonei_never_names_the_mainland() -> None:
    assert "国内" in LEXICON.hotline_places["CN"]
    assert LEXICON.present_place is not None and "国内" in LEXICON.present_place.excluded
    for text in ("我现在在国内", "我人在国内", "我回国内了，现在在国内"):
        assert READER.read(text) is None


def test_the_rule_stub_reports_the_place() -> None:
    signals = STUB.perceive("我在东京读研，最近很累", CALM)[1]
    assert (signals.present_place, signals.present_country) == ("ZZ", "JP")
    assert STUB.perceive("最近很累", CALM)[1].present_place is None
    assert STUB.perceive("/exit", CALM)[1].present_place is None


def _doc() -> dict[str, Any]:
    loaded = yaml.safe_load(PACKAGED.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _load(tmp_path: Path, mutate: Callable[[dict[str, Any]], None]) -> None:
    doc = _doc()
    mutate(doc)
    (tmp_path / "perception.yaml").write_text(
        yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    load_perception_lexicon(TAX, tmp_path)


def test_an_excluded_name_must_be_a_hotline_place(tmp_path: Path) -> None:
    def mutate(doc: dict[str, Any]) -> None:
        doc["present_place"]["excluded"] = ["火星"]

    with pytest.raises(PerceptionLexiconError, match="excluded"):
        _load(tmp_path, mutate)


def test_every_key_of_the_grammar_is_required(tmp_path: Path) -> None:
    def mutate(doc: dict[str, Any]) -> None:
        del doc["present_place"]["not_after"]

    with pytest.raises(PerceptionLexiconError, match="not_after"):
        _load(tmp_path, mutate)


def test_without_the_grammar_nothing_is_read() -> None:
    from dataclasses import replace

    assert PresentPlaceReader(replace(LEXICON, present_place=None)).read("我在多伦多") is None
