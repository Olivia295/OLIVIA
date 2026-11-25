"""Crisis tracker behaviour that mutation testing found unchecked (``safety/tracker.py``).

Each test kills one or more surviving mutants listed in ``docs/safety/mutation-report.md``
and asserts a documented rule: the L1 escalation and the exit rule of PRD §9.1 / SDD §8.2
(an L1 turn in a crisis pauses the count and never escalates, §9.4 item 3), the F8a reading
of an awaited confirmation, the round 6 ``confirmable`` and ``confirm_on_entry`` flags and
the ways to confirm safety of §9.4 item 17. Turns are hand-built assessments where the
level is what matters, and the packaged rule screen where the confirmation reading needs
its ``rule_clear``. Every example message is written here.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from olivia.core.models import CrisisLevel as L
from olivia.core.safety.crisis import CrisisAssessment, SafetyScreen
from olivia.core.safety.lexicon import DenialRules, load_safety_lexicons
from olivia.core.safety.tracker import CrisisStatus, CrisisTracker
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
LEX = load_safety_lexicons(TAX)
SCREEN = SafetyScreen(TAX, LEX)


def _a(
    level: L, score: float, *, rule: L | None = None, cues: tuple[str, ...] = ()
) -> CrisisAssessment:
    return CrisisAssessment(level, score, "STAGE2", False, cues, rule_level=rule)


def _rule_l1() -> CrisisAssessment:
    return _a(L.L1, 0.4, rule=L.L1, cues=("L1_TEST",))


def _model_l2() -> CrisisAssessment:
    # An injected model's L2 on a turn the rules read at L0 (F8a).
    return _a(L.L2, 0.6, rule=L.L0, cues=("FAKE",))


def _entered() -> CrisisTracker:
    tracker = CrisisTracker(TAX, LEX)
    status = tracker.observe(_a(L.L2, 0.7, rule=L.L2), "x")
    assert status.just_entered and status.awaiting_confirmation
    return tracker


def _screened(tracker: CrisisTracker, text: str) -> CrisisStatus:
    return tracker.observe(SCREEN.assess(text), text)


# -- in a crisis an L1 turn pauses the count and never escalates (SDD §8.2, §9.4 item 3) ----


def test_l1_turns_in_a_crisis_never_escalate_after_a_confirmation():
    tracker = _entered()
    assert not tracker.observe(_a(L.L0, 0.0, rule=L.L0), "我现在是安全的").awaiting_confirmation
    for _ in range(4):
        status = tracker.observe(_rule_l1(), "x")
        assert (status.level, status.escalated) == (L.L1, False)
        assert status.in_crisis and not status.awaiting_confirmation
    assert tracker.consecutive_l1_count == 0


def test_l1_turns_in_a_crisis_never_escalate_while_a_confirmation_is_awaited():
    tracker = _entered()
    for _ in range(4):
        status = tracker.observe(_rule_l1(), "x")
        assert (status.level, status.escalated, status.entry_level) == (L.L1, False, L.L2)
    assert tracker.consecutive_l1_count == 0


# -- confirmable=False (round 6): a short yes to another question is no confirmation, and
# the F8a reading of an awaited confirmation does not apply to it -------------------------


def test_a_model_l2_on_a_yes_to_another_question_is_still_a_relapse():
    tracker = _entered()
    status = tracker.observe(_model_l2(), "是的", confirmable=False)
    assert (status.level, status.awaiting_confirmation) == (L.L2, True)
    # The same yes to the safety question is an awaited confirmation the model alone raised.
    status = tracker.observe(_model_l2(), "是的")
    assert (status.level, status.awaiting_confirmation) == (L.L0, False)


# -- confirm_on_entry (round 6): on the turn that enters a crisis, a confirmation counts ----


@pytest.mark.parametrize("text", ["我现在是安全的", "我现在在家，是安全的"])
def test_a_confirmation_on_the_entry_turn_counts_with_confirm_on_entry(text):
    rules = SCREEN.assess(text)
    tracker = CrisisTracker(TAX, LEX)
    status = tracker.observe(_model_l2(), text, confirm_on_entry=rules)
    assert status.just_entered and status.in_crisis and not status.awaiting_confirmation
    # Without it the entry turn always awaits a confirmation.
    status = CrisisTracker(TAX, LEX).observe(_model_l2(), text)
    assert status.just_entered and status.awaiting_confirmation


def test_confirm_on_entry_only_counts_on_the_entry_turn():
    text = "我现在是安全的"
    tracker = _entered()
    status = tracker.observe(_a(L.L2, 0.7, rule=L.L2), text, confirm_on_entry=SCREEN.assess(text))
    assert not status.just_entered and status.awaiting_confirmation


# -- ways to confirm safety (§9.4 item 17; tracker round 5 and round 6) ---------------------


@pytest.mark.parametrize("text", ["那个念头我放下了", "我把这个想法打消了"])
def test_letting_go_of_the_thought_confirms(text):
    tracker = _entered()
    assert not _screened(tracker, text).awaiting_confirmation


@pytest.mark.parametrize(
    "text", ["我好好的，人在家", "人在宿舍，我没事的", "我妈在旁边陪着我，我挺好的"]
)
def test_a_status_report_of_two_kinds_confirms(text):
    tracker = _entered()
    assert not _screened(tracker, text).awaiting_confirmation


@pytest.mark.parametrize("text", ["我好好的，今天吃了面", "人在家，门锁着", "我没事，我挺好的"])
def test_a_status_report_of_one_kind_does_not_confirm(text):
    tracker = _entered()
    assert _screened(tracker, text).awaiting_confirmation


# -- a time word is a promise's or a scoped clause's own scope only inside that clause
# (tracker rounds 3-5): anywhere else a confirm veto, a sarcasm, a danger word or a rule risk
# cue still voids the confirmation (SDD §8.2 F2a: vetoes win; "fails toward staying in
# crisis") ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "今晚不会做傻事",
        "我答应你，今晚不会做傻事",
        "我保证今晚好好的，我现在在家，是安全的",
        "今晚不会做傻事，我现在在家，是安全的",
        "今晚就在家里待着，我现在在家，是安全的",
        # Going to bed, a means handed over or a height left (rounds 4, 5, 7) are dropped
        # before the guard reads the message, so the clause they stood in keeps its scope.
        "今天晚上就在家里待着准备睡了，我现在在家，是安全的",
        "今天晚上就在家里待着药都交给室友了，我现在在家，是安全的",
        "我从天台下来了今天晚上就在家里待着，我现在在家，是安全的",
    ],
)
def test_a_time_word_inside_a_promise_or_a_scoped_clause_confirms(text):
    tracker = _entered()
    assert not _screened(tracker, text).awaiting_confirmation


@pytest.mark.parametrize(
    "text",
    [
        # A sarcasm (才怪) after the exempted clause still vetoes.
        "今晚不会做傻事，才怪",
        "今晚我很安全，才怪",
        # A rule risk cue elsewhere voids a time the clause scoped (round 5).
        "今晚我很安全，就是活着好累",
        # A time word outside the promise clause is a veto again.
        "我保证不会做傻事，我很安全，今晚想早点睡",
        "我保证不会做傻事，今天晚上再看",
        # An F10 time veto outside every scoped clause voids the safe clause (S5).
        "我现在在家，是安全的，今天晚上再看",
        "那个念头我放下了，今天晚上再看",
        "今晚就在家里待着，我现在在家，是安全的，今天晚上再看",
        # A danger word after the exempted clause still voids the safe clause.
        "我保证今晚好好的，我在家，是安全的，药还在",
        "今晚就在家里待着，我在家，是安全的，药还在",
    ],
)
def test_a_veto_outside_the_scoped_clause_still_voids(text):
    tracker = _entered()
    assert _screened(tracker, text).awaiting_confirmation


# -- asks_after_confirmation (负责人 2026-11-01 决定, §9.4 item 33): only in a crisis after a
# confirmation, and only for a farewell-family D3 cue -------------------------------------


def test_a_farewell_cue_asks_first_only_in_a_crisis_after_a_confirmation():
    raised = next(e.id for e in LEX.compositions.entries if e.raise_with_risk)
    farewell = CrisisAssessment(L.L1, 0.3, "STAGE2", False, (raised,), True, rule_level=L.L1)
    other_ask = CrisisAssessment(L.L1, 0.3, "STAGE2", False, ("ASK_OTHER",), True, L.L1)
    tracker = CrisisTracker(TAX, LEX)
    assert not tracker.asks_after_confirmation(farewell)  # outside a crisis
    tracker = _entered()
    assert not tracker.asks_after_confirmation(farewell)  # awaiting a confirmation
    tracker.observe(_a(L.L0, 0.0, rule=L.L0), "我现在是安全的")
    assert tracker.asks_after_confirmation(farewell)
    assert not tracker.asks_after_confirmation(other_ask)
    no_ask = CrisisAssessment(L.L1, 0.3, "STAGE2", False, (raised,), False, L.L1)
    assert not tracker.asks_after_confirmation(no_ask)


# -- without any F10 veto or contrast in the lexicon nothing voids the safe clause (S5) -----


def test_a_safe_clause_confirms_when_the_lexicon_has_no_denial_vetoes():
    bare = replace(LEX, denial=DenialRules())
    tracker = CrisisTracker(TAX, bare)
    tracker.observe(_a(L.L2, 0.7, rule=L.L2), "x")
    clear = CrisisAssessment(L.L0, 0.05, "STAGE2", False, (), rule_level=L.L0, rule_clear=True)
    assert not tracker.observe(clear, "我现在在家，是安全的").awaiting_confirmation
