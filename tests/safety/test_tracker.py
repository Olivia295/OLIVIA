import pytest

from olivia.core.models import CrisisLevel as L
from olivia.core.safety.crisis import CrisisAssessment, SafetyScreen
from olivia.core.safety.lexicon import load_safety_lexicons
from olivia.core.safety.tracker import CrisisTracker
from olivia.core.taxonomy import load_taxonomy


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


def test_plain_l1_does_not_escalate(run):
    statuses = [run("活着好累") for _ in range(5)]
    assert all(s.level is L.L1 and not s.in_crisis for s in statuses)


def test_strong_l1_escalates_on_third_turn(run):
    s1, s2, s3 = (run("想彻底睡过去") for _ in range(3))
    assert s1.level is L.L1 and s2.level is L.L1
    assert s3.level is L.L2 and s3.escalated and s3.in_crisis and s3.just_entered


def test_valence_must_worsen_when_given(tax, lex):
    t = CrisisTracker(tax, lex)
    statuses = [t.observe(_a(L.L1, 0.48), "x", v) for v in (-0.5, -0.5, -0.5)]
    assert statuses[-1].level is L.L1  # 极性未恶化，不升级
    t2 = CrisisTracker(tax, lex)
    statuses = [t2.observe(_a(L.L1, 0.48), "x", v) for v in (-0.3, -0.5, -0.7)]
    assert statuses[-1].level is L.L2


def test_isolated_l0_does_not_break_streak(run):
    run("想彻底睡过去")
    run("今天吃了面")
    run("想彻底睡过去")
    assert run("想彻底睡过去").level is L.L2


def test_three_l0_turns_clear_streak(run):
    run("想彻底睡过去")
    run("想彻底睡过去")
    for _ in range(3):
        run("今天吃了面")
    assert run("想彻底睡过去").level is L.L1


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
    assert s.in_crisis and not s.awaiting_confirmation and s.safe_turns_remaining == 1


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
