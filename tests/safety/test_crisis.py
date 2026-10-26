from dataclasses import replace
from fractions import Fraction

import pytest

from olivia.core.models import CrisisLevel as L
from olivia.core.safety.crisis import (
    RiskPrediction,
    RuleRiskModel,
    SafetyScreen,
    _MaskCover,
    arbitrate,
)
from olivia.core.safety.lexicon import DenialRules, load_safety_lexicons
from olivia.core.safety.matcher import Match
from olivia.core.taxonomy import load_taxonomy


@pytest.fixture(scope="module")
def tax():
    return load_taxonomy()


@pytest.fixture(scope="module")
def screen(tax):
    return SafetyScreen(tax, load_safety_lexicons(tax))


@pytest.mark.parametrize(
    "text,level,stage",
    [
        ("今天开会好累，想早点下班", L.L0, "STAGE2"),
        ("活着好累，每天都一样", L.L1, "STAGE2"),
        ("我真的想死", L.L2, "STAGE2"),
        ("[5%] 不想活了", L.L2, "STAGE2"),
        ("药已经买好了，今晚", L.L3, "STAGE1"),
        ("遗书写好了", L.L3, "STAGE1"),
    ],
)
def test_levels(screen, text, level, stage):
    a = screen.assess(text)
    assert (a.level, a.stage) == (level, stage)


@pytest.mark.parametrize("text", ["想死的心都有了", "加班到十点，累死了", "这个视频笑死"])
def test_hyperbole_is_not_ideation(screen, text):
    a = screen.assess(text)
    assert a.level is L.L0 and a.score == pytest.approx(0.1)


@pytest.mark.parametrize("text", ["其实我不想死，只是太累了", "我绝不想自杀", "我没想过自杀"])
def test_pure_negation_scores_below_point_15(screen, text):  # MIYI-02 第一条
    a = screen.assess(text)
    assert a.level is L.L0 and a.score < 0.15


def test_negation_does_not_hide_means(screen):  # MIYI-02 第二条
    a = screen.assess("我不想死，但药已经买好了")
    assert a.level is L.L3 and a.score >= 0.8 and a.has_plan_evidence
    assert a.cue_ids == ("S1_MEANS_PILLS",)


def test_negation_does_not_hide_other_ideation(screen):
    assert screen.assess("我不想死，可是真的活不下去了").level is L.L2


def test_cue_at_end_of_long_text(screen):
    a = screen.assess("今天发生了很多事。" * 120 + "我想结束自己的生命")
    assert a.level is L.L2


def test_variants_are_normalized(screen):
    assert screen.assess("我 想 死").level is L.L2
    assert screen.assess("遗书 写好了").level is L.L3


def test_assessment_carries_cue_ids_not_text(screen):
    a = screen.assess("我真的想死")
    assert a.cue_ids == ("L2_WANT_DIE",)
    assert all("想" not in cue for cue in a.cue_ids)


def test_strongest_stage2_cue_wins(screen):
    a = screen.assess("活着好累，不想活了")
    assert a.level is L.L2 and a.score == pytest.approx(0.7)
    assert set(a.cue_ids) == {"L1_WEARY", "L2_NOT_WANT_LIVE"}


@pytest.mark.parametrize(
    "l_cls,score,evidence,expected",
    [
        (L.L1, 0.6, False, L.L2),  # 取高
        (L.L2, 0.1, False, L.L2),  # 取高
        (L.L3, 0.9, False, L.L2),  # 无证据降级
        (L.L1, 0.85, False, L.L2),  # 分数 L3 无证据降级
        (L.L3, 0.9, True, L.L3),
        (L.L0, 0.0, False, L.L0),
    ],
)
def test_arbitrate(tax, l_cls, score, evidence, expected):
    assert arbitrate(tax, l_cls, score, evidence) is expected


def test_model_l3_without_evidence_is_downgraded(tax):
    class FakeModel:
        def predict(self, text):
            return RiskPrediction(L.L3, 0.95, ())

    a = SafetyScreen(tax, load_safety_lexicons(tax), FakeModel()).assess("随便说点什么")
    assert a.level is L.L2 and a.stage == "STAGE2" and not a.has_plan_evidence


def test_rule_model_predict_matches_screen(tax):
    lexicons = load_safety_lexicons(tax)
    prediction = RuleRiskModel(tax, lexicons).predict("[5%] 不想活了")
    assert prediction == RiskPrediction(L.L2, 0.7, ("L2_NOT_WANT_LIVE",))


@pytest.mark.parametrize(
    "text,level",
    [
        ("我想自殺", L.L2),
        ("遺書寫好了", L.L3),
        ("安眠藥已經買好了", L.L3),
        ("我想結束自己的生命", L.L2),
        ("我已經吃了三十片安眠藥", L.L3),
        ("活著好累", L.L1),
    ],
)
def test_traditional_chinese_is_screened(screen, text, level):
    assert screen.assess(text).level is level


class _FixedModel:
    def __init__(self, level, score):
        self._prediction = RiskPrediction(level, score, ("FAKE",))

    def predict(self, text):
        return self._prediction


class _RaisingModel:
    def predict(self, text):
        raise RuntimeError("model crashed")


def _screen_with(tax, model):
    return SafetyScreen(tax, load_safety_lexicons(tax), model)


def test_model_exception_fails_safe_to_l2(tax):
    a = _screen_with(tax, _RaisingModel()).assess("随便说点什么")
    assert a.level is L.L2 and a.stage == "STAGE2"
    assert a.score == pytest.approx(tax.threshold("risk.lexicon_scores.L2"))
    assert a.cue_ids == ("MODEL_FAILURE",)


@pytest.mark.parametrize("score", [float("nan"), float("inf"), 1.2, -0.1])
def test_invalid_model_score_fails_safe_to_l2(tax, score):
    a = _screen_with(tax, _FixedModel(L.L0, score)).assess("随便说点什么")
    assert a.level is L.L2 and a.cue_ids == ("MODEL_FAILURE",)


@pytest.mark.parametrize("level", [2, "L2", None])
def test_model_level_not_a_crisis_level_fails_safe_to_l2(tax, level):
    a = _screen_with(tax, _FixedModel(level, 0.5)).assess("随便说点什么")
    assert a.level is L.L2 and a.cue_ids == ("MODEL_FAILURE",)


def test_model_returning_wrong_type_fails_safe_to_l2(tax):
    class WrongType:
        def predict(self, text):
            return (L.L0, 0.0)

    a = _screen_with(tax, WrongType()).assess("随便说点什么")
    assert a.level is L.L2 and a.cue_ids == ("MODEL_FAILURE",)


def test_rules_stay_a_floor_under_an_injected_model(tax):
    a = _screen_with(tax, _FixedModel(L.L0, 0.0)).assess("我想死")
    assert a.level is L.L2 and "L2_WANT_DIE" in a.cue_ids


def test_injected_model_can_raise_above_the_rule_floor(tax):
    a = _screen_with(tax, _FixedModel(L.L2, 0.7)).assess("今天吃了面")
    assert a.level is L.L2 and a.cue_ids == ("FAKE",)


def test_injected_model_failure_keeps_stage1(tax):
    a = _screen_with(tax, _RaisingModel()).assess("遗书写好了")
    assert a.level is L.L3 and a.stage == "STAGE1"


class _CueIdsModel:
    def __init__(self, cue_ids):
        self._prediction = RiskPrediction(L.L0, 0.0, cue_ids)

    def predict(self, text):
        return self._prediction


@pytest.mark.parametrize("cue_ids", [None, "FAKE", ([],), (1,), ["FAKE", {}]])
def test_malformed_model_cue_ids_fail_safe_to_l2(tax, cue_ids):
    a = _screen_with(tax, _CueIdsModel(cue_ids)).assess("随便说点什么")
    assert a.level is L.L2 and a.cue_ids == ("MODEL_FAILURE",)


def test_model_cue_ids_list_is_accepted_as_a_tuple(tax):
    a = _screen_with(tax, _CueIdsModel(["FAKE"])).assess("随便说点什么")
    assert a.cue_ids == ("FAKE",)


def test_model_score_of_any_real_number_type_is_accepted(tax):
    # Stands in for numpy.float32, which is registered as numbers.Real like Fraction.
    a = _screen_with(tax, _FixedModel(L.L2, Fraction(7, 10))).assess("今天吃了面")
    assert a.level is L.L2 and a.cue_ids == ("FAKE",)
    assert type(a.score) is float and a.score == pytest.approx(0.7)


def test_numeric_string_score_is_out_of_contract(tax):
    a = _screen_with(tax, _FixedModel(L.L0, "0.1")).assess("随便说点什么")
    assert a.cue_ids == ("MODEL_FAILURE",)


@pytest.mark.parametrize(
    ("span", "covered"),
    [((3, 6), True), ((0, 10), True), ((4, 11), False), ((12, 13), False), ((10, 12), True)],
)
def test_mask_cover_uses_the_widest_earlier_mask(span, covered):
    # A short mask starting after a long one must not shadow the long one's coverage.
    masks = [Match("A", 0, 10), Match("B", 2, 4), Match("C", 10, 12)]
    assert _MaskCover(masks).contains(Match("X", *span)) is covered


def _evidence_screen(tax, model=None, *, model_plan_evidence=True):
    return SafetyScreen(
        tax, load_safety_lexicons(tax), model, model_plan_evidence=model_plan_evidence
    )


def test_model_plan_evidence_is_off_by_default(tax):
    a = _evidence_screen(tax, _FixedModel(L.L3, 0.95), model_plan_evidence=False).assess(
        "随便说点什么"
    )
    assert a.level is L.L2 and a.stage == "STAGE2" and not a.has_plan_evidence


def test_model_plan_evidence_lets_model_l3_stay_l3(tax):
    a = _evidence_screen(tax, _FixedModel(L.L3, 0.95)).assess("随便说点什么")
    assert (a.level, a.stage, a.has_plan_evidence) == (L.L3, "STAGE2", True)
    assert a.score == pytest.approx(0.95) and a.cue_ids == ("FAKE",)


def test_model_plan_evidence_keeps_the_rule_floor_cues(tax):
    a = _evidence_screen(tax, _FixedModel(L.L3, 0.9)).assess("我真的想死")
    assert a.level is L.L3 and a.has_plan_evidence
    assert a.cue_ids == ("L2_WANT_DIE", "FAKE")


def test_model_plan_evidence_model_exception_stays_l2(tax):
    a = _evidence_screen(tax, _RaisingModel()).assess("随便说点什么")
    assert a.level is L.L2 and not a.has_plan_evidence
    assert a.cue_ids == ("MODEL_FAILURE",)


@pytest.mark.parametrize(
    "model",
    [
        _FixedModel(L.L3, float("nan")),
        _FixedModel(L.L3, 1.2),
        _FixedModel("L3", 0.95),
        _CueIdsModel(None),
    ],
)
def test_model_plan_evidence_invalid_prediction_stays_l2(tax, model):
    a = _evidence_screen(tax, model).assess("随便说点什么")
    assert a.level is L.L2 and not a.has_plan_evidence
    assert a.cue_ids == ("MODEL_FAILURE",)


@pytest.mark.parametrize("score", [0.7, 0.95])
def test_model_plan_evidence_model_l2_stays_l2(tax, score):
    # Even a score in the L3 band is not plan evidence when the model's level is L2.
    a = _evidence_screen(tax, _FixedModel(L.L2, score)).assess("我真的想死")
    assert a.level is L.L2 and a.stage == "STAGE2" and not a.has_plan_evidence


@pytest.mark.parametrize(
    "text",
    [
        "今天开会好累，想早点下班",
        "活着好累，每天都一样",
        "我真的想死",
        "想死的心都有了",
        "遗书写好了",
    ],
)
def test_model_plan_evidence_without_a_model_changes_nothing(tax, screen, text):
    assert _evidence_screen(tax).assess(text) == screen.assess(text)


@pytest.mark.parametrize(
    "model", [_FixedModel(L.L0, 0.0), _FixedModel(L.L3, 0.95), _RaisingModel()]
)
def test_model_plan_evidence_leaves_stage1_unchanged(tax, screen, model):
    a = _evidence_screen(tax, model).assess("药已经买好了，今晚")
    assert a == screen.assess("药已经买好了，今晚")
    assert (a.level, a.stage, a.has_plan_evidence) == (L.L3, "STAGE1", True)


@pytest.mark.parametrize(
    ("level", "score", "expected"),
    [
        (L.L0, 0.25, L.L1),
        (L.L0, 0.6, L.L2),
        (L.L1, 0.6, L.L2),
        (L.L1, 0.85, L.L2),  # the L3 band without plan evidence is L2
        (L.L2, 0.1, L.L2),
    ],
)
def test_injected_model_level_is_the_higher_of_its_level_and_score_band(
    tax, level, score, expected
):
    a = _screen_with(tax, _FixedModel(level, score)).assess("今天吃了面")
    assert a.level is expected and a.rule_level is L.L0 and a.score == pytest.approx(score)


def test_rule_level_stays_the_floor_under_a_low_model_score(tax):
    a = _screen_with(tax, _FixedModel(L.L0, 0.0)).assess("活着好累，每天都一样")
    assert a.level is L.L1 and a.score == pytest.approx(0.4)


@pytest.mark.parametrize("text", ["我想死你们了", "真想死他了", "想死你了，好久没见"])
def test_injected_model_is_at_most_l1_where_a_hyperbole_cue_covers_every_risk_phrase(tax, text):
    # F8a: the rules read "想死" here as "miss you"; the model's L2 or L3 counts as L1.
    for level in (L.L2, L.L3):
        a = _screen_with(tax, _FixedModel(level, 0.9)).assess(text)
        assert a.level is L.L1 and a.rule_level is L.L0 and a.cue_ids[-1] == "FAKE"


@pytest.mark.parametrize(
    ("text", "level"),
    [
        # A real risk phrase next to the idiom is not covered by the hyperbole cue.
        ("想死你了，可是我最近真的想死", L.L2),
        # Negation masks get no hyperbole cap: the model's L2 on a double negation is kept.
        ("很难说我不想死", L.L2),
        ("说我不想死，那是假的", L.L2),
    ],
)
def test_the_hyperbole_cap_needs_every_risk_phrase_figurative(tax, text, level):
    assert _screen_with(tax, _FixedModel(L.L2, 0.9)).assess(text).level is level


def test_a_model_failure_on_an_idiom_still_fails_safe_to_l2(tax):
    a = _screen_with(tax, _RaisingModel()).assess("我想死你们了")
    assert a.level is L.L2 and a.cue_ids[-1] == "MODEL_FAILURE"


@pytest.mark.parametrize("model", [_FixedModel(L.L0, 0.0), _FixedModel(L.L1, 0.3)])
def test_negation_with_means_stays_l3_whatever_the_model_says(tax, model):
    a = _screen_with(tax, model).assess("我不想死，但药已经买好了")
    assert (a.level, a.stage, a.rule_level) == (L.L3, "STAGE1", L.L3)


@pytest.mark.parametrize(
    ("text", "level"), [("药我都攒够了", L.L2), ("我不会伤害自己的，药我都攒够了", L.L3)]
)
def test_hoarded_pills_are_rated_by_the_rules_and_never_denial_capped(tax, screen, text, level):
    # F16a: the rules used to rate both L0. Hoarded pills are L2 without a death word
    # (L2_MEANS_HOARDED) and Stage 1 with one (伤害自己 is a death context); the denial is
    # never a cap on them, whatever the model says.
    assert screen.assess(text).level is level
    for model in (_FixedModel(L.L0, 0.0), _FixedModel(L.L1, 0.3), _FixedModel(L.L2, 0.9)):
        a = _screen_with(tax, model).assess(text)
        assert a.level is level and a.rule_level is level and a.uncapped_level is None


def test_rule_level_is_the_rules_own_level(tax, screen):
    assert screen.assess("活着好累，每天都一样").rule_level is L.L1
    a = _screen_with(tax, _FixedModel(L.L2, 0.7)).assess("今天吃了面")
    assert (a.level, a.rule_level) == (L.L2, L.L0)


_DENIALS = [
    "我不会伤害自己",
    "我没有想死",
    "我不想死，只是很累",
    "我已经好多了",
    "就是有点烦，不是想死",
]


@pytest.mark.parametrize("text", _DENIALS)
def test_injected_model_is_at_most_l1_on_a_first_person_denial(tax, text):
    # F10: only the model rates these L2/L3; the cap keeps a crisis from opening on them.
    for model, uncapped in ((_FixedModel(L.L2, 0.5), L.L2), (_FixedModel(L.L3, 0.9), L.L2)):
        a = _screen_with(tax, model).assess(text)
        assert (a.level, a.rule_level, a.uncapped_level) == (L.L1, L.L0, uncapped)
        assert a.cue_ids[-1] == "FAKE" and not a.has_plan_evidence


@pytest.mark.parametrize(
    "text",
    [
        # A contrast after the denial, whatever follows it.
        "我不想死，可是真的撑不下去了",
        "我不想死，但是那个念头一直都在",
        "我没事，不过有时候会想很多",
        # Double negations, retractions and hedges.
        "我不是不想死",
        "其实我没有不想死",
        "不是我不想死",
        "谁说我不想死",
        "很难说我不想死",
        "说我不想死，那是假的",
        "我现在还不想死",
        "我暂时不会伤害自己",
        "我今天不想死",
        "I don't want to die today, just venting",
        # Means, time, farewell and preparation.
        "我不想死，但药已经买好了",
        "我没事，今晚就去",
        "我不会伤害自己，东西都准备好了",
        "我已经好多了，跟大家说声再见",
        # A means word is a veto even where no rule rates the message (F16a).
        "我不会伤害自己的，药我都攒着呢",
        # A risk phrase the denial does not cover.
        "我没事，就是想消失",
    ],
)
def test_the_denial_cap_needs_a_plain_denial(tax, text):
    a = _screen_with(tax, _FixedModel(L.L2, 0.6)).assess(text)
    assert a.level >= L.L2 and a.uncapped_level is None


@pytest.mark.parametrize(
    "text",
    [
        # F16a: risk content after a denial joined by 只是 / 就是 (no contrast word), which the
        # cap used to lower to L1. A wish not to wake or never to have been born (L2).
        "我不想死，我想永远睡过去",
        "我不想死，只是想永远睡过去",
        "我好多了，只是想永远睡过去",
        "我不想死，只是想一觉睡过去",
        "我没事，只是想一直睡下去",
        "我没想死，只是想长眠",
        "我不想死，只是不想再睁开眼睛",
        "我不想死，只是常常希望自己没出生",
        # Means.
        "我不想死，只是想吞一整瓶药",
        "我不想死，只是在网上查了很多吃药的事",
        # Time and place.
        "我不想死，就是今晚想去楼顶看看",
        # Farewell, giving away, leaving to someone, joining the dead, leaving early.
        "我没事，就是想把东西都送人",
        "我好多了，就是东西都送人了",
        "我不想死，只是钱都留给你们了",
        "我没事，就是想把猫托付给你",
        "我没事，只是想最后见你一面",
        "我不会伤害自己，只是想和这个世界说再见",
        "我不想死，只是想去天上陪奶奶",
        "我不想死，只是想早点走",
        # Rule cues of their own (L1 weariness, D3 asks).
        "我不想死，只是想解脱",
        "我不想死，只是想消失",
        "我不想死，只是觉得没有我大家会更好",
        "我不想自杀，只是想让一切结束",
    ],
)
def test_the_denial_cap_never_hides_risk_content_after_the_denial(tax, text):
    for model in (_FixedModel(L.L2, 0.6), _FixedModel(L.L3, 0.9)):
        a = _screen_with(tax, model).assess(text)
        assert a.level >= L.L2 and a.uncapped_level is None, text


@pytest.mark.parametrize("lead", ["我不想死，", "我不想死，只是", "我没事，就是", "我已经好多了，"])
def test_every_stage2_phrase_voids_the_denial_cap(tax, lead):
    # F16a: a Stage 2 phrase the denial does not cover keeps the rules above L0, so the cap
    # never applies; whatever the model says, the level stays at least the phrase's own.
    lexicons = load_safety_lexicons(tax)
    screen = _screen_with(tax, _FixedModel(L.L2, 0.6))
    for cue in lexicons.cues("stage2"):
        for phrase in cue.patterns:
            a = screen.assess(lead + phrase)
            assert a.level >= L.L2 and a.uncapped_level is None, (lead, phrase, a)


@pytest.mark.parametrize(
    "text",
    [
        "我妈生日是哪天来着",
        "我妈生日是几号来着",
        "我上次让你记的我妈生日是哪天",
        "我该吃的药是几点来着",
    ],
)
def test_injected_model_is_at_most_l1_on_a_plain_note_question(tax, screen, text):
    # F16a: a note recall phrase and not one risk word; the model's L2/L3 counts as L1.
    assert screen.assess(text).level is L.L0
    for model in (_FixedModel(L.L2, 0.5), _FixedModel(L.L3, 0.9)):
        a = _screen_with(tax, model).assess(text)
        assert (a.level, a.rule_level, a.uncapped_level) == (L.L1, L.L0, None)
        assert a.cue_ids[-1] == "FAKE" and not a.has_plan_evidence


@pytest.mark.parametrize(
    "text",
    [
        "我妈生日是哪天来着，我不想活了",  # a Stage 2 phrase
        "我上次让你记的遗书放在哪来着",  # a death word
        "安眠药放在哪来着",  # a means
        "王师傅是谁来着，以后也用不上了",  # a farewell
        "累死了，王师傅是谁来着",  # a hyperbole phrase is still a risk phrase
        "我没事，王师傅是谁来着",  # a denial phrase: the denial cap decides
        "王师傅是谁来着，一次吃几片来着",  # a dose
        "今天加班好累",  # no note question at all
    ],
)
def test_the_note_question_cap_needs_a_question_and_no_risk_word(tax, text):
    a = _screen_with(tax, _FixedModel(L.L2, 0.6)).assess(text)
    assert a.level >= L.L2 or a.uncapped_level is not None, text


def test_the_note_question_cap_never_lowers_the_rules_or_a_model_failure(tax, screen):
    assert _screen_with(tax, _RaisingModel()).assess("我妈生日是哪天来着").level is L.L2
    a = _evidence_screen(tax, _FixedModel(L.L3, 0.95)).assess("我妈生日是哪天来着")
    assert (a.level, a.has_plan_evidence) == (L.L1, False)


def test_a_model_failure_on_a_denial_still_fails_safe_to_l2(tax):
    a = _screen_with(tax, _RaisingModel()).assess("我没有想死")
    assert a.level is L.L2 and a.cue_ids[-1] == "MODEL_FAILURE" and a.uncapped_level is None


@pytest.mark.parametrize("model", [_FixedModel(L.L0, 0.1), _FixedModel(L.L1, 0.3)])
def test_the_denial_cap_leaves_a_model_l0_or_l1_alone(tax, model):
    a = _screen_with(tax, model).assess("我没有想死")
    assert a.uncapped_level is None and a.level <= L.L1


def test_the_denial_cap_blocks_model_plan_evidence(tax):
    a = _evidence_screen(tax, _FixedModel(L.L3, 0.95)).assess("我不会伤害自己")
    assert (a.level, a.uncapped_level, a.has_plan_evidence) == (L.L1, L.L3, False)


@pytest.mark.parametrize("text", _DENIALS)
def test_the_rules_alone_are_unchanged_by_the_denial_cap(screen, text):
    a = screen.assess(text)
    assert a.level is L.L0 and a.uncapped_level is None


@pytest.mark.parametrize("text", ["我不想死但好累", "我没事可是心里很乱", "我已经好多了不过还是怕"])
def test_a_contrast_right_after_the_denial_voids_the_cap(tax, text):
    # A contrast word directly after the denial, with no comma between, still voids the cap.
    a = _screen_with(tax, _FixedModel(L.L2, 0.6)).assess(text)
    assert a.level >= L.L2 and a.uncapped_level is None


@pytest.mark.parametrize("text", ["我没事，没有想要自杀", "我好多了，不要去死"])
def test_a_masked_risk_phrase_outside_the_denial_voids_the_cap(tax, text):
    # A Stage 2 phrase a negation masks, but no denial phrase covers, keeps the model's L2.
    a = _screen_with(tax, _FixedModel(L.L2, 0.6)).assess(text)
    assert a.rule_level is L.L0
    assert a.level >= L.L2 and a.uncapped_level is None


def test_a_hyperbole_after_a_denial_keeps_the_cap(tax):
    # Only Stage 2 phrases void the cap: a hyperbole phrase outside the denial does not.
    a = _screen_with(tax, _FixedModel(L.L2, 0.6)).assess("我没事，笑死我了")
    assert (a.level, a.uncapped_level) == (L.L1, L.L2)


def test_a_denial_next_to_a_pair_phrase_does_not_crash(tax):
    # Pair anchors are matches without a risk cue; the denial check must skip them.
    lexicons = load_safety_lexicons(tax)
    screen = _screen_with(tax, _FixedModel(L.L2, 0.6))
    for pair in (*lexicons.pairs, *lexicons.ask_pairs):
        screen.assess("我没事，" + pair.anchors[0])


def test_a_model_score_of_exactly_one_is_in_contract(tax):
    a = _screen_with(tax, _FixedModel(L.L2, 1.0)).assess("今天吃了面")
    assert "MODEL_FAILURE" not in a.cue_ids and a.score == 1.0


def test_without_denial_phrases_the_denial_cap_is_off(tax):
    # An empty denial section means no cap at all, not a cap on every rule-L0 turn.
    lexicons = replace(load_safety_lexicons(tax), denial=DenialRules())
    a = SafetyScreen(tax, lexicons, _FixedModel(L.L2, 0.6)).assess("我不会伤害自己")
    assert a.level is L.L2 and a.uncapped_level is None


@pytest.mark.parametrize("tail", ["don't want to die", "not suicidal"])
def test_the_note_recall_cap_needs_no_risk_phrase_at_all(tax, tail):
    # An English negation phrase has no Chinese veto word, yet it is a risk phrase: no cap.
    a = _screen_with(tax, _FixedModel(L.L2, 0.6)).assess("我妈生日是哪天来着，" + tail)
    assert a.level is L.L2
