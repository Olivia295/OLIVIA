"""The direct question about intent (decision D3, step A7) inside a session.

A turn whose screen reports an ``ASK_INTENT`` cue below L2, outside a crisis, gets one
gentle, direct question about suicidal intent plus the region's L2 resource lines
(``ReplyKind.SAFETY_CHECK``). The next turn decides: a denial returns to the ordinary flow
and sets the in-session gentle-care flag; anything else (yes, unclear, no answer, a new
crisis cue) is read as L2 and enters the crisis flow. A turn that screens L2/L3 on its own
goes straight to crisis. Every flow runs in rules mode and in model mode.
"""

from __future__ import annotations

import random
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from olivia.core.models import CrisisLevel, HelpStage, PersonaProfile, UserRegion
from olivia.core.safety.crisis import RiskPrediction
from olivia.core.session import ReplyKind, Session
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
NOW = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)
# L1 in both modes: the packaged student does not raise it (it raises 想走了 + 不痛 to L2,
# which goes straight to crisis; see test_a_turn_the_student_raises_goes_straight_to_crisis).
ASK = "有没有最快的办法离开"
QUESTION_MARKERS = ("结束自己的生命", "结束自己生命")
BOTH_MODES = pytest.mark.parametrize(
    "rules_only", [pytest.param(True, id="rules"), pytest.param(False, id="model")]
)


def _profile(**overrides: object) -> PersonaProfile:
    base = PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        user_name="小林",
        region=UserRegion("CN", "Asia/Shanghai"),
    )
    return replace(base, **overrides)


def _open(rules_only: bool = True, seed: int = 3, **overrides: object) -> Session:
    return Session.open(
        TAX, _profile(**overrides), rng=random.Random(seed), now=lambda: NOW, student=not rules_only
    )


def _assert_ask(result, number: str = "12356", *, mid_card: bool = False) -> None:
    assert result.reply_kind is ReplyKind.SAFETY_CHECK
    assert result.inspect["safety_check"] == "asked"
    assert any(marker in result.reply for marker in QUESTION_MARKERS), result.reply
    assert number in result.reply
    assert not result.in_crisis and result.crisis_level < CrisisLevel.L2
    assert result.stage is not HelpStage.S_CRISIS
    # The request is never passed on as a direct request; only a card already waiting in
    # S_empower keeps the session there.
    assert mid_card or result.stage is not HelpStage.S_EMPOWER
    assert result.action_id is None and result.referral_flags == ()
    assert result.inspect["candidates"] == [] and result.inspect["chosen"] is None
    assert result.resource_card is not None and result.resource_card.level is CrisisLevel.L2


@BOTH_MODES
def test_euphemism_gets_one_direct_question_with_resources(rules_only):
    _assert_ask(_open(rules_only).turn(ASK))


@BOTH_MODES
@pytest.mark.parametrize("answer", ["是的", "嗯", "对", "有一点", "I do"])
def test_affirmation_enters_the_crisis_flow(rules_only, answer):
    session = _open(rules_only)
    _assert_ask(session.turn(ASK))
    result = session.turn(answer)
    assert result.reply_kind is ReplyKind.CRISIS and result.stage is HelpStage.S_CRISIS
    assert result.in_crisis and result.crisis_level >= CrisisLevel.L2
    assert result.inspect["safety_check"] == "affirmed"
    assert "12356" in result.reply
    assert session.snapshot()["in_crisis"] is True


@BOTH_MODES
@pytest.mark.parametrize("answer", ["", "……", "随便吧", "/done", "我也说不清"])
def test_unclear_or_no_answer_is_read_as_l2(rules_only, answer):
    session = _open(rules_only)
    session.turn(ASK)
    result = session.turn(answer)
    assert result.reply_kind is ReplyKind.CRISIS and result.in_crisis
    assert result.crisis_level >= CrisisLevel.L2
    assert result.inspect["safety_check"] == "unclear"


@BOTH_MODES
@pytest.mark.parametrize("answer", ["不是，就是活着好累", "不是，有没有最快的办法离开"])
def test_a_new_crisis_cue_after_a_denial_word_is_l2(rules_only, answer):
    session = _open(rules_only)
    session.turn(ASK)
    result = session.turn(answer)
    assert result.reply_kind is ReplyKind.CRISIS and result.in_crisis
    assert result.inspect["safety_check"] == "unclear"


@BOTH_MODES
def test_denial_returns_to_the_ordinary_flow_with_gentle_care(rules_only):
    session = _open(rules_only)
    session.turn(ASK)
    assert session.snapshot()["awaiting_safety_check"] is True
    result = session.turn("不是，我就是想辞职")
    assert result.reply_kind is not ReplyKind.CRISIS and not result.in_crisis
    assert result.reply_kind is not ReplyKind.SAFETY_CHECK
    assert result.inspect["safety_check"] == "denied"
    snapshot = session.snapshot()
    assert snapshot["gentle_care"] is True and snapshot["awaiting_safety_check"] is False
    # The question waits for exactly one turn.
    later = session.turn("最近工作压力好大")
    assert later.inspect["safety_check"] is None and not later.in_crisis


def test_no_gentle_care_without_a_denial():
    session = _open()
    session.turn("最近工作压力好大")
    assert session.snapshot()["gentle_care"] is False


@BOTH_MODES
def test_a_turn_that_screens_l2_goes_straight_to_crisis(rules_only):
    result = _open(rules_only).turn("我想死，有没有不痛的办法离开")
    assert result.reply_kind is ReplyKind.CRISIS and result.in_crisis
    assert result.inspect["safety_check"] is None


def test_a_turn_the_student_raises_goes_straight_to_crisis():
    result = _open(rules_only=False).turn("想走了，有没有不痛的办法")
    assert result.inspect["model_level"] == CrisisLevel.L2.name
    assert result.reply_kind is ReplyKind.CRISIS and result.inspect["safety_check"] is None
    rules = _open().turn("想走了，有没有不痛的办法")
    assert rules.reply_kind is ReplyKind.SAFETY_CHECK


@BOTH_MODES
def test_no_question_inside_a_crisis(rules_only):
    session = _open(rules_only)
    session.turn("不想活了")
    result = session.turn(ASK)
    assert result.reply_kind is ReplyKind.CRISIS and result.inspect["safety_check"] is None


@BOTH_MODES
def test_a_crisis_on_the_answer_turn_is_not_delayed(rules_only):
    session = _open(rules_only)
    session.turn(ASK)
    result = session.turn("我写了一封遗书")
    assert result.reply_kind is ReplyKind.CRISIS and result.crisis_level is CrisisLevel.L3


def test_question_never_offers_a_card_even_mid_flow():
    session = _open()
    card = session.turn("最近拖延很严重，给我一个方法")
    assert card.reply_kind is ReplyKind.CARD
    asked = session.turn(ASK)
    _assert_ask(asked, mid_card=True)
    assert "/done" not in asked.reply and "「" not in asked.reply


@pytest.mark.parametrize(
    ("region", "number", "mainland"),
    [("US", "988", "12356"), ("HK", "18111", "12356"), ("GB", "116 123", "12356")],
)
def test_resources_follow_the_region(region, number, mainland):
    session = _open(region=UserRegion(region, "UTC"))
    result = session.turn(ASK)
    _assert_ask(result, number)
    assert mainland not in result.reply


def test_question_ignores_taboo_topics_and_the_battery_prefix():
    session = _open(taboo_topics=("生命",))
    _assert_ask(session.turn("[5%] " + ASK))


def test_red_flag_referral_waits_for_the_next_ordinary_turn():
    session = _open(clinical_history=("SIT-02-04",))
    asked = session.turn(ASK)
    _assert_ask(asked)
    later = session.turn("不是，我就是想辞职")
    assert later.referral_flags == ("SIT-02-04",)


def test_inspect_carries_the_key_but_never_text():
    session = _open()
    asked = session.turn(ASK)
    denied = session.turn("不是，我就是想辞职")
    for result in (asked, denied):
        values = [str(v) for v in result.inspect.values()]
        assert not any("想走" in v or "辞职" in v or "生命" in v for v in values)
    calm = _open().turn("今天天气不错")
    assert "safety_check" in calm.inspect and calm.inspect["safety_check"] is None


class _RaisesDenials:
    """An injected model that rates the denial turn L2 and everything else L0."""

    def predict(self, text: str) -> RiskPrediction:
        if text.startswith("不是"):
            return RiskPrediction(CrisisLevel.L2, 0.7, ())
        return RiskPrediction(CrisisLevel.L0, 0.25, ())


def test_a_model_l2_on_the_answer_turn_still_enters_crisis():
    # The rule screen decides that the answer is a no; the model's own L2 still counts.
    session = Session.open(
        TAX, _profile(), rng=random.Random(3), now=lambda: NOW, model=_RaisesDenials()
    )
    _assert_ask(session.turn(ASK))
    result = session.turn("不是，我就是想辞职")
    assert result.inspect["safety_check"] == "denied"
    assert result.reply_kind is ReplyKind.CRISIS and result.in_crisis


def test_a_model_score_band_alone_does_not_void_a_denial():
    session = Session.open(
        TAX, _profile(), rng=random.Random(3), now=lambda: NOW, model=_RaisesDenials()
    )
    session.turn(ASK)
    result = session.turn("没有啦，你想多了")
    assert result.inspect["assessed_level"] == CrisisLevel.L1.name  # 0.25 is in the L1 band
    assert result.inspect["safety_check"] == "denied" and not result.in_crisis
