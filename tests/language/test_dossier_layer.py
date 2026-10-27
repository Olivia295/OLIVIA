"""The dossier layer of the language data (plan D-2, PRD §8.2).

``metaphors.yaml by_situation`` holds imagery drawn from each wired dossier, and
``grade_bc_info.yaml situation_lenses`` the Grade B methods a dossier names. While a
situation is active the engine prefers them: situation images, then the spectrum x
yearning cell, then the fallback; situation lenses, then the spectrum's lenses. The nature
images are ZEN_PHILOSOPHER's: GENTLE_HOLDING and RATIONAL_PEER speak in their own everyday
images (``by_persona``, F3), so the image tests here speak as ZEN_PHILOSOPHER.
"""

from __future__ import annotations

import random
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from olivia.core.language import ContentKind, LanguageEngine, apply_willow
from olivia.core.language.data import LanguageData, LanguageDataError, load_language_data
from olivia.core.language.dossiers import lens_pool, situation_images
from olivia.core.models import HelpStage, PersonaSpectrum, SafetyGrade
from olivia.core.taxonomy import Taxonomy

DATA = Path(__file__).resolve().parents[2] / "olivia/data"
FILES = [
    "language/willow.yaml",
    "language/metaphors.yaml",
    "language/needs.yaml",
    "language/render.yaml",
    "language/feelings.yaml",
    "language/utterances.yaml",
    "templates/gentle_holding.yaml",
    "templates/zen_philosopher.yaml",
    "templates/rational_peer.yaml",
    "templates/silent_anchor.yaml",
    "cards/grade_a.yaml",
    "cards/grade_bc_info.yaml",
    "lexicons/substance.yaml",
]


def _copy(tmp_path: Path) -> Path:
    for rel in FILES:
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(DATA / rel, target)
    return tmp_path


def _edit(root: Path, rel: str, change: Callable[[dict[str, Any]], None]) -> None:
    path = root / rel
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


# -- data --------------------------------------------------------------------------------


def test_situation_images_cover_the_wired_dossiers(tax: Taxonomy, lang: LanguageData) -> None:
    by_situation = lang.metaphors.by_situation
    assert len(by_situation) >= 48
    assert set(by_situation) <= set(tax.situation_codes())
    assert not set(by_situation) & set(tax.red_flags())
    for code, images in by_situation.items():
        # Three dossier images; the perfectionism dossiers add PRD WILLOW-02's willow (F14).
        assert len(images) == (4 if code in WILLOW_SITUATIONS else 3), code


WILLOW_SITUATIONS = ("SIT-04-01", "SIT-04-05")


def test_perfectionism_pools_hold_the_willow_image(lang: LanguageData) -> None:
    """PRD WILLOW-02: perfectionist self-criticism is met with the bending willow."""
    m = lang.metaphors
    for code in WILLOW_SITUATIONS:
        assert any("柳枝" in image for image in m.by_situation[code]), code
    assert any("柳" in image for cell in m.by_spectrum_yearning["04"].values() for image in cell)
    gentle = m.by_persona[PersonaSpectrum.GENTLE_HOLDING].by_spectrum["04"]
    assert any("柳" in image for image in gentle)


def test_situation_images_pass_the_willow_filters_and_the_gate(
    lang: LanguageData, engine: LanguageEngine
) -> None:
    for code, images in lang.metaphors.by_situation.items():
        for image in images:
            assert apply_willow(image, ContentKind.NORMAL, lang.willow) == image, code
            reasons = engine.gate.reasons(image, kind=ContentKind.NORMAL, stage=HelpStage.S_EXPLORE)
            assert not reasons, (code, image, reasons)


def test_situation_lenses_are_grade_b_methods_the_dossier_names(
    tax: Taxonomy, lang: LanguageData
) -> None:
    lenses = lang.situation_lenses
    assert lenses  # at least one dossier names a Grade B method
    assert set(lenses) <= set(tax.situation_codes())
    assert not set(lenses) & set(tax.red_flags())
    for code, ids in lenses.items():
        assert ids, code
        for mid in ids:
            assert lang.info[mid].grade is SafetyGrade.GRADE_B, (code, mid)


def _unknown_situation_image(d: dict[str, Any]) -> None:
    d["by_situation"]["SIT-99-01"] = ["风轻轻吹过"]


def _red_flag_situation_image(d: dict[str, Any]) -> None:
    d["by_situation"]["SIT-02-04"] = ["风轻轻吹过"]


def _empty_situation_images(d: dict[str, Any]) -> None:
    d["by_situation"]["SIT-05-02"] = []


def _grade_c_situation_lens(d: dict[str, Any]) -> None:
    d["situation_lenses"]["SIT-06-02"] = ["21"]  # EMDR is Grade C: never unasked


def _red_flag_situation_lens(d: dict[str, Any]) -> None:
    d["situation_lenses"]["SIT-09-01"] = ["33"]


def _unknown_situation_lens(d: dict[str, Any]) -> None:
    d["situation_lenses"]["SIT-99-01"] = ["33"]


@pytest.mark.parametrize(
    ("rel", "change"),
    [
        ("language/metaphors.yaml", _unknown_situation_image),
        ("language/metaphors.yaml", _red_flag_situation_image),
        ("language/metaphors.yaml", _empty_situation_images),
        ("cards/grade_bc_info.yaml", _grade_c_situation_lens),
        ("cards/grade_bc_info.yaml", _red_flag_situation_lens),
        ("cards/grade_bc_info.yaml", _unknown_situation_lens),
    ],
)
def test_bad_dossier_data_fails_fast(
    tmp_path: Path, tax: Taxonomy, rel: str, change: Callable[[dict[str, Any]], None]
) -> None:
    root = _copy(tmp_path)
    _edit(root, rel, change)
    with pytest.raises(LanguageDataError):
        load_language_data(tax, root)


def test_the_dossier_sections_are_optional(tmp_path: Path, tax: Taxonomy) -> None:
    root = _copy(tmp_path)
    _edit(root, "language/metaphors.yaml", lambda d: d.pop("by_situation"))
    _edit(root, "cards/grade_bc_info.yaml", lambda d: d.pop("situation_lenses"))
    data = load_language_data(tax, root)
    assert dict(data.metaphors.by_situation) == {}
    assert dict(data.situation_lenses) == {}


# -- metaphor precedence -----------------------------------------------------------------


@pytest.fixture
def zen(lang: LanguageData) -> LanguageData:
    return lang.for_persona(PersonaSpectrum.ZEN_PHILOSOPHER)


def test_an_active_situation_picks_its_dossier_imagery(tax: Taxonomy, zen: LanguageData) -> None:
    images = zen.metaphors.by_situation["SIT-05-02"]
    for seed in range(20):
        engine = LanguageEngine(tax, rng=random.Random(seed), data=zen)
        assert engine.metaphor_phrase("05", "SAFETY", frozenset({"SIT-05-02"})) in images


def test_two_situations_pool_their_images(tax: Taxonomy, zen: LanguageData) -> None:
    both = frozenset({"SIT-05-02", "SIT-06-03"})
    pooled = situation_images(zen.metaphors.by_situation, both)
    assert set(pooled) == set(zen.metaphors.by_situation["SIT-05-02"]) | set(
        zen.metaphors.by_situation["SIT-06-03"]
    )
    seen = {
        LanguageEngine(tax, rng=random.Random(seed), data=zen).metaphor_phrase("05", "SAFETY", both)
        for seed in range(60)
    }
    assert seen <= set(pooled)
    assert seen & set(zen.metaphors.by_situation["SIT-06-03"])
    assert seen & set(zen.metaphors.by_situation["SIT-05-02"])


def test_without_a_situation_the_grid_and_the_rng_are_untouched(
    tax: Taxonomy, lang: LanguageData
) -> None:
    for seed in range(20):
        plain = LanguageEngine(tax, rng=random.Random(seed), data=lang)
        layered = LanguageEngine(tax, rng=random.Random(seed), data=lang)
        for spectrum, yearning in (("05", "SAFETY"), (None, None), ("99", "SAFETY")):
            assert plain.metaphor_phrase(spectrum, yearning) == layered.metaphor_phrase(
                spectrum, yearning, frozenset()
            )


def test_a_situation_without_images_falls_through_to_the_grid(
    tax: Taxonomy, zen: LanguageData
) -> None:
    # A red-flag code never has dossier imagery: the red-flag path owns those dossiers.
    engine = LanguageEngine(tax, rng=random.Random(1), data=zen)
    cell = zen.metaphors.by_spectrum_yearning["02"]["SAFETY"]
    assert engine.metaphor_phrase("02", "SAFETY", frozenset({"SIT-02-04"})) in cell


def test_build_slots_passes_the_situations(tax: Taxonomy, zen: LanguageData) -> None:
    engine = LanguageEngine(tax, rng=random.Random(3), data=zen)
    slots = engine.build_slots(
        user_name="小林",
        agent_name="Olivia",
        spectrum_id="05",
        yearning_id="SAFETY",
        situations=frozenset({"SIT-05-02"}),
    )
    assert slots.metaphor in zen.metaphors.by_situation["SIT-05-02"]


# -- lens precedence ---------------------------------------------------------------------


def test_lens_pool_prefers_the_dossier_lenses() -> None:
    allowed = ("19", "33", "36", "40", "47")
    by_situation = {"SIT-09-04": ("36",), "SIT-06-02": ("19", "47")}
    spectrum = ("33", "40", "47")
    assert lens_pool(allowed, by_situation, frozenset({"SIT-09-04"}), spectrum) == ["36"]
    assert lens_pool(allowed, by_situation, frozenset({"SIT-09-04", "SIT-06-02"}), spectrum) == [
        "19",
        "36",
        "47",
    ]
    assert lens_pool(allowed, by_situation, frozenset(), spectrum) == ["33", "40", "47"]


def test_lens_pool_falls_back_when_the_masks_remove_every_dossier_lens() -> None:
    allowed = ("33", "40")  # the masks took 36 away
    assert lens_pool(allowed, {"SIT-09-04": ("36",)}, frozenset({"SIT-09-04"}), ("33",)) == ["33"]
    assert lens_pool((), {"SIT-09-04": ("36",)}, frozenset({"SIT-09-04"}), ("33",)) == []
