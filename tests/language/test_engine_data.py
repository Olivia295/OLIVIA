"""Strict loading of the language data, plus the needs.yaml and render.yaml contents."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from olivia.core.language import ContentKind, apply_willow
from olivia.core.language.data import LanguageData, LanguageDataError, load_language_data
from olivia.core.taxonomy import Taxonomy

DATA = Path(__file__).resolve().parents[2] / "olivia/data"
DRAFT_HEADER = (
    "# 草稿：待 G-0 两名注册心理师审核"
    "（docs/superpowers/plans/2026-10-22-remaining-roadmap.md R1-4）"
)
FILES = [
    "language/willow.yaml",
    "language/metaphors.yaml",
    "language/needs.yaml",
    "language/render.yaml",
    "templates/gentle_holding.yaml",
    "cards/grade_a.yaml",
    "cards/grade_bc_info.yaml",
]


@pytest.mark.parametrize("name", ["language/needs.yaml", "language/render.yaml"])
def test_new_files_carry_the_draft_header(name: str) -> None:
    assert (DATA / name).read_text(encoding="utf-8").splitlines()[0] == DRAFT_HEADER


def test_needs_cover_every_yearning(tax: Taxonomy, lang: LanguageData) -> None:
    assert list(lang.needs) == list(tax.values("satir_yearnings"))
    seen: set[str] = set()
    for yid, phrases in lang.needs.items():
        assert len(phrases) >= 3, yid
        for phrase in phrases:
            assert 2 <= len(phrase) <= 6, phrase
            assert "我" not in phrase and "你" not in phrase, phrase
            assert phrase not in seen, phrase
            seen.add(phrase)
            assert apply_willow(phrase, ContentKind.NORMAL, lang.willow) == phrase
            assert not [t for t in lang.willow.diagnosis_terms if t in phrase.casefold()]


def test_render_text_is_clean(lang: LanguageData) -> None:
    r = lang.render
    texts = [v for v in vars(r).values() if isinstance(v, str)]
    texts += list(r.referral_destinations.values()) + list(r.crisis_emergency_heading.values())
    texts += list(r.emergency_purposes.values())
    for text in texts:
        assert not [t for t in lang.willow.diagnosis_terms if t in text.casefold()], text
        assert not any(ch.isdigit() for ch in text.replace("{minutes}", "")), text
    for text in [r.referral_intro, r.referral_closing, *r.referral_destinations.values()]:
        assert "你应该" not in text and "必须" not in text


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


def test_copied_data_loads(tmp_path: Path, tax: Taxonomy) -> None:
    assert load_language_data(tax, _copy(tmp_path)).templates.persona == "GENTLE_HOLDING"


def _drop_card_title_slot(d: dict[str, Any]) -> None:
    part = d["stages"]["S_empower"]["parts"][1]
    part["variants"][0] = "这个小练习很短。"


def _unknown_slot(d: dict[str, Any]) -> None:
    d["stages"]["S_haven"]["variants"][0] = "{mood} 我在这里。"


def _missing_need(d: dict[str, Any]) -> None:
    del d["by_yearning"]["SAFETY"]


def _extra_card_step(d: dict[str, Any]) -> None:
    d["cards"][0]["steps"].append("多出来的一步。")


def _unknown_card_key(d: dict[str, Any]) -> None:
    d["cards"][0]["emoji"] = "x"


def _unknown_exemption_kind(d: dict[str, Any]) -> None:
    d["exemptions"]["depathologize"].append("WHATEVER")


def _diagnosis_exempt(d: dict[str, Any]) -> None:
    d["exemptions"]["diagnosis_terms"] = ["CRISIS"]


def _missing_referral(d: dict[str, Any]) -> None:
    del d["referral"]["destinations"]["SIT-02-04"]


def _missing_purpose(d: dict[str, Any]) -> None:
    del d["crisis"]["emergency_purposes"]["police"]


def _missing_metaphor_cell(d: dict[str, Any]) -> None:
    del d["by_spectrum_yearning"]["01"]["SAFETY"]


def _cold_water_card(d: dict[str, Any]) -> None:
    d["excluded"] = [{"id": "12:tipp_breathing", "reason": "x"}]


def _info_grade(d: dict[str, Any]) -> None:
    d["entries"][0]["grade"] = "C"


def _template_without_haven_fallback(d: dict[str, Any]) -> None:
    d["stages"]["S_haven"]["variants"] = ["{user_name}，我在这里陪着你，慢慢歇一歇就好。"]


def _followup_missing(d: dict[str, Any]) -> None:
    del d["followups"]["kit_empty"]


def _followup_with_mirror(d: dict[str, Any]) -> None:
    d["followups"]["clarify_feedback"].append("{mirror}，要先收进锦囊吗？")


def _followup_without_plain_variant(d: dict[str, Any]) -> None:
    d["followups"]["closing_declined"] = ["{user_name}，不用定也没关系。"]


def _bad_version(d: dict[str, Any]) -> None:
    d["version"] = 2


@pytest.mark.parametrize(
    ("rel", "change"),
    [
        ("templates/gentle_holding.yaml", _drop_card_title_slot),
        ("templates/gentle_holding.yaml", _unknown_slot),
        ("templates/gentle_holding.yaml", _template_without_haven_fallback),
        ("templates/gentle_holding.yaml", _followup_missing),
        ("templates/gentle_holding.yaml", _followup_with_mirror),
        ("templates/gentle_holding.yaml", _followup_without_plain_variant),
        ("language/needs.yaml", _missing_need),
        ("language/needs.yaml", _bad_version),
        ("cards/grade_a.yaml", _extra_card_step),
        ("cards/grade_a.yaml", _unknown_card_key),
        ("cards/grade_a.yaml", _cold_water_card),
        ("cards/grade_bc_info.yaml", _info_grade),
        ("language/willow.yaml", _unknown_exemption_kind),
        ("language/willow.yaml", _diagnosis_exempt),
        ("language/render.yaml", _missing_referral),
        ("language/render.yaml", _missing_purpose),
        ("language/metaphors.yaml", _missing_metaphor_cell),
    ],
)
def test_bad_data_fails_fast(
    tmp_path: Path, tax: Taxonomy, rel: str, change: Callable[[dict[str, Any]], None]
) -> None:
    root = _copy(tmp_path)
    _edit(root, rel, change)
    with pytest.raises(LanguageDataError):
        load_language_data(tax, root)


def test_missing_file_fails_fast(tmp_path: Path, tax: Taxonomy) -> None:
    root = _copy(tmp_path)
    (root / "language/needs.yaml").unlink()
    with pytest.raises(LanguageDataError, match="cannot read"):
        load_language_data(tax, root)


def test_invalid_yaml_fails_fast(tmp_path: Path, tax: Taxonomy) -> None:
    root = _copy(tmp_path)
    (root / "language/render.yaml").write_text("card: [", encoding="utf-8")
    with pytest.raises(LanguageDataError, match="invalid YAML"):
        load_language_data(tax, root)
