import pytest

from olivia.core.models import CrisisLevel as L
from olivia.core.safety.crisis import RiskPrediction, RuleRiskModel, SafetyScreen, arbitrate
from olivia.core.safety.lexicon import load_safety_lexicons
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
