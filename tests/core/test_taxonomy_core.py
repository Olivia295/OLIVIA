from pathlib import Path

import pytest

from olivia.core.taxonomy import Taxonomy, TaxonomyError, load_taxonomy


@pytest.fixture(scope="module")
def tax() -> Taxonomy:
    return load_taxonomy()


def test_version(tax: Taxonomy) -> None:
    assert tax.version == "3.2.0"


@pytest.mark.parametrize(
    "path,expected",
    [
        ("arousal.thresholds.somatic_priority", 0.80),
        ("arousal.thresholds.cognitive_block", 0.85),
        ("arousal.thresholds.exploration_allow", 0.60),
        ("battery.thresholds.haven_enter", 0.20),
        ("battery.thresholds.haven_exit", 0.35),
        ("battery.thresholds.empower_min", 0.40),
        ("risk.ewma_lambda", 0.5),
        ("thompson_sampling_index.lambda_decay_per_day", 0.1),
        # SDD section 6.3 evidence-level priors Beta(alpha_0, beta_0).
        ("thompson_sampling_index.evidence_level_priors.Level I.alpha", 4.0),
        ("thompson_sampling_index.evidence_level_priors.Level I.beta", 1.0),
        ("thompson_sampling_index.evidence_level_priors.Level II.alpha", 3.0),
        ("thompson_sampling_index.evidence_level_priors.Level II.beta", 1.0),
        ("thompson_sampling_index.evidence_level_priors.Level III.alpha", 2.0),
        ("thompson_sampling_index.evidence_level_priors.Level III.beta", 1.0),
    ],
)
def test_threshold_values(tax: Taxonomy, path: str, expected: float) -> None:
    assert tax.threshold(path) == pytest.approx(expected)


def test_every_method_evidence_level_has_a_prior(tax: Taxonomy) -> None:
    levels = {m.evidence_level for m in tax.methods().values() if m.evidence_level is not None}
    assert levels == {"Level I", "Level II", "Level III"}
    for level in levels:
        base = f"thompson_sampling_index.evidence_level_priors.{level}"
        assert tax.threshold(f"{base}.alpha") > 0
        assert tax.threshold(f"{base}.beta") > 0


def test_spectrum_ids(tax: Taxonomy) -> None:
    assert tax.spectrum_ids() == tuple(f"{i:02d}" for i in range(1, 12))


def test_threshold_missing_key_raises(tax: Taxonomy) -> None:
    with pytest.raises(TaxonomyError, match="battery.thresholds.nope"):
        tax.threshold("battery.thresholds.nope")


def test_threshold_non_numeric_raises(tax: Taxonomy) -> None:
    with pytest.raises(TaxonomyError):
        tax.threshold("version")


def test_threshold_bool_is_not_numeric(tmp_path: Path) -> None:
    f = tmp_path / "t.yaml"
    packaged = Path(__file__).resolve().parents[2] / "olivia" / "data" / "taxonomy.yaml"
    f.write_text(packaged.read_text(encoding="utf-8") + "\nflag: true\n", encoding="utf-8")
    with pytest.raises(TaxonomyError, match="flag"):
        load_taxonomy(f).threshold("flag")


def test_values_counts(tax: Taxonomy) -> None:
    assert len(tax.values("emotions")) == 16
    assert len(tax.values("cognitive_distortions")) == 9
    assert len(tax.values("schemas")) == 20
    assert len(tax.values("satir_yearnings")) == 5
    assert len(tax.values("communication_stances")) == 5
    assert len(tax.values("contraindication_enums")) == 13
    assert tax.values("distress_categories")[0] == "ANXIETY_PANIC"


def test_values_unknown_name_raises(tax: Taxonomy) -> None:
    with pytest.raises(TaxonomyError):
        tax.values("planets")


def test_canonical_label(tax: Taxonomy) -> None:
    assert tax.canonical_label("emotion", "anxiety") == "anxiety"
    assert tax.canonical_label("emotion", "irritability") == "anger"
    assert tax.canonical_label("distortion", "LABELING") == "ALL_OR_NOTHING"
    assert tax.canonical_label("schema", "PERFECTIONISM") == "UNRELENTING_STANDARDS"
    assert tax.canonical_label("yearning", "SAFETY_ORDER") == "SAFETY"
    with pytest.raises(TaxonomyError):
        tax.canonical_label("emotion", "joy")


def test_load_rejects_malformed_yaml(tmp_path: Path) -> None:
    bad = tmp_path / "t.yaml"
    bad.write_text("version: [unclosed", encoding="utf-8")
    with pytest.raises(TaxonomyError):
        load_taxonomy(bad)


def test_load_rejects_non_mapping(tmp_path: Path) -> None:
    bad = tmp_path / "t.yaml"
    bad.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(TaxonomyError):
        load_taxonomy(bad)


def test_load_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(TaxonomyError):
        load_taxonomy(tmp_path / "absent.yaml")
