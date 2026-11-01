"""负责人 2026-11-01 决定 (round 7):

* A: after a no to a model-only question that passed F10, a later model-only alarm with a
  score below 0.6 and no rule cue, at least 3 turns on, asks first once more; at most two
  such questions per session.
* B: a run-of-days word lifts the "X得想死" figure to L2 only in the figure's own clause or
  in a clause about the wish or the pain itself; next to the cause ("……，天天饿肚子") it
  asks first.
* C: "不是 + a feeling, 就是 / 只是 + something neutral" is a no (it must still pass F10).

Every example message is written here; none comes from an evaluation set or the re-test.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest

from olivia.core.models import CrisisLevel, PersonaProfile, UserRegion
from olivia.core.safety.crisis import RiskPrediction, SafetyScreen
from olivia.core.safety.intent_check import IntentAnswer, read_answer
from olivia.core.safety.lexicon import load_safety_lexicons
from olivia.core.session import ReplyKind, Session
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
LEX = load_safety_lexicons(TAX)
NOW = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)
RULES = SafetyScreen(TAX, LEX)
CALM = ["早上喝了杯豆浆", "中午和同事吃了面", "下班路上听了歌", "晚上看了会儿书"]


class Scripted:
    def __init__(self, scores: dict[str, float]) -> None:
        self.scores = scores

    def predict(self, text: str) -> RiskPrediction:
        score = self.scores.get(text)
        if score is None:
            return RiskPrediction(CrisisLevel.L0, 0.05, ())
        return RiskPrediction(CrisisLevel.L2, score, ())


def _open(scores: dict[str, float]) -> Session:
    profile = PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        user_name="小周",
        region=UserRegion("CN", "Asia/Shanghai"),
    )
    return Session.open(
        TAX,
        profile,
        rng=random.Random(11),
        now=lambda: NOW,
        model=Scripted(scores),  # type: ignore[arg-type]
    )


# -- A ----------------------------------------------------------------------------------

FIRST, SECOND, THIRD = "心里总是闷闷的", "朋友最近都不怎么回我", "我是不是想得太多了呀"


def _denied_then(scores: dict[str, float], calm: int) -> Session:
    session = _open({FIRST: 0.42, **scores})
    assert session.turn(FIRST).reply_kind is ReplyKind.SAFETY_CHECK
    assert not session.turn("没有，我没那么想").in_crisis
    for text in CALM[:calm]:
        assert not session.turn(text).in_crisis
    return session


def test_a_low_alarm_three_turns_after_a_clear_no_asks_again() -> None:
    session = _denied_then({SECOND: 0.38}, calm=3)
    result = session.turn(SECOND)
    assert result.reply_kind is ReplyKind.SAFETY_CHECK
    assert not result.in_crisis


def test_too_soon_after_the_no_enters_the_crisis() -> None:
    session = _denied_then({SECOND: 0.38}, calm=1)
    assert session.turn(SECOND).in_crisis


def test_a_sure_alarm_after_the_no_enters_the_crisis() -> None:
    session = _denied_then({SECOND: 0.66}, calm=3)
    assert session.turn(SECOND).in_crisis


def test_at_most_two_questions_per_session() -> None:
    session = _denied_then({SECOND: 0.38, THIRD: 0.35}, calm=3)
    assert session.turn(SECOND).reply_kind is ReplyKind.SAFETY_CHECK
    assert not session.turn("没有，真的没有").in_crisis
    for text in CALM[:3]:
        session.turn(text)
    assert session.turn(THIRD).in_crisis


def test_an_unclear_answer_keeps_the_crisis() -> None:
    session = _open({FIRST: 0.42})
    session.turn(FIRST)
    assert session.turn("嗯……说不好").in_crisis


# -- B ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["搬砖搬得想死，每天都要扛水泥", "刷题刷得想死，老师天天发卷子", "背书背得想死，一直在背公式"],
)
def test_a_run_of_days_on_the_cause_asks_first(text: str) -> None:
    assessment = RULES.assess(text)
    assert assessment.level is CrisisLevel.L1
    assert assessment.asks_intent


@pytest.mark.parametrize(
    "text",
    ["天天熬夜熬得想死", "累得想死，每天都很难受", "烦得想死，天天都这样", "忙得想死，一直很痛苦"],
)
def test_a_run_of_days_on_the_wish_or_the_pain_stays_l2(text: str) -> None:
    assert RULES.assess(text).level >= CrisisLevel.L2


# -- C ----------------------------------------------------------------------------------


def _answer(text: str) -> IntentAnswer:
    reading = read_answer(LEX.intent_answers, text, RULES.assess(text), RULES.assess)
    if reading.reason_split and not RULES.clear_denial(text):
        return IntentAnswer.UNCLEAR
    return reading.answer


@pytest.mark.parametrize("text", ["不是伤心，就是有点好奇", "不是难受啊，只是想问问"])
def test_not_a_feeling_just_something_neutral_is_a_no(text: str) -> None:
    assert _answer(text) is IntentAnswer.DENIED


@pytest.mark.parametrize(
    "text", ["不是伤心，就是不想活了", "不是难受，只是药都备好了", "不是难过，但有时候会想"]
)
def test_not_a_feeling_with_risk_or_a_hedge_stays_unclear(text: str) -> None:
    assert _answer(text) is not IntentAnswer.DENIED
