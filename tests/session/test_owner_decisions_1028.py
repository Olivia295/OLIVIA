"""Owner decisions 2026-10-28.

1. The mainland (CN) L2 crisis card also lists the ambulance number 120 (never 110), after
   12356 and the other lines, with the L2 card's gentler emergency heading; the number
   comes from CN's ``ambulance`` entry in the signed hotline data. Other regions are as
   before.
2. A crisis alarm only the model raises asks first by its score alone: below 0.6 it asks
   (also when its class is L3), at 0.6 or above it enters the crisis flow. A model L3 keeps
   its emergency numbers in front of the card on the question turn, and the crisis that
   follows the answer is framed the same way.
3. The "X得 / 到想死" figure of speech ("烦得想死", "加班加到想死", "激到我想死", "气得想死") is
   L1 with the D3 question instead of L2, unless the same message or the session holds any
   other risk cue (``tests/safety/test_hyperbole_ask.py`` has the screen's side).

Example messages are written here; none is taken from an evaluation set.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest

from olivia.core.chang.safety_plan import Contact, SafetyPlan
from olivia.core.language.engine import load_language_data
from olivia.core.models import CrisisLevel, HelpStage, PersonaProfile, UserRegion
from olivia.core.safety.crisis import RiskPrediction
from olivia.core.safety.lexicon import load_safety_lexicons
from olivia.core.session import ReplyKind, Session, TurnResult
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
NOW = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)
RENDER = load_language_data(TAX).render
L2_HEADING = RENDER.crisis_emergency_heading[CrisisLevel.L2]
L3_HEADING = RENDER.crisis_emergency_heading[CrisisLevel.L3]
QUESTION_MARKERS = ("结束自己的生命", "结束自己生命")
TRIP = "下周还要出差，想想就头大"
CALM = "今天去公园走了走"


class Scripted:
    """A risk model that rates the listed messages and everything else L0."""

    def __init__(self, levels: dict[str, tuple[CrisisLevel, float]]) -> None:
        self.levels = levels

    def predict(self, text: str) -> RiskPrediction:
        level, score = self.levels.get(text, (CrisisLevel.L0, 0.05))
        return RiskPrediction(level, score, ())


def _profile(region: str = "CN") -> PersonaProfile:
    return PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        user_name="小林",
        region=UserRegion(region, "Asia/Shanghai"),
    )


def _open(
    levels: dict[str, tuple[CrisisLevel, float]] | None = None,
    *,
    region: str = "CN",
    **kwargs: object,
) -> Session:
    model = None if levels is None else Scripted(levels)
    return Session.open(
        TAX, _profile(region), rng=random.Random(5), now=lambda: NOW, model=model, **kwargs
    )  # type: ignore[arg-type]


def _assert_crisis(result: TurnResult) -> None:
    assert result.reply_kind is ReplyKind.CRISIS and result.stage is HelpStage.S_CRISIS
    assert result.in_crisis and result.crisis_level >= CrisisLevel.L2


def _assert_asked(result: TurnResult) -> None:
    assert result.reply_kind is ReplyKind.SAFETY_CHECK
    assert result.inspect["safety_check"] == "asked"
    assert any(marker in result.reply for marker in QUESTION_MARKERS), result.reply
    assert not result.in_crisis and result.stage is not HelpStage.S_CRISIS


def _gentle_120(reply: str) -> None:
    """12356 first, then 120 under the L2 heading; no 110 and no L3 framing."""
    assert "12356" in reply and "120" in reply
    assert reply.index("12356") < reply.index(L2_HEADING) < reply.index("120")
    assert "110" not in reply and L3_HEADING not in reply


def _urgent(reply: str) -> None:
    """110 and 120 under the L3 heading, before 12356."""
    assert reply.index(L3_HEADING) < reply.index("110") < reply.index("12356")
    assert reply.index("120") < reply.index("12356")


# -- 1. the mainland L2 card lists 120 ------------------------------------------------------------


def test_the_l2_crisis_reply_lists_120_after_12356():
    result = _open().turn("我不想活了")
    _assert_crisis(result)
    _gentle_120(result.reply)


def test_every_l2_crisis_turn_keeps_the_120_line():
    session = _open()
    session.turn("我不想活了")
    _gentle_120(session.turn("还是很难受").reply)


def test_the_d3_question_lists_120_after_12356():
    result = _open().turn("有没有最快的办法离开")
    _assert_asked(result)
    _gentle_120(result.reply)


def test_an_l3_crisis_is_unchanged():
    result = _open().turn("我决定了 今晚就去死")
    _assert_crisis(result)
    assert result.crisis_level is CrisisLevel.L3
    _urgent(result.reply)


def test_a_capped_model_l3_still_frames_the_l2_card_as_urgent():
    """The 2026-10-24 rule (a model L3 under the L3 switch): the region's emergency numbers,
    110 included, lead the L2 card. The new 120 on the card does not switch it off."""
    result = _open({"我不想活了": (CrisisLevel.L3, 0.9)}).turn("我不想活了")
    _assert_crisis(result)
    _urgent(result.reply)
    assert result.reply.count("120") == 1


def test_the_safety_plan_still_comes_before_the_l2_card():
    plan = SafetyPlan(people=(Contact("阿青", "138-0000-0000"),))
    reply = _open(safety_plan=plan).turn("我不想活了").reply
    assert reply.index("阿青") < reply.index("12356") < reply.index("120")


def test_the_farewell_lists_120_after_12356():
    session = _open()
    session.turn("我不想活了")
    farewell = session.farewell()
    assert farewell is not None
    _gentle_120(farewell.text)


def test_a_minor_still_gets_the_emergency_numbers_first():
    session = _open()
    session.turn("其实我才14岁")
    reply = session.turn("今天好累").reply
    assert reply.index("110") < reply.index("12355")
    assert reply.index("120") < reply.index("12355")


@pytest.mark.parametrize(("region", "emergency"), [("HK", "999"), ("US", "911"), ("GB", "999")])
def test_other_regions_l2_cards_are_unchanged(region, emergency):
    result = _open(region=region).turn("我不想活了")
    _assert_crisis(result)
    assert emergency not in result.reply
    assert "120" not in result.reply and "12356" not in result.reply


# -- 2. a model-only alarm asks first by its score alone ------------------------------------------


@pytest.mark.parametrize("score", [0.3, 0.52, 0.59])
def test_a_model_only_l3_class_below_0_6_asks_first_with_the_emergency_numbers(score):
    result = _open({TRIP: (CrisisLevel.L3, score)}).turn(TRIP)
    _assert_asked(result)
    assert result.inspect["safety_check_by"] == "model"
    _urgent(result.reply)


@pytest.mark.parametrize("score", [0.6, 0.85])
def test_a_model_only_l3_class_at_0_6_or_above_enters_the_crisis_flow(score):
    result = _open({TRIP: (CrisisLevel.L3, score)}).turn(TRIP)
    _assert_crisis(result)
    assert result.inspect["safety_check"] is None
    _urgent(result.reply)


def test_a_model_only_l2_class_below_0_6_still_asks_without_urgency():
    result = _open({TRIP: (CrisisLevel.L2, 0.55)}).turn(TRIP)
    _assert_asked(result)
    _gentle_120(result.reply)


@pytest.mark.parametrize("answer", ["嗯", "我也说不清", ""])
def test_the_crisis_after_a_model_l3_question_keeps_the_emergency_numbers_first(answer):
    session = _open({TRIP: (CrisisLevel.L3, 0.5)})
    session.turn(TRIP)
    result = session.turn(answer)
    _assert_crisis(result)
    _urgent(result.reply)
    _urgent(session.turn("还是那样").reply)


def test_a_clear_no_to_a_model_l3_question_stays_in_ordinary_talk():
    session = _open({TRIP: (CrisisLevel.L3, 0.5)})
    session.turn(TRIP)
    result = session.turn("不是")
    assert not result.in_crisis and result.inspect["safety_check"] == "denied"
    assert session.snapshot()["gentle_care"] is False


def test_the_ask_line_reads_only_the_score():
    rules = load_safety_lexicons(TAX).model_ask
    assert rules.asks_first(0.59) and not rules.asks_first(0.6)


def test_the_pause_after_a_confirmation_still_treats_an_l3_class_as_a_relapse():
    """The 2026-10-27 pause is for an unsure model L2 after a confirmation; decision 2 is
    about the first alarm, so an L3 class in the crisis flow still voids a confirmation."""
    rules = load_safety_lexicons(TAX).model_ask
    assert rules.pauses(CrisisLevel.L2, 0.5)
    assert not rules.pauses(CrisisLevel.L3, 0.5)
    assert not rules.pauses(CrisisLevel.L2, 0.6)


# -- 3. "X得 / 到想死" asks first ----------------------------------------------------------------

OWNER_EXAMPLES = ["烦得想死", "这个月加班加到想死", "激到我想死", "气得想死"]


@pytest.mark.parametrize("text", OWNER_EXAMPLES)
def test_the_figure_of_speech_asks_the_d3_question(text):
    result = _open().turn(text)
    _assert_asked(result)
    assert result.crisis_level is CrisisLevel.L1
    assert "safety_check_by" not in result.inspect
    _gentle_120(result.reply)


@pytest.mark.parametrize("text", OWNER_EXAMPLES)
@pytest.mark.parametrize(
    "rating", [(CrisisLevel.L2, 0.55), (CrisisLevel.L2, 0.75), (CrisisLevel.L3, 0.9)]
)
def test_in_model_mode_the_figure_of_speech_asks_too(text, rating):
    result = _open({text: rating}).turn(text)
    _assert_asked(result)


def test_a_model_failure_on_the_figure_of_speech_enters_the_crisis_flow():
    class Broken:
        def predict(self, text: str) -> RiskPrediction:
            raise RuntimeError("boom")

    session = Session.open(TAX, _profile(), rng=random.Random(5), now=lambda: NOW, model=Broken())
    _assert_crisis(session.turn("烦得想死"))


@pytest.mark.parametrize(
    "text",
    [
        "烦得想死 真的不想活了",  # cases.yaml d40
        "烦得想死 是真的想死那种",  # d41
        "加班加到想死 不是开玩笑",  # d43
        "气得想死，药都攒够了",
    ],
)
def test_the_figure_of_speech_with_a_real_cue_enters_the_crisis_flow(text):
    _assert_crisis(_open().turn(text))


@pytest.mark.parametrize("answer", ["嗯", "有一点", "随便吧", ""])
def test_anything_but_a_clear_no_enters_the_crisis_flow(answer):
    session = _open()
    session.turn("烦得想死")
    result = session.turn(answer)
    _assert_crisis(result)


def test_a_clear_no_stays_in_ordinary_talk_with_the_d3_care_flag():
    session = _open()
    session.turn("烦得想死")
    result = session.turn("不是，就是被老板气到了")
    assert not result.in_crisis and result.inspect["safety_check"] == "denied"
    assert session.snapshot()["gentle_care"] is True


@pytest.mark.parametrize("earlier", ["活着好累", "有没有最快的办法离开"])
def test_after_an_earlier_risk_cue_in_the_session_it_enters_the_crisis_flow(earlier):
    session = _open()
    session.turn(earlier)
    session.turn("不是，我就是想辞职")
    session.turn(CALM)
    result = session.turn("烦得想死")
    _assert_crisis(result)


def test_after_an_earlier_crisis_in_the_session_it_enters_the_crisis_flow():
    session = _open()
    session.turn("我不想活了")
    for text in ("我现在是安全的", CALM, "去楼下买了杯奶茶"):
        session.turn(text)
    assert session.snapshot()["in_crisis"] is False
    _assert_crisis(session.turn("烦得想死"))


def test_a_second_figure_of_speech_after_a_no_asks_again():
    """The figure of speech itself is not "another" risk cue: after a clear no the next
    one asks again instead of entering the crisis flow."""
    session = _open()
    session.turn("烦得想死")
    session.turn("不是，就是吐槽一下")
    session.turn(CALM)
    _assert_asked(session.turn("加班加到想死"))
