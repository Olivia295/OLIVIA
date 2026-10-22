"""One test group per rule of olivia/core/perception/rule_stub.py."""

from pathlib import Path
from typing import Any

import pytest
import yaml

from olivia.core.models import CrisisLevel
from olivia.core.perception.lexicon import PerceptionLexicon, load_perception_lexicon
from olivia.core.perception.rule_stub import (
    AROUSAL_STEP,
    DEFAULT_READINESS,
    DEFAULT_STANCE,
    MAX_LOWER_STEPS,
    MAX_RAISE_STEPS,
    EmpathyIntent,
    RuleStub,
    dominant_spectrum,
)
from olivia.core.perception.signals import Command
from olivia.core.safety.crisis import CrisisAssessment
from olivia.core.safety.normalize import PERCEPTION_HEAD, PERCEPTION_TAIL
from olivia.core.taxonomy import Taxonomy, TaxonomyError, load_taxonomy


@pytest.fixture(scope="module")
def tax() -> Taxonomy:
    return load_taxonomy()


@pytest.fixture(scope="module")
def lexicon(tax: Taxonomy) -> PerceptionLexicon:
    return load_perception_lexicon(tax)


@pytest.fixture(scope="module")
def stub(tax: Taxonomy, lexicon: PerceptionLexicon) -> RuleStub:
    return RuleStub(tax, lexicon)


def _assessment(level: CrisisLevel = CrisisLevel.L0, score: float = 0.0) -> CrisisAssessment:
    return CrisisAssessment(level, score, "STAGE2", False, ())


def _default_arousal(tax: Taxonomy, emotion: str) -> float:
    return tax.emotion_profiles()[emotion].default_arousal


# -- risk is copied, never recomputed ----------------------------------------------


@pytest.mark.parametrize(
    "level,score", [(CrisisLevel.L0, 0.0), (CrisisLevel.L1, 0.4), (CrisisLevel.L3, 0.9)]
)
def test_risk_fields_are_copied_from_the_assessment(
    stub: RuleStub, level: CrisisLevel, score: float
) -> None:
    ctx, _ = stub.perceive("今天挺好的", _assessment(level, score))
    assert (ctx.risk_level, ctx.crisis_confidence) == (level, score)


# -- battery prefix ------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,battery",
    [
        ("[5%] 好累", 0.05),
        ("[0%]", 0.0),
        ("[100%] 状态满格", 1.0),
        ("[150%] 精神很好", 1.0),
        ("［３０％］ 今天还行", 0.30),
        ("  [45%]今天还行", 0.45),
    ],
)
def test_battery_prefix_is_read(stub: RuleStub, text: str, battery: float) -> None:
    _, signals = stub.perceive(text, _assessment())
    assert signals.battery == pytest.approx(battery)


@pytest.mark.parametrize("text", ["今天还行", "今天电量 [30%]", "[30] 今天还行", "[-5%] 今天"])
def test_no_battery_without_a_leading_prefix(stub: RuleStub, text: str) -> None:
    _, signals = stub.perceive(text, _assessment())
    assert signals.battery is None


def test_battery_prefix_is_not_scanned_as_text(stub: RuleStub, tax: Taxonomy) -> None:
    ctx, _ = stub.perceive("[20%] 好焦虑", _assessment())
    assert ctx.fine_grained_emotion == "anxiety"


# -- commands ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,command",
    [
        ("/done", Command.DONE),
        ("  /not-now \n", Command.NOT_NOW),
        ("/UNHELPFUL", Command.UNHELPFUL),
        ("／ｄｏｎｅ", Command.DONE),
    ],
)
def test_whole_message_commands(stub: RuleStub, text: str, command: Command) -> None:
    _, signals = stub.perceive(text, _assessment())
    assert signals.command is command


@pytest.mark.parametrize("text", ["/done 了", "我 /done", "[20%] /done", "/finish", "done"])
def test_command_must_be_the_whole_message(stub: RuleStub, text: str) -> None:
    _, signals = stub.perceive(text, _assessment())
    assert signals.command is None


# -- direct request and the listening lock -------------------------------------------


@pytest.mark.parametrize("text", ["别问了，直接给我个方法", "有什么办法能让我睡着吗", "教教我"])
def test_direct_request(stub: RuleStub, text: str) -> None:
    _, signals = stub.perceive(text, _assessment())
    assert signals.direct_request


@pytest.mark.parametrize("text", ["我不要给我个方法，听着就行", "现在没有什么方法能帮我"])
def test_negated_direct_request_does_not_trigger(stub: RuleStub, text: str) -> None:
    _, signals = stub.perceive(text, _assessment())
    assert not signals.direct_request


@pytest.mark.parametrize("text", ["我只想说说", "不要建议，听我说就好", "你别分析了"])
def test_lock_on(stub: RuleStub, text: str) -> None:
    _, signals = stub.perceive(text, _assessment())
    assert signals.listening_lock_on and not signals.listening_lock_off


@pytest.mark.parametrize("text", ["我不是只想说说", "也并不是只想吐槽"])
def test_negated_lock_on_does_not_trigger(stub: RuleStub, text: str) -> None:
    _, signals = stub.perceive(text, _assessment())
    assert not signals.listening_lock_on


@pytest.mark.parametrize("text", ["我想听听你的建议", "那我们下一步该怎么做"])
def test_lock_off_uses_the_prd_wording(stub: RuleStub, text: str) -> None:
    _, signals = stub.perceive(text, _assessment())
    assert signals.listening_lock_off and not signals.listening_lock_on


def test_when_both_lock_phrases_occur_the_later_one_wins(stub: RuleStub) -> None:
    _, on_then_off = stub.perceive("刚才只想说说，现在想听听你的建议", _assessment())
    assert (on_then_off.listening_lock_on, on_then_off.listening_lock_off) == (False, True)
    _, off_then_on = stub.perceive("想听听你的建议吗？算了，我只想说说", _assessment())
    assert (off_then_on.listening_lock_on, off_then_on.listening_lock_off) == (True, False)


# -- aversion and implementation intention (SDD 4.2) ---------------------------------


@pytest.mark.parametrize(
    "text",
    ["我不想做这个", "这有什么用啊", "别让我练了，真的", "这个方法没用，听着就烦", "什么破练习"],
)
def test_aversion(stub: RuleStub, text: str) -> None:
    _, signals = stub.perceive(text, _assessment())
    assert signals.aversion and not signals.intent_confirmed


@pytest.mark.parametrize(
    "text", ["我不是不想做这个，就是有点累", "也不是根本没用", "我并不讨厌做这个"]
)
def test_negated_aversion_does_not_trigger(stub: RuleStub, text: str) -> None:
    _, signals = stub.perceive(text, _assessment())
    assert not signals.aversion


@pytest.mark.parametrize(
    "text", ["好的，我明天早上试试", "今晚睡前做一次", "我会试试的", "就这么定了，我定个闹钟"]
)
def test_intent_confirmed(stub: RuleStub, text: str) -> None:
    _, signals = stub.perceive(text, _assessment())
    assert signals.intent_confirmed and not signals.aversion


@pytest.mark.parametrize("text", ["我不会试试的", "不用设个提醒", "我不打算明天早上试试"])
def test_negated_intent_does_not_trigger(stub: RuleStub, text: str) -> None:
    _, signals = stub.perceive(text, _assessment())
    assert not signals.intent_confirmed


@pytest.mark.parametrize("text", ["今天挺好的", "我觉得自己没什么用", "这个练习是做什么用的"])
def test_no_aversion_or_intent_without_a_phrase(stub: RuleStub, text: str) -> None:
    _, signals = stub.perceive(text, _assessment())
    assert not (signals.aversion or signals.intent_confirmed)


# -- emotion -------------------------------------------------------------------------


def test_dominant_emotion_has_the_most_hits(stub: RuleStub) -> None:
    ctx, _ = stub.perceive("有点生气，但更多是难过，真的好伤心，想哭", _assessment())
    assert ctx.fine_grained_emotion == "sadness"


@pytest.mark.parametrize(
    "text,emotion",
    [
        ("好焦虑，喘不上气", "panic"),  # panic over anxiety
        ("好伤心，看不到希望", "hopelessness"),  # hopelessness over sadness
        ("好丢人，我好后悔", "shame"),  # shame over guilt
    ],
)
def test_ties_go_to_the_emotion_closer_to_risk(stub: RuleStub, text: str, emotion: str) -> None:
    ctx, _ = stub.perceive(text, _assessment())
    assert ctx.fine_grained_emotion == emotion


@pytest.mark.parametrize("text,emotion", [("又失眠了", "anxiety"), ("心里空空的", "numbness")])
def test_alias_cues_report_the_canonical_emotion(stub: RuleStub, text: str, emotion: str) -> None:
    ctx, _ = stub.perceive(text, _assessment())
    assert ctx.fine_grained_emotion == emotion


def test_no_cue_means_calm_with_neutral_valence(stub: RuleStub, tax: Taxonomy) -> None:
    ctx, _ = stub.perceive("我在地铁上", _assessment())
    assert ctx.fine_grained_emotion == "calm"
    assert ctx.valence == 0.0
    assert ctx.arousal == pytest.approx(_default_arousal(tax, "calm"))


def test_valence_is_the_midpoint_of_the_tax_window(stub: RuleStub, tax: Taxonomy) -> None:
    for text, emotion in (("我好焦虑", "anxiety"), ("今天挺放松", "calm")):
        ctx, _ = stub.perceive(text, _assessment())
        low, high = tax.emotion_profiles()[emotion].valence_range
        assert ctx.fine_grained_emotion == emotion
        assert ctx.valence == pytest.approx((low + high) / 2)


def test_longer_cue_wins_over_the_cue_inside_it(stub: RuleStub) -> None:
    ctx, _ = stub.perceive("最近开心不起来", _assessment())
    assert ctx.fine_grained_emotion == "sadness"


# -- negation ------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["我一点都不焦虑", "其实没有很焦虑", "我不是焦虑"])
def test_negated_emotion_cue_is_void(stub: RuleStub, text: str) -> None:
    ctx, _ = stub.perceive(text, _assessment())
    assert ctx.fine_grained_emotion == "calm"


@pytest.mark.parametrize(
    "text,emotion",
    [
        ("我是不是焦虑了", "anxiety"),  # A-not-A question
        ("会不会紧张啊", "anxiety"),
        ("也不是不难过", "sadness"),  # double negation
        ("特别焦虑", "anxiety"),  # 特别 ends in 别 but negates nothing
    ],
)
def test_negation_exceptions(stub: RuleStub, text: str, emotion: str) -> None:
    ctx, _ = stub.perceive(text, _assessment())
    assert ctx.fine_grained_emotion == emotion


# -- arousal -------------------------------------------------------------------------


def test_arousal_starts_at_the_emotion_default(stub: RuleStub, tax: Taxonomy) -> None:
    ctx, _ = stub.perceive("我好焦虑", _assessment())
    assert ctx.arousal == pytest.approx(_default_arousal(tax, "anxiety"))


def test_raise_modifiers_add_bounded_steps(stub: RuleStub, tax: Taxonomy) -> None:
    base = _default_arousal(tax, "sadness")
    one, _ = stub.perceive("非常难过", _assessment())
    assert one.arousal == pytest.approx(base + AROUSAL_STEP)
    many, _ = stub.perceive("非常非常特别特别超级难过！！", _assessment())
    assert many.arousal == pytest.approx(base + MAX_RAISE_STEPS * AROUSAL_STEP)


def test_lower_modifiers_remove_bounded_steps(stub: RuleStub, tax: Taxonomy) -> None:
    base = _default_arousal(tax, "anxiety")
    one, _ = stub.perceive("有点焦虑", _assessment())
    assert one.arousal == pytest.approx(base - AROUSAL_STEP)
    many, _ = stub.perceive("有点有点有些稍微焦虑", _assessment())
    assert many.arousal == pytest.approx(base - MAX_LOWER_STEPS * AROUSAL_STEP)


def test_negated_modifier_is_void(stub: RuleStub, tax: Taxonomy) -> None:
    ctx, _ = stub.perceive("也不是特别焦虑", _assessment())
    assert ctx.arousal == pytest.approx(_default_arousal(tax, "anxiety"))


def test_arousal_stays_within_the_unit_interval(stub: RuleStub) -> None:
    ctx, _ = stub.perceive("非常特别超级喘不上气", _assessment())
    assert ctx.arousal == 1.0


@pytest.mark.parametrize(
    "text",
    [
        "我现在心跳快炸了，手一直在抖",
        "我整个人在发抖，停不下来",
        "崩溃了崩溃了，心慌到要吐",
        "头皮发麻，直冒冷汗",
        "又焦虑又担心又紧张，胸口发紧",  # anxiety wins the vote, the body sets the floor
    ],
)
def test_acute_body_cue_floors_arousal_at_the_cognitive_block_line(
    stub: RuleStub, tax: Taxonomy, text: str
) -> None:
    ctx, _ = stub.perceive(text, _assessment())
    assert ctx.arousal >= tax.threshold("arousal.thresholds.cognitive_block")


def test_acute_body_cue_alone_reads_as_panic(stub: RuleStub) -> None:
    ctx, _ = stub.perceive("手一直在抖", _assessment())
    assert ctx.fine_grained_emotion == "panic"


def test_negated_or_mild_body_cue_sets_no_floor(stub: RuleStub, tax: Taxonomy) -> None:
    block = tax.threshold("arousal.thresholds.cognitive_block")
    for text in ("我没有发抖", "有点心慌"):
        ctx, _ = stub.perceive(text, _assessment())
        assert ctx.arousal < block, text


def test_somatic_eligibility_follows_the_tax_threshold(stub: RuleStub, tax: Taxonomy) -> None:
    threshold = tax.threshold("arousal.thresholds.somatic_priority")
    for text in ("喘不上气", "我好焦虑", "今天挺好"):
        ctx, _ = stub.perceive(text, _assessment())
        assert ctx.somatic_stabilization_eligible is (ctx.arousal >= threshold)
    panic, _ = stub.perceive("喘不上气", _assessment())
    assert panic.somatic_stabilization_eligible


# -- distress vector -----------------------------------------------------------------


def test_distress_vector_is_normalized_over_all_spectra(stub: RuleStub, tax: Taxonomy) -> None:
    ctx, _ = stub.perceive("失眠好久了，工作又一直加班", _assessment())
    vector = ctx.distress_vector
    assert tuple(vector) == tax.spectrum_ids()
    assert sum(vector.values()) == pytest.approx(1.0)
    assert vector["05"] == pytest.approx(2 / 3)
    assert vector["08"] == pytest.approx(1 / 3)
    assert dominant_spectrum(vector) == "05"


def test_no_spectrum_cue_gives_an_empty_vector(stub: RuleStub) -> None:
    ctx, _ = stub.perceive("我在地铁上", _assessment())
    assert dict(ctx.distress_vector) == {}
    assert dominant_spectrum(ctx.distress_vector) is None


def test_dominant_spectrum_breaks_ties_by_vector_order() -> None:
    assert dominant_spectrum({"01": 0.0, "02": 0.5, "03": 0.5}) == "02"


# -- empathy intent (guide §4.2) -----------------------------------------------------


@pytest.mark.parametrize(
    "text,level,intent",
    [
        ("今天挺好的", CrisisLevel.L2, EmpathyIntent.REFERRAL),  # 1. risk first
        ("喘不上气", CrisisLevel.L3, EmpathyIntent.REFERRAL),
        ("喘不上气", CrisisLevel.L0, EmpathyIntent.STABILIZATION),  # 2. acute arousal
        ("我想去看心理医生", CrisisLevel.L0, EmpathyIntent.REFERRAL),  # 3. referral cue
        ("我好焦虑，胸闷", CrisisLevel.L0, EmpathyIntent.STABILIZATION),  # 3a. elevated + body
        ("这种状态正常吗", CrisisLevel.L0, EmpathyIntent.INFORMATION),  # 4. question
        ("好迷茫，有什么办法吗", CrisisLevel.L0, EmpathyIntent.INFORMATION),
        ("我好焦虑，这正常吗", CrisisLevel.L0, EmpathyIntent.VALIDATION),  # elevated: no 4
        ("好伤心，这正常吗", CrisisLevel.L0, EmpathyIntent.VALIDATION),  # valence <= -0.70
        ("好伤心", CrisisLevel.L0, EmpathyIntent.VALIDATION),  # 5. valence
        ("今天挺好的", CrisisLevel.L1, EmpathyIntent.VALIDATION),  # 5. L1
        ("我只想说说", CrisisLevel.L0, EmpathyIntent.VALIDATION),  # 5. lock on
        ("好迷茫", CrisisLevel.L0, EmpathyIntent.REFLECTION),  # 6. confusion
        ("今天挺好的", CrisisLevel.L0, EmpathyIntent.EXPLORATION),  # 7. otherwise
    ],
)
def test_intent_follows_the_guide_order(
    stub: RuleStub, text: str, level: CrisisLevel, intent: EmpathyIntent
) -> None:
    ctx, _ = stub.perceive(text, _assessment(level, 0.0))
    assert ctx.empathy_intent == intent.value


def test_validation_emotions_without_a_question(stub: RuleStub) -> None:
    ctx, _ = stub.perceive("好孤独", _assessment())
    assert ctx.fine_grained_emotion == "loneliness"
    assert ctx.empathy_intent == EmpathyIntent.VALIDATION


# -- placeholders until P6 -----------------------------------------------------------


def test_placeholder_heads(stub: RuleStub, tax: Taxonomy) -> None:
    ctx, _ = stub.perceive("我好焦虑，都怪他们", _assessment())
    assert ctx.communication_stance == DEFAULT_STANCE == "CONGRUENT"
    assert ctx.readiness_to_change == DEFAULT_READINESS == 0.5
    assert ctx.detected_distortions == () and ctx.detected_schemas == ()
    assert ctx.deep_yearning == tax.values("satir_yearnings")[0] == "SAFETY"


# -- perception window ---------------------------------------------------------------


def test_only_the_head_and_tail_window_is_scanned(stub: RuleStub) -> None:
    filler = "今天去了趟超市买了点菜" * 60
    middle = filler[: PERCEPTION_HEAD + 50] + "我好焦虑" + filler[: PERCEPTION_TAIL + 50]
    ctx, _ = stub.perceive(middle, _assessment())
    assert ctx.fine_grained_emotion == "calm"
    tail = filler + "我好焦虑"
    ctx, _ = stub.perceive(tail, _assessment())
    assert ctx.fine_grained_emotion == "anxiety"


def test_constructor_requires_the_default_stance(lexicon: PerceptionLexicon) -> None:
    data = _taxonomy_data()
    stances = data["communication_stances"]
    data["communication_stances"] = [s for s in stances if s["id"] != DEFAULT_STANCE]
    with pytest.raises(ValueError, match=DEFAULT_STANCE):
        RuleStub(Taxonomy(data), lexicon)


def _taxonomy_data() -> dict[str, Any]:
    path = Path(__file__).resolve().parents[2] / "olivia" / "data" / "taxonomy.yaml"
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def test_intent_valence_cut_offs_come_from_the_taxonomy(lexicon: PerceptionLexicon) -> None:
    text = "好伤心，这正常吗"  # sadness: valence -0.70, below the elevated band
    default, _ = RuleStub(load_taxonomy(), lexicon).perceive(text, _assessment())
    assert default.empathy_intent == EmpathyIntent.VALIDATION
    data = _taxonomy_data()
    data["intent_rules"]["information_min_valence"] = -0.80
    relaxed, _ = RuleStub(Taxonomy(data), lexicon).perceive(text, _assessment())
    assert relaxed.empathy_intent == EmpathyIntent.INFORMATION


def test_validation_cut_off_comes_from_the_taxonomy(lexicon: PerceptionLexicon) -> None:
    text = "好迷茫"  # confusion: valence -0.35, so step 5 passes and step 6 answers
    data = _taxonomy_data()
    data["intent_rules"]["validation_max_valence"] = -0.30
    ctx, _ = RuleStub(Taxonomy(data), lexicon).perceive(text, _assessment())
    assert ctx.empathy_intent == EmpathyIntent.VALIDATION


@pytest.mark.parametrize("key", ["information_min_valence", "validation_max_valence"])
def test_missing_intent_rule_fails_at_construction(lexicon: PerceptionLexicon, key: str) -> None:
    data = _taxonomy_data()
    del data["intent_rules"][key]
    with pytest.raises(TaxonomyError, match=f"intent_rules.{key}"):
        RuleStub(Taxonomy(data), lexicon)
