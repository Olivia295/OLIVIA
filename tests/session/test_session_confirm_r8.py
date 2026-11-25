"""Rules round 8, task G2b-2 (2026-11-25): the session side.

1. 负责人 2026-11-25 决定: a means "put away" with nothing else of risk ("我不想死，刀我已经收
   好了", a plan candidate) asks once first, the emergency numbers first (an L3 candidate, as
   for a model L3 that asks first, §9.4 第 2 条). A clear no or a safety confirmation that
   passes F10 (§9.4 第 17、26 条) returns to the ordinary chat; a yes, an unclear answer, no
   answer or any other cue enters the crisis flow at L3. With other risk earlier in the
   session (a rule L1 or a D3 cue, or a crisis) it is L3 at once, as before.
2. "不是不想活，就是太累了" answers a direct question (D3 or a model-only alarm's) with a no;
   "不是不想死，就是太累了" (a wish to die) still enters the crisis flow.

Every sentence here was written for this round; none comes from an evaluation set or the
red-team suite.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest

from olivia.core.language.engine import load_language_data
from olivia.core.models import CrisisLevel as L
from olivia.core.models import PersonaProfile, UserRegion
from olivia.core.safety.crisis import RiskPrediction
from olivia.core.session import ReplyKind, Session, TurnResult
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
NOW = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)
RENDER = load_language_data(TAX).render
L3_HEADING = RENDER.crisis_emergency_heading[L.L3]


class Scripted:
    """A risk model that rates the listed messages an unsure L2 and everything else L0."""

    def __init__(self, unsure: dict[str, float]) -> None:
        self.unsure = unsure

    def predict(self, text: str) -> RiskPrediction:
        score = self.unsure.get(text)
        if score is None:
            return RiskPrediction(L.L0, 0.05, ())
        return RiskPrediction(L.L2, score, ())


def _profile(region: str = "CN") -> PersonaProfile:
    return PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        user_name="小禾",
        region=UserRegion(region, "Asia/Shanghai"),
    )


def _session(region: str = "CN") -> Session:
    return Session.open(
        TAX, _profile(region), rng=random.Random(13), now=lambda: NOW, student=False
    )


def _scripted(unsure: dict[str, float]) -> Session:
    return Session.open(
        TAX,
        _profile(),
        rng=random.Random(13),
        now=lambda: NOW,
        model=Scripted(unsure),  # type: ignore[arg-type]
    )


def _urgent(reply: str) -> None:
    """The emergency numbers under the L3 heading, before 12356."""
    assert reply.index(L3_HEADING) < reply.index("110") < reply.index("12356")
    assert reply.index("120") < reply.index("12356")


def _asked(result: TurnResult) -> None:
    assert result.reply_kind is ReplyKind.SAFETY_CHECK
    assert result.inspect["safety_check"] == "asked"
    assert not result.in_crisis


# -- 1. a means put away ---------------------------------------------------------------------

PUT_AWAY = [
    "我不想死，刀我已经收好了",
    "我不会伤害自己的，刀我已经收好了",
    "放心，我不会做傻事，药都收好了",
]


@pytest.mark.parametrize("text", PUT_AWAY)
def test_a_means_put_away_asks_first_with_the_emergency_numbers_first(text: str) -> None:
    result = _session().turn(text)
    _asked(result)
    _urgent(result.reply)
    # The question turn reports the screen's own level: an L3 candidate, only not the
    # crisis flow yet (as a model-only alarm that asks first).
    assert result.crisis_level is L.L3
    assert result.inspect["safety_check_by"] == "plan"


@pytest.mark.parametrize("answer", ["没有，我没事", "不是，真的没有那种想法", "我现在是安全的"])
def test_a_clear_no_or_a_safety_confirmation_returns_to_the_chat(answer: str) -> None:
    session = _session()
    _asked(session.turn(PUT_AWAY[0]))
    result = session.turn(answer)
    assert not result.in_crisis
    assert result.reply_kind is not ReplyKind.CRISIS
    assert result.crisis_level < L.L2
    assert result.inspect["safety_check"] == "denied"


@pytest.mark.parametrize("answer", ["是的", "嗯", "嗯……说不好", "不知道", "没有，刀还在手边"])
def test_a_yes_an_unclear_answer_or_another_cue_enters_the_crisis_at_l3(answer: str) -> None:
    session = _session()
    _asked(session.turn(PUT_AWAY[1]))
    result = session.turn(answer)
    assert result.in_crisis
    assert result.reply_kind is ReplyKind.CRISIS
    assert result.crisis_level is L.L3
    _urgent(result.reply)


def test_no_answer_says_goodbye_at_l3() -> None:
    session = _session()
    _asked(session.turn(PUT_AWAY[2]))
    farewell = session.farewell()
    assert farewell is not None
    assert farewell.level is L.L3
    _urgent(farewell.text)


@pytest.mark.parametrize(
    "earlier",
    [
        ["活着好累"],  # a rule L1
        ["我觉得自己是个累赘", "没有，就是随口一说"],  # a D3 cue, then a no
        ["我真的不想活了", "我现在安全了", "今天吃了面条", "天气还不错"],  # a crisis, ended
    ],
)
def test_earlier_risk_in_the_session_makes_it_l3_at_once(earlier: list[str]) -> None:
    session = _session()
    for text in earlier:
        session.turn(text)
    result = session.turn(PUT_AWAY[0])
    assert result.in_crisis
    assert result.reply_kind is ReplyKind.CRISIS
    assert result.crisis_level is L.L3


def test_in_a_crisis_it_stays_l3_at_once() -> None:
    session = _session()
    assert session.turn("我真的不想活了").in_crisis
    session.turn("我现在安全了")
    result = session.turn(PUT_AWAY[0])
    assert result.in_crisis
    assert result.crisis_level is L.L3
    assert result.reply_kind is ReplyKind.CRISIS


def test_a_second_put_away_after_a_clear_no_asks_again() -> None:
    # The put-away cue itself is no "other risk" (as the X得想死 figure, §9.4 第 4 条).
    session = _session()
    _asked(session.turn(PUT_AWAY[0]))
    assert not session.turn("没有，我没事").in_crisis
    _asked(session.turn(PUT_AWAY[1]))


def test_with_more_in_the_message_it_is_l3_at_once() -> None:
    result = _session().turn("我不想死，刀我已经收好了，今晚再说")
    assert result.in_crisis
    assert result.crisis_level is L.L3


# -- 2. "不是……就是……" -------------------------------------------------------------------------

D3_CUE = "我觉得自己是个累赘"
MODEL_ONLY = "心里一直闷闷的"


@pytest.mark.parametrize(
    "answer",
    [
        "不是，就是不开心",
        "不是那个意思，就是有点累",
        "不是不想活，就是太累了",
        "不是不开心，就是累",
    ],
)
def test_not_that_just_tired_answers_the_d3_question_with_a_no(answer: str) -> None:
    session = _session()
    _asked(session.turn(D3_CUE))
    result = session.turn(answer)
    assert result.inspect["safety_check"] == "denied"
    assert not result.in_crisis


@pytest.mark.parametrize(
    "answer", ["不是那个意思，就是有点累", "不是不想活，就是太累了", "我不是不想活，只是太累了"]
)
def test_not_that_just_tired_answers_a_model_only_question_with_a_no(answer: str) -> None:
    session = _scripted({MODEL_ONLY: 0.42})
    asked = session.turn(MODEL_ONLY)
    assert asked.reply_kind is ReplyKind.SAFETY_CHECK
    result = session.turn(answer)
    assert result.inspect["safety_check"] == "denied"
    assert not result.in_crisis


@pytest.mark.parametrize("answer", ["不是不想死，就是太累了", "我不是不想死，就是没力气"])
def test_not_not_wanting_to_die_enters_the_crisis(answer: str) -> None:
    for session, first in ((_session(), D3_CUE), (_scripted({MODEL_ONLY: 0.42}), MODEL_ONLY)):
        assert session.turn(first).reply_kind is ReplyKind.SAFETY_CHECK
        result = session.turn(answer)
        assert result.in_crisis
        assert result.crisis_level >= L.L2
