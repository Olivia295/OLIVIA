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
    assert len(reg) == 10
    assert reg["REFERRAL_CARD_PRESENTATION"].action_type is ActionType.REFERRAL
    assert reg["12:tipp_cold_water"].contraindications == (
        "RED_FLAG_ANOREXIA",
        "RED_FLAG_BPD_NSSI",
        "CARDIORESPIRATORY_INSTABILITY",
    )
    assert reg["12:tipp_breathing"].parent_method_id == "12"
    assert reg["12:tipp_breathing"].contraindications == ()
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
