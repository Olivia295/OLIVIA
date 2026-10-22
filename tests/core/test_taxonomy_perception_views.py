"""Taxonomy accessors the perception stub reads: emotion profiles and bands."""

from pathlib import Path
from typing import Any

import pytest
import yaml

from olivia.core.taxonomy import Taxonomy, TaxonomyError, load_taxonomy

ROOT = Path(__file__).resolve().parents[2] / "olivia" / "data"


@pytest.fixture(scope="module")
def tax() -> Taxonomy:
    return load_taxonomy()


def _data() -> dict[str, Any]:
    loaded = yaml.safe_load((ROOT / "taxonomy.yaml").read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def test_emotion_profiles_cover_every_emotion_in_order(tax: Taxonomy) -> None:
    profiles = tax.emotion_profiles()
    assert tuple(profiles) == tax.values("emotions")
    anxiety = profiles["anxiety"]
    assert anxiety.valence_range == (-0.9, -0.3)
    assert anxiety.default_arousal == pytest.approx(0.75)


@pytest.mark.parametrize(
    "path,expected",
    [
        ("intent_rules.information_min_valence", -0.70),
        ("intent_rules.validation_max_valence", -0.50),
    ],
)
def test_intent_rule_thresholds_may_be_negative(tax: Taxonomy, path: str, expected: float) -> None:
    assert tax.threshold(path) == pytest.approx(expected)


def test_arousal_bands_tile_the_unit_interval(tax: Taxonomy) -> None:
    bands = tax.bands("arousal")
    assert list(bands) == ["low", "moderate", "elevated", "acute"]
    assert bands["elevated"] == (0.65, 0.80)
    assert list(tax.bands("battery")) == ["critical_low", "low", "medium", "full"]


def test_band_order_follows_the_edges_not_the_file() -> None:
    data = _data()
    data["arousal"]["bands"] = dict(reversed(list(data["arousal"]["bands"].items())))
    assert list(Taxonomy(data).bands("arousal")) == ["low", "moderate", "elevated", "acute"]


@pytest.mark.parametrize(
    "value,band",
    [(0.0, "low"), (0.3499, "low"), (0.35, "moderate"), (0.65, "elevated"), (0.8, "acute")],
)
def test_band_of_uses_half_open_bands(tax: Taxonomy, value: float, band: str) -> None:
    assert tax.band_of("arousal", value) == band


def test_band_of_top_edge_is_closed(tax: Taxonomy) -> None:
    assert tax.band_of("arousal", 1.0) == "acute"
    assert tax.band_of("battery", 1.0) == "full"


@pytest.mark.parametrize("value", [-0.01, 1.01, float("nan")])
def test_band_of_rejects_out_of_range(tax: Taxonomy, value: float) -> None:
    with pytest.raises(ValueError):
        tax.band_of("arousal", value)


def test_unknown_band_scale_raises(tax: Taxonomy) -> None:
    with pytest.raises(TaxonomyError, match="band scale"):
        tax.bands("mood")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "field,value,message",
    [
        ("default_arousal", 1.5, "default_arousal"),
        ("default_arousal", True, "default_arousal"),
        ("valence_range", [0.5], "valence_range"),
        ("valence_range", [0.5, -0.5], "valence_range"),
        ("valence_range", [-2.0, 0.0], "valence_range"),
    ],
)
def test_malformed_emotion_profile_is_rejected(field: str, value: Any, message: str) -> None:
    data = _data()
    data["emotions"][0][field] = value
    with pytest.raises(TaxonomyError, match=message):
        Taxonomy(data)


def test_duplicate_emotion_id_is_rejected() -> None:
    data = _data()
    data["emotions"].append(dict(data["emotions"][0]))
    with pytest.raises(TaxonomyError, match="duplicate emotion"):
        Taxonomy(data)


@pytest.mark.parametrize(
    "band,value,message",
    [
        ("moderate", [0.40, 0.65], "must start at"),
        ("acute", [0.80, 0.95], "must end at 1.0"),
        ("elevated", [0.65, 0.65], "must start at"),
        ("low", "x", r"\[low, high\]"),
    ],
)
def test_bands_with_gaps_or_bad_values_are_rejected(band: str, value: Any, message: str) -> None:
    data = _data()
    data["arousal"]["bands"][band] = value
    with pytest.raises(TaxonomyError, match=message):
        Taxonomy(data)
