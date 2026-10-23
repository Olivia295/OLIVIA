import copy
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
import yaml
from hypothesis import given
from hypothesis import strategies as st

from olivia.core.fsm import Reason, TurnInput, close_session, step
from olivia.core.models import (
    CrisisLevel,
    HelpStage,
    PerceptionContext,
    PersonaSpectrum,
    SessionState,
)
from olivia.core.perception.signals import Command, TurnSignals
from olivia.core.safety.tracker import CrisisStatus
from olivia.core.taxonomy import Taxonomy, TaxonomyError, load_taxonomy

TAX = load_taxonomy()
S = HelpStage
NON_CRISIS = [s for s in HelpStage if s is not S.S_CRISIS]


def perception(arousal=0.5, risk=CrisisLevel.L0):
    return PerceptionContext(
        valence=0.0,
        arousal=arousal,
        fine_grained_emotion="CALM",
        empathy_intent="EXPLORATION",
        risk_level=risk,
        crisis_confidence=0.0,
        communication_stance="CONGRUENT",
        readiness_to_change=0.5,
        distress_vector={},
        detected_distortions=(),
        detected_schemas=(),
        deep_yearning="SAFETY",
        somatic_stabilization_eligible=arousal >= 0.80,
    )


def crisis(in_crisis=False, just_exited=False, level=None):
    if level is None:
        level = CrisisLevel.L2 if in_crisis else CrisisLevel.L0
    return CrisisStatus(
        level=level,
        in_crisis=in_crisis,
        entry_level=CrisisLevel.L2 if in_crisis else None,
        escalated=False,
        awaiting_confirmation=in_crisis,
        safe_turns_remaining=2 if in_crisis else 0,
        just_entered=False,
        just_exited=just_exited,
    )


def turn(
    arousal=0.5,
    status=None,
    persona=PersonaSpectrum.GENTLE_HOLDING,
    **signals,
):
    return TurnInput(
        perception=perception(arousal),
        crisis=status if status is not None else crisis(),
        signals=TurnSignals(**signals),
        persona=persona,
    )


def state(stage=S.S_EXPLORE, turns=1, battery=0.6, locked=False, entry=None):
    return SessionState(
        session_id=uuid4(),
        current_stage=stage,
        global_turn_count=turns,
        stage_turn_count=turns,
        pure_listening_locked=locked,
        social_battery=battery,
        stage_entry_arousal=entry,
    )


def run(st_, inp):
    return step(TAX, st_, inp)


# --- one test per SDD 4.2 transition-table row ------------------------------------------


def test_row_session_start_ready_to_explore():
    t = run(SessionState(session_id=uuid4()), turn(arousal=0.4))
    assert (t.previous, t.state.current_stage, t.reason) == (
        S.S_READY,
        S.S_EXPLORE,
        Reason.SESSION_START,
    )
    assert t.state.stage_turn_count == 1 and t.state.global_turn_count == 1
    assert t.state.stage_entry_arousal == 0.4


@pytest.mark.parametrize("stage", NON_CRISIS)
def test_row_any_non_crisis_to_crisis(stage):
    t = run(state(stage), turn(status=crisis(in_crisis=True)))
    assert t.state.current_stage is S.S_CRISIS and t.reason is Reason.CRISIS_ENTER
    assert t.state.current_risk_level is CrisisLevel.L2


@pytest.mark.parametrize("stage", [s for s in NON_CRISIS if s is not S.S_HAVEN])
def test_row_any_non_crisis_to_haven(stage):
    t = run(state(stage), turn(battery=0.20))
    assert t.state.current_stage is S.S_HAVEN and t.reason is Reason.HAVEN_ENTER
    assert t.state.social_battery == 0.20


def test_row_ready_low_battery_first_turn_goes_to_haven():
    t = run(SessionState(session_id=uuid4()), turn(battery=0.05))
    assert t.state.current_stage is S.S_HAVEN and t.reason is Reason.HAVEN_ENTER


@pytest.mark.parametrize("stage", [s for s in NON_CRISIS if s is not S.S_EMPOWER])
def test_row_any_non_crisis_direct_request_to_empower(stage):
    battery = 0.30 if stage is S.S_HAVEN else 0.6  # above haven_enter, below haven_exit
    t = run(state(stage, battery=battery), turn(direct_request=True))
    assert t.state.current_stage is S.S_EMPOWER and t.reason is Reason.DIRECT_REQUEST


def test_row_explore_to_clarify():
    t = run(state(S.S_EXPLORE, turns=2), turn(arousal=0.79, battery=0.40))
    assert t.state.current_stage is S.S_CLARIFY and t.reason is Reason.EXPLORE_TO_CLARIFY
    assert t.state.stage_turn_count == 1


@pytest.mark.parametrize(
    "turns,arousal,locked,battery",
    [
        (1, 0.5, False, 0.6),  # only one turn spent in S_explore so far
        (2, 0.80, False, 0.6),  # arousal at the somatic line
        (2, 0.5, True, 0.6),  # pure-listening lock
        (2, 0.5, False, 0.39),  # battery below the clarify gate
    ],
)
def test_row_explore_to_clarify_gates(turns, arousal, locked, battery):
    t = run(state(S.S_EXPLORE, turns=turns, locked=locked, battery=battery), turn(arousal))
    assert t.state.current_stage is S.S_EXPLORE and t.reason is Reason.STAY
    assert t.state.stage_turn_count == turns + 1


def test_row_clarify_to_empower_auto_advance():
    t = run(state(S.S_CLARIFY, turns=5), turn(battery=0.40))
    assert t.state.current_stage is S.S_EMPOWER and t.reason is Reason.CLARIFY_TO_EMPOWER


@pytest.mark.parametrize(
    "turns,locked,persona,battery",
    [
        (4, False, PersonaSpectrum.GENTLE_HOLDING, 0.6),
        (5, True, PersonaSpectrum.GENTLE_HOLDING, 0.6),
        (5, False, PersonaSpectrum.SILENT_ANCHOR, 0.6),
        (5, False, PersonaSpectrum.GENTLE_HOLDING, 0.39),
    ],
)
def test_row_clarify_to_empower_gates(turns, locked, persona, battery):
    t = run(
        state(S.S_CLARIFY, turns=turns, locked=locked, battery=battery),
        turn(persona=persona),
    )
    assert t.state.current_stage is S.S_CLARIFY and t.reason is Reason.STAY


def test_row_clarify_to_empower_on_a_confirmed_core_belief():
    # PRD C_2 "核心信念识别" (decision D4): no need to wait for the auto-advance count.
    t = run(state(S.S_CLARIFY, turns=1), turn(core_belief_confirmed=True))
    assert t.state.current_stage is S.S_EMPOWER and t.reason is Reason.CLARIFY_CORE_BELIEF
    assert t.state.stage_turn_count == 1


def test_confirmed_core_belief_wins_the_reason_over_the_auto_advance():
    t = run(state(S.S_CLARIFY, turns=5), turn(core_belief_confirmed=True))
    assert t.reason is Reason.CLARIFY_CORE_BELIEF


@pytest.mark.parametrize(
    "locked,persona,battery",
    [
        (True, PersonaSpectrum.GENTLE_HOLDING, 0.6),
        (False, PersonaSpectrum.SILENT_ANCHOR, 0.6),
        (False, PersonaSpectrum.GENTLE_HOLDING, 0.39),
    ],
)
def test_confirmed_core_belief_keeps_the_c2_gates(locked, persona, battery):
    t = run(
        state(S.S_CLARIFY, turns=1, locked=locked, battery=battery),
        turn(persona=persona, core_belief_confirmed=True),
    )
    assert t.state.current_stage is S.S_CLARIFY and t.reason is Reason.STAY


@pytest.mark.parametrize("stage", [S.S_EXPLORE, S.S_CLOSING])
def test_confirmed_core_belief_means_nothing_outside_clarify(stage):
    t = run(state(stage, turns=1), turn(core_belief_confirmed=True))
    assert t.state.current_stage is stage and t.reason is Reason.STAY


def test_crisis_wins_over_a_confirmed_core_belief():
    t = run(
        state(S.S_CLARIFY, turns=1),
        turn(status=crisis(in_crisis=True), core_belief_confirmed=True),
    )
    assert t.state.current_stage is S.S_CRISIS


@pytest.mark.parametrize(
    "entry,arousal",
    [
        (0.30, 0.55),  # ΔArousal exactly 0.25
        (0.45, 0.70),  # ΔArousal 0.25 reached through float rounding
        (None, 0.85),  # absolute line, no baseline known
        (0.84, 0.85),  # absolute line with a small delta
    ],
)
def test_row_empower_arousal_retreat(entry, arousal):
    t = run(state(S.S_EMPOWER, entry=entry), turn(arousal))
    assert t.state.current_stage is S.S_EXPLORE and t.reason is Reason.EMPOWER_AROUSAL_RETREAT


def test_row_empower_small_arousal_rise_stays():
    t = run(state(S.S_EMPOWER, entry=0.30), turn(0.54))
    assert t.state.current_stage is S.S_EMPOWER and t.reason is Reason.STAY


def test_row_empower_unhelpful_to_explore():
    t = run(state(S.S_EMPOWER, entry=0.5), turn(command=Command.UNHELPFUL))
    assert t.state.current_stage is S.S_EXPLORE and t.reason is Reason.EMPOWER_UNHELPFUL


def test_row_empower_aversion_to_explore():
    # SDD 4.2 "表达反感" (COLBO-04 "强烈排斥"): routed like /unhelpful.
    t = run(state(S.S_EMPOWER, entry=0.5), turn(aversion=True))
    assert t.state.current_stage is S.S_EXPLORE and t.reason is Reason.EMPOWER_AVERSION
    assert t.state.stage_turn_count == 1


@pytest.mark.parametrize("command", [Command.DONE, Command.NOT_NOW])
def test_row_empower_done_or_not_now_to_closing(command):
    t = run(state(S.S_EMPOWER, entry=0.5), turn(command=command))
    assert t.state.current_stage is S.S_CLOSING and t.reason is Reason.EMPOWER_TO_CLOSING


@pytest.mark.parametrize("battery,expected", [(0.35, S.S_EXPLORE), (0.34, S.S_HAVEN)])
def test_row_haven_exit(battery, expected):
    t = run(state(S.S_HAVEN, battery=0.1), turn(battery=battery))
    assert t.state.current_stage is expected
    assert t.reason is (Reason.HAVEN_EXIT if expected is S.S_EXPLORE else Reason.STAY)


def test_row_closing_to_ready():
    before = state(S.S_CLOSING, turns=3, entry=0.4)
    t = close_session(before)
    assert t.state.current_stage is S.S_READY and t.reason is Reason.CLOSING_TO_READY
    assert t.state.stage_turn_count == 0 and t.state.stage_entry_arousal is None
    assert t.state.global_turn_count == before.global_turn_count
    assert before.current_stage is S.S_CLOSING


def test_row_closing_intent_confirmed_to_ready():
    # SDD 4.2 "实施意向确认完成": a user turn, so it is counted.
    before = state(S.S_CLOSING, turns=2, entry=0.4)
    t = run(before, turn(intent_confirmed=True))
    assert t.state.current_stage is S.S_READY and t.reason is Reason.CLOSING_INTENT_CONFIRMED
    assert t.state.global_turn_count == before.global_turn_count + 1
    # The next turn opens a new session through the ordinary q0 row.
    assert run(t.state, turn()).reason is Reason.SESSION_START


def test_row_crisis_exit_to_explore():
    t = run(state(S.S_CRISIS), turn(status=crisis(just_exited=True)))
    assert t.state.current_stage is S.S_EXPLORE and t.reason is Reason.CRISIS_EXIT


# --- approved rules ---------------------------------------------------------------------


def test_crisis_beats_battery_lock_commands_and_direct_request():
    inp = turn(
        status=crisis(in_crisis=True),
        battery=0.05,
        listening_lock_on=True,
        direct_request=True,
        command=Command.DONE,
    )
    for stage in HelpStage:
        assert run(state(stage), inp).state.current_stage is S.S_CRISIS


def test_crisis_stays_without_just_exited():
    t = run(state(S.S_CRISIS), turn(battery=0.05, direct_request=True))
    assert t.state.current_stage is S.S_CRISIS and t.reason is Reason.STAY


def test_crisis_stay_while_in_crisis_is_stay():
    t = run(state(S.S_CRISIS, turns=2), turn(status=crisis(in_crisis=True)))
    assert t.reason is Reason.STAY and t.state.stage_turn_count == 3


def test_crisis_exit_never_routes_to_haven():
    t = run(
        state(S.S_CRISIS, battery=0.05),
        turn(status=crisis(just_exited=True), battery=0.05, direct_request=True),
    )
    assert t.state.current_stage is S.S_EXPLORE and t.reason is Reason.CRISIS_EXIT
    # The next turn may enter the haven through the ordinary battery row.
    nxt = run(t.state, turn())
    assert nxt.state.current_stage is S.S_HAVEN


def test_low_battery_without_a_request_enters_the_haven():
    # Was test_haven_beats_direct_request: since the 2026-10-24 owner decision a direct
    # request wins over the haven (COLBO-03, see test_direct_request_leaves_haven).
    t = run(state(S.S_EXPLORE), turn(battery=0.20))
    assert t.state.current_stage is S.S_HAVEN


def test_haven_has_hysteresis_between_enter_and_exit():
    t = run(state(S.S_HAVEN, battery=0.1), turn(battery=0.30))
    assert t.state.current_stage is S.S_HAVEN and t.state.social_battery == 0.30


def test_silent_anchor_enters_empower_by_direct_request():
    t = run(
        state(S.S_CLARIFY, turns=1),
        turn(persona=PersonaSpectrum.SILENT_ANCHOR, direct_request=True),
    )
    assert t.state.current_stage is S.S_EMPOWER and t.reason is Reason.DIRECT_REQUEST


def test_silent_anchor_never_auto_advances():
    st_ = state(S.S_CLARIFY, turns=1)
    for _ in range(20):
        st_ = run(st_, turn(persona=PersonaSpectrum.SILENT_ANCHOR)).state
    assert st_.current_stage is S.S_CLARIFY and st_.stage_turn_count == 21


def test_l1_alone_does_not_change_stage():
    t = run(state(S.S_EXPLORE), turn(status=crisis(level=CrisisLevel.L1)))
    assert t.state.current_stage is S.S_EXPLORE and t.reason is Reason.STAY
    assert t.state.current_risk_level is CrisisLevel.L1


def test_state_mirrors_the_tracker_l1_run_count():
    status = replace(crisis(level=CrisisLevel.L1), consecutive_l1_count=2)
    t = run(state(S.S_EXPLORE), turn(status=status))
    assert t.state.consecutive_l1_count == 2
    t = run(t.state, turn(status=crisis()))
    assert t.state.consecutive_l1_count == 0


def test_direct_request_in_empower_stays():
    t = run(state(S.S_EMPOWER, turns=2, entry=0.5), turn(direct_request=True))
    assert t.state.current_stage is S.S_EMPOWER and t.reason is Reason.STAY
    assert t.state.stage_turn_count == 3


def test_direct_request_releases_listening_lock():
    # PRD Q-4: asking for advice releases the lock.
    t = run(state(S.S_EXPLORE, locked=True), turn(direct_request=True))
    assert t.state.current_stage is S.S_EMPOWER and not t.state.pure_listening_locked


def test_arousal_spike_beats_done_command():
    t = run(state(S.S_EMPOWER, entry=0.3), turn(0.9, command=Command.DONE))
    assert t.reason is Reason.EMPOWER_AROUSAL_RETREAT


def test_arousal_spike_beats_aversion():
    t = run(state(S.S_EMPOWER, entry=0.3), turn(0.9, aversion=True))
    assert t.reason is Reason.EMPOWER_AROUSAL_RETREAT


def test_aversion_beats_done_command():
    t = run(state(S.S_EMPOWER, entry=0.5), turn(aversion=True, command=Command.DONE))
    assert t.state.current_stage is S.S_EXPLORE and t.reason is Reason.EMPOWER_AVERSION


def test_aversion_with_direct_request_in_empower_still_retreats():
    # Direct request never fires inside S_empower, so the aversion row decides.
    t = run(state(S.S_EMPOWER, entry=0.5), turn(aversion=True, direct_request=True))
    assert t.reason is Reason.EMPOWER_AVERSION


@pytest.mark.parametrize(
    "kwargs,stage,reason",
    [
        ({"status": crisis(in_crisis=True)}, S.S_CRISIS, Reason.CRISIS_ENTER),
        ({"battery": 0.20}, S.S_HAVEN, Reason.HAVEN_ENTER),
        ({"direct_request": True}, S.S_EMPOWER, Reason.DIRECT_REQUEST),
    ],
)
def test_crisis_haven_and_direct_request_beat_new_rows(kwargs, stage, reason):
    empower = run(state(S.S_EMPOWER, entry=0.5), turn(aversion=True, **kwargs))
    closing = run(state(S.S_CLOSING), turn(intent_confirmed=True, **kwargs))
    if stage is not S.S_EMPOWER:  # direct request does not fire inside S_empower
        assert (empower.state.current_stage, empower.reason) == (stage, reason)
    assert (closing.state.current_stage, closing.reason) == (stage, reason)


@pytest.mark.parametrize("stage", [s for s in NON_CRISIS if s is not S.S_EMPOWER])
def test_aversion_outside_empower_is_ignored(stage):
    battery = 0.1 if stage is S.S_HAVEN else 0.6
    t = run(state(stage, battery=battery), turn(aversion=True))
    assert t.reason is not Reason.EMPOWER_AVERSION
    if stage is not S.S_READY:
        assert t.state.current_stage is stage and t.reason is Reason.STAY


@pytest.mark.parametrize("stage", [s for s in NON_CRISIS if s is not S.S_CLOSING])
def test_intent_confirmed_outside_closing_is_ignored(stage):
    battery = 0.1 if stage is S.S_HAVEN else 0.6
    t = run(state(stage, battery=battery, entry=0.5), turn(intent_confirmed=True))
    assert t.reason is not Reason.CLOSING_INTENT_CONFIRMED
    if stage is not S.S_READY:
        assert t.state.current_stage is stage and t.reason is Reason.STAY


@pytest.mark.parametrize("stage", [S.S_EXPLORE, S.S_CLARIFY, S.S_HAVEN, S.S_CLOSING])
def test_commands_outside_empower_are_ignored(stage):
    battery = 0.1 if stage is S.S_HAVEN else 0.6
    for command in Command:
        t = run(state(stage, battery=battery), turn(command=command))
        assert t.state.current_stage is stage and t.reason is Reason.STAY


def test_closing_stays_on_ordinary_turns():
    t = run(state(S.S_CLOSING), turn())
    assert t.state.current_stage is S.S_CLOSING and t.reason is Reason.STAY


@pytest.mark.parametrize("stage", [s for s in HelpStage if s is not S.S_CLOSING])
def test_close_session_outside_closing_is_a_no_op(stage):
    before = state(stage)
    t = close_session(before)
    assert t.reason is Reason.STAY and t.state == before
    assert t.state.user_shelved_actions is not before.user_shelved_actions


def test_battery_prefix_persists_and_defaults_to_six_tenths():
    st_ = SessionState(session_id=uuid4())
    st_ = run(st_, turn()).state
    assert st_.social_battery == 0.6
    st_ = run(st_, turn(battery=0.5)).state
    st_ = run(st_, turn()).state
    assert st_.social_battery == 0.5


def test_listening_lock_on_blocks_and_off_releases():
    st_ = run(state(S.S_EXPLORE, turns=2), turn(listening_lock_on=True)).state
    assert st_.pure_listening_locked and st_.current_stage is S.S_EXPLORE
    st_ = run(st_, turn()).state
    assert st_.pure_listening_locked and st_.current_stage is S.S_EXPLORE
    t = run(st_, turn(listening_lock_off=True))
    assert not t.state.pure_listening_locked
    assert t.state.current_stage is S.S_CLARIFY


def test_stage_entry_arousal_is_the_entry_turn_and_kept_while_staying():
    st_ = run(state(S.S_CLARIFY, turns=1), turn(0.3, direct_request=True)).state
    assert st_.stage_entry_arousal == 0.3
    st_ = run(st_, turn(0.5)).state
    assert st_.current_stage is S.S_EMPOWER and st_.stage_entry_arousal == 0.3
    t = run(st_, turn(0.56))  # 0.26 above the entry baseline, though only 0.06 above last turn
    assert t.reason is Reason.EMPOWER_AROUSAL_RETREAT and t.state.stage_entry_arousal == 0.56


def test_full_session_walkthrough():
    st_ = SessionState(session_id=uuid4())
    stages = []
    for _ in range(9):
        st_ = run(st_, turn()).state
        stages.append(st_.current_stage)
    assert stages == [S.S_EXPLORE] * 2 + [S.S_CLARIFY] * 5 + [S.S_EMPOWER] * 2
    st_ = run(st_, turn(command=Command.DONE)).state
    assert st_.current_stage is S.S_CLOSING
    t = close_session(st_)
    assert t.state.current_stage is S.S_READY and t.state.global_turn_count == 10


def test_walkthrough_with_aversion_and_intent():
    st_ = run(state(S.S_CLARIFY, turns=1, entry=0.4), turn(0.4, direct_request=True)).state
    st_ = run(st_, turn(0.45, aversion=True)).state
    assert st_.current_stage is S.S_EXPLORE
    st_ = run(st_, turn(0.4, direct_request=True)).state
    st_ = run(st_, turn(0.4, command=Command.DONE)).state
    assert st_.current_stage is S.S_CLOSING
    t = run(st_, turn(0.3, intent_confirmed=True))
    assert t.state.current_stage is S.S_READY and t.reason is Reason.CLOSING_INTENT_CONFIRMED


def test_reason_has_one_member_per_row_plus_stay():
    assert len(Reason) == 17 and Reason.STAY in Reason


def test_turn_thresholds_must_be_whole_numbers():
    raw = (Path(__file__).resolve().parents[2] / "olivia/data/taxonomy.yaml").read_text("utf-8")
    data = yaml.safe_load(raw)
    data["colbo"]["fsm"]["clarify_min_stage_turns"] = 1.5
    with pytest.raises(TaxonomyError, match="clarify_min_stage_turns"):
        step(Taxonomy(data), state(), turn())


# --- properties -------------------------------------------------------------------------

unit = st.floats(min_value=0.0, max_value=1.0, allow_nan=False)


@st.composite
def states(draw):
    return SessionState(
        session_id=uuid4(),
        current_stage=draw(st.sampled_from(HelpStage)),
        global_turn_count=draw(st.integers(0, 50)),
        stage_turn_count=draw(st.integers(0, 10)),
        pure_listening_locked=draw(st.booleans()),
        social_battery=draw(unit),
        current_risk_level=draw(st.sampled_from(CrisisLevel)),
        user_shelved_actions=draw(st.lists(st.sampled_from(["28", "29"]), max_size=2)),
        stage_entry_arousal=draw(st.none() | unit),
    )


@st.composite
def inputs(draw):
    in_crisis = draw(st.booleans())
    just_exited = (not in_crisis) and draw(st.booleans())
    lock = draw(st.sampled_from(["on", "off", None]))
    return TurnInput(
        perception=perception(draw(unit)),
        crisis=crisis(
            in_crisis=in_crisis,
            just_exited=just_exited,
            level=draw(st.sampled_from(CrisisLevel)),
        ),
        signals=TurnSignals(
            battery=draw(st.none() | unit),
            direct_request=draw(st.booleans()),
            listening_lock_on=lock == "on",
            listening_lock_off=lock == "off",
            aversion=draw(st.booleans()),
            intent_confirmed=draw(st.booleans()),
            command=draw(st.none() | st.sampled_from(Command)),
        ),
        persona=draw(st.sampled_from(PersonaSpectrum)),
    )


@given(states(), inputs())
def test_property_in_crisis_always_means_s_crisis(st_, inp):
    t = run(st_, inp)
    if inp.crisis.in_crisis:
        assert t.state.current_stage is S.S_CRISIS


@given(states(), inputs())
def test_property_crisis_left_only_on_just_exited_and_only_to_explore(st_, inp):
    t = run(st_, inp)
    if t.previous is S.S_CRISIS and t.state.current_stage is not S.S_CRISIS:
        assert inp.crisis.just_exited and t.state.current_stage is S.S_EXPLORE
        assert t.reason is Reason.CRISIS_EXIT


@given(states(), inputs())
def test_property_input_state_is_never_mutated(st_, inp):
    before = copy.deepcopy(st_)
    t = run(st_, inp)
    assert st_ == before
    assert t.state is not st_
    assert t.state.user_shelved_actions is not st_.user_shelved_actions


@given(states(), inputs())
def test_property_battery_stays_in_unit_interval(st_, inp):
    assert 0.0 <= run(st_, inp).state.social_battery <= 1.0


@given(states(), inputs())
def test_property_stage_counter_resets_or_increments(st_, inp):
    t = run(st_, inp)
    assert t.state.global_turn_count == st_.global_turn_count + 1
    if t.state.current_stage is t.previous:
        assert t.reason is Reason.STAY
        assert t.state.stage_turn_count == st_.stage_turn_count + 1
    else:
        assert t.reason is not Reason.STAY and t.state.stage_turn_count == 1


@given(states(), inputs())
def test_property_aversion_never_keeps_empower(st_, inp):
    t = run(st_, inp)
    if t.previous is S.S_EMPOWER and inp.signals.aversion:
        assert t.state.current_stage is not S.S_EMPOWER


@given(states(), inputs())
def test_property_s_ready_is_reached_by_a_turn_only_from_closing_with_intent(st_, inp):
    t = run(st_, inp)
    if t.state.current_stage is S.S_READY:
        assert t.previous is S.S_CLOSING and inp.signals.intent_confirmed
        assert t.reason is Reason.CLOSING_INTENT_CONFIRMED


# --- fix F2a: L1 guard, stabilization flags, clarify retreat, haven exit -----------------

L1 = CrisisLevel.L1


def l1(**kwargs):
    return replace(crisis(level=L1), consecutive_l1_count=1, **kwargs)


def test_l1_blocks_explore_to_clarify():
    t = run(state(S.S_EXPLORE, turns=5), turn(arousal=0.3, status=l1()))
    assert t.state.current_stage is S.S_EXPLORE and t.reason is Reason.STAY


def test_l1_blocks_clarify_to_empower():
    t = run(state(S.S_CLARIFY, turns=9), turn(arousal=0.3, status=l1()))
    assert t.state.current_stage is S.S_CLARIFY and t.reason is Reason.STAY


def test_l1_does_not_hold_a_confirmed_core_belief():
    # The session only sets core_belief_confirmed on a turn the rule screen found below L1,
    # so L1 here is a risk model's score band (MIYI-03 dialogue in model mode).
    t = run(state(S.S_CLARIFY), turn(arousal=0.3, status=l1(), core_belief_confirmed=True))
    assert t.state.current_stage is S.S_EMPOWER and t.reason is Reason.CLARIFY_CORE_BELIEF


def test_eight_l1_turns_stay_in_explore():
    # "我想消失" x 8 used to reach S_empower through the two auto-advances.
    st_ = run(SessionState(session_id=uuid4()), turn(arousal=0.25, status=l1())).state
    for _ in range(7):
        st_ = run(st_, turn(arousal=0.25, status=l1())).state
    assert st_.current_stage is S.S_EXPLORE and st_.stage_turn_count == 8


def test_l0_turn_after_l1_turns_advances_again():
    st_ = run(state(S.S_EXPLORE, turns=4), turn(arousal=0.3, status=l1())).state
    t = run(st_, turn(arousal=0.3))
    assert t.state.current_stage is S.S_CLARIFY and t.reason is Reason.EXPLORE_TO_CLARIFY


@pytest.mark.parametrize("stage", [S.S_EXPLORE, S.S_CLARIFY, S.S_CLOSING, S.S_HAVEN])
def test_l1_direct_request_still_reaches_empower_with_stabilization_only(stage):
    # Ruling 5: a direct request at L1 may get a card, from the stabilization whitelist only.
    battery = 0.1 if stage is S.S_HAVEN else 0.6
    t = run(state(stage, battery=battery), turn(status=l1(), direct_request=True))
    assert t.state.current_stage is S.S_EMPOWER and t.reason is Reason.DIRECT_REQUEST
    assert t.stabilization_only


def test_stabilization_only_follows_the_turn_level():
    t = run(state(S.S_EMPOWER, entry=0.5), turn(status=l1()))
    assert t.state.current_stage is S.S_EMPOWER and t.stabilization_only
    t = run(state(S.S_EMPOWER, entry=0.5), turn())
    assert not t.stabilization_only
    t = run(state(S.S_EXPLORE), turn(direct_request=True))
    assert t.state.current_stage is S.S_EMPOWER and not t.stabilization_only
    assert not run(state(S.S_EXPLORE), turn(status=crisis(in_crisis=True))).stabilization_only


@pytest.mark.parametrize("arousal", [0.80, 0.95, 1.0])
def test_clarify_at_the_somatic_line_retreats_to_explore(arousal):
    t = run(state(S.S_CLARIFY, turns=9), turn(arousal=arousal))
    assert t.state.current_stage is S.S_EXPLORE and t.reason is Reason.CLARIFY_AROUSAL_RETREAT
    assert t.offer_stabilization
    assert t.state.stage_entry_arousal == arousal


def test_clarify_below_the_somatic_line_does_not_retreat():
    t = run(state(S.S_CLARIFY, turns=1), turn(arousal=0.79))
    assert t.state.current_stage is S.S_CLARIFY and t.reason is Reason.STAY
    assert not t.offer_stabilization


def test_clarify_retreat_beats_the_auto_advance_and_core_belief():
    t = run(state(S.S_CLARIFY, turns=9), turn(arousal=0.9, core_belief_confirmed=True))
    assert t.reason is Reason.CLARIFY_AROUSAL_RETREAT


@pytest.mark.parametrize(
    "st_,inp,reason",
    [
        (state(S.S_EMPOWER, entry=0.3), turn(0.9), Reason.EMPOWER_AROUSAL_RETREAT),
        (state(S.S_EMPOWER, entry=0.3), turn(0.55), Reason.EMPOWER_AROUSAL_RETREAT),
        (state(S.S_EMPOWER, entry=0.5), turn(aversion=True), Reason.EMPOWER_AVERSION),
    ],
)
def test_empower_retreats_ask_for_stabilization(st_, inp, reason):
    t = run(st_, inp)
    assert t.state.current_stage is S.S_EXPLORE and t.reason is reason
    assert t.offer_stabilization


@pytest.mark.parametrize(
    "st_,inp",
    [
        (state(S.S_EMPOWER, entry=0.5), turn(command=Command.UNHELPFUL)),
        (state(S.S_EMPOWER, entry=0.5), turn(command=Command.DONE)),
        (state(S.S_EXPLORE), turn()),
        (state(S.S_EXPLORE), turn(0.9)),
        (state(S.S_EMPOWER, entry=0.5), turn()),
    ],
)
def test_other_turns_do_not_ask_for_stabilization(st_, inp):
    assert not run(st_, inp).offer_stabilization


def test_close_session_carries_no_flags():
    t = close_session(state(S.S_CLOSING))
    assert not t.offer_stabilization and not t.stabilization_only


def test_direct_request_leaves_haven():
    # PRD COLBO-03: a direct request works in any non-crisis stage, the haven included.
    t = run(state(S.S_HAVEN, battery=0.1), turn(direct_request=True))
    assert (t.previous, t.state.current_stage, t.reason) == (
        S.S_HAVEN,
        S.S_EMPOWER,
        Reason.DIRECT_REQUEST,
    )
    assert t.state.social_battery == 0.1


def test_direct_request_beats_a_low_battery_reading_on_the_same_turn():
    t = run(state(S.S_EXPLORE), turn(battery=0.05, direct_request=True))
    assert t.state.current_stage is S.S_EMPOWER and t.reason is Reason.DIRECT_REQUEST


def test_empower_left_from_haven_stays_until_a_new_reading_or_an_exit():
    st_ = run(state(S.S_HAVEN, battery=0.1), turn(direct_request=True)).state
    t = run(st_, turn())
    assert t.state.current_stage is S.S_EMPOWER and t.reason is Reason.STAY
    # A new low reading puts the session back in the haven.
    back = run(t.state, turn(battery=0.1))
    assert back.state.current_stage is S.S_HAVEN and back.reason is Reason.HAVEN_ENTER
    # Leaving S_empower the ordinary way returns to the haven on the next turn.
    done = run(t.state, turn(command=Command.DONE))
    assert done.state.current_stage is S.S_CLOSING
    assert run(done.state, turn()).state.current_stage is S.S_HAVEN


def test_crisis_still_beats_direct_request_in_haven():
    t = run(state(S.S_HAVEN, battery=0.1), turn(status=crisis(in_crisis=True), direct_request=True))
    assert t.state.current_stage is S.S_CRISIS and t.reason is Reason.CRISIS_ENTER


@given(states(), inputs())
def test_property_l1_never_auto_advances(st_, inp):
    t = run(st_, inp)
    if inp.crisis.level is CrisisLevel.L1 and not inp.crisis.in_crisis:
        assert t.reason not in (Reason.EXPLORE_TO_CLARIFY, Reason.CLARIFY_TO_EMPOWER)


@given(states(), inputs())
def test_property_flags_match_their_reasons(st_, inp):
    t = run(st_, inp)
    assert t.offer_stabilization == (
        t.reason
        in (
            Reason.CLARIFY_AROUSAL_RETREAT,
            Reason.EMPOWER_AROUSAL_RETREAT,
            Reason.EMPOWER_AVERSION,
        )
    )
    if t.stabilization_only:
        assert inp.crisis.level is CrisisLevel.L1 and not inp.crisis.in_crisis
