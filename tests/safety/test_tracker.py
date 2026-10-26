import copy
from pathlib import Path

import pytest
import yaml

from olivia.core.models import CrisisLevel as L
from olivia.core.safety.crisis import CrisisAssessment, SafetyScreen
from olivia.core.safety.lexicon import load_safety_lexicons
from olivia.core.safety.tracker import CrisisTracker
from olivia.core.taxonomy import Taxonomy, load_taxonomy


@pytest.fixture(scope="module")
def tax():
    return load_taxonomy()


@pytest.fixture(scope="module")
def lex(tax):
    return load_safety_lexicons(tax)


@pytest.fixture
def run(tax, lex):
    screen = SafetyScreen(tax, lex)
    tracker = CrisisTracker(tax, lex)
    return lambda text, valence=None: tracker.observe(screen.assess(text), text, valence)


def _a(level, score):
    return CrisisAssessment(
        level=level, score=score, stage="STAGE2", has_plan_evidence=False, cue_ids=()
    )


def test_plain_l1_escalates_on_third_turn_without_improvement(run):
    # Owner decision 2026-10-24: cue strength no longer matters (the old EWMA gate of 0.45
    # could never be reached by plain 0.40 cues, so these never escalated).
    s1, s2, s3 = (run("活着好累") for _ in range(3))
    assert s1.level is L.L1 and s2.level is L.L1 and not s2.in_crisis
    assert s3.level is L.L2 and s3.escalated and s3.in_crisis and s3.just_entered


def test_strong_l1_escalates_on_third_turn(run):
    s1, s2, s3 = (run("好想人间蒸发") for _ in range(3))
    assert s1.level is L.L1 and s2.level is L.L1
    assert s3.level is L.L2 and s3.escalated and s3.in_crisis and s3.just_entered


@pytest.mark.parametrize(
    "valences",
    [
        (-0.5, -0.5, -0.5),  # flat is no improvement
        (-0.3, -0.5, -0.7),  # worsening
        (None, None, None),  # no emotion evidence is never an improvement
        (-0.5, None, -0.6),
        (None, -0.7, -0.7),
        (0.6, 0.6, 0.6),  # a positive word on an L1 turn is not an improvement by itself
    ],
)
def test_three_l1_turns_without_improvement_escalate(tax, lex, valences):
    t = CrisisTracker(tax, lex)
    statuses = [t.observe(_a(L.L1, 0.40), "x", v) for v in valences]
    assert [s.consecutive_l1_count for s in statuses[:2]] == [1, 2]
    assert statuses[-1].level is L.L2 and statuses[-1].escalated


@pytest.mark.parametrize(
    "valences,expected",
    [
        ((-0.7, -0.5, -0.5), [1, 0, 1]),  # valence up on the second turn
        ((-0.7, None, -0.6), [1, 2, 0]),  # compared with the last known L1 valence
        ((-0.8, -0.7, -0.6), [1, 0, 0]),  # steadily improving never escalates
    ],
)
def test_an_improving_l1_turn_resets_the_count(tax, lex, valences, expected):
    t = CrisisTracker(tax, lex)
    statuses = [t.observe(_a(L.L1, 0.40), "x", v) for v in valences]
    assert [s.consecutive_l1_count for s in statuses] == expected
    assert all(s.level is L.L1 and not s.in_crisis for s in statuses)


@pytest.mark.parametrize("valence", [0.0, 0.6, -0.5])
def test_a_calm_or_improving_l0_turn_resets_the_count(tax, lex, valence):
    # 0.0 and 0.6 are calm; -0.5 is up on the last L1 turn's -0.7.
    t = CrisisTracker(tax, lex)
    t.observe(_a(L.L1, 0.40), "x", -0.7)
    t.observe(_a(L.L1, 0.40), "x", -0.7)
    assert t.observe(_a(L.L0, 0.0), "x", valence).consecutive_l1_count == 0
    assert t.observe(_a(L.L1, 0.40), "x", -0.7).level is L.L1


@pytest.mark.parametrize("valence", [None, -0.8])
def test_other_l0_turns_pause_the_count(tax, lex, valence):
    t = CrisisTracker(tax, lex)
    t.observe(_a(L.L1, 0.40), "x", -0.7)
    t.observe(_a(L.L1, 0.40), "x", -0.7)
    assert t.observe(_a(L.L0, 0.0), "x", valence).consecutive_l1_count == 2
    assert t.observe(_a(L.L1, 0.40), "x", -0.7).level is L.L2


def test_non_finite_valence_is_no_evidence(tax, lex):
    t = CrisisTracker(tax, lex)
    statuses = [t.observe(_a(L.L1, 0.40), "x", v) for v in (-0.7, float("nan"), float("inf"))]
    assert statuses[-1].level is L.L2


def test_an_infinite_valence_is_no_improvement(tax, lex):
    # +inf on the middle turn must not count as a rise that clears the run.
    t = CrisisTracker(tax, lex)
    statuses = [t.observe(_a(L.L1, 0.40), "x", v) for v in (-0.7, float("inf"), -0.7)]
    assert statuses[-1].escalated and statuses[-1].level is L.L2


@pytest.mark.parametrize("valence", [0.0, 0.4])
def test_a_calm_l0_resets_the_count_without_an_earlier_l1_valence(tax, lex, valence):
    # Calm alone resets: no earlier L1 valence is there for a rise to be measured against.
    t = CrisisTracker(tax, lex)
    t.observe(_a(L.L1, 0.40), "x")
    t.observe(_a(L.L1, 0.40), "x")
    assert t.observe(_a(L.L0, 0.0), "x", valence).consecutive_l1_count == 0
    assert not t.observe(_a(L.L1, 0.40), "x").escalated


def test_a_slightly_negative_l0_turn_only_pauses_the_count(tax, lex):
    # Calm starts at 0.0: a valence just below it is no reset.
    t = CrisisTracker(tax, lex)
    t.observe(_a(L.L1, 0.40), "x")
    t.observe(_a(L.L1, 0.40), "x")
    assert t.observe(_a(L.L0, 0.0), "x", -0.2).consecutive_l1_count == 2
    assert t.observe(_a(L.L1, 0.40), "x").escalated


def test_isolated_l0_does_not_break_streak(run):
    run("好想人间蒸发")
    run("今天吃了面")
    run("好想人间蒸发")
    assert run("好想人间蒸发").level is L.L2


def test_three_l0_turns_clear_streak(run):
    run("好想人间蒸发")
    run("好想人间蒸发")
    for _ in range(3):
        run("今天吃了面")
    assert run("好想人间蒸发").level is L.L1


def test_l2_exit_needs_confirmation_then_two_safe_turns(run):
    assert run("我想死").in_crisis
    assert run("今天吃了面").awaiting_confirmation  # 没有确认，不计数
    s = run("我现在安全了")
    assert s.in_crisis and not s.awaiting_confirmation and s.safe_turns_remaining == 2
    assert run("今天吃了面").in_crisis
    s = run("今天吃了面")
    assert not s.in_crisis and s.just_exited


def test_l3_exit_needs_three_safe_turns(run):
    run("遗书写好了")
    run("我联系上朋友了")
    assert run("嗯").in_crisis and run("嗯").in_crisis
    assert run("嗯").just_exited


def test_confirmation_inside_crisis_message_is_ignored(run):
    run("我想死")
    s = run("我现在安全了，但还是想死")
    assert s.level is L.L2 and s.in_crisis and s.awaiting_confirmation


def test_relapse_during_exit_resets_and_raises_entry_level(run):
    run("我想死")
    run("我现在安全了")
    run("嗯")
    s = run("药已经买好了")
    assert s.in_crisis and s.entry_level is L.L3 and s.awaiting_confirmation


def test_battery_prefix_cannot_bypass_crisis(run):
    run("我想死")
    s = run("[5%] 好累")
    assert s.in_crisis and s.awaiting_confirmation


@pytest.mark.parametrize(
    "phrase",
    [
        "我不觉得我现在安全了",
        "你觉得我现在安全了吗",
        "我现在没事了才怪",
        "我现在安全了？",
        "我没有联系上朋友了",
    ],
)
def test_negated_questioned_or_sarcastic_confirmation_does_not_count(run, phrase):
    assert run("我想死").in_crisis
    run(phrase)
    for _ in range(3):
        s = run("嗯")
    assert s.in_crisis and s.awaiting_confirmation and not s.just_exited


def test_confirmation_with_topic_change_still_counts(run):
    run("我想死")
    s = run("我现在安全了，想聊点别的")
    assert s.in_crisis and not s.awaiting_confirmation and s.safe_turns_remaining == 2
    assert run("嗯").in_crisis
    assert run("嗯").just_exited


def test_crisis_entry_resets_the_l1_trend(run):
    # Reviewer sequence: the L2 score must not leak into the L1 escalation trend.
    run("活着好累")
    run("活着好累")
    assert run("我想死").just_entered
    assert not run("我现在安全了").awaiting_confirmation
    s = run("活着好累")
    assert s.level is L.L1 and not s.escalated
    assert s.in_crisis and not s.awaiting_confirmation and s.safe_turns_remaining == 2


def test_l1_after_confirmation_pauses_the_exit_count(run):
    run("我想死")
    assert run("我现在安全了").safe_turns_remaining == 2
    s = run("活着好累")  # L1 is not a safe turn
    assert s.level is L.L1 and s.in_crisis and s.safe_turns_remaining == 2
    assert run("今天吃了面").safe_turns_remaining == 1
    s = run("活着好累")  # nor does it reset the turns already counted
    assert s.level is L.L1 and s.in_crisis and s.safe_turns_remaining == 1
    assert run("今天吃了面").just_exited


def test_relapse_inside_crisis_also_resets_the_l1_trend(run):
    assert run("遗书写好了").just_entered  # L3 entry: three safe turns to exit
    run("我现在安全了")
    run("活着好累")
    run("活着好累")
    s = run("我又想死了")  # relapse inside crisis, not a new entry
    assert s.level is L.L2 and not s.just_entered and s.awaiting_confirmation
    run("我现在安全了")
    s = run("活着好累")
    assert s.level is L.L1 and not s.escalated and not s.awaiting_confirmation


def test_l1_run_count_is_exposed_on_status_and_tracker(tax, lex):
    screen = SafetyScreen(tax, lex)
    tracker = CrisisTracker(tax, lex)

    def observe(text):
        return tracker.observe(screen.assess(text), text).consecutive_l1_count

    assert tracker.consecutive_l1_count == 0
    assert [observe("活着好累") for _ in range(2)] == [1, 2]
    assert observe("今天吃了面") == 2  # an L0 turn with no valence pauses the run
    assert observe("今天吃了面") == 2
    assert observe("今天吃了面") == 0  # l1_clear_streak L0 turns reset it
    observe("活着好累")
    assert observe("我想死") == 0  # any L2/L3 turn resets the run
    assert tracker.consecutive_l1_count == 0


# -- safety confirmation (fix F2a) ----------------------------------------------------------


@pytest.mark.parametrize(
    "reply",
    [
        "是的，我是安全的",
        "我很安全",
        "我是安全的",
        "我现在是安全的",
        "我没事了",
        "我不会伤害自己",
        "我已经联系上朋友了",
        "我都联系上家人了",
        "我在家，家人在旁边",
        "我给12356打过电话了",
        "我现在已经安全了",
        "朋友在身边",
    ],
)
def test_confirmation_phrases_with_gap_tolerance(run, reply):
    run("我想死")
    s = run(reply)
    assert s.in_crisis and not s.awaiting_confirmation and s.safe_turns_remaining == 2


@pytest.mark.parametrize(
    "reply",
    [
        "是",
        "是的",
        "对",
        "对的",
        "安全",
        "安全的",
        "安全了",
        "嗯安全",
        "嗯，安全的。",
        "嗯 是的",
        "是的，我很安全",
        "我安全",
        "是安全的",
        "Yes",
        "I'm safe",
        "I’m safe",
    ],
)
def test_short_answer_to_the_safety_question_confirms(run, reply):
    assert run("我想死").awaiting_confirmation
    s = run(reply)
    assert s.in_crisis and not s.awaiting_confirmation and s.safe_turns_remaining == 2
    assert run("嗯").in_crisis
    assert run("嗯").just_exited


@pytest.mark.parametrize(
    "reply",
    [
        "嗯",
        "嗯嗯",
        "好",
        "不是",
        "不安全",
        "是不安全的",
        "不是很安全",
        "我不安全",
        "安全吗",
        "是吗",
        "我是",
        "暂时安全",
        "安全吧",
        "是 但还是想死",
        "是的 但是很难受",
        "我觉得我是安全的吗",
        "我不是安全的",
        "说不上安全",
    ],
)
def test_non_answers_do_not_confirm(run, reply):
    run("我想死")
    s = run(reply)
    assert s.in_crisis and s.awaiting_confirmation
    for _ in range(3):
        s = run("嗯")
    assert s.in_crisis and s.awaiting_confirmation


def test_short_answer_outside_crisis_is_ignored(run):
    s = run("是的")
    assert not s.in_crisis and not s.awaiting_confirmation


def test_short_answer_after_relapse_needs_a_new_answer(run):
    run("我想死")
    run("是的")
    s = run("我又想死了")
    assert s.awaiting_confirmation
    assert run("嗯").awaiting_confirmation
    assert not run("安全的").awaiting_confirmation


def _model_l2(rule_level, cue_ids=("FAKE",)):
    return CrisisAssessment(L.L2, 0.6, "STAGE2", False, cue_ids, rule_level=rule_level)


def _in_crisis(tax, lex):
    tracker = CrisisTracker(tax, lex)
    assert tracker.observe(_a(L.L2, 0.7), "x").in_crisis
    return tracker


def test_an_awaited_confirmation_only_a_model_raises_is_not_a_relapse(tax, lex):
    # F8a: the rules read the confirmation at L0; the model's L2 alone does not void it.
    tracker = _in_crisis(tax, lex)
    status = tracker.observe(_model_l2(L.L0), "我不会伤害自己")
    assert status.level is L.L0 and status.in_crisis and not status.awaiting_confirmation
    assert tracker.observe(_a(L.L0, 0.0), "今天天气不错").in_crisis
    assert tracker.observe(_a(L.L0, 0.0), "我去吃饭了").just_exited


@pytest.mark.parametrize(
    ("assessment", "text"),
    [
        # A model failure is not the model's own L2: it still fails toward crisis.
        (_model_l2(L.L0, ("MODEL_FAILURE",)), "我不会伤害自己"),
        # The rules themselves put the turn at L2.
        (_model_l2(L.L2), "我不会伤害自己"),
        # No explicit confirmation.
        (_model_l2(L.L0), "今天天气不错"),
        (_model_l2(L.L0), "我不觉得我是安全的"),
        # No rule level (an assessment built elsewhere).
        (_model_l2(None), "我不会伤害自己"),
    ],
)
def test_other_model_l2_turns_in_crisis_stay_relapses(tax, lex, assessment, text):
    tracker = _in_crisis(tax, lex)
    status = tracker.observe(assessment, text)
    assert status.level is L.L2 and status.awaiting_confirmation


def test_after_confirmation_a_model_l2_turn_is_still_a_relapse(tax, lex):
    tracker = _in_crisis(tax, lex)
    assert not tracker.observe(_a(L.L0, 0.0), "我现在是安全的").awaiting_confirmation
    status = tracker.observe(_model_l2(L.L0), "我不会伤害自己")
    assert status.level is L.L2 and status.awaiting_confirmation


def _model_l1():
    return CrisisAssessment(L.L1, 0.3, "STAGE2", False, ("FAKE",), rule_level=L.L0)


def test_model_only_l1_turns_do_not_escalate(tax, lex):
    # F8a: an L1 only an injected model gives is reported as L1 but is not part of a run.
    tracker = CrisisTracker(tax, lex)
    statuses = [tracker.observe(_model_l1(), "x") for _ in range(5)]
    assert all(s.level is L.L1 and not s.in_crisis for s in statuses)
    assert tracker.consecutive_l1_count == 0


def test_model_only_l1_turns_do_not_join_a_rule_l1_run(tax, lex):
    tracker = CrisisTracker(tax, lex)
    rule_l1 = CrisisAssessment(L.L1, 0.4, "STAGE2", False, ("L1_WEARY",), rule_level=L.L1)
    tracker.observe(rule_l1, "x")
    tracker.observe(rule_l1, "x")
    assert not tracker.observe(_model_l1(), "x").in_crisis
    assert tracker.consecutive_l1_count == 2
    assert tracker.observe(rule_l1, "x").escalated


def test_a_calm_model_only_l1_resets_the_run_like_an_l0_turn(tax, lex):
    # Counted as an L0 turn, a calm model-only L1 resets the run instead of pausing it.
    tracker = CrisisTracker(tax, lex)
    tracker.observe(_a(L.L1, 0.40), "x", -0.7)
    tracker.observe(_a(L.L1, 0.40), "x", -0.7)
    assert tracker.observe(_model_l1(), "x", 0.3).consecutive_l1_count == 0
    assert not tracker.observe(_a(L.L1, 0.40), "x", -0.7).escalated


def _denial(uncapped=L.L2):
    # F10: a denial the screen capped at L1 (the model alone said L2).
    return CrisisAssessment(
        L.L1, 0.6, "STAGE2", False, ("FAKE",), rule_level=L.L0, uncapped_level=uncapped
    )


def test_a_capped_denial_outside_a_crisis_is_a_model_only_l1(tax, lex):
    t = CrisisTracker(tax, lex)
    statuses = [t.observe(_denial(), "我已经好多了") for _ in range(4)]
    assert all(s.level is L.L1 and not s.in_crisis for s in statuses)
    assert t.consecutive_l1_count == 0


def test_in_a_crisis_a_capped_denial_is_tracked_at_its_uncapped_level(run, tax, lex):
    t = CrisisTracker(tax, lex)
    screen = SafetyScreen(tax, lex)
    t.observe(screen.assess("我想死"), "我想死")
    # Awaiting a confirmation: an all-clear is no confirmation, and its L2 is a relapse.
    s = t.observe(_denial(), "我已经好多了")
    assert (s.level, s.in_crisis, s.awaiting_confirmation) == (L.L2, True, True)
    # "我不会伤害自己" is an explicit confirmation: the model's L2 alone does not void it (F8a).
    s = t.observe(_denial(), "我不会伤害自己")
    assert s.in_crisis and not s.awaiting_confirmation
    # After it, the uncapped L2 is a relapse as before F10.
    s = t.observe(_denial(), "我没事")
    assert (s.level, s.awaiting_confirmation) == (L.L2, True)


# -- S5 (2026-10-26): a clause of a longer message that says the user is safe ----------------


@pytest.mark.parametrize(
    "reply",
    [
        "我现在在家，是安全的",  # the 2026-10-26 transcript p6-s2
        "是的，我现在安全，已经给我姐打了电话",  # transcript mt011 shape
        "我现在安全",
        "我在家，我很安全",
        "嗯，我在家里，挺安全的",
        "我在家里很安全，谢谢你",
    ],
)
def test_a_clause_that_says_safe_confirms(run, reply):
    run("我想死")
    s = run(reply)
    assert s.in_crisis and not s.awaiting_confirmation and s.safe_turns_remaining == 2


@pytest.mark.parametrize(
    "reply",
    [
        "我现在在家，是安全的，可是药还在",  # a contrast and a means veto (F10)
        "我现在安全，但今晚不一定",  # contrast, time
        "我现在是安全的，不过明天就不知道了",
        "我在家，是安全的，就是还想死",  # a Stage 2 phrase: a rule risk cue
        "我在家，是安全的，活着好累",  # the rules' L1
        "我现在在家，安全吗",  # a question
        "我在楼顶，是安全的",  # a place veto
        "暂时是安全的",  # a hedge
        "我妹妹在家，她是安全的",  # someone else is safe
        "我家里人是安全的",
        "我在家，现在还安全",
        "我在家，不太安全",
    ],
)
def test_a_safe_clause_with_a_veto_contrast_or_risk_does_not_confirm(run, reply):
    run("我想死")
    s = run(reply)
    assert s.in_crisis and s.awaiting_confirmation


def test_the_clause_reading_needs_the_screens_all_clear(tax, lex):
    """A hand-built assessment never says the rules found nothing (``rule_clear``)."""
    tracker = _in_crisis(tax, lex)
    s = tracker.observe(_a(L.L0, 0.0), "我现在在家，是安全的")
    assert s.awaiting_confirmation
    # The phrase and short-answer readings do not depend on it.
    assert not tracker.observe(_a(L.L0, 0.0), "我现在是安全的").awaiting_confirmation


# -- confirmation edges, status fields and thresholds ---------------------------------------


@pytest.mark.parametrize("text", ["我现在安全了吗。", "我安全了吗！", "我是安全的吗…"])
def test_a_question_with_trailing_punctuation_does_not_confirm(tax, lex, text):
    # Trailing punctuation is dropped before the question check, so these still ask.
    tracker = _in_crisis(tax, lex)
    assert tracker.observe(_a(L.L0, 0.0), text).awaiting_confirmation


@pytest.mark.parametrize("text", ["我现在安全了么", "我安全了么？"])
def test_a_question_ending_in_me_does_not_confirm(tax, lex, text):
    tracker = _in_crisis(tax, lex)
    assert tracker.observe(_a(L.L0, 0.0), text).awaiting_confirmation


# Written out rather than read from the module, so the test pins the list itself.
@pytest.mark.parametrize("prefix", ["不", "没", "没有", "不是", "并非", "哪里"])
def test_every_negating_prefix_blocks_every_confirm_phrase(tax, lex, prefix):
    for cue in lex.cues("safety_confirm"):
        for phrase in cue.patterns:
            tracker = _in_crisis(tax, lex)
            status = tracker.observe(_a(L.L0, 0.0), prefix + phrase)
            assert status.awaiting_confirmation, prefix + phrase


def test_only_the_exit_turn_reports_just_exited(tax, lex):
    tracker = CrisisTracker(tax, lex)
    assert not tracker.observe(_a(L.L0, 0.0), "今天吃了面").just_exited
    assert not tracker.observe(_a(L.L2, 0.7), "x").just_exited
    status = tracker.observe(_a(L.L0, 0.0), "我现在是安全的")
    assert not status.awaiting_confirmation and not status.just_exited
    assert not tracker.observe(_a(L.L1, 0.40), "x").just_exited
    statuses = [tracker.observe(_a(L.L0, 0.0), "嗯") for _ in range(2)]
    assert [s.just_exited for s in statuses] == [False, True]


def test_safe_turns_remaining_is_zero_outside_a_crisis(tax, lex):
    tracker = CrisisTracker(tax, lex)
    assert tracker.observe(_a(L.L0, 0.0), "今天吃了面").safe_turns_remaining == 0


_RAW_TAXONOMY = yaml.safe_load(
    (Path(__file__).resolve().parents[2] / "olivia/data/taxonomy.yaml").read_text("utf-8")
)


def _with_ewma_streak(value):
    data = copy.deepcopy(_RAW_TAXONOMY)
    data["risk"]["ewma_streak"] = value
    return Taxonomy(data)


def test_tracker_streaks_must_be_positive_whole_numbers(lex):
    CrisisTracker(_with_ewma_streak(1), lex)  # 1 is the smallest valid streak
    for bad in (2.5, 0):
        with pytest.raises(ValueError, match="ewma_streak"):
            CrisisTracker(_with_ewma_streak(bad), lex)
