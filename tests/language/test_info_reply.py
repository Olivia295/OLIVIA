"""Grade B/C information replies and the S_clarify lens table (roadmap next-phase A4).

``render_info_reply`` frames the information card: a lead line (the user asked, or
S_clarify offers a perspective), the card, then a closing that says what the card is not:
Grade B is a way of seeing, not a task; Grade C is for a trained professional, and the
reply suggests seeing one. The whole reply passes the output gate.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from olivia.core.language import LanguageEngine
from olivia.core.language.data import LanguageData, LanguageDataError, load_language_data
from olivia.core.models import SafetyGrade
from olivia.core.taxonomy import Taxonomy

DATA = Path(__file__).resolve().parents[2] / "olivia/data"
STEP_MARKERS = ("1.", "第一步", "跟着我", "你应该", "必须", "现在请", "试着做")


@pytest.mark.parametrize("lens", [False, True])
def test_every_info_reply_passes_the_gate(
    lang: LanguageData, engine: LanguageEngine, lens: bool
) -> None:
    r = lang.render
    for mid, entry in lang.info.items():
        text = engine.render_info_reply(mid, lens=lens)
        assert engine.last_gate is not None and engine.last_gate.ok, (mid, engine.last_gate)
        assert text.startswith(r.info_lens_intro if lens else r.info_ask_intro)
        assert entry.title in text and entry.what_it_is in text
        if entry.grade is SafetyGrade.GRADE_C:
            # Clinical wording is kept and a professional is suggested explicitly.
            assert text.endswith(r.info_c_closing)
            assert "不建议独自尝试" in text
        else:
            assert text.endswith(r.info_b_closing)
        assert not any(marker in text for marker in STEP_MARKERS), mid
        assert not re.search(r"\d{3,}", text), mid  # no stray numbers


def test_closings_suggest_a_professional_and_ask_nothing_of_the_user(lang: LanguageData) -> None:
    r = lang.render
    assert any(w in r.info_c_closing for w in ("心理门诊", "精神科", "咨询师"))
    assert "自己尝试" in r.info_c_closing
    assert "不需要你去做" in r.info_b_closing


@pytest.mark.parametrize("method_id", ["01", "28", "EMOTIONAL_HOLDING_PRESENCE"])
def test_info_reply_refuses_non_info_ids(engine: LanguageEngine, method_id: str) -> None:
    with pytest.raises(ValueError):
        engine.render_info_reply(method_id, lens=False)


def test_lens_table_holds_grade_b_ids_per_spectrum(tax: Taxonomy, lang: LanguageData) -> None:
    assert lang.info_lenses, "the S_clarify lens table is empty"
    assert set(lang.info_lenses) <= set(tax.spectrum_ids())
    for spectrum, ids in lang.info_lenses.items():
        assert ids and len(set(ids)) == len(ids), spectrum
        for mid in ids:
            assert lang.info[mid].grade is SafetyGrade.GRADE_B, (spectrum, mid)


def _copy(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    shutil.copytree(DATA, root)
    return root


def _edit_info(root: Path, lenses: Any) -> None:
    path = root / "cards/grade_bc_info.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    doc["clarify_lenses"] = lenses
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")


@pytest.mark.parametrize(
    "lenses",
    [
        {"02": ["21"]},  # Grade C is never offered unasked
        {"02": ["01"]},  # Grade A has no information card
        {"99": ["19"]},  # unknown spectrum
        {"02": []},
        {"02": ["19", "19"]},
        ["19"],
    ],
)
def test_bad_lens_table_fails_fast(tmp_path: Path, tax: Taxonomy, lenses: Any) -> None:
    root = _copy(tmp_path)
    _edit_info(root, lenses)
    with pytest.raises(LanguageDataError):
        load_language_data(tax, root)


@pytest.mark.parametrize("key", ["ask_intro", "lens_intro", "b_closing", "c_closing"])
def test_render_info_lines_are_required(tmp_path: Path, tax: Taxonomy, key: str) -> None:
    root = _copy(tmp_path)
    path = root / "language/render.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    del doc["info"][key]
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    with pytest.raises(LanguageDataError):
        load_language_data(tax, root)
