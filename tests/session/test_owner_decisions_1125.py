"""负责人 2026-11-25 决定 (regional cards; new wording 草稿：待 G-0):

* A: the L2 crisis card of Hong Kong, Macau, Taiwan, the US, Canada, Great Britain and
  Australia lists one local emergency number after its hotlines, as the mainland card
  lists 120 (HK 999, MO 999 without 110 / 112, TW 119 without 110, US 911, CA 911, GB 999,
  AU 000); Taiwan's L3 card lists 119 before 110.
* B: after the user said in the chat where they are now ("我在多伦多"), the session's crisis
  cards (the crisis reply, the D3 question's card, the crisis farewell, a calm waiting
  turn's line) list that region's numbers first and the profile region's after them; a
  country only ``crisis.local_emergency`` lists gets that line first. The latest place
  counts; the past, the future, a condition and someone else's place change nothing;
  the place is never written. 12356, 120 and 12355 show outside a CN profile only after
  the user named mainland China as where they are now (GEO-03 / R8).

Every example message is written here; none comes from an evaluation set. Crisis messages
state a wish, a plan or a time, never how.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest

from olivia.core.language.data import load_language_data
from olivia.core.models import CrisisLevel, PersonaProfile, UserRegion
from olivia.core.session import ReplyKind, Session
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
NOW = datetime(2026, 11, 25, 15, 0, tzinfo=UTC)
RENDER = load_language_data(TAX).render
WISH = "我真的不想活了"
PLAN = "我写了一封遗书，今晚就走"
ASK = "有没有最快的办法离开"
MAINLAND_ONLY = ("12356", "120", "12355")

# Owner decision 2026-11-25 A: (the region's L2 lines in order, the number after them).
L2_CARDS = {
    "CN": (["12356"], "120"),
    "HK": (["18111", "2389 2222", "2382 0000"], "999"),
    "MO": (["2852 5222", "2871 2356"], "999"),
    "TW": (["1925", "1995", "1980"], "119"),
    "US": (["988", "741741"], "911"),
    "CA": (["988", "686868"], "911"),
    "GB": (["116 123", "111", "85258"], "999"),
    "AU": (["13 11 14", "0477 13 11 14", "1300 22 4636"], "000"),
}


def _open(region: str = "CN", seed: int = 5) -> Session:
    profile = PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        user_name="小禾",
        region=UserRegion(region, "UTC"),
    )
    return Session.open(TAX, profile, rng=random.Random(seed), now=lambda: NOW)


def _order(reply: str, numbers: list[str]) -> list[int]:
    positions = [reply.index(n) for n in numbers]
    assert positions == sorted(positions), (numbers, reply)
    return positions


# -- A ----------------------------------------------------------------------------------


@pytest.mark.parametrize("region", sorted(L2_CARDS))
def test_every_l2_crisis_reply_lists_the_local_emergency_number_after_its_lines(
    region: str,
) -> None:
    result = _open(region).turn(WISH)
    assert result.reply_kind is ReplyKind.CRISIS and result.crisis_level is CrisisLevel.L2
    lines, emergency = L2_CARDS[region]
    reply = result.reply
    _order(reply, [*lines, emergency])
    heading = RENDER.crisis_emergency_heading[CrisisLevel.L2]
    assert reply.index(heading) > reply.index(lines[-1])
    card = result.resource_card
    assert card is not None and [e.number for e in card.emergency] == [emergency]
    assert card.emergency_leads is False and card.here is None


def test_macau_and_taiwan_l2_list_one_number_only() -> None:
    macau = _open("MO").turn(WISH).reply
    assert "999" in macau and "110" not in macau and "112" not in macau
    taiwan = _open("TW").turn(WISH).reply
    assert "119" in taiwan and "110" not in taiwan


def test_taiwan_l3_lists_119_before_110() -> None:
    result = _open("TW").turn(PLAN)
    assert result.crisis_level is CrisisLevel.L3
    _order(result.reply, ["119", "110", "1925"])


@pytest.mark.parametrize("region", [r for r in sorted(L2_CARDS) if r != "CN"])
def test_no_l2_card_outside_the_mainland_shows_a_mainland_number(region: str) -> None:
    reply = _open(region).turn(WISH).reply
    for number in ("12356", "12355", "120"):
        assert number not in reply, (region, number)


# -- B: the card follows where the user is ------------------------------------------------


def test_a_place_said_earlier_leads_the_crisis_card() -> None:
    session = _open("CN")
    assert session.turn("我在多伦多读书，这边冬天好冷").reply_kind is not ReplyKind.CRISIS
    result = session.turn(WISH)
    assert result.reply_kind is ReplyKind.CRISIS
    reply = result.reply
    _order(
        reply, [RENDER.here_heading, "988", "686868", "911", RENDER.home_heading, "12356", "120"]
    )
    assert not reply.startswith(RENDER.crisis_minimal)
    card = result.resource_card
    assert card is not None and card.region_used == "CN"
    assert card.here is not None and card.here.region_used == "CA"
    assert card.numbers() == ("911", "988", "686868", "120", "12356")


def test_an_english_place_leads_the_l3_card_and_asks_for_someone_close_once() -> None:
    session = _open("CN")
    session.turn("I'm in Sydney now, it's late here")
    result = session.turn(PLAN)
    assert result.crisis_level is CrisisLevel.L3
    reply = result.reply
    _order(reply, ["000", "13 11 14", RENDER.home_heading, "110", "120", "12356"])
    assert reply.count(RENDER.crisis_contact_people) == 1
    assert reply.index(RENDER.crisis_contact_people) < reply.index(RENDER.home_heading)


def test_the_place_in_the_crisis_message_itself_counts() -> None:
    result = _open("HK").turn("我在伦敦一个人住，最近每天都想死")
    assert result.reply_kind is ReplyKind.CRISIS
    _order(result.reply, ["116 123", "111", "85258", "999", "18111"])


def test_the_d3_question_lists_the_place_first() -> None:
    session = _open("CN")
    session.turn("我现在人在温哥华")
    result = session.turn(ASK)
    assert result.reply_kind is ReplyKind.SAFETY_CHECK
    _order(result.reply, ["988", "911", "12356"])


def test_the_crisis_farewell_lists_the_place_first() -> None:
    session = _open("US")
    session.turn("我现在在香港")
    assert session.turn(WISH).in_crisis
    goodbye = session.farewell()
    assert goodbye is not None
    _order(goodbye.text, ["18111", "999", RENDER.home_heading, "988", "911"])


def test_a_calm_waiting_turn_lists_the_place_first() -> None:
    session = _open("CN")
    session.turn("我在墨尔本")
    assert session.turn(WISH).in_crisis
    assert session.turn("我现在是安全的").in_crisis
    result = session.turn("今天下午去超市买了点水果")
    assert result.reply_kind is ReplyKind.CRISIS
    _order(result.reply, ["13 11 14", "000", "12356", "120"])


def test_a_country_with_only_official_emergency_numbers_leads_with_that_line() -> None:
    session = _open("HK")
    session.turn("我现在在东京读研")
    result = session.turn(WISH)
    reply = result.reply
    line = f"{RENDER.hotline_local_emergency_intro}{RENDER.local_emergency['JP']}"
    assert line in reply
    _order(reply, [line, RENDER.home_heading, "18111", "999"])
    assert not reply.startswith(RENDER.crisis_minimal)
    card = result.resource_card
    assert card is not None and card.here is None and card.here_numbers == ("110", "119")


def test_the_latest_place_counts() -> None:
    session = _open("CN")
    session.turn("我在多伦多")
    session.turn("我现在人在悉尼了")
    reply = session.turn(WISH).reply
    assert "13 11 14" in reply and "686868" not in reply
    _order(reply, ["13 11 14", "000", "12356"])


def test_a_place_without_verified_numbers_replaces_an_earlier_one() -> None:
    session = _open("CN")
    session.turn("我在多伦多")
    session.turn("我现在在泰国")
    result = session.turn(WISH)
    assert "686868" not in result.reply and RENDER.here_heading not in result.reply
    assert result.resource_card is not None and result.resource_card.here is None


def test_back_in_the_profile_region_the_card_is_the_regions_own() -> None:
    session = _open("CN")
    session.turn("我在多伦多")
    session.turn("我现在在大陆了")
    result = session.turn(WISH)
    assert "988" not in result.reply and RENDER.home_heading not in result.reply


@pytest.mark.parametrize(
    "said",
    [
        "我以前在多伦多读书",
        "下个月去悉尼",
        "我朋友在伦敦",
        "如果我在美国就好了",
        "我在东京读书的时候特别孤单",
        "I was in Toronto last year",
        "我妈现在在温哥华",
        "我在美国公司上班",
    ],
)
def test_the_past_the_future_or_someone_elses_place_changes_nothing(said: str) -> None:
    session = _open("CN")
    session.turn(said)
    result = session.turn(WISH)
    plain = _open("CN").turn(WISH)
    assert result.resource_card is not None and result.resource_card.here is None
    assert result.resource_card.here_note == ""
    assert result.resource_card == plain.resource_card


def test_a_place_in_the_profiles_region_adds_nothing() -> None:
    session = _open("AU")
    session.turn("我在墨尔本")
    result = session.turn(WISH)
    assert result.resource_card is not None and result.resource_card.here is None
    assert RENDER.here_heading not in result.reply


def test_the_place_is_kept_for_this_session_only() -> None:
    session = _open("CN")
    session.turn("我在多伦多")
    assert "CA" not in str(session.snapshot())
    later = _open("CN").turn(WISH)
    assert later.resource_card is not None and later.resource_card.here is None


def test_a_later_hotline_request_still_names_the_said_place() -> None:
    session = _open("CN")
    session.turn("我现在人在蒙特利尔")
    reply = session.turn("有没有求助热线").reply
    assert reply.startswith(RENDER.hotline_other_region[0])
    assert "12356" not in reply


# -- B and GEO-03 / R8 -------------------------------------------------------------------


@pytest.mark.parametrize("region", ["HK", "MO", "TW", "US", "CA", "GB", "AU", "ZZ"])
def test_mainland_numbers_show_outside_cn_only_after_naming_the_mainland(region: str) -> None:
    session = _open(region)
    session.turn("我现在在大陆，回来看家人")
    reply = session.turn(WISH).reply
    assert "12356" in reply and "120" in reply
    assert reply.index("12356") < reply.index(RENDER.home_heading)


@pytest.mark.parametrize(
    "said",
    [
        "我现在在国内",
        "跟国内有时差，好久没跟家里人说话了",
        "给我大陆的心理热线，我只信那个",
        "我以前在大陆读书",
        "如果我在内地就好了",
        "我朋友在大陆",
    ],
)
@pytest.mark.parametrize("region", ["HK", "TW", "US"])
def test_no_mainland_number_without_saying_one_is_there_now(region: str, said: str) -> None:
    """The crisis card that follows; an explicit request for another region's numbers
    outside a crisis ("给我大陆的心理热线") is round 3's, not this decision's."""
    session = _open(region)
    session.turn(said)
    result = session.turn(WISH)
    assert result.reply_kind is ReplyKind.CRISIS
    assert result.resource_card is not None and result.resource_card.here is None
    for number in MAINLAND_ONLY:
        assert number not in result.reply, (region, said, number)
