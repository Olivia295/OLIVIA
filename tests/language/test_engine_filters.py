"""W.I.L.L.O.W. filters: order, masking, exemptions and the diagnosis sentence gate."""

from __future__ import annotations

from dataclasses import replace
from types import MappingProxyType

import pytest

from olivia.core.language import ContentKind, apply_willow
from olivia.core.language.data import LanguageData, LanguageDataError, WillowData
from olivia.core.language.filters import replace_longest

ALL_KINDS = list(ContentKind)


@pytest.fixture(scope="module")
def willow(lang: LanguageData) -> WillowData:
    return lang.willow


@pytest.mark.parametrize("kind", ALL_KINDS)
def test_protected_terms_survive_every_kind(willow: WillowData, kind: ContentKind) -> None:
    for term in willow.protected_terms:
        # Surround each term with triggers from both rewrite tables.
        text = f"你应该了解{term}，患者必须坚强点。"
        out = apply_willow(text, kind, willow)
        assert term in out, (kind, term, out)


def test_masking_shields_terms_a_table_would_otherwise_change(willow: WillowData) -> None:
    toy = replace(
        willow,
        depathologize=MappingProxyType({"治疗": "照料"}),
        protected_terms=("心理治疗",),
    )
    assert apply_willow("去做心理治疗，也需要治疗。", ContentKind.NORMAL, toy) == (
        "去做心理治疗，也需要照料。"
    )


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("你应该早点睡。", "或许可以试试早点睡。"),
        ("你应该很累吧。", "你可能很累吧。"),
        ("说出来不是必须的。", "说出来并不强求。"),
        ("首先，深呼吸三次。", "如果愿意，可以先深呼吸三次。"),
        ("你的症状让你很辛苦。", "你的这些感受让你很辛苦。"),
        ("这种病态的想法。", "这种卡住的想法。"),
        # depathologize runs before didactic rewrites.
        ("患者必须休息。", "朋友可以试着休息。"),
    ],
)
def test_normal_text_is_rewritten(willow: WillowData, before: str, after: str) -> None:
    assert apply_willow(before, ContentKind.NORMAL, willow) == after


def test_replacement_is_never_rescanned() -> None:
    assert replace_longest("ab", {"a": "b", "b": "c"}) == "bc"
    assert replace_longest("abc", {"ab": "x", "abc": "y", "c": "z"}) == "y"


@pytest.mark.parametrize("kind", [ContentKind.CRISIS, ContentKind.REFERRAL])
def test_crisis_and_referral_keep_safety_wording(willow: WillowData, kind: ContentKind) -> None:
    text = "必须确保安全，请务必联系身边人。"
    assert apply_willow(text, kind, willow) == text


def test_grade_c_info_keeps_clinical_wording(willow: WillowData) -> None:
    text = "必须在专业人员陪同下进行，接受治疗前先就医。"
    assert apply_willow(text, ContentKind.GRADE_C_INFO, willow) == text
    assert apply_willow(text, ContentKind.NORMAL, willow) != text


@pytest.mark.parametrize("kind", ALL_KINDS)
def test_diagnosis_sentences_are_dropped_for_every_kind(
    willow: WillowData, kind: ContentKind
) -> None:
    text = "今天辛苦了。你患有焦虑症吧？\n\n我在这里。听起来像PTSD。"
    assert apply_willow(text, kind, willow) == "今天辛苦了。\n\n我在这里。"


def test_text_without_diagnosis_is_untouched_by_the_gate(willow: WillowData) -> None:
    text = "第一段。\n\n  第二段，留着空格。"
    assert apply_willow(text, ContentKind.CRISIS, willow) == text


def test_protected_method_names_never_trigger_the_diagnosis_gate(willow: WillowData) -> None:
    text = "可以了解一下情绪障碍跨诊断统一方案。"
    assert apply_willow(text, ContentKind.NORMAL, willow) == text


def test_default_willow_is_the_packaged_file(willow: WillowData) -> None:
    assert apply_willow("你应该早点睡。", ContentKind.NORMAL) == apply_willow(
        "你应该早点睡。", ContentKind.NORMAL, willow
    )


def test_unknown_filter_name_is_rejected(willow: WillowData) -> None:
    with pytest.raises(LanguageDataError, match="unknown filter"):
        willow.exempt("nope", ContentKind.NORMAL)
