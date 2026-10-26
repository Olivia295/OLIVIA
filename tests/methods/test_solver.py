import copy
import math
from pathlib import Path
from typing import Any

import pytest
import yaml

from olivia.core.methods.solver import (
    M0_ACTION_ID,
    M0_SITUATIONS,
    AllowedSet,
    SolverInput,
    active_contraindications,
    allowed_actions,
    banned_actions,
    build_plan,
    red_flag_only_actions,
)
from olivia.core.models import ActionType, HelpStage, SafetyGrade
from olivia.core.taxonomy import Taxonomy, TaxonomyError, UnknownActionError, load_taxonomy

TAXONOMY_PATH = Path(__file__).resolve().parents[2] / "olivia" / "data" / "taxonomy.yaml"
WHITELIST_AT_080 = ("12:tipp_breathing", "28", "29", "29:pmr_release", "30:grounding")
SUB_ACTIONS = ("12:tipp_breathing", "12:tipp_cold_water", "29:pmr_release", "30:grounding")


@pytest.fixture(scope="module")
def tax() -> Taxonomy:
    return load_taxonomy()


def _raw() -> dict[str, Any]:
    data = yaml.safe_load(TAXONOMY_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return copy.deepcopy(data)


def _flag(data: dict[str, Any], code: str) -> dict[str, Any]:
    for entry in data["clinical_red_flags"]["mandatory_referral_disorders"]:
        if entry["code"] == code:
            assert isinstance(entry, dict)
            return entry
    raise AssertionError(code)


def inp(
    stage: HelpStage = HelpStage.S_EMPOWER,
    arousal: float = 0.5,
    flags: frozenset[str] = frozenset(),
    contra: frozenset[str] = frozenset(),
    situations: frozenset[str] = frozenset(),
    shelved: frozenset[str] = frozenset(),
    battery: float = 0.6,
) -> SolverInput:
    return SolverInput(stage, arousal, flags, contra, situations, shelved, battery)


# -- C_candidates: the stage pool ---------------------------------------------------------


def test_empower_pool_is_grade_a_plus_sub_actions_in_taxonomy_order(tax: Taxonomy) -> None:
    result = allowed_actions(tax, inp())
    assert set(result.candidates) == set(tax.grade_a_ids()) | set(SUB_ACTIONS)
    assert len(result.candidates) == 36 and not result.use_m0
    assert result.candidates[0] == "01"
    i = result.candidates.index("12")
    assert result.candidates[i : i + 4] == ("12", "12:tipp_breathing", "12:tipp_cold_water", "13")
    assert M0_ACTION_ID not in result.candidates
    assert "REFERRAL_CARD_PRESENTATION" not in result.candidates


@pytest.mark.parametrize("stage", [HelpStage.S_EXPLORE, HelpStage.S_CLARIFY])
@pytest.mark.parametrize("arousal", [0.0, 0.5, 0.79])
def test_pre_empower_stages_offer_no_exercise_below_somatic_priority(
    tax: Taxonomy, stage: HelpStage, arousal: float
) -> None:
    result = allowed_actions(tax, inp(stage, arousal))
    assert result == AllowedSet((), True, ())


@pytest.mark.parametrize("stage", [HelpStage.S_EXPLORE, HelpStage.S_CLARIFY, HelpStage.S_EMPOWER])
def test_high_arousal_pool_is_the_stabilization_whitelist(tax: Taxonomy, stage: HelpStage) -> None:
    assert tax.threshold("arousal.thresholds.somatic_priority") == 0.80
    assert allowed_actions(tax, inp(stage, 0.80)).candidates == WHITELIST_AT_080


# COLBO-07: the right wing (the Grade A pool) needs Battery >= 0.40 as well as low arousal.
@pytest.mark.parametrize("battery", [0.0, 0.20, 0.21, 0.39])
def test_empower_below_right_wing_battery_keeps_to_the_whitelist(
    tax: Taxonomy, battery: float
) -> None:
    assert tax.threshold("battery.thresholds.empower_min") == 0.40
    result = allowed_actions(tax, inp(arousal=0.3, battery=battery))
    assert result.candidates == WHITELIST_AT_080
    assert result.battery_gated and not result.use_m0


@pytest.mark.parametrize("battery", [0.40, 0.41, 0.6, 1.0])
def test_empower_at_right_wing_battery_gets_the_full_pool(tax: Taxonomy, battery: float) -> None:
    result = allowed_actions(tax, inp(arousal=0.3, battery=battery))
    assert set(result.candidates) == set(tax.grade_a_ids()) | set(SUB_ACTIONS)
    assert not result.battery_gated


def test_low_battery_at_overload_still_drops_method_28(tax: Taxonomy) -> None:
    result = allowed_actions(tax, inp(arousal=0.9, battery=0.3))
    assert result.candidates == ("12:tipp_breathing", "29", "29:pmr_release", "30:grounding")
    assert result.battery_gated


@pytest.mark.parametrize("stage", [HelpStage.S_EXPLORE, HelpStage.S_CLARIFY, HelpStage.S_HAVEN])
def test_battery_gate_is_only_for_empower(tax: Taxonomy, stage: HelpStage) -> None:
    for arousal in (0.3, 0.9):
        low = allowed_actions(tax, inp(stage, arousal, battery=0.1))
        assert low == allowed_actions(tax, inp(stage, arousal, battery=0.9))
        assert not low.battery_gated


# SDD §6.3: only the regular Grade A pool may be explored by the sampler.
def test_only_the_flag_free_right_wing_is_explorable(tax: Taxonomy) -> None:
    assert allowed_actions(tax, inp(arousal=0.3)).explorable
    assert allowed_actions(tax, inp(arousal=0.79)).explorable  # the sampler gates arousal
    assert not allowed_actions(tax, inp(arousal=0.8)).explorable  # the whitelist
    assert not allowed_actions(tax, inp(arousal=0.3, battery=0.3)).explorable  # battery-gated
    for stage in (HelpStage.S_EXPLORE, HelpStage.S_CLARIFY, HelpStage.S_HAVEN):
        for arousal in (0.3, 0.9):
            assert not allowed_actions(tax, inp(stage, arousal)).explorable
    assert not allowed_actions(tax, inp(situations=frozenset(M0_SITUATIONS))).explorable


@pytest.mark.parametrize("code", ["SIT-02-04", "SIT-06-01", "SIT-08-04", "SIT-09-01", "SIT-10-04"])
def test_a_red_flag_pool_is_never_explorable(tax: Taxonomy, code: str) -> None:
    # With or without a red-flag-only action (D-3) in it, the closed set is not the pool.
    result = allowed_actions(tax, inp(arousal=0.3, flags=frozenset({code})))
    assert result.candidates and not result.explorable


def test_low_battery_gate_keeps_red_flag_closure_and_referral(tax: Taxonomy) -> None:
    result = allowed_actions(tax, inp(flags=frozenset({"SIT-06-01"}), battery=0.3))
    assert result.candidates == ("30:grounding", "SAFE_PLACE_CONTAINER")
    assert result.referral_flags == ("SIT-06-01",) and result.battery_gated


def test_right_wing_battery_comes_from_the_taxonomy() -> None:
    data = _raw()
    data["battery"]["thresholds"]["empower_min"] = 0.5
    data["battery"]["empower_min"] = 0.5  # the deprecated mirror key must agree
    synthetic = Taxonomy(data)
    assert allowed_actions(synthetic, inp(battery=0.45)).candidates == WHITELIST_AT_080
    assert len(allowed_actions(synthetic, inp(battery=0.5)).candidates) == 36


@pytest.mark.parametrize("arousal", [0.85, 1.0])
def test_method_28_drops_out_at_overload(tax: Taxonomy, arousal: float) -> None:
    result = allowed_actions(tax, inp(HelpStage.S_EXPLORE, arousal))
    assert result.candidates == ("12:tipp_breathing", "29", "29:pmr_release", "30:grounding")


@pytest.mark.parametrize(
    "stage", [HelpStage.S_READY, HelpStage.S_CLOSING, HelpStage.S_CRISIS, HelpStage.S_HAVEN]
)
def test_other_stages_fall_back_to_m0(tax: Taxonomy, stage: HelpStage) -> None:
    for arousal in (0.3, 0.9):
        assert allowed_actions(tax, inp(stage, arousal)) == AllowedSet((), True, ())


# -- A_allowed: red-flag closure ------------------------------------------------------------


@pytest.mark.parametrize("stage", [HelpStage.S_EXPLORE, HelpStage.S_EMPOWER])
def test_bipolar_closure_blocks_the_whitelist_and_adds_referral(
    tax: Taxonomy, stage: HelpStage
) -> None:
    # D-3 (F13): only the bipolar flag's own stabilization action is left at high arousal.
    result = allowed_actions(tax, inp(stage, 0.9, flags=frozenset({"SIT-02-04"})))
    assert result == AllowedSet(("ENVIRONMENT_STIMULUS_REDUCTION",), False, ("SIT-02-04",))


@pytest.mark.parametrize("stage", [HelpStage.S_EXPLORE, HelpStage.S_EMPOWER])
def test_perinatal_closure_empties_the_set_at_high_arousal(tax: Taxonomy, stage: HelpStage) -> None:
    # Its only red-flag-only action is psychoeducation, which the left wing never offers.
    result = allowed_actions(tax, inp(stage, 0.9, flags=frozenset({"SIT-02-06"})))
    assert result == AllowedSet((), True, ("SIT-02-06",))


# -- D-3 (F13, draft G-0): red-flag-only actions join the pool of their own type ----------

_BIPOLAR_RIGHT = ("CIRCADIAN_RHYTHM_STABILIZATION", "ENVIRONMENT_STIMULUS_REDUCTION")
_PTSD = ("30:grounding", "SAFE_PLACE_CONTAINER")
_DISSOCIATION = ("30:grounding", "ENVIRONMENT_PHYSICAL_ANCHOR")
_BPD = ("12:tipp_breathing", "29:pmr_release")


@pytest.mark.parametrize(
    ("code", "left", "right"),
    [
        ("SIT-02-04", ("ENVIRONMENT_STIMULUS_REDUCTION",), _BIPOLAR_RIGHT),
        ("SIT-02-06", (), ("CIRCADIAN_RHYTHM_STABILIZATION",)),
        ("SIT-06-01", _PTSD, _PTSD),
        ("SIT-06-05", _DISSOCIATION, _DISSOCIATION),
        ("SIT-08-04", ("12:tipp_breathing",), ("12:tipp_breathing",)),
        ("SIT-09-01", _BPD, _BPD),
        ("SIT-10-04", (), ("WITHDRAWAL_RISK_WARNING",)),
    ],
)
def test_red_flag_only_actions_by_wing(
    tax: Taxonomy, code: str, left: tuple[str, ...], right: tuple[str, ...]
) -> None:
    flags = frozenset({code})
    high = allowed_actions(tax, inp(HelpStage.S_EXPLORE, 0.85, flags=flags))
    low_battery = allowed_actions(tax, inp(arousal=0.3, flags=flags, battery=0.3))
    assert high.candidates == left and low_battery.candidates == left
    assert allowed_actions(tax, inp(arousal=0.3, flags=flags)).candidates == right
    # Outside the pools they join, nothing changes: low-arousal S_explore stays m0.
    assert allowed_actions(tax, inp(HelpStage.S_EXPLORE, 0.3, flags=flags)).use_m0
    for stage in (HelpStage.S_HAVEN, HelpStage.S_CLOSING, HelpStage.S_CRISIS):
        assert allowed_actions(tax, inp(stage, 0.9, flags=flags)).use_m0


_RED_FLAG_ONLY = {
    "SAFE_PLACE_CONTAINER",
    "CIRCADIAN_RHYTHM_STABILIZATION",
    "ENVIRONMENT_STIMULUS_REDUCTION",
    "ENVIRONMENT_PHYSICAL_ANCHOR",
    "WITHDRAWAL_RISK_WARNING",
}


def test_red_flag_only_actions_need_their_flag(tax: Taxonomy) -> None:
    for stage in HelpStage:
        for arousal in (0.3, 0.85):
            for battery in (0.3, 0.6):
                result = allowed_actions(tax, inp(stage, arousal, battery=battery))
                assert not _RED_FLAG_ONLY & set(result.candidates)


def test_red_flag_only_actions_keep_every_mask(tax: Taxonomy) -> None:
    flags = frozenset({"SIT-06-01"})
    shelved = allowed_actions(
        tax, inp(arousal=0.3, flags=flags, shelved=frozenset({"SAFE_PLACE_IMAGERY"}))
    )
    assert shelved.candidates == ("30:grounding",)  # shelving goes through the alias
    assert allowed_actions(tax, inp(situations=frozenset({"SIT-06-04"}), flags=flags)).use_m0
    # Two flags: the intersection of their bounds still decides.
    both = allowed_actions(tax, inp(arousal=0.3, flags=frozenset({"SIT-02-04", "SIT-02-06"})))
    assert both.candidates == ("CIRCADIAN_RHYTHM_STABILIZATION",)
    assert both.referral_flags == ("SIT-02-04", "SIT-02-06")


def test_red_flag_only_actions_skip_m0_and_referral(tax: Taxonomy) -> None:
    found = red_flag_only_actions(tax, frozenset(tax.red_flags()))
    assert set(found) == _RED_FLAG_ONLY


def test_closure_uses_canonical_ids_for_aliases(tax: Taxonomy) -> None:
    # BPD lists the alias DBT_TIPP_MODIFIED_BREATHING; it must meet 12:tipp_breathing.
    assert "DBT_TIPP_MODIFIED_BREATHING" in tax.red_flags()["SIT-09-01"].allowed_actions
    result = allowed_actions(tax, inp(HelpStage.S_EXPLORE, 0.8, flags=frozenset({"SIT-09-01"})))
    assert result.candidates == ("12:tipp_breathing", "29:pmr_release")
    assert result.referral_flags == ("SIT-09-01",)


def test_several_flags_intersect_their_allowed_actions(tax: Taxonomy) -> None:
    # Both bounds name the paced breathing (COLBO-05e); only BPD names 29:pmr_release.
    flags = frozenset({"SIT-09-01", "SIT-08-04"})
    result = allowed_actions(tax, inp(HelpStage.S_EXPLORE, 0.85, flags=flags))
    assert result == AllowedSet(("12:tipp_breathing",), False, ("SIT-08-04", "SIT-09-01"))
    flags = frozenset({"SIT-09-01", "SIT-06-01"})
    result = allowed_actions(tax, inp(HelpStage.S_EXPLORE, 0.85, flags=flags))
    assert result == AllowedSet((), True, ("SIT-06-01", "SIT-09-01"))


# -- COLBO-05e: an anorexia history still allows the paced breathing (PRD COLBO-05 rule 1) --


@pytest.mark.parametrize(
    ("stage", "arousal", "battery"),
    [
        (HelpStage.S_EXPLORE, 0.85, 0.6),
        (HelpStage.S_CLARIFY, 0.8, 0.6),
        (HelpStage.S_EMPOWER, 0.3, 0.6),
        (HelpStage.S_EMPOWER, 0.3, 0.2),
        (HelpStage.S_EMPOWER, 0.95, 0.6),
    ],
)
def test_anorexia_gets_the_paced_breathing_and_nothing_else(
    tax: Taxonomy, stage: HelpStage, arousal: float, battery: float
) -> None:
    flags = frozenset({"SIT-08-04"})
    result = allowed_actions(tax, inp(stage, arousal, flags=flags, battery=battery))
    assert result.candidates == ("12:tipp_breathing",)
    assert result.referral_flags == ("SIT-08-04",)
    contra = frozenset({"RED_FLAG_ANOREXIA", "CARDIORESPIRATORY_INSTABILITY"})
    result = allowed_actions(tax, inp(stage, arousal, flags=flags, contra=contra, battery=battery))
    assert result.candidates == ("12:tipp_breathing",)


def test_anorexia_bound_names_only_the_breathing_among_exercises(tax: Taxonomy) -> None:
    bound = {tax.canonical_action_id(a) for a in tax.red_flags()["SIT-08-04"].allowed_actions}
    assert bound == {"12:tipp_breathing", M0_ACTION_ID, "REFERRAL_CARD_PRESENTATION"}
    assert "12" not in bound and "12:tipp_cold_water" not in bound
    # Low arousal outside S_empower is still m0 with the referral.
    flags = frozenset({"SIT-08-04"})
    for stage in (HelpStage.S_EXPLORE, HelpStage.S_CLARIFY):
        assert allowed_actions(tax, inp(stage, 0.3, flags=flags)).use_m0


def test_red_flag_user_still_gets_candidates_in_empower(tax: Taxonomy) -> None:
    result = allowed_actions(tax, inp(flags=frozenset({"SIT-06-01"})))
    assert result.candidates == ("30:grounding", "SAFE_PLACE_CONTAINER")
    assert result.referral_flags == ("SIT-06-01",)


# -- B_banned: tag expansion and parent-ban penetration -------------------------------------


def test_banned_tags_expand_to_method_ids(tax: Taxonomy) -> None:
    banned = banned_actions(tax, frozenset({"SIT-02-06"}))
    assert banned == set(tax.banned_tag_methods("DEEP_SCHEMA_EXCAVATION")) | set(
        tax.banned_tag_methods("HIGH_COGNITIVE_LOAD")
    )
    assert banned_actions(tax, frozenset()) == frozenset()


def test_sub_action_can_be_banned_directly(tax: Taxonomy) -> None:
    banned = banned_actions(tax, frozenset({"SIT-08-04"}))
    assert "12:tipp_cold_water" in banned and "12:tipp_breathing" not in banned
    assert {"13", "59"} <= banned


def test_banned_tag_removes_methods_the_closure_would_admit() -> None:
    data = _raw()
    _flag(data, "SIT-02-06")["allowed_actions"] = ["01", "17", "REFERRAL_CARD_PRESENTATION"]
    synthetic = Taxonomy(data)
    result = allowed_actions(synthetic, inp(flags=frozenset({"SIT-02-06"})))
    assert result.candidates == ("17",)  # "01" is in HIGH_COGNITIVE_LOAD


def test_parent_ban_penetrates_unless_sub_action_is_explicitly_allowed() -> None:
    data = _raw()
    _flag(data, "SIT-09-01")["banned_methods"].append("12")
    _flag(data, "SIT-06-01")["banned_methods"].append("29")
    synthetic = Taxonomy(data)
    bpd = banned_actions(synthetic, frozenset({"SIT-09-01"}))
    assert {"12", "12:tipp_cold_water"} <= bpd
    assert "12:tipp_breathing" not in bpd  # exempt: BPD names it via its alias
    ptsd = banned_actions(synthetic, frozenset({"SIT-06-01"}))
    assert {"29", "29:pmr_release"} <= ptsd  # PTSD does not name the sub-action
    explore = inp(HelpStage.S_EXPLORE, 0.85, flags=frozenset({"SIT-09-01"}))
    assert allowed_actions(synthetic, explore).candidates == ("12:tipp_breathing", "29:pmr_release")


# -- X_contraindicated: own contraindications only -------------------------------------------


def test_parent_contraindications_do_not_flow_down(tax: Taxonomy) -> None:
    result = allowed_actions(tax, inp(contra=frozenset({"CARDIORESPIRATORY_INSTABILITY"})))
    assert {"12", "12:tipp_breathing"} <= set(result.candidates)
    assert not {"12:tipp_cold_water", "28", "29", "29:pmr_release", "70"} & set(result.candidates)
    crisis = allowed_actions(tax, inp(contra=frozenset({"CRISIS_ACTIVE_RISK"})))
    assert "30" not in crisis.candidates and "30:grounding" in crisis.candidates


def test_whitelist_entries_still_pass_their_own_contraindications(tax: Taxonomy) -> None:
    contra = frozenset({"CARDIORESPIRATORY_INSTABILITY"})
    result = allowed_actions(tax, inp(HelpStage.S_EXPLORE, 0.8, contra=contra))
    assert result.candidates == ("12:tipp_breathing", "30:grounding")


def test_overload_is_derived_from_arousal(tax: Taxonomy) -> None:
    threshold = tax.threshold("arousal.thresholds.cognitive_block")
    assert threshold == 0.85
    below = math.nextafter(threshold, 0.0)
    assert active_contraindications(tax, inp(arousal=below)) == frozenset()
    assert active_contraindications(tax, inp(arousal=threshold)) == {"ACUTE_AROUSAL_OVERLOAD"}
    caller = frozenset({"TOXIC_SHAME_SPIRAL"})
    assert active_contraindications(tax, inp(arousal=0.9, contra=caller)) == caller | {
        "ACUTE_AROUSAL_OVERLOAD"
    }


def test_caller_supplied_overload_masks_at_low_arousal(tax: Taxonomy) -> None:
    result = allowed_actions(tax, inp(contra=frozenset({"ACUTE_AROUSAL_OVERLOAD"})))
    assert not {"07", "28", "61"} & set(result.candidates)
    assert "01" in result.candidates


# -- shelved actions ---------------------------------------------------------------------------


def test_shelved_actions_are_removed_after_canonicalization(tax: Taxonomy) -> None:
    result = allowed_actions(
        tax, inp(HelpStage.S_EXPLORE, 0.8, shelved=frozenset({"GROUNDING_54321"}))
    )
    assert "30:grounding" not in result.candidates and "28" in result.candidates


def test_shelving_everything_falls_back_to_m0_without_referral(tax: Taxonomy) -> None:
    result = allowed_actions(
        tax, inp(HelpStage.S_EXPLORE, 0.8, shelved=frozenset(WHITELIST_AT_080))
    )
    assert result == AllowedSet((), True, ())


# -- m0 fixed rule -------------------------------------------------------------------------------


@pytest.mark.parametrize("code", sorted(M0_SITUATIONS))
def test_m0_situations_override_every_stage(tax: Taxonomy, code: str) -> None:
    for stage in (HelpStage.S_EMPOWER, HelpStage.S_EXPLORE):
        result = allowed_actions(tax, inp(stage, 0.9, situations=frozenset({code, "SIT-01-01"})))
        assert result == AllowedSet((), True, ())


def test_m0_situations_are_real_taxonomy_codes() -> None:
    codes = {item["code"] for spectrum in _raw()["distress_spectra"] for item in spectrum["items"]}
    assert codes >= M0_SITUATIONS


def test_other_situations_do_not_trigger_m0(tax: Taxonomy) -> None:
    assert not allowed_actions(tax, inp(situations=frozenset({"SIT-01-01"}))).use_m0


def test_haven_with_red_flag_keeps_the_referral(tax: Taxonomy) -> None:
    result = allowed_actions(tax, inp(HelpStage.S_HAVEN, flags=frozenset({"SIT-09-01"})))
    assert result == AllowedSet((), True, ("SIT-09-01",))


# -- input validation ----------------------------------------------------------------------------


def test_unknown_inputs_are_rejected(tax: Taxonomy) -> None:
    with pytest.raises(ValueError, match="red flag"):
        allowed_actions(tax, inp(flags=frozenset({"SIT-99-99"})))
    with pytest.raises(ValueError, match="contraindication"):
        allowed_actions(tax, inp(contra=frozenset({"NOT_AN_ENUM"})))
    with pytest.raises(UnknownActionError):
        allowed_actions(tax, inp(shelved=frozenset({"NO_SUCH_ACTION"})))
    for bad in (-0.1, 1.1, math.nan):
        with pytest.raises(ValueError, match="arousal"):
            inp(arousal=bad)
        with pytest.raises(ValueError, match="battery"):
            inp(battery=bad)


def test_allowed_set_ties_use_m0_to_an_empty_candidate_list() -> None:
    with pytest.raises(ValueError):
        AllowedSet(("01",), True, ())
    with pytest.raises(ValueError):
        AllowedSet((), False, ())


# -- build_plan ----------------------------------------------------------------------------------


def test_m0_plan_is_companionship_and_carries_referral(tax: Taxonomy) -> None:
    plan = build_plan(tax, None, AllowedSet((), True, ("SIT-02-04",)))
    assert plan.primary.method_id == M0_ACTION_ID
    assert plan.primary.action_type is ActionType.COMPANIONSHIP
    assert plan.primary.safety_grade is None
    assert plan.referral_flags == ("SIT-02-04",)


def test_no_choice_gives_m0_even_with_candidates(tax: Taxonomy) -> None:
    plan = build_plan(tax, None, AllowedSet(("01",), False, ()))
    assert plan.primary.method_id == M0_ACTION_ID and plan.referral_flags == ()


def test_grade_a_method_plan_is_a_micro_exercise(tax: Taxonomy) -> None:
    allowed = allowed_actions(tax, inp())
    plan = build_plan(tax, "15", allowed)
    method = tax.methods()["15"]
    assert plan.primary.method_id == "15"
    assert plan.primary.action_type is ActionType.MICRO_EXERCISE
    assert plan.primary.safety_grade is SafetyGrade.GRADE_A
    assert plan.primary.core_action_steps == method.core_action_steps
    assert plan.primary.duration_minutes == method.duration_minutes
    assert plan.primary.contraindications == method.contraindications
    assert plan.referral_flags == ()


def test_sub_action_plan_uses_its_declared_type_and_aliases_resolve(tax: Taxonomy) -> None:
    allowed = allowed_actions(tax, inp(HelpStage.S_EXPLORE, 0.85, flags=frozenset({"SIT-09-01"})))
    plan = build_plan(tax, "DBT_TIPP_MODIFIED_BREATHING", allowed)
    assert plan.primary.method_id == "12:tipp_breathing"
    assert plan.primary.action_type is ActionType.STABILIZATION
    assert plan.primary.safety_grade is SafetyGrade.GRADE_A  # the parent's grade
    assert plan.referral_flags == ("SIT-09-01",)


def test_standalone_registered_action_keeps_its_type(tax: Taxonomy) -> None:
    plan = build_plan(
        tax,
        "CIRCADIAN_RHYTHM_STABILIZATION",
        AllowedSet(("CIRCADIAN_RHYTHM_STABILIZATION",), False, ()),
    )
    assert plan.primary.action_type is ActionType.PSYCHOEDUCATION
    assert plan.primary.safety_grade is None


def test_build_plan_rejects_ids_outside_the_candidates(tax: Taxonomy) -> None:
    allowed = allowed_actions(tax, inp(HelpStage.S_EXPLORE, 0.8))
    with pytest.raises(KeyError):
        build_plan(tax, "01", allowed)  # a real method, but not eligible here
    with pytest.raises(KeyError):
        build_plan(tax, "NO_SUCH_ACTION", allowed)
    with pytest.raises(KeyError):
        build_plan(tax, M0_ACTION_ID, allowed)


def test_build_plan_refuses_non_grade_a_methods(tax: Taxonomy) -> None:
    with pytest.raises(ValueError, match="Grade A"):
        build_plan(tax, "04", AllowedSet(("04",), False, ()))


def test_m0_must_be_a_companionship_action() -> None:
    data = _raw()
    for entry in data["action_registry"]:
        if entry["id"] == M0_ACTION_ID:
            entry["action_type"] = "STABILIZATION"
    with pytest.raises(TaxonomyError, match="COMPANIONSHIP"):
        build_plan(Taxonomy(data), None, AllowedSet((), True, ()))
