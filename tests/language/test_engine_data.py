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
from olivia.core.models import PersonaSpectrum
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
    "language/feelings.yaml",
    "language/utterances.yaml",
    "templates/gentle_holding.yaml",
    "templates/zen_philosopher.yaml",
    "templates/rational_peer.yaml",
    "templates/silent_anchor.yaml",
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


def _goodbyes_only_for_the_evening(d: dict[str, Any]) -> None:
    # F6b: one line without an evening word is not enough for the daytime.
    d["stages"]["S_ready"]["after_close"] = [
        "好，那就先这样。今天辛苦了，好好休息。",
        "愿你今晚过得轻松一点，我一直在这里。",
        "好的。今天就先停在这里，什么时候想回来聊聊，都可以。",
    ]


def _daytime_goodbyes_need_a_slot_free_line(d: dict[str, Any]) -> None:
    d["stages"]["S_ready"]["after_close"] = [
        "愿你今晚过得轻松一点，我一直在这里。",
        "{user_name}，今天先停在这里。",
        "{user_name}，嗯，我知道了，我一直在这里。",
    ]


def _haven_exit_hint_asks(d: dict[str, Any]) -> None:
    # F9: it replaces the haven line, so it never asks.
    d["followups"]["haven_exit_hint"] = [
        "想聊别的吗？说「我好多了」就好。",
        "我在这里陪着你，慢慢歇。",
    ]


def _grief_request_with_a_number(d: dict[str, Any]) -> None:
    # F10: not a crisis line, so no hotline number.
    d["followups"]["grief_request"] = [
        "你想要一个方法，我听见了。可以打 12356 找人聊聊哀伤咨询。",
        "{user_name}，也可以找做哀伤咨询的心理咨询师。",
    ]


def _grief_request_without_counselling(d: dict[str, Any]) -> None:
    d["followups"]["grief_request"] = [
        "你想要一个方法，我听见了，我们先慢慢说。",
        "{user_name}，先慢慢说就好。",
    ]


def _haven_exit_hint_without_the_words(d: dict[str, Any]) -> None:
    d["followups"]["haven_exit_hint"] = [
        "我在这里陪着你，慢慢歇一歇。",
        "{user_name}，我一直都在。",
    ]


def _haven_exit_hint_with_one_way_out(d: dict[str, Any]) -> None:
    # F10: both ways out are quoted, not only 「我好多了」.
    d["followups"]["haven_exit_hint"] = [
        "我就在这里陪着你。想聊别的时，说一句「我好多了」就好。",
        "{user_name}，想聊别的，说「我好多了」或「换个话题吧」就好。",
    ]


def _followup_missing(d: dict[str, Any]) -> None:
    del d["followups"]["kit_empty"]


def _followup_with_mirror(d: dict[str, Any]) -> None:
    d["followups"]["clarify_feedback"].append("{mirror}，要先收进锦囊吗？")


def _followup_without_plain_variant(d: dict[str, Any]) -> None:
    d["followups"]["closing_declined"] = ["{user_name}，不用定也没关系。"]


def _wellbeing_missing(d: dict[str, Any]) -> None:
    del d["wellbeing"]["late_night"]


def _wellbeing_with_mirror(d: dict[str, Any]) -> None:
    d["wellbeing"]["real_support"].append("{mirror}，身边有谁可以说说吗？")


def _bad_version(d: dict[str, Any]) -> None:
    d["version"] = 2


def _wrong_persona(d: dict[str, Any]) -> None:
    d["persona"] = "GENTLE_HOLDING"


def _silent_with_three_parts(d: dict[str, Any]) -> None:
    reflect = d["stages"]["S_explore"]["parts"][0]
    d["stages"]["S_explore"]["parts"] = [
        reflect,
        {"name": "image", "variants": ["{metaphor}。"]},
        {"name": "invite", "variants": ["想说说吗？"]},
    ]


def _reworded_safety_check(d: dict[str, Any]) -> None:
    d["followups"]["safety_check"][0] = "你还好吗？"


def _inverted_empower_window(d: dict[str, Any]) -> None:
    d["window"]["empower"] = [70, 10]


def _unknown_window_key(d: dict[str, Any]) -> None:
    d["window"]["closing"] = [10, 30]


@pytest.mark.parametrize(
    ("rel", "change"),
    [
        ("templates/gentle_holding.yaml", _drop_card_title_slot),
        ("templates/gentle_holding.yaml", _unknown_slot),
        ("templates/gentle_holding.yaml", _template_without_haven_fallback),
        ("templates/gentle_holding.yaml", _followup_missing),
        ("templates/gentle_holding.yaml", _haven_exit_hint_asks),
        ("templates/silent_anchor.yaml", _haven_exit_hint_without_the_words),
        ("templates/rational_peer.yaml", _grief_request_with_a_number),
        ("templates/gentle_holding.yaml", _haven_exit_hint_with_one_way_out),
        ("templates/zen_philosopher.yaml", _grief_request_without_counselling),
        ("templates/gentle_holding.yaml", _followup_with_mirror),
        ("templates/gentle_holding.yaml", _followup_without_plain_variant),
        ("templates/gentle_holding.yaml", _wellbeing_missing),
        ("templates/gentle_holding.yaml", _wellbeing_with_mirror),
        ("templates/zen_philosopher.yaml", _wrong_persona),
        ("templates/rational_peer.yaml", _drop_card_title_slot),
        ("templates/rational_peer.yaml", _reworded_safety_check),
        ("templates/silent_anchor.yaml", _silent_with_three_parts),
        ("templates/silent_anchor.yaml", _inverted_empower_window),
        ("templates/silent_anchor.yaml", _unknown_window_key),
        ("templates/silent_anchor.yaml", _template_without_haven_fallback),
        ("templates/gentle_holding.yaml", _goodbyes_only_for_the_evening),
        ("templates/zen_philosopher.yaml", _daytime_goodbyes_need_a_slot_free_line),
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


@pytest.mark.parametrize("rel", ["language/needs.yaml", "templates/silent_anchor.yaml"])
def test_missing_file_fails_fast(tmp_path: Path, tax: Taxonomy, rel: str) -> None:
    root = _copy(tmp_path)
    (root / rel).unlink()
    with pytest.raises(LanguageDataError, match="cannot read"):
        load_language_data(tax, root)


def test_persona_argument_picks_the_templates(tmp_path: Path, tax: Taxonomy) -> None:
    data = load_language_data(tax, _copy(tmp_path), persona=PersonaSpectrum.SILENT_ANCHOR)
    assert data.templates.persona is PersonaSpectrum.SILENT_ANCHOR
    assert data.for_persona(PersonaSpectrum.SILENT_ANCHOR) is data
    assert data.for_persona(PersonaSpectrum.RATIONAL_PEER).templates.persona == "RATIONAL_PEER"


def test_invalid_yaml_fails_fast(tmp_path: Path, tax: Taxonomy) -> None:
    root = _copy(tmp_path)
    (root / "language/render.yaml").write_text("card: [", encoding="utf-8")
    with pytest.raises(LanguageDataError, match="invalid YAML"):
        load_language_data(tax, root)
