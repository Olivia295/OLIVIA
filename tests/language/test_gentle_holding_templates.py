"""GENTLE_HOLDING reply templates: slots, word windows, and banned wording (WILLOW-01..04).

Lengths are checked under two readings of "字": every non-whitespace character, and Chinese
characters only. Each bound uses the stricter reading: upper bounds and the paragraph limit
count every character, lower bounds count Chinese characters only.
"""

from __future__ import annotations

import itertools
import random
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

from olivia.core.language.data import ContentKind, load_language_data
from olivia.core.language.filters import apply_willow
from olivia.core.language.gate import OutputGate
from olivia.core.models import HelpStage, PersonaSpectrum
from olivia.core.perception.signals import Command
from olivia.core.taxonomy import load_taxonomy

TEMPLATES = Path(__file__).resolve().parents[2] / "olivia/data/templates/gentle_holding.yaml"

ALLOWED_SLOTS = {"user_name", "agent_name", "emotion", "mirror", "metaphor", "need", "card_title"}

# Typical slot lengths: emotion 3, mirror 14, metaphor 12, need 3, card_title 6, names 2.
TYPICAL = {
    "user_name": "小雨",
    "agent_name": "阿柳",
    "emotion": "无力感",
    "mirror": "你在家里做了很多却没有人看见",
    "metaphor": "柳枝在风里低伏却没有折断",
    "need": "被看见",
    "card_title": "五感着陆练习",
}
# The longest values the slot contracts allow, for the upper bounds only.
LONGEST = {
    **TYPICAL,
    "emotion": "被辜负感",
    "mirror": "你在家里做了很多很多事情却始终没有人看见",
    "metaphor": "柳枝在大风里低低伏下却始终没有折断",
    "need": "被真正看见",
}

NORMAL = (140, 260)
PARAGRAPH_MAX = 80
HAVEN = (15, 40)
SAMPLE_LIMIT = 20_000
SAMPLE_SIZE = 2_000

FORBIDDEN = [
    "你应该",
    "应该",
    "必须",
    "一定要",
    "症状",
    "病",
    "诊断",
    "患者",
    "治疗",
    "首先",
    "其次",
    "再次",
    "总而言之",
    "！",
    "!",
]
ADVICE_WORDS = ["建议", "试试", "试着", "方法", "练习"]
SCHEMA_WORDS = ["信念", "图式", "模式", "核心"]
NATURE_WORDS = ["柳", "溪", "草木", "风雨", "花", "树"]

COMPOSED_STAGES = [HelpStage.S_EXPLORE, HelpStage.S_CLARIFY, HelpStage.S_EMPOWER]

SLOT = re.compile(r"\{([^{}]*)\}")
CJK = re.compile(r"[一-鿿]")
WHITESPACE = re.compile(r"\s")
EMOJI = re.compile("[☀-➿\U0001f000-\U0001faff️]")


def _load() -> dict[str, Any]:
    with TEMPLATES.open(encoding="utf-8") as fh:
        data: dict[str, Any] = yaml.safe_load(fh)
    return data


DATA = _load()
STAGES: dict[str, Any] = DATA["stages"]


def _fill(template: str, values: dict[str, str]) -> str:
    return SLOT.sub(lambda m: values[m.group(1)], template)


def _all_chars(text: str) -> int:
    return len(WHITESPACE.sub("", text))


def _cjk_chars(text: str) -> int:
    return len(CJK.findall(text))


def _paragraphs(text: str) -> list[str]:
    return [p for p in text.split("\n\n") if p.strip()]


def _parts(stage: str) -> list[tuple[str, list[str]]]:
    """The ordered paragraph pools a composed reply draws from."""
    parts = [(p["name"], p["variants"]) for p in STAGES[stage]["parts"]]
    if stage == HelpStage.S_EMPOWER:
        # The card body sits between card_intro and after_card and is rendered elsewhere.
        parts.append(("after_card", STAGES[stage]["after_card"]))
    return parts


def _combinations(stage: str) -> Iterator[tuple[str, ...]]:
    pools = [variants for _, variants in _parts(stage)]
    total = 1
    for pool in pools:
        total *= len(pool)
    if total <= SAMPLE_LIMIT:
        yield from itertools.product(*pools)
        return
    rng = random.Random(20261022)
    for _ in range(SAMPLE_SIZE):
        yield tuple(rng.choice(pool) for pool in pools)


def _compose(combo: tuple[str, ...], values: dict[str, str]) -> str:
    return "\n\n".join(_fill(part, values) for part in combo)


def _every_string(node: Any) -> Iterator[str]:
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _every_string(value)
    elif isinstance(node, list):
        for value in node:
            yield from _every_string(value)


def _stage_strings(stage: str) -> list[str]:
    return list(_every_string(STAGES[stage]))


def _templates() -> Iterator[str]:
    """Every reply text in the file, without the part names."""
    for stage, body in STAGES.items():
        if stage in COMPOSED_STAGES:
            for _, variants in _parts(stage):
                yield from variants
        else:
            yield from _every_string(body)


def test_header_and_stage_set() -> None:
    assert DATA["persona"] == PersonaSpectrum.GENTLE_HOLDING
    assert DATA["window"] == {
        "normal": list(NORMAL),
        "paragraph_max": PARAGRAPH_MAX,
        "haven": list(HAVEN),
        "short": [60, 170],
    }
    assert set(STAGES) == {stage.value for stage in HelpStage}


def test_draft_review_banner() -> None:
    first_line = TEMPLATES.read_text(encoding="utf-8").splitlines()[0]
    assert first_line.startswith("# 草稿：待 G-0 两名注册心理师审核")
    assert "R1-4" in first_line


def test_part_layout_and_variant_counts() -> None:
    assert [n for n, _ in _parts(HelpStage.S_EXPLORE)] == ["reflect", "image", "invite"]
    assert [n for n, _ in _parts(HelpStage.S_CLARIFY)] == ["reflect", "need", "invite"]
    assert [n for n, _ in _parts(HelpStage.S_EMPOWER)] == ["bridge", "card_intro", "after_card"]
    for stage in COMPOSED_STAGES:
        for name, variants in _parts(stage):
            assert len(variants) >= 6, f"{stage}.{name}"
    assert len(STAGES[HelpStage.S_HAVEN]["variants"]) >= 8
    assert len(STAGES[HelpStage.S_CRISIS]["variants"]) >= 4
    assert len(STAGES[HelpStage.S_CLOSING]["variants"]) >= 6
    assert len(STAGES[HelpStage.S_READY]["greeting"]) >= 6
    assert len(STAGES[HelpStage.S_READY]["returning_after_crisis"]) >= 6
    assert len(STAGES[HelpStage.S_READY]["returning_after_check"]) >= 3


def test_no_duplicate_variants() -> None:
    texts = list(_templates())
    assert len(texts) == len(set(texts))


def test_only_allowed_slots() -> None:
    for text in _every_string(STAGES):
        assert set(SLOT.findall(text)) <= ALLOWED_SLOTS, text
        assert "{" not in SLOT.sub("", text) and "}" not in SLOT.sub("", text), text


def test_forbidden_wording_and_emoji_absent() -> None:
    for text in _every_string(STAGES):
        for word in FORBIDDEN:
            assert word not in text, f"{word!r} in {text!r}"
        assert not EMOJI.search(text), text
        assert "?" not in text, text


@pytest.mark.parametrize(
    ("stage", "part", "required"),
    [
        (HelpStage.S_EXPLORE, "reflect", {"mirror", "emotion"}),
        (HelpStage.S_EXPLORE, "image", {"metaphor"}),
        (HelpStage.S_CLARIFY, "reflect", {"mirror", "emotion"}),
        (HelpStage.S_CLARIFY, "need", {"need"}),
        (HelpStage.S_EMPOWER, "card_intro", {"card_title"}),
    ],
)
def test_parts_carry_their_slots(stage: str, part: str, required: set[str]) -> None:
    variants = dict(_parts(stage))[part]
    for text in variants:
        assert required <= set(SLOT.findall(text)), text


@pytest.mark.parametrize("stage", [HelpStage.S_EXPLORE, HelpStage.S_CLARIFY])
def test_invite_is_one_question(stage: str) -> None:
    for text in dict(_parts(stage))["invite"]:
        assert text.count("？") == 1, text


@pytest.mark.parametrize("stage", [HelpStage.S_EXPLORE, HelpStage.S_CLARIFY])
def test_no_advice_before_empower(stage: str) -> None:
    for text in _stage_strings(stage):
        for word in ADVICE_WORDS:
            assert word not in text, f"{word!r} in {text!r}"


def test_clarify_mirrors_feeling_and_need_only() -> None:
    for text in _stage_strings(HelpStage.S_CLARIFY):
        for word in SCHEMA_WORDS:
            assert word not in text, f"{word!r} in {text!r}"


def test_after_card_names_every_feedback_command() -> None:
    for text in STAGES[HelpStage.S_EMPOWER]["after_card"]:
        for command in Command:
            assert command.value in text, text


@pytest.mark.parametrize("stage", COMPOSED_STAGES)
def test_composed_replies_fit_the_normal_window(stage: str) -> None:
    lengths: list[int] = []
    for combo in _combinations(stage):
        reply = _compose(combo, TYPICAL)
        paragraphs = _paragraphs(reply)
        assert len(paragraphs) == len(combo)
        for paragraph in paragraphs:
            assert _all_chars(paragraph) <= PARAGRAPH_MAX, paragraph
        assert NORMAL[0] <= _cjk_chars(reply), reply
        assert _all_chars(reply) <= NORMAL[1], reply
        lengths.append(_all_chars(reply))
    assert lengths


@pytest.mark.parametrize("stage", COMPOSED_STAGES)
def test_longest_slot_values_stay_under_the_ceilings(stage: str) -> None:
    for combo in _combinations(stage):
        reply = _compose(combo, LONGEST)
        for paragraph in _paragraphs(reply):
            assert _all_chars(paragraph) <= PARAGRAPH_MAX, paragraph
        assert _all_chars(reply) <= NORMAL[1], reply


@pytest.mark.parametrize("pool", ["variants", "after_not_now"])
def test_closing_fits_the_normal_window(pool: str) -> None:
    for variant in STAGES[HelpStage.S_CLOSING][pool]:
        reply = _fill(variant, TYPICAL)
        assert len(_paragraphs(reply)) >= 2, reply
        for paragraph in _paragraphs(reply):
            assert _all_chars(paragraph) <= PARAGRAPH_MAX, paragraph
        assert NORMAL[0] <= _cjk_chars(reply), reply
        assert _all_chars(reply) <= NORMAL[1], reply


def test_haven_is_one_short_line_without_questions() -> None:
    for variant in STAGES[HelpStage.S_HAVEN]["variants"]:
        line = _fill(variant, TYPICAL)
        assert "\n" not in line
        assert HAVEN[0] <= _cjk_chars(line), line
        assert _all_chars(line) <= HAVEN[1], line
        assert "？" not in line, line


def test_crisis_is_short_calm_and_asks_about_safety() -> None:
    for variant in STAGES[HelpStage.S_CRISIS]["variants"]:
        assert "metaphor" not in SLOT.findall(variant), variant
        for word in NATURE_WORDS:
            assert word not in variant, f"{word!r} in {variant!r}"
        assert "\n" not in variant
        sentences = [s for s in re.split(r"[。？]", variant) if s.strip()]
        assert 2 <= len(sentences) <= 3, variant
        assert "安全" in variant and "？" in variant, variant


def test_ready_lines_are_single_short_paragraphs() -> None:
    ready = STAGES[HelpStage.S_READY]
    returning = ready["returning_after_crisis"] + ready["returning_after_check"]
    for variant in ready["greeting"] + returning + ready["after_close"]:
        line = _fill(variant, TYPICAL)
        assert "\n" not in line
        assert _all_chars(line) <= PARAGRAPH_MAX, line
    for variant in ready["returning_after_crisis"]:
        assert "安全" in variant, variant
    for variant in returning:
        assert set(SLOT.findall(variant)) <= {"user_name", "agent_name"}, variant


# Someone else may be reading the screen: a returning greeting never says what happened.
REVEALING_WORDS = ["危机", "自杀", "轻生", "生命", "死", "伤害", "热线", "风险", "L2", "L3", "求助"]


@pytest.mark.parametrize("pool", ["returning_after_crisis", "returning_after_check"])
def test_returning_greetings_reveal_nothing(pool: str) -> None:
    variants = STAGES[HelpStage.S_READY][pool]
    assert any(not SLOT.findall(v) for v in variants), "needs a slot-free variant"
    for variant in variants:
        for word in REVEALING_WORDS:
            assert word not in variant, (word, variant)


# -- low-battery light bridge (COLBO-07) ----------------------------------------------------

LIGHT_BRIDGE: list[str] = STAGES[HelpStage.S_EMPOWER]["light_bridge"]


def test_light_bridge_says_we_start_light() -> None:
    assert len(LIGHT_BRIDGE) >= 6 and len(set(LIGHT_BRIDGE)) == len(LIGHT_BRIDGE)
    bridges = dict(_parts(HelpStage.S_EMPOWER))["bridge"]
    for text in LIGHT_BRIDGE:
        assert "先从轻一点的开始" in text, text
        assert text not in bridges and "？" not in text, text


@pytest.mark.parametrize("values", [TYPICAL, LONGEST])
def test_light_bridge_replies_fit_the_normal_window(values: dict[str, str]) -> None:
    rest = [variants for name, variants in _parts(HelpStage.S_EMPOWER) if name != "bridge"]
    for combo in itertools.product(LIGHT_BRIDGE, *rest):
        reply = _compose(combo, values)
        for paragraph in _paragraphs(reply):
            assert _all_chars(paragraph) <= PARAGRAPH_MAX, paragraph
        assert _all_chars(reply) <= NORMAL[1], reply
        if values is TYPICAL:
            assert NORMAL[0] <= _cjk_chars(reply), reply


def test_light_bridge_passes_willow_unchanged_and_the_output_gate() -> None:
    tax = load_taxonomy()
    data = load_language_data(tax)
    gate = OutputGate(tax, data)
    assert list(data.templates.light_bridge) == LIGHT_BRIDGE
    for variant in LIGHT_BRIDGE:
        text = _fill(variant, TYPICAL)
        assert apply_willow(text, ContentKind.NORMAL, data.willow) == text, text
        assert gate.reasons(text, kind=ContentKind.NORMAL, stage=HelpStage.S_EMPOWER) == (), text


# -- natural-language follow-ups (roadmap R-7b) ---------------------------------------------

FOLLOWUPS: dict[str, list[str]] = DATA["followups"]
FOLLOWUP_SLOTS = {"user_name", "agent_name"}


def test_followup_groups_and_variant_counts() -> None:
    assert set(FOLLOWUPS) == {
        "clarify_feedback",
        "kit_empty",
        "closing_declined",
        "safety_check",
        "health_hint",
        "no_pending_feedback",
        "unhelpful_ack",
        "safety_confirmed",
        "forget_hint",
        "haven_return",
        "haven_exit_hint",
        "therapy_referred",
        "grief_request",
        "grief_request_prolonged",
    }
    for name, variants in FOLLOWUPS.items():
        assert 2 <= len(variants) <= 5, name
        assert len(set(variants)) == len(variants), name
        assert any(not SLOT.findall(v) for v in variants), name
    assert len(FOLLOWUPS["safety_check"]) >= 3


def test_followups_are_one_short_paragraph_with_name_slots_only() -> None:
    for variants in FOLLOWUPS.values():
        for variant in variants:
            assert set(SLOT.findall(variant)) <= FOLLOWUP_SLOTS, variant
            line = _fill(variant, TYPICAL)
            assert "\n" not in line
            assert _all_chars(line) <= PARAGRAPH_MAX, line
            for word in FORBIDDEN:
                assert word not in variant, f"{word!r} in {variant!r}"
            assert not EMOJI.search(variant) and "?" not in variant, variant


def test_clarification_asks_one_question_about_the_kit() -> None:
    for variant in FOLLOWUPS["clarify_feedback"]:
        assert variant.count("？") == 1 and "锦囊" in variant, variant


def test_kit_empty_and_closing_declined_ask_nothing() -> None:
    for name in ("kit_empty", "closing_declined"):
        for variant in FOLLOWUPS[name]:
            assert "？" not in variant, variant


def test_followups_pass_willow_unchanged_and_the_output_gate() -> None:
    tax = load_taxonomy()
    data = load_language_data(tax)
    gate = OutputGate(tax, data)
    templates = data.templates
    loaded = {
        "clarify_feedback": templates.clarify_feedback,
        "kit_empty": templates.kit_empty,
        "closing_declined": templates.closing_declined,
        "safety_check": templates.safety_check,
        "health_hint": templates.health_hint,
        "no_pending_feedback": templates.no_pending_feedback,
        "unhelpful_ack": templates.unhelpful_ack,
        "safety_confirmed": templates.safety_confirmed,
        "forget_hint": templates.forget_hint,
        "haven_return": templates.haven_return,
        "haven_exit_hint": templates.haven_exit_hint,
        "therapy_referred": templates.therapy_referred,
        "grief_request": templates.grief_request,
        "grief_request_prolonged": templates.grief_request_prolonged,
    }
    assert {name: list(v) for name, v in loaded.items()} == FOLLOWUPS
    stages = (HelpStage.S_EXPLORE, HelpStage.S_CLARIFY, HelpStage.S_EMPOWER, HelpStage.S_CLOSING)
    for variants in loaded.values():
        for variant in variants:
            text = _fill(variant, TYPICAL)
            assert apply_willow(text, ContentKind.NORMAL, data.willow) == text, text
            for stage in stages:
                assert gate.reasons(text, kind=ContentKind.NORMAL, stage=stage) == (), text


def test_safety_check_asks_one_direct_question_and_nothing_else() -> None:
    # Decision D3: one gentle, direct question about suicidal intent; never a method, a
    # card or advice, and never a number (the session adds the region's hotlines).
    for variant in FOLLOWUPS["safety_check"]:
        assert variant.count("？") == 1, variant
        assert "结束自己" in variant and "生命" in variant, variant
        for word in [*ADVICE_WORDS, "办法", "方式"]:
            assert word not in variant, f"{word!r} in {variant!r}"
        assert not any(ch.isdigit() for ch in variant), variant


# -- anti-dependence prompts (next-phase B7, PRD NG-4 / RSK-07 / §11.1) ---------------------

WELLBEING: dict[str, list[str]] = DATA["wellbeing"]
HAVEN_GROUPS = ("break_reminder_haven", "late_night_haven")
PEOPLE_WORDS = ("朋友", "家人", "同事", "心理咨询师", "信得过的人", "信任的")


def test_wellbeing_groups_and_variant_counts() -> None:
    assert set(WELLBEING) == {
        "break_reminder",
        "break_reminder_haven",
        "late_night",
        "late_night_haven",
        "real_support",
    }
    for name, variants in WELLBEING.items():
        assert 2 <= len(variants) <= 5, name
        assert len(set(variants)) == len(variants), name
        assert any(not SLOT.findall(v) for v in variants), name


def test_wellbeing_lines_carry_name_slots_only_and_no_banned_words() -> None:
    for variants in WELLBEING.values():
        for variant in variants:
            assert set(SLOT.findall(variant)) <= FOLLOWUP_SLOTS, variant
            assert "\n" not in variant
            for word in [*FORBIDDEN, *ADVICE_WORDS, *SCHEMA_WORDS]:
                assert word not in variant, f"{word!r} in {variant!r}"
            assert not EMOJI.search(variant) and "?" not in variant, variant
            assert not any(ch.isdigit() for ch in variant), variant


def test_wellbeing_paragraphs_fit_the_paragraph_limit() -> None:
    for name, variants in WELLBEING.items():
        if name in HAVEN_GROUPS:
            continue
        for variant in variants:
            assert _all_chars(_fill(variant, LONGEST)) <= PARAGRAPH_MAX, variant


def test_wellbeing_haven_lines_follow_the_haven_contract() -> None:
    for name in HAVEN_GROUPS:
        for variant in WELLBEING[name]:
            line = _fill(variant, TYPICAL)
            assert HAVEN[0] <= _cjk_chars(line), line
            assert _all_chars(line) <= HAVEN[1], line
            assert "？" not in line, line


def test_late_night_names_the_hour_and_someone_to_reach() -> None:
    for variant in WELLBEING["late_night"]:
        assert "夜" in variant, variant
        assert any(word in variant for word in PEOPLE_WORDS), variant
    for variant in WELLBEING["late_night_haven"]:
        assert "夜" in variant, variant


def test_real_support_asks_one_question_about_people_in_the_users_life() -> None:
    for variant in WELLBEING["real_support"]:
        assert variant.count("？") == 1, variant
        assert any(word in variant for word in [*PEOPLE_WORDS, "谁"]), variant


@pytest.mark.parametrize("stage", [HelpStage.S_EXPLORE, HelpStage.S_CLARIFY])
def test_real_support_as_the_invite_keeps_the_normal_window(stage: str) -> None:
    # The session swaps a real-support line in for the invite paragraph.
    pools = [variants for name, variants in _parts(stage) if name != "invite"]
    for combo in itertools.product(*pools, WELLBEING["real_support"]):
        reply = _compose(combo, TYPICAL)
        assert NORMAL[0] <= _cjk_chars(reply), reply
        assert _all_chars(reply) <= NORMAL[1], reply
        assert _all_chars(_compose(combo, LONGEST)) <= NORMAL[1]


def test_wellbeing_lines_pass_willow_unchanged_and_the_output_gate() -> None:
    tax = load_taxonomy()
    data = load_language_data(tax)
    gate = OutputGate(tax, data)
    templates = data.templates
    loaded = {
        "break_reminder": templates.break_reminder,
        "break_reminder_haven": templates.break_reminder_haven,
        "late_night": templates.late_night,
        "late_night_haven": templates.late_night_haven,
        "real_support": templates.real_support,
    }
    assert {name: list(v) for name, v in loaded.items()} == WELLBEING
    stages = (
        HelpStage.S_EXPLORE,
        HelpStage.S_CLARIFY,
        HelpStage.S_EMPOWER,
        HelpStage.S_CLOSING,
        HelpStage.S_HAVEN,
    )
    for variants in loaded.values():
        for variant in variants:
            text = _fill(variant, TYPICAL)
            assert apply_willow(text, ContentKind.NORMAL, data.willow) == text, text
            for stage in stages:
                assert gate.reasons(text, kind=ContentKind.NORMAL, stage=stage) == (), text


def test_health_hint_names_the_command_and_asks_nothing() -> None:
    # Decision D2 (step A1): a disclosure heard in the conversation is only offered for
    # saving; the line names the command, says it is optional and asks no question.
    for variant in FOLLOWUPS["health_hint"]:
        assert "olivia health" in variant and "加密" in variant, variant
        assert "？" not in variant, variant
        assert "没关系" in variant or "如果愿意" in variant, variant
