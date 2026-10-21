import shutil
from pathlib import Path

import pytest
import yaml

from olivia.core.models import CrisisLevel
from olivia.core.safety.lexicon import LexiconError, load_safety_lexicons
from olivia.core.taxonomy import load_taxonomy

PKG_LEX = Path(__file__).resolve().parents[2] / "olivia/data/lexicons"


@pytest.fixture(scope="module")
def tax():
    return load_taxonomy()


def test_loads_packaged_lexicons(tax):
    lex = load_safety_lexicons(tax)
    assert lex.risk["S1_MEANS_PILLS"].level is CrisisLevel.L3
    assert lex.risk["S1_MEANS_PILLS"].score == pytest.approx(0.9)
    assert lex.risk["L2_WANT_DIE"].score == pytest.approx(0.7)
    assert lex.risk["L1_WEARY"].score == pytest.approx(0.4)
    assert lex.risk["L1_DISAPPEAR"].score == pytest.approx(0.45)
    assert lex.risk["L2_SLEEP_NO_WAKE"].level is CrisisLevel.L2
    assert lex.risk["HYP_X_TO_DEATH"].level is CrisisLevel.L0
    assert lex.risk["HYP_X_TO_DEATH"].score == pytest.approx(0.1)
    assert lex.risk["NEG_NOT_DIE"].level is None
    assert {c.code for c in lex.red_flags.values()} == set(tax.red_flags())
    assert "ptsd" in lex.red_flags["RF_PTSD_SELF"].patterns


def test_sections(tax):
    lex = load_safety_lexicons(tax)
    assert {c.id for c in lex.cues("safety_confirm")} == {
        "CONFIRM_SAFE_NOW",
        "CONFIRM_REACHED_SUPPORT",
    }


def test_confirm_veto_section_loads(tax):
    lex = load_safety_lexicons(tax)
    (veto,) = lex.cues("confirm_veto")
    assert veto.id == "CONFIRM_VETO" and veto.level is None and veto.score is None
    assert "才怪" in veto.patterns


def _copy(tmp_path, mutate_risk=None, mutate_rf=None):
    d = tmp_path / "lex"
    shutil.copytree(PKG_LEX, d)
    for name, mutate in (("risk.yaml", mutate_risk), ("red_flags.yaml", mutate_rf)):
        if mutate:
            data = yaml.safe_load((d / name).read_text(encoding="utf-8"))
            mutate(data)
            (d / name).write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return d


def test_rejects_duplicate_id(tax, tmp_path):
    def m(d):
        d["stage2"].append({"id": "S1_MEANS_PILLS", "level": "L2", "patterns": ["x"]})

    with pytest.raises(LexiconError, match="S1_MEANS_PILLS"):
        load_safety_lexicons(tax, _copy(tmp_path, mutate_risk=m))


def test_rejects_score_outside_level_band(tax, tmp_path):
    def m(d):
        d["stage2"][0]["score"] = 0.85

    with pytest.raises(LexiconError, match="L2_WANT_DIE"):
        load_safety_lexicons(tax, _copy(tmp_path, mutate_risk=m))


def test_rejects_pattern_in_two_sections(tax, tmp_path):
    def m(d):
        d["negation"][0]["patterns"].append("想死")

    with pytest.raises(LexiconError, match="想死"):
        load_safety_lexicons(tax, _copy(tmp_path, mutate_risk=m))


def test_rejects_stage2_level_l3(tax, tmp_path):
    def m(d):
        d["stage2"][0]["level"] = "L3"

    with pytest.raises(LexiconError, match="L2_WANT_DIE"):
        load_safety_lexicons(tax, _copy(tmp_path, mutate_risk=m))


def test_rejects_unknown_red_flag_code(tax, tmp_path):
    def m(d):
        d["entries"][0]["code"] = "SIT-99-99"

    with pytest.raises(LexiconError, match="SIT-99-99"):
        load_safety_lexicons(tax, _copy(tmp_path, mutate_rf=m))


def test_rejects_code_without_feature_tier(tax, tmp_path):
    def m(d):
        d["entries"] = [e for e in d["entries"] if e["id"] != "RF_BPD_FEAT"]

    with pytest.raises(LexiconError, match="SIT-09-01"):
        load_safety_lexicons(tax, _copy(tmp_path, mutate_rf=m))


def test_rejects_empty_patterns(tax, tmp_path):
    def m(d):
        d["hyperbole"][0]["patterns"] = []

    with pytest.raises(LexiconError, match="HYP_DEATH_IDIOM"):
        load_safety_lexicons(tax, _copy(tmp_path, mutate_risk=m))


def test_mappings_are_read_only(tax):
    lex = load_safety_lexicons(tax)
    with pytest.raises(TypeError):
        lex.risk["X"] = lex.risk["NEG_NOT_DIE"]  # type: ignore[index]
    with pytest.raises(TypeError):
        lex.red_flags["X"] = lex.red_flags["RF_PTSD_SELF"]  # type: ignore[index]


def test_patterns_and_negations_are_normalized(tax, tmp_path):
    def m(d):
        d["entries"][4]["patterns"] = ["P T S D"]

    lex = load_safety_lexicons(tax, _copy(tmp_path, mutate_rf=m))
    assert lex.red_flags["RF_PTSD_SELF"].patterns == ("ptsd",)
    assert lex.self_report_negations == ("没有", "不是", "并没有", "并非", "没")


def test_rejects_wrong_version(tax, tmp_path):
    def m(d):
        d["version"] = 2

    with pytest.raises(LexiconError, match="risk.yaml"):
        load_safety_lexicons(tax, _copy(tmp_path, mutate_risk=m))


def test_rejects_pattern_shared_by_two_red_flag_codes(tax, tmp_path):
    def m(d):
        d["entries"][2]["patterns"].append("双相")

    with pytest.raises(LexiconError, match="双相"):
        load_safety_lexicons(tax, _copy(tmp_path, mutate_rf=m))


def test_rejects_pattern_empty_after_normalization(tax, tmp_path):
    def m(d):
        d["hyperbole"][0]["patterns"] = [" \u200b "]

    with pytest.raises(LexiconError, match="HYP_DEATH_IDIOM"):
        load_safety_lexicons(tax, _copy(tmp_path, mutate_risk=m))


def test_rejects_score_on_non_stage2_cue(tax, tmp_path):
    def m(d):
        d["stage1"][0]["score"] = 0.9

    with pytest.raises(LexiconError, match="S1_MEANS_PILLS"):
        load_safety_lexicons(tax, _copy(tmp_path, mutate_risk=m))
