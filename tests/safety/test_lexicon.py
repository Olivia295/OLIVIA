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


# -- stage2_pairs ----------------------------------------------------------------------


def _pair(d, cue_id="L2_METHOD_PAIR_MANNER"):
    return next(p for p in d["stage2_pairs"] if p["id"] == cue_id)


def test_loads_pair_cues(tax):
    lex = load_safety_lexicons(tax)
    by_id = {p.id: p for p in lex.pairs}
    assert set(by_id) == {"L2_METHOD_PAIR_MANNER", "L2_METHOD_PAIR_MEANS"}
    manner = by_id["L2_METHOD_PAIR_MANNER"]
    assert manner.level is CrisisLevel.L2 and manner.score == pytest.approx(0.7)
    assert "自杀" in manner.anchors and "无痛" in manner.requests
    assert "预防自杀" in manner.exceptions
    assert not set(by_id) & set(lex.risk)


def test_pair_section_is_optional(tax, tmp_path):
    def m(d):
        del d["stage2_pairs"]

    assert load_safety_lexicons(tax, _copy(tmp_path, mutate_risk=m)).pairs == ()


def test_pair_phrases_are_normalized(tax, tmp_path):
    def m(d):
        _pair(d)["anchors"].append("End  My Own Days")

    lex = load_safety_lexicons(tax, _copy(tmp_path, mutate_risk=m))
    (manner,) = [p for p in lex.pairs if p.id == "L2_METHOD_PAIR_MANNER"]
    assert manner.anchors[-1] == "endmyowndays"


@pytest.mark.parametrize(
    "mutate,match",
    [
        (lambda d: _pair(d)["anchors"].append("想死"), "L2_WANT_DIE"),
        (lambda d: _pair(d)["requests"].append("自杀"), "自杀"),
        (lambda d: _pair(d)["anchors"].append("自杀"), "自杀"),
        (lambda d: _pair(d)["exceptions"].append("预防感冒"), "预防感冒"),
        (lambda d: _pair(d).update(requests=[]), "requests"),
        (lambda d: _pair(d).pop("anchors"), "anchors"),
        (lambda d: _pair(d).update(level="L3"), "L2_METHOD_PAIR_MANNER"),
        (lambda d: _pair(d).update(patterns=["x"]), "unknown keys"),
        (lambda d: _pair(d).update(id="S1_MEANS_PILLS"), "S1_MEANS_PILLS"),
        (lambda d: _pair(d).update(id="X\x00"), "printable"),
    ],
)
def test_rejects_malformed_pair_cue(tax, tmp_path, mutate, match):
    with pytest.raises(LexiconError, match=match):
        load_safety_lexicons(tax, _copy(tmp_path, mutate_risk=mutate))


def test_pair_phrase_may_repeat_across_entries(tax):
    # The two entries share anchors (轻生, 结束生命 ...); the matcher keys pair phrases by
    # phrase, so one phrase can serve several entries.
    lex = load_safety_lexicons(tax)
    manner, means = sorted(lex.pairs, key=lambda p: p.id)
    assert set(manner.anchors) & set(means.anchors)
