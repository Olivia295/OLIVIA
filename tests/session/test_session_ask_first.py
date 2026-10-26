"""Owner decisions 2026-10-26: an unsure crisis alarm only the model raises asks first.

When a turn's crisis level reaches L2 only because of the injected model (the student in
the product) while the rules found no risk cue at all (``CrisisAssessment.rule_clear``,
defined by ``safety.crisis.rules_found_nothing``), and the student is unsure (its class
below L3 and its crisis score below ``risk.yaml`` ``model_ask.direct_from_score``, 0.6),
the session does not enter the crisis flow on that turn. It asks the direct question of
decision D3 once (``SAFETY_CHECK``) with the region's hotlines. A sure student (class L3
or score >= 0.6) enters the crisis flow at once, as before. The next turn decides: yes,
unclear, off topic, no answer (the session ending included) or any new risk enters the
crisis flow; only a clear no that also passes the F10 denial
conditions stays in ordinary talk, and it leaves no gentle-care flag (I9). A second
model-only alarm in the same session (also after a sure one) goes straight to the crisis
flow. With any rule cue, or inside a crisis, nothing changes.

Example messages come from the 2026-10-26 black-box transcripts (B1) or are written here;
none is taken from an evaluation set.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest

from olivia.core.chang.safety_plan import Contact, SafetyPlan
from olivia.core.models import CrisisLevel, HelpStage, PersonaProfile, UserRegion
from olivia.core.safety.crisis import RiskPrediction, SafetyScreen
from olivia.core.safety.lexicon import load_safety_lexicons
from olivia.core.session import MODEL_CHECK_CUE, ReplyKind, Session, TurnResult
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
NOW = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)
RULES = SafetyScreen(TAX, load_safety_lexicons(TAX))
QUESTION_MARKERS = ("结束自己的生命", "结束自己生命")
# B1: ordinary messages the packaged student rated L2/L3 while the rules found nothing.
BREAKUP = "我们分手了，就在上周"
TRIP = "下周还要出差，想想就头大"
MEETING = "就这样吧，我去开会了"
CALM = "今天去公园走了走"


class Scripted:
    """A risk model that rates the listed messages and everything else L0."""

    def __init__(self, levels: dict[str, tuple[CrisisLevel, float]]) -> None:
        self.levels = levels

    def predict(self, text: str) -> RiskPrediction:
        level, score = self.levels.get(text, (CrisisLevel.L0, 0.05))
        return RiskPrediction(level, score, ())


# Unsure: class L2, score below 0.6, so the alarm asks first.
L2 = (CrisisLevel.L2, 0.55)
# Sure: a score at the line, or the class L3 whatever the score.
SURE = (CrisisLevel.L2, 0.6)
L3 = (CrisisLevel.L3, 0.52)
ALARMS = {BREAKUP: L3, TRIP: L2, MEETING: L2}


def _profile(region: str = "CN") -> PersonaProfile:
    return PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        user_name="小林",
        region=UserRegion(region, "Asia/Shanghai"),
    )


def _open(levels: dict[str, tuple[CrisisLevel, float]] | None = None, **kwargs: object) -> Session:
    model = Scripted(ALARMS if levels is None else levels)
    return Session.open(
        TAX, _profile(), rng=random.Random(5), now=lambda: NOW, model=model, **kwargs
    )  # type: ignore[arg-type]


def _assert_asked(result: TurnResult) -> None:
    assert result.reply_kind is ReplyKind.SAFETY_CHECK
    assert result.inspect["safety_check"] == "asked"
    assert result.inspect["safety_check_by"] == "model"
    assert any(marker in result.reply for marker in QUESTION_MARKERS), result.reply
    assert not result.in_crisis and result.stage is not HelpStage.S_CRISIS
    # The alarm is still reported at its level: only the crisis flow waits.
    assert result.crisis_level is CrisisLevel.L2 and result.inspect["assessed_level"] == "L2"
    assert result.action_id is None and result.referral_flags == ()
    assert "12356" in result.reply
    assert "110" not in result.reply and "120" not in result.reply


def _assert_crisis(result: TurnResult) -> None:
    assert result.reply_kind is ReplyKind.CRISIS and result.stage is HelpStage.S_CRISIS
    assert result.in_crisis and result.crisis_level >= CrisisLevel.L2
    assert "12356" in result.reply


# -- the definition of "no rule risk cue" -------------------------------------------------------


@pytest.mark.parametrize(
    "text", [BREAKUP, TRIP, MEETING, CALM, "我妈说别再想了，可我做不到", "有什么放松的方法吗"]
)
def test_ordinary_messages_are_clear_of_rule_cues(text):
    assert RULES.assess(text).rule_clear is True


@pytest.mark.parametrize(
    "text",
    [
        "我想死",  # a Stage 2 phrase
        "活着好累",  # the rules' own L1
        "累死了，今天跑了一天",  # a hyperbole phrase: the rules saw a death word
        "我不想死，就是很累",  # a negation phrase, masked or not
        "我在看一篇讲自杀的报道",  # a pair anchor without its request word
        "有没有最快的办法离开",  # an ask cue (D3)
        "我觉得自己就是个累赘",  # an ask composition (burden)
        "我写了一封遗书",  # Stage 1
    ],
)
def test_any_rule_cue_means_not_clear(text):
    assert RULES.assess(text).rule_clear is False


def test_a_hand_built_assessment_is_never_clear():
    from olivia.core.safety.crisis import CrisisAssessment

    assert CrisisAssessment(CrisisLevel.L2, 0.6, "STAGE2", False, ()).rule_clear is False


# -- asking once ---------------------------------------------------------------------------------


def test_a_model_only_l2_asks_once_with_the_regional_hotlines():
    _assert_asked(_open().turn(TRIP))


def test_a_model_only_l3_class_enters_the_crisis_flow_with_the_emergency_numbers():
    result = _open().turn(BREAKUP)
    _assert_crisis(result)
    assert result.inspect["safety_check"] is None and "safety_check_by" not in result.inspect
    assert result.reply.index("110") < result.reply.index("12356")


@pytest.mark.parametrize(("score", "asks"), [(0.59, True), (0.6, False), (0.79, False)])
def test_the_score_line_is_0_6(score, asks):
    result = _open({TRIP: (CrisisLevel.L2, score)}).turn(TRIP)
    if asks:
        _assert_asked(result)
    else:
        _assert_crisis(result)


def test_a_sure_first_alarm_spends_the_question():
    session = _open({TRIP: SURE, MEETING: L2})
    _assert_crisis(session.turn(TRIP))
    for text in ("我现在是安全的", CALM, "去楼下买了杯奶茶"):
        session.turn(text)
    assert session.snapshot()["in_crisis"] is False
    _assert_crisis(session.turn(MEETING))


@pytest.mark.parametrize("answer", ["是的", "嗯", "有一点"])
def test_a_yes_enters_the_crisis_flow(answer):
    session = _open()
    session.turn(TRIP)
    result = session.turn(answer)
    _assert_crisis(result)
    assert result.inspect["safety_check"] == "affirmed"
    assert result.inspect["safety_check_by"] == "model"
    assert MODEL_CHECK_CUE in result.inspect["cue_ids"]  # type: ignore[operator]


@pytest.mark.parametrize(
    "answer",
    [
        "",  # nothing
        "……",
        "随便吧",
        "我也说不清",
        "在一起四年，他说没感觉了",  # off topic (B1, p2-s1)
        "/done",
    ],
)
def test_unclear_off_topic_or_no_answer_enters_the_crisis_flow(answer):
    session = _open()
    session.turn(TRIP)
    result = session.turn(answer)
    _assert_crisis(result)
    assert result.inspect["safety_check"] == "unclear"


@pytest.mark.parametrize(
    "answer",
    [
        "不是，但是我真的撑不住了",  # a contrast (F10)
        "不是，可是今晚不想一个人待着",  # contrast and a time veto
        "没有，明天还要上班呢",  # an F10 time veto: stricter than D3's no
        "不是，就是活着好累",  # a new rule cue (L1)
        "不是，有没有最快的办法离开",  # a new ask cue
        "不是吧",  # a hedge (D3 unsure)
    ],
)
def test_a_no_with_a_veto_contrast_or_new_risk_enters_the_crisis_flow(answer):
    session = _open()
    session.turn(TRIP)
    result = session.turn(answer)
    _assert_crisis(result)
    assert result.inspect["safety_check"] == "unclear"


def test_the_models_own_alarm_on_the_answer_enters_the_crisis_flow():
    session = _open({TRIP: L2, "不是": L2})
    session.turn(TRIP)
    _assert_crisis(session.turn("不是"))


@pytest.mark.parametrize(
    "answer", ["不是", "没有", "不是，我就是失恋了很难过", "不是，我不想死，就是难过"]
)
def test_a_clear_no_stays_in_ordinary_talk_without_a_care_flag(answer):
    session = _open()
    session.turn(TRIP)
    assert session.snapshot()["awaiting_safety_check"] is True
    result = session.turn(answer)
    assert not result.in_crisis and result.reply_kind is not ReplyKind.CRISIS
    assert result.reply_kind is not ReplyKind.SAFETY_CHECK
    assert result.inspect["safety_check"] == "denied"
    assert result.inspect["safety_check_by"] == "model"
    snapshot = session.snapshot()
    # I9: only being asked and saying no leaves no gentle-care flag for the next session.
    assert snapshot["gentle_care"] is False and snapshot["awaiting_safety_check"] is False
    assert session.farewell() is None
    later = session.turn(CALM)
    assert later.inspect["safety_check"] is None and "safety_check_by" not in later.inspect


def test_a_second_model_only_alarm_goes_straight_to_the_crisis_flow():
    session = _open()
    _assert_asked(session.turn(TRIP))
    session.turn("不是")
    session.turn(CALM)
    result = session.turn(MEETING)
    _assert_crisis(result)
    assert result.inspect["safety_check"] is None


def test_after_a_crisis_a_model_only_alarm_is_never_asked_again():
    session = _open()
    session.turn(TRIP)
    session.turn("嗯")  # the crisis flow
    for text in ("我现在是安全的", CALM, "去楼下买了杯奶茶"):
        session.turn(text)
    assert session.snapshot()["in_crisis"] is False
    _assert_crisis(session.turn(MEETING))


# -- nothing else changes ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "累死了，下周还要出差",  # hyperbole
        "活着好累，下周还要出差",  # the rules' L1
        "我在看一篇讲自杀的报道",  # a pair anchor
    ],
)
def test_with_any_rule_cue_a_model_l2_enters_the_crisis_flow_as_before(text):
    result = _open({text: L2}).turn(text)
    _assert_crisis(result)
    assert result.inspect["safety_check"] is None


def test_a_d3_ask_cue_that_the_model_raises_enters_the_crisis_flow_as_before():
    ask = "有没有最快的办法离开"
    _assert_crisis(_open({ask: L2}).turn(ask))


def test_inside_a_crisis_a_model_only_alarm_asks_nothing():
    session = _open({TRIP: L2})
    _assert_crisis(session.turn("我不想活了"))
    result = session.turn(TRIP)
    _assert_crisis(result)
    assert result.inspect["safety_check"] is None


def test_a_model_failure_enters_the_crisis_flow_as_before():
    class Broken:
        def predict(self, text: str) -> RiskPrediction:
            raise RuntimeError("boom")

    session = Session.open(TAX, _profile(), rng=random.Random(5), now=lambda: NOW, model=Broken())
    _assert_crisis(session.turn(CALM))


def test_rules_mode_never_asks_for_a_model():
    session = Session.open(TAX, _profile(), rng=random.Random(5), now=lambda: NOW)
    for text in (BREAKUP, TRIP, MEETING):
        result = session.turn(text)
        assert result.reply_kind is not ReplyKind.SAFETY_CHECK and not result.in_crisis


def test_the_d3_denial_still_sets_the_gentle_care_flag():
    session = _open({})
    session.turn("有没有最快的办法离开")
    result = session.turn("不是，我就是想辞职")
    assert result.inspect["safety_check"] == "denied" and "safety_check_by" not in result.inspect
    assert session.snapshot()["gentle_care"] is True


# -- the session ending with the question unanswered ----------------------------------------------


def test_ending_with_the_question_unanswered_counts_as_the_crisis_flow():
    plan = SafetyPlan(people=(Contact("阿青", "138-0000-0000"),))
    session = _open(safety_plan=plan)
    session.turn(TRIP)
    farewell = session.farewell()
    assert farewell is not None and farewell.level is CrisisLevel.L2
    text = farewell.text
    assert text.index("12356") < text.index("阿青") < text.index("138-0000-0000")
    assert not any(marker in text for marker in QUESTION_MARKERS)


def test_a_d3_question_left_unanswered_also_gets_the_crisis_farewell():
    session = _open({})
    session.turn("有没有最快的办法离开")
    farewell = session.farewell()
    assert farewell is not None and "12356" in farewell.text and "110" not in farewell.text


# -- the line itself (risk.yaml model_ask) --------------------------------------------------------


def _lexicons_with(tmp_path, replacement: str | None):
    import shutil
    from importlib import resources

    source = resources.files("olivia").joinpath("data/lexicons")
    for name in ("risk.yaml", "red_flags.yaml", "perception.yaml"):
        shutil.copyfile(str(source.joinpath(name)), tmp_path / name)
    risk = tmp_path / "risk.yaml"
    text = risk.read_text(encoding="utf-8")
    old = "model_ask:\n  direct_from_score: 0.6\n"
    assert old in text
    risk.write_text(text.replace(old, replacement or ""), encoding="utf-8")
    return load_safety_lexicons(TAX, tmp_path)


def test_the_packaged_line_is_0_6():
    rules = load_safety_lexicons(TAX).model_ask
    assert rules.direct_from_score == 0.6
    assert rules.asks_first(CrisisLevel.L2, 0.59) and not rules.asks_first(CrisisLevel.L2, 0.6)
    assert not rules.asks_first(CrisisLevel.L3, 0.3)


@pytest.mark.parametrize("value", ["0", "1.5", "-0.1", "true", "'0.6'", ".nan"])
def test_a_bad_line_does_not_load(tmp_path, value):
    from olivia.core.safety.lexicon import LexiconError

    with pytest.raises(LexiconError):
        _lexicons_with(tmp_path, f"model_ask:\n  direct_from_score: {value}\n")


def test_without_the_section_every_model_only_alarm_enters_the_crisis_flow(tmp_path):
    rules = _lexicons_with(tmp_path, None).model_ask
    assert rules.direct_from_score is None
    assert not rules.asks_first(CrisisLevel.L2, 0.01)


# -- #119 cues count as rule cues (2026-10-26) -----------------------------------------------------

REPORTED = "她跟我说她不想活了"  # someone else's words: the rules void them, yet saw them
FAREWELL_ASK = "谢谢你这段时间的陪伴，以后不会再来了"  # an ASK composition
RAISED = "我的身后事都安排好了，活着好累"  # an ASK composition raised with risk (L2)


@pytest.mark.parametrize("text", [REPORTED, FAREWELL_ASK, RAISED])
def test_reported_speech_ask_compositions_and_raised_cues_are_rule_cues(text):
    assessment = RULES.assess(text)
    assert assessment.rule_clear is False


def test_reported_speech_stays_l0_for_the_rules_but_is_not_clear():
    """The rules narrow a friend's reported words to L0, but they did see a death phrase:
    a model alarm on it is not "the rules found nothing", so it never asks first."""
    assessment = RULES.assess(REPORTED)
    assert assessment.rule_level is CrisisLevel.L0 and not assessment.rule_clear
    result = _open({REPORTED: L2}).turn(REPORTED)
    _assert_crisis(result)
    assert result.inspect["safety_check"] is None


def test_an_ask_composition_the_model_raises_enters_the_crisis_flow():
    _assert_crisis(_open({FAREWELL_ASK: L2}).turn(FAREWELL_ASK))


def test_a_raised_ask_composition_is_a_rule_l2_crisis_without_a_model():
    session = Session.open(TAX, _profile(), rng=random.Random(5), now=lambda: NOW)
    _assert_crisis(session.turn(RAISED))
