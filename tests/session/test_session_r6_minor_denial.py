"""A no to the age question with a model-only alarm, and teachers (round 6 follow-up).

* 负责人 2026-10-30 决定: on the turn that answers whether the user is under 18, a no
  (``reads_no``) the rules find no risk cue in asks the direct question first even when the
  model is sure (score >= 0.6), instead of entering the crisis flow. A rule cue in the same
  message, or an answer that is no no, keeps the crisis flow as before.
* A school year followed by teaching in the same clause ("在初中教数学") is no disclosure
  of one's own age; a pupil's words about a teacher in the next clause still are.

Every example message is written here; none comes from a re-test sheet or an evaluation set.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest

from olivia.core.models import CrisisLevel, PersonaProfile, UserRegion
from olivia.core.perception.lexicon import load_perception_lexicon
from olivia.core.perception.rule_stub import RuleStub
from olivia.core.safety.crisis import RiskPrediction
from olivia.core.session import ReplyKind, Session
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
NOW = datetime(2026, 10, 30, 15, 0, tzinfo=UTC)
STUB = RuleStub(TAX, load_perception_lexicon(TAX))
AGE = "我才十五，同桌又不理我了"


class Sure:
    """A risk model that rates every message but the age one L3 at 0.9."""

    def predict(self, text: str) -> RiskPrediction:
        if text == AGE:
            return RiskPrediction(CrisisLevel.L0, 0.05, ())
        return RiskPrediction(CrisisLevel.L3, 0.9, ())


def _asked() -> Session:
    profile = PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        user_name="小林",
        region=UserRegion("CN", "Asia/Shanghai"),
    )
    session = Session.open(TAX, profile, rng=random.Random(30), now=lambda: NOW, model=Sure())  # type: ignore[arg-type]
    first = session.turn(AGE)
    assert first.inspect.get("resources_reply") == "minor"
    return session


@pytest.mark.parametrize(
    "text", ["不对不对，按错键了，我三十五", "没有哦，我都快四十了", "nah, I'm 41"]
)
def test_a_no_with_only_the_models_alarm_asks_first(text):
    # 负责人 2026-10-30 决定
    result = _asked().turn(text)
    assert result.reply_kind is ReplyKind.SAFETY_CHECK
    assert not result.in_crisis
    assert result.inspect.get("minor_record") == "session_only"


@pytest.mark.parametrize(
    "text",
    ["不对，我三十五了，可我今晚就想死", "最近一直提不起劲", "我也说不清"],
)
def test_a_rule_cue_or_no_no_keeps_the_crisis_flow(text):
    result = _asked().turn(text)
    assert result.in_crisis and result.reply_kind is ReplyKind.CRISIS


TEACHERS = ["我在高二教历史", "本人在国中任教", "我在初一带班三年了", "我在中五代课"]
PUPILS = ["我在读初一，教室好冷", "我高二，老师管得严", "我在念中五，教导处又找我"]


@pytest.mark.parametrize("text", TEACHERS)
def test_teaching_a_school_year_is_no_minor(text):
    assert not STUB.discloses_minor(text)


@pytest.mark.parametrize("text", PUPILS)
def test_a_pupil_who_names_a_teacher_is_still_a_minor(text):
    assert STUB.discloses_minor(text)
