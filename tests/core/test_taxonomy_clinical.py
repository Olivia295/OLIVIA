import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from olivia.core.models import ActionType, CrisisLevel, SafetyGrade
from olivia.core.taxonomy import Taxonomy, TaxonomyError, UnknownActionError, load_taxonomy

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def tax() -> Taxonomy:
    return load_taxonomy()


def test_method_counts_by_grade(tax: Taxonomy) -> None:
    grades = [m.grade for m in tax.methods().values()]
    assert (
        grades.count(SafetyGrade.GRADE_A),
        grades.count(SafetyGrade.GRADE_B),
        grades.count(SafetyGrade.GRADE_C),
    ) == (32, 26, 17)
    ids = tax.grade_a_ids()
    assert len(ids) == 32 and "12" in ids and "04" not in ids


def test_grade_a_method_fields(tax: Taxonomy) -> None:
    m = tax.methods()["15"]
    assert m.evidence_level == "Level I" and m.duration_minutes == 4
    assert m.contraindications == ("RED_FLAG_PTSD_FLASHBACK",)
    assert tax.methods()["12"].sub_actions == ("12:tipp_breathing", "12:tipp_cold_water")


def test_grade_b_and_c_optional_fields_are_empty(tax: Taxonomy) -> None:
    for mid in ("09", "04"):
        m = tax.methods()[mid]
        assert m.evidence_level is None and m.duration_minutes is None
        assert m.stealth_workplace_compatible is None and m.clinical_rationale is None
        assert m.core_action_steps == () and m.contraindications == () and m.sub_actions == ()
    assert tax.methods()["09"].grade is SafetyGrade.GRADE_B
    assert tax.methods()["04"].grade is SafetyGrade.GRADE_C


def test_action_registry(tax: Taxonomy) -> None:
    reg = tax.action_registry()
    assert len(reg) == 11
    assert reg["REFERRAL_CARD_PRESENTATION"].action_type is ActionType.REFERRAL
    assert reg["12:tipp_cold_water"].contraindications == (
        "RED_FLAG_ANOREXIA",
        "RED_FLAG_BPD_NSSI",
        "CARDIORESPIRATORY_INSTABILITY",
    )
    assert reg["12:tipp_breathing"].parent_method_id == "12"
    assert reg["12:tipp_breathing"].contraindications == ()
    assert reg["29:pmr_release"].parent_method_id == "29"
    assert reg["29:pmr_release"].contraindications == ("CARDIORESPIRATORY_INSTABILITY",)
    assert tax.methods()["29"].sub_actions == ("29:pmr_release",)
    assert reg["SAFE_PLACE_CONTAINER"].parent_method_id is None


@pytest.mark.parametrize(
    "raw,canonical",
    [
        ("DBT_TIPP_MODIFIED_BREATHING", "12:tipp_breathing"),
        ("GROUNDING_54321", "30:grounding"),
        ("GENTLE_PRESENCE", "EMOTIONAL_HOLDING_PRESENCE"),
        ("30:grounding", "30:grounding"),
        ("28", "28"),
    ],
)
def test_canonical_action_id(tax: Taxonomy, raw: str, canonical: str) -> None:
    assert tax.canonical_action_id(raw) == canonical


def test_canonical_action_id_unknown_raises_key_error(tax: Taxonomy) -> None:
    with pytest.raises(UnknownActionError):
        tax.canonical_action_id("REFERRAL_CARD")


def test_situation_codes_and_contraindication_sources(tax: Taxonomy) -> None:
    codes = tax.situation_codes()
    assert len(codes) == len(set(codes)) and codes[0] == "SIT-01-01"
    assert {"SIT-06-04", "SIT-11-01"} <= set(codes)
    assert set(tax.red_flags()) <= set(codes)
    sources = tax.contraindication_sources()
    assert tuple(sources) == tax.values("contraindication_enums")
    assert sources["CRISIS_ACTIVE_RISK"] == "CRISIS_DETECTOR"
    assert "SIT-06-04" in sources["ACUTE_BEREAVEMENT_SHOCK"]
    assert issubclass(UnknownActionError, KeyError)


def test_red_flags(tax: Taxonomy) -> None:
    flags = tax.red_flags()
    assert sorted(flags) == [
        "SIT-02-04",
        "SIT-02-06",
        "SIT-06-01",
        "SIT-06-05",
        "SIT-08-04",
        "SIT-09-01",
        "SIT-10-04",
    ]
    assert flags["SIT-09-01"].allowed_actions == (
        "EMOTIONAL_HOLDING_PRESENCE",
        "DBT_TIPP_MODIFIED_BREATHING",
        "29:pmr_release",
        "REFERRAL_CARD_PRESENTATION",
    )
    assert flags["SIT-02-04"].banned_methods == ("03", "RADICAL_COGNITIVE_DEBATE")


def test_banned_tags(tax: Taxonomy) -> None:
    assert tax.banned_tag_methods("SELF_DETOX_GUIDANCE") == ("10",)
    assert tax.is_banned_tag("TRAUMA_DETAIL_EXPLORATION") and not tax.is_banned_tag("03")
    with pytest.raises(TaxonomyError):
        tax.banned_tag_methods("NOT_A_TAG")


def test_stabilization_whitelist(tax: Taxonomy) -> None:
    assert tax.stabilization_whitelist() == ("28", "29", "30:grounding", "12:tipp_breathing")


@pytest.mark.parametrize(
    "score,level",
    [
        (0.0, CrisisLevel.L0),
        (0.1999, CrisisLevel.L0),
        (0.2, CrisisLevel.L1),
        (0.4999, CrisisLevel.L1),
        (0.5, CrisisLevel.L2),
        (0.7999, CrisisLevel.L2),
        (0.8, CrisisLevel.L3),
        (1.0, CrisisLevel.L3),
    ],
)
def test_crisis_level_boundaries(tax: Taxonomy, score: float, level: CrisisLevel) -> None:
    assert tax.crisis_level_for_score(score) is level


@pytest.mark.parametrize("score", [-0.01, 1.01, math.nan])
def test_crisis_level_rejects_out_of_range(tax: Taxonomy, score: float) -> None:
    with pytest.raises(ValueError):
        tax.crisis_level_for_score(score)


def test_crisis_exit_safe_turns(tax: Taxonomy) -> None:
    assert tax.crisis_exit_safe_turns(CrisisLevel.L2) == 2
    assert tax.crisis_exit_safe_turns(CrisisLevel.L3) == 3
    with pytest.raises(ValueError):
        tax.crisis_exit_safe_turns(CrisisLevel.L1)
    with pytest.raises(ValueError):
        tax.crisis_exit_safe_turns(CrisisLevel.L0)


def _mutated(tmp_path: Path, mutate: Callable[[dict[str, Any]], None]) -> Path:
    data = yaml.safe_load((ROOT / "taxonomy.yaml").read_text(encoding="utf-8"))
    mutate(data)
    p = tmp_path / "t.yaml"
    p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return p


def test_integrity_accepts_unmodified_taxonomy(tmp_path: Path) -> None:
    assert load_taxonomy(_mutated(tmp_path, lambda d: None)).version == "3.2.0"


def test_integrity_rejects_alias_collision(tmp_path: Path) -> None:
    def m(d: dict[str, Any]) -> None:
        d["action_registry"][0]["aliases"].append("30:grounding")

    with pytest.raises(TaxonomyError, match="alias"):
        load_taxonomy(_mutated(tmp_path, m))


def test_integrity_rejects_alias_equal_to_method_id(tmp_path: Path) -> None:
    def m(d: dict[str, Any]) -> None:
        d["action_registry"][0]["aliases"].append("28")

    with pytest.raises(TaxonomyError, match="alias"):
        load_taxonomy(_mutated(tmp_path, m))


def test_integrity_rejects_alias_shared_by_two_actions(tmp_path: Path) -> None:
    def m(d: dict[str, Any]) -> None:
        d["action_registry"][0]["aliases"].append("GROUNDING_54321")

    with pytest.raises(TaxonomyError, match="alias"):
        load_taxonomy(_mutated(tmp_path, m))


def test_integrity_rejects_unresolvable_red_flag_action(tmp_path: Path) -> None:
    def m(d: dict[str, Any]) -> None:
        d["clinical_red_flags"]["mandatory_referral_disorders"][0]["allowed_actions"].append("NOPE")

    with pytest.raises(TaxonomyError, match="SIT-02-04"):
        load_taxonomy(_mutated(tmp_path, m))


def test_integrity_rejects_unresolvable_banned_entry(tmp_path: Path) -> None:
    def m(d: dict[str, Any]) -> None:
        d["clinical_red_flags"]["mandatory_referral_disorders"][1]["banned_methods"].append("NOPE")

    with pytest.raises(TaxonomyError, match="SIT-02-06"):
        load_taxonomy(_mutated(tmp_path, m))


def test_integrity_rejects_unresolvable_whitelist_entry(tmp_path: Path) -> None:
    def m(d: dict[str, Any]) -> None:
        d["colbo"]["explore_stabilization_whitelist"]["method_ids"].append("99:nope")

    with pytest.raises(TaxonomyError, match="99:nope"):
        load_taxonomy(_mutated(tmp_path, m))


def test_integrity_rejects_unknown_contraindication(tmp_path: Path) -> None:
    def m(d: dict[str, Any]) -> None:
        d["method_safety_tiers"]["grade_A"]["methods"][0]["contraindications"].append("MADE_UP")

    with pytest.raises(TaxonomyError, match="MADE_UP"):
        load_taxonomy(_mutated(tmp_path, m))


def test_integrity_rejects_unknown_action_contraindication(tmp_path: Path) -> None:
    def m(d: dict[str, Any]) -> None:
        d["action_registry"][1]["contraindications"].append("MADE_UP")

    with pytest.raises(TaxonomyError, match="MADE_UP"):
        load_taxonomy(_mutated(tmp_path, m))


def test_integrity_rejects_crisis_gap(tmp_path: Path) -> None:
    def m(d: dict[str, Any]) -> None:
        d["crisis_hierarchy"]["L2"]["score_range"] = [0.55, 0.8]

    with pytest.raises(TaxonomyError, match="crisis"):
        load_taxonomy(_mutated(tmp_path, m))


def test_integrity_rejects_crisis_wrong_interval_type(tmp_path: Path) -> None:
    def m(d: dict[str, Any]) -> None:
        d["crisis_hierarchy"]["L3"]["interval_type"] = "HALF_OPEN"

    with pytest.raises(TaxonomyError, match="crisis"):
        load_taxonomy(_mutated(tmp_path, m))


def test_integrity_rejects_crisis_not_ending_at_one(tmp_path: Path) -> None:
    def m(d: dict[str, Any]) -> None:
        d["crisis_hierarchy"]["L3"]["score_range"] = [0.8, 0.95]

    with pytest.raises(TaxonomyError, match="crisis"):
        load_taxonomy(_mutated(tmp_path, m))


def test_integrity_rejects_label_alias_with_unknown_target(tmp_path: Path) -> None:
    def m(d: dict[str, Any]) -> None:
        d["emotion_aliases"]["rumination"] = "not_an_emotion"

    with pytest.raises(TaxonomyError, match="rumination"):
        load_taxonomy(_mutated(tmp_path, m))


# -- duplicated safety values must agree (F1) ------------------------------------


def test_integrity_rejects_model_threshold_disagreeing_with_crisis_band(tmp_path: Path) -> None:
    def m(d: dict[str, Any]) -> None:
        d["risk"]["model_thresholds"]["L2"] = 0.55

    with pytest.raises(TaxonomyError, match=r"risk\.model_thresholds\.L2"):
        load_taxonomy(_mutated(tmp_path, m))


def test_integrity_rejects_exit_turns_disagreeing_with_exit_rule(tmp_path: Path) -> None:
    def m(d: dict[str, Any]) -> None:
        d["risk"]["crisis_exit_safe_turns"]["L3"] = 4

    with pytest.raises(TaxonomyError, match=r"risk\.crisis_exit_safe_turns\.L3"):
        load_taxonomy(_mutated(tmp_path, m))


@pytest.mark.parametrize("key", ["haven_enter", "haven_exit", "empower_min"])
def test_integrity_rejects_deprecated_battery_key_drift(tmp_path: Path, key: str) -> None:
    def m(d: dict[str, Any]) -> None:
        d["battery"][key] = 0.99

    with pytest.raises(TaxonomyError, match=rf"battery\.{key}"):
        load_taxonomy(_mutated(tmp_path, m))


@pytest.mark.parametrize(
    "mutation,path",
    [
        (("thresholds", "block_high_load", 0.75), "arousal.thresholds.block_high_load"),
        (("thresholds", "explore_eligible_max", 0.5), "arousal.thresholds.explore_eligible_max"),
        (("scale", None, [0.0, 2.0]), "arousal.scale"),
    ],
)
def test_integrity_rejects_deprecated_arousal_key_drift(
    tmp_path: Path, mutation: tuple[str, str | None, Any], path: str
) -> None:
    section, key, value = mutation

    def m(d: dict[str, Any]) -> None:
        if key is None:
            d["arousal"][section] = value
        else:
            d["arousal"][section][key] = value

    with pytest.raises(TaxonomyError, match=path.replace(".", r"\.")):
        load_taxonomy(_mutated(tmp_path, m))


# -- Grade A contraindications are mandatory (F2) --------------------------------


def test_grade_a_method_requires_contraindications(tmp_path: Path) -> None:
    def m(d: dict[str, Any]) -> None:
        del d["method_safety_tiers"]["grade_A"]["methods"][0]["contraindications"]

    first = yaml.safe_load((ROOT / "taxonomy.yaml").read_text(encoding="utf-8"))
    mid = first["method_safety_tiers"]["grade_A"]["methods"][0]["id"]
    with pytest.raises(TaxonomyError, match=rf"method {mid}.*contraindications"):
        load_taxonomy(_mutated(tmp_path, m))


# -- construction is always validated and isolated (F3) --------------------------


def test_constructing_taxonomy_from_bad_data_raises() -> None:
    with pytest.raises(TaxonomyError):
        Taxonomy({})
    with pytest.raises(TaxonomyError):
        Taxonomy({"version": "x"})


def _data() -> dict[str, Any]:
    loaded = yaml.safe_load((ROOT / "taxonomy.yaml").read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def test_taxonomy_constructor_validates_cross_checks() -> None:
    data = _data()
    data["risk"]["model_thresholds"]["L1"] = 0.25
    with pytest.raises(TaxonomyError, match=r"risk\.model_thresholds\.L1"):
        Taxonomy(data)


def test_taxonomy_is_isolated_from_later_mutation_of_input() -> None:
    data = _data()
    tax = Taxonomy(data)
    data["risk"]["ewma_lambda"] = 0.9
    data["emotion_aliases"]["irritability"] = "joy"
    data["crisis_hierarchy"]["exit_rule"]["safe_streak_required"]["L2"] = 9
    assert tax.threshold("risk.ewma_lambda") == 0.5
    assert tax.canonical_label("emotion", "irritability") == "anger"
    assert tax.crisis_exit_safe_turns(CrisisLevel.L2) == 2


def test_taxonomy_has_no_public_raw_view() -> None:
    assert not hasattr(Taxonomy(_data()), "raw")


# -- load errors are always TaxonomyError (F7) -----------------------------------


def test_load_rejects_invalid_utf8(tmp_path: Path) -> None:
    bad = tmp_path / "t.yaml"
    bad.write_bytes(b"version: \xff\xfe\n")
    with pytest.raises(TaxonomyError):
        load_taxonomy(bad)


@pytest.mark.parametrize("target", [["anger"], {"a": "b"}, 3])
def test_integrity_rejects_non_string_alias_target(tmp_path: Path, target: Any) -> None:
    def m(d: dict[str, Any]) -> None:
        d["emotion_aliases"]["rumination"] = target

    with pytest.raises(TaxonomyError, match="rumination"):
        load_taxonomy(_mutated(tmp_path, m))


# -- threshold() never returns non-finite numbers (F8) ---------------------------


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_threshold_rejects_non_finite(tmp_path: Path, value: float) -> None:
    def m(d: dict[str, Any]) -> None:
        d["risk"]["ewma_lambda"] = value

    tax = load_taxonomy(_mutated(tmp_path, m))
    with pytest.raises(TaxonomyError, match=r"risk\.ewma_lambda"):
        tax.threshold("risk.ewma_lambda")
