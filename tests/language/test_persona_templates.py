"""The three further persona template files (PRD 特性六 / ONB-03, WILLOW-03; plan D-1).

ZEN_PHILOSOPHER and RATIONAL_PEER have GENTLE_HOLDING's layout and windows; SILENT_ANCHOR
has one short paragraph per composed stage and the [10, 30] window. Every reply text must
pass WILLOW unchanged and the output gate; crisis wording stays as plain and complete as
GENTLE_HOLDING's, and the D3 question is the same wording for every persona.

Lengths use the readings of ``test_gentle_holding_templates.py``: upper bounds and the
paragraph limit count every non-whitespace character, lower bounds Chinese characters only.
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

from olivia.core.language.data import (
    PERSONA_TEMPLATE_FILES,
    ContentKind,
    LanguageData,
    Templates,
)
from olivia.core.language.filters import apply_willow
from olivia.core.language.gate import OutputGate
from olivia.core.models import HelpStage, PersonaSpectrum
from olivia.core.perception.signals import Command
from olivia.core.taxonomy import Taxonomy

DATA = Path(__file__).resolve().parents[2] / "olivia/data"
SLOT = re.compile(r"\{([^{}]*)\}")
CJK = re.compile(r"[一-鿿]")
WHITESPACE = re.compile(r"\s")
EMOJI = re.compile("[☀-➿\U0001f000-\U0001faff️]")
BANNER = "# 草稿：待 G-0 两名注册心理师审核（docs/superpowers/plans/2026-10-23-next-phase.md D-1）"

TYPICAL = {
    "user_name": "小雨",
    "agent_name": "阿柳",
    "emotion": "无力感",
    "mirror": "你在家里做了很多却没有人看见",
    "metaphor": "柳枝在风里低伏却没有折断",
    "need": "被看见",
    "card_title": "五感着陆练习",
}
LONGEST = {
    **TYPICAL,
    "emotion": "被辜负感",
    "mirror": "你在家里做了很多很多事情却始终没有人看见",
    "metaphor": "柳枝在大风里低低伏下却始终没有折断",
    "need": "被真正看见",
}
FORBIDDEN = ["你应该", "应该", "必须", "一定要", "症状", "病", "诊断", "患者", "治疗"]
FORBIDDEN += ["首先", "其次", "再次", "总而言之", "！", "!"]
ADVICE_WORDS = ["建议", "试试", "试着", "方法", "练习"]
SCHEMA_WORDS = ["信念", "图式", "模式", "核心"]
NATURE_WORDS = ["柳", "溪", "草木", "风雨", "花", "树", "山", "云", "月", "湖", "雨"]

NEW = [PersonaSpectrum.ZEN_PHILOSOPHER, PersonaSpectrum.RATIONAL_PEER]
NEW_ALL = [*NEW, PersonaSpectrum.SILENT_ANCHOR]
FULL = [PersonaSpectrum.GENTLE_HOLDING, *NEW]
WINDOWS: dict[PersonaSpectrum, dict[str, Any]] = {
    PersonaSpectrum.ZEN_PHILOSOPHER: {"normal": [140, 260], "paragraph_max": 80, "haven": [15, 40]},
    PersonaSpectrum.RATIONAL_PEER: {"normal": [140, 260], "paragraph_max": 80, "haven": [15, 40]},
    PersonaSpectrum.SILENT_ANCHOR: {
        "normal": [10, 30],
        "paragraph_max": 50,
        "haven": [15, 30],
        "empower": [10, 70],
    },
}
SILENT_WINDOW = (10, 30)
COMPOSED = [HelpStage.S_EXPLORE, HelpStage.S_CLARIFY, HelpStage.S_EMPOWER]
WELLBEING_GROUPS = (
    "break_reminder",
    "break_reminder_haven",
    "late_night",
    "late_night_haven",
    "real_support",
)
HAVEN_GROUPS = ("break_reminder_haven", "late_night_haven")
PEOPLE_WORDS = ("朋友", "家人", "同事", "心理咨询师", "信得过的人", "信任的")
# Someone else may be reading the screen: a returning greeting never says what happened
# (the list of tests/language/test_gentle_holding_templates.py, step A3).
REVEALING_WORDS = ["危机", "自杀", "轻生", "生命", "死", "伤害", "热线", "风险", "L2", "L3", "求助"]
SAMPLE_LIMIT = 20_000
SAMPLE_SIZE = 2_000


def _raw(persona: PersonaSpectrum) -> dict[str, Any]:
    text = (DATA / PERSONA_TEMPLATE_FILES[persona]).read_text(encoding="utf-8")
    data: dict[str, Any] = yaml.safe_load(text)
    return data


def _fill(template: str, values: dict[str, str]) -> str:
    return SLOT.sub(lambda m: values[m.group(1)], template)


def _all(text: str) -> int:
    return len(WHITESPACE.sub("", text))


def _cjk(text: str) -> int:
    return len(CJK.findall(text))


def _paragraphs(text: str) -> list[str]:
    return [p for p in text.split("\n\n") if p.strip()]


def _pools(tpl: Templates, stage: HelpStage) -> list[tuple[str, ...]]:
    pools = [part.variants for part in tpl.parts[stage]]
    if stage is HelpStage.S_EMPOWER:
        pools.append(tpl.after_card)
    return pools


def _combos(pools: list[tuple[str, ...]]) -> Iterator[tuple[str, ...]]:
    total = 1
    for pool in pools:
        total *= len(pool)
    if total <= SAMPLE_LIMIT:
        yield from itertools.product(*pools)
        return
    rng = random.Random(20261023)
    for _ in range(SAMPLE_SIZE):
        yield tuple(rng.choice(pool) for pool in pools)


def _wellbeing(tpl: Templates) -> dict[str, tuple[str, ...]]:
    return {name: getattr(tpl, name) for name in WELLBEING_GROUPS}


def _every_text(tpl: Templates) -> Iterator[tuple[str, str]]:
    """(where, template) for every reply text the persona can say."""
    for stage, parts in tpl.parts.items():
        for part in parts:
            for text in part.variants:
                yield f"{stage}.{part.name}", text
    named = {
        "after_card": tpl.after_card,
        "light_bridge": tpl.light_bridge,
        "haven": tpl.haven,
        "crisis": tpl.crisis,
        "closing": tpl.closing,
        "greeting": tpl.greeting,
        "returning_after_crisis": tpl.returning_after_crisis,
        "returning_after_check": tpl.returning_after_check,
        "clarify_feedback": tpl.clarify_feedback,
        "kit_empty": tpl.kit_empty,
        "closing_declined": tpl.closing_declined,
        "safety_check": tpl.safety_check,
        **_wellbeing(tpl),
    }
    for where, texts in named.items():
        for text in texts:
            yield where, text


# -- files and loading -----------------------------------------------------------------------


@pytest.mark.parametrize("persona", NEW_ALL)
def test_file_header_persona_and_windows(persona: PersonaSpectrum) -> None:
    path = DATA / PERSONA_TEMPLATE_FILES[persona]
    assert path.read_text(encoding="utf-8").splitlines()[0] == BANNER
    raw = _raw(persona)
    assert raw["persona"] == persona.value
    assert raw["window"] == WINDOWS[persona]
    assert set(raw["stages"]) == {stage.value for stage in HelpStage}


def test_every_persona_is_loaded_and_chosen(lang: LanguageData) -> None:
    assert set(lang.personas) == set(PersonaSpectrum)
    assert lang.templates.persona is PersonaSpectrum.GENTLE_HOLDING
    for persona in PersonaSpectrum:
        chosen = lang.for_persona(persona)
        assert chosen.templates is lang.personas[persona]
        assert chosen.templates.persona is persona
        assert chosen.cards is lang.cards and chosen.render is lang.render
    assert lang.for_persona(PersonaSpectrum.GENTLE_HOLDING) is lang


def test_silent_anchor_windows_are_loaded(lang: LanguageData) -> None:
    silent = lang.personas[PersonaSpectrum.SILENT_ANCHOR]
    assert silent.normal_window == SILENT_WINDOW
    assert silent.haven_window == (15, 30)
    assert silent.empower_window == (10, 70)
    gentle = lang.personas[PersonaSpectrum.GENTLE_HOLDING]
    assert gentle.empower_window == gentle.normal_window == (140, 260)


@pytest.mark.parametrize("persona", FULL)
def test_full_layout_and_variant_counts(lang: LanguageData, persona: PersonaSpectrum) -> None:
    tpl = lang.personas[persona]
    names = {stage: [p.name for p in tpl.parts[stage]] for stage in COMPOSED}
    assert names == {
        HelpStage.S_EXPLORE: ["reflect", "image", "invite"],
        HelpStage.S_CLARIFY: ["reflect", "need", "invite"],
        HelpStage.S_EMPOWER: ["bridge", "card_intro"],
    }
    for stage in COMPOSED:
        for pool in _pools(tpl, stage):
            assert len(pool) >= 6, stage
    assert len(tpl.light_bridge) >= 6 and len(tpl.haven) >= 8 and len(tpl.crisis) >= 4
    assert len(tpl.closing) >= 6 and len(tpl.greeting) >= 6
    assert len(tpl.returning_after_crisis) >= 6


def test_silent_anchor_layout(lang: LanguageData) -> None:
    tpl = lang.personas[PersonaSpectrum.SILENT_ANCHOR]
    names = {stage: [p.name for p in tpl.parts[stage]] for stage in COMPOSED}
    assert names == {
        HelpStage.S_EXPLORE: ["reflect"],
        HelpStage.S_CLARIFY: ["reflect"],
        HelpStage.S_EMPOWER: ["bridge", "card_intro"],
    }
    for stage in COMPOSED:
        for pool in _pools(tpl, stage):
            assert len(pool) >= 6, stage
    assert len(tpl.light_bridge) >= 6 and len(tpl.haven) >= 8 and len(tpl.crisis) >= 4
    assert len(tpl.closing) >= 6 and len(tpl.greeting) >= 6
    assert len(tpl.returning_after_crisis) >= 6


# -- wording rules shared by every persona ---------------------------------------------------


@pytest.mark.parametrize("persona", NEW_ALL)
def test_no_duplicates_forbidden_words_or_emoji(
    lang: LanguageData, persona: PersonaSpectrum
) -> None:
    texts = [text for _, text in _every_text(lang.personas[persona])]
    assert len(texts) == len(set(texts))
    for text in texts:
        for word in FORBIDDEN:
            assert word not in text, f"{word!r} in {text!r}"
        assert not EMOJI.search(text) and "?" not in text, text


@pytest.mark.parametrize("persona", NEW_ALL)
def test_every_text_passes_willow_unchanged_and_the_gate(
    tax: Taxonomy, lang: LanguageData, persona: PersonaSpectrum
) -> None:
    data = lang.for_persona(persona)
    gate = OutputGate(tax, data)
    for where, template in _every_text(data.templates):
        for values in (TYPICAL, LONGEST):
            text = _fill(template, values)
            kind = ContentKind.CRISIS if where == "crisis" else ContentKind.NORMAL
            assert apply_willow(text, kind, data.willow) == text, text
            stage = HelpStage.S_CRISIS if where == "crisis" else HelpStage.S_EMPOWER
            assert gate.reasons(text, kind=kind, stage=stage) == (), text
            if where.startswith(("S_explore", "S_clarify")):
                assert gate.reasons(text, kind=kind, stage=HelpStage.S_EXPLORE) == (), text


@pytest.mark.parametrize("persona", NEW_ALL)
def test_no_advice_before_empower_and_no_schema_talk(
    lang: LanguageData, persona: PersonaSpectrum
) -> None:
    tpl = lang.personas[persona]
    for stage in (HelpStage.S_EXPLORE, HelpStage.S_CLARIFY):
        for part in tpl.parts[stage]:
            for text in part.variants:
                for word in ADVICE_WORDS:
                    assert word not in text, f"{word!r} in {text!r}"
                if stage is HelpStage.S_CLARIFY:
                    for word in SCHEMA_WORDS:
                        assert word not in text, f"{word!r} in {text!r}"


@pytest.mark.parametrize("persona", NEW)
def test_invites_ask_exactly_one_question(lang: LanguageData, persona: PersonaSpectrum) -> None:
    tpl = lang.personas[persona]
    for stage in (HelpStage.S_EXPLORE, HelpStage.S_CLARIFY):
        invite = dict((p.name, p.variants) for p in tpl.parts[stage])["invite"]
        for text in invite:
            assert text.count("？") == 1, text


@pytest.mark.parametrize("persona", NEW_ALL)
def test_after_card_names_every_feedback_command(
    lang: LanguageData, persona: PersonaSpectrum
) -> None:
    for text in lang.personas[persona].after_card:
        for command in Command:
            assert command.value in text, text


@pytest.mark.parametrize("persona", NEW_ALL)
def test_light_bridge_says_we_start_light(lang: LanguageData, persona: PersonaSpectrum) -> None:
    tpl = lang.personas[persona]
    bridges = tpl.parts[HelpStage.S_EMPOWER][0].variants
    for text in tpl.light_bridge:
        assert "先从轻一点的开始" in text and "？" not in text, text
        assert text not in bridges, text


# -- safety wording: as plain and complete as GENTLE_HOLDING's -------------------------------


@pytest.mark.parametrize("persona", NEW_ALL)
def test_crisis_lines_are_plain_and_ask_about_safety(
    lang: LanguageData, persona: PersonaSpectrum
) -> None:
    for variant in lang.personas[persona].crisis:
        assert "metaphor" not in SLOT.findall(variant), variant
        for word in NATURE_WORDS:
            assert word not in variant, f"{word!r} in {variant!r}"
        assert "\n" not in variant
        sentences = [s for s in re.split(r"[。？]", variant) if s.strip()]
        assert 2 <= len(sentences) <= 3, variant
        assert "安全" in variant and "？" in variant, variant
        # Points to the numbers the engine appends below it.
        assert "下面" in variant and "电话" in variant, variant
        assert not any(ch.isdigit() for ch in variant), variant


@pytest.mark.parametrize("persona", PersonaSpectrum)
def test_safety_check_is_the_same_question_for_every_persona(
    lang: LanguageData, persona: PersonaSpectrum
) -> None:
    gentle = lang.personas[PersonaSpectrum.GENTLE_HOLDING]
    assert lang.personas[persona].safety_check == gentle.safety_check


@pytest.mark.parametrize("persona", NEW_ALL)
def test_returning_after_crisis_asks_about_safety(
    lang: LanguageData, persona: PersonaSpectrum
) -> None:
    for variant in lang.personas[persona].returning_after_crisis:
        assert "安全" in variant and "？" in variant, variant
        assert "metaphor" not in SLOT.findall(variant), variant


# -- word windows (WILLOW-03) ----------------------------------------------------------------


@pytest.mark.parametrize("persona", NEW)
@pytest.mark.parametrize("stage", COMPOSED)
def test_full_personas_fit_the_normal_window(
    lang: LanguageData, persona: PersonaSpectrum, stage: HelpStage
) -> None:
    tpl = lang.personas[persona]
    low, high = tpl.normal_window
    for combo in _combos(_pools(tpl, stage)):
        typical = "\n\n".join(_fill(p, TYPICAL) for p in combo)
        assert low <= _cjk(typical), typical
        longest = "\n\n".join(_fill(p, LONGEST) for p in combo)
        assert _all(longest) <= high, longest
        for para in _paragraphs(longest):
            assert _all(para) <= tpl.paragraph_max, para


@pytest.mark.parametrize("persona", NEW)
@pytest.mark.parametrize("values", [TYPICAL, LONGEST])
def test_full_personas_light_bridge_fits(
    lang: LanguageData, persona: PersonaSpectrum, values: dict[str, str]
) -> None:
    tpl = lang.personas[persona]
    rest = _pools(tpl, HelpStage.S_EMPOWER)[1:]
    low, high = tpl.normal_window
    for combo in itertools.product(tpl.light_bridge, *rest):
        reply = "\n\n".join(_fill(p, values) for p in combo)
        assert _all(reply) <= high, reply
        for para in _paragraphs(reply):
            assert _all(para) <= tpl.paragraph_max, para
        if values is TYPICAL:
            assert low <= _cjk(reply), reply


@pytest.mark.parametrize("persona", NEW)
def test_full_personas_closing_and_haven(lang: LanguageData, persona: PersonaSpectrum) -> None:
    tpl = lang.personas[persona]
    low, high = tpl.normal_window
    for variant in tpl.closing:
        reply = _fill(variant, TYPICAL)
        assert len(_paragraphs(reply)) >= 2, reply
        assert low <= _cjk(reply) and _all(_fill(variant, LONGEST)) <= high, reply
        for para in _paragraphs(reply):
            assert _all(para) <= tpl.paragraph_max, para
    h_low, h_high = tpl.haven_window
    assert any(not SLOT.findall(v) for v in tpl.haven)
    for variant in tpl.haven:
        line = _fill(variant, TYPICAL)
        assert "\n" not in line and "？" not in line, line
        assert h_low <= _cjk(line) and _all(line) <= h_high, line


@pytest.mark.parametrize("persona", NEW_ALL)
def test_ready_lines_are_single_short_paragraphs(
    lang: LanguageData, persona: PersonaSpectrum
) -> None:
    tpl = lang.personas[persona]
    limit = SILENT_WINDOW[1] if persona is PersonaSpectrum.SILENT_ANCHOR else 80
    for variant in tpl.greeting + tpl.returning_after_crisis + tpl.returning_after_check:
        line = _fill(variant, TYPICAL)
        assert "\n" not in line and _all(line) <= limit, line


@pytest.mark.parametrize("persona", NEW_ALL)
def test_followups_are_short_name_slot_lines(lang: LanguageData, persona: PersonaSpectrum) -> None:
    tpl = lang.personas[persona]
    groups = {
        "clarify_feedback": tpl.clarify_feedback,
        "kit_empty": tpl.kit_empty,
        "closing_declined": tpl.closing_declined,
    }
    for name, variants in groups.items():
        assert 2 <= len(variants) <= 5, name
        for variant in variants:
            assert set(SLOT.findall(variant)) <= {"user_name", "agent_name"}, variant
            line = _fill(variant, TYPICAL)
            assert "\n" not in line and _all(line) <= 80, line
        if name != "clarify_feedback":
            assert all("？" not in v for v in variants), name
    for variant in tpl.clarify_feedback:
        assert "锦囊" in variant, variant
        expected = 0 if persona is PersonaSpectrum.SILENT_ANCHOR else 1
        assert variant.count("？") == expected, variant


# -- SILENT_ANCHOR: [10, 30] presence, no questions unless for safety ------------------------


SILENT = PersonaSpectrum.SILENT_ANCHOR


@pytest.mark.parametrize(
    "stage", [HelpStage.S_EXPLORE, HelpStage.S_CLARIFY, HelpStage.S_CLOSING, HelpStage.S_HAVEN]
)
def test_silent_anchor_presence_lines_fit_ten_to_thirty(
    lang: LanguageData, stage: HelpStage
) -> None:
    tpl = lang.personas[SILENT]
    if stage is HelpStage.S_CLOSING:
        variants = tpl.closing
    elif stage is HelpStage.S_HAVEN:
        variants = tpl.haven
    else:
        variants = tpl.parts[stage][0].variants
    low = 15 if stage is HelpStage.S_HAVEN else SILENT_WINDOW[0]
    for variant in variants:
        typical, longest = _fill(variant, TYPICAL), _fill(variant, LONGEST)
        assert "\n" not in typical, typical
        assert low <= _cjk(typical), typical
        assert _all(longest) <= SILENT_WINDOW[1], longest


def test_silent_anchor_asks_only_for_safety(lang: LanguageData) -> None:
    tpl = lang.personas[SILENT]
    safety = {*tpl.crisis, *tpl.returning_after_crisis, *tpl.safety_check}
    for where, text in _every_text(tpl):
        if text not in safety:
            assert "？" not in text, f"{where}: {text}"
        assert "metaphor" not in SLOT.findall(text), text


@pytest.mark.parametrize("bridges", ["bridge", "light_bridge"])
def test_silent_anchor_empower_framing_fits_its_window(lang: LanguageData, bridges: str) -> None:
    tpl = lang.personas[SILENT]
    first = tpl.parts[HelpStage.S_EMPOWER][0].variants if bridges == "bridge" else tpl.light_bridge
    low, high = tpl.empower_window
    for combo in itertools.product(
        first, tpl.parts[HelpStage.S_EMPOWER][1].variants, tpl.after_card
    ):
        typical = "\n\n".join(_fill(p, TYPICAL) for p in combo)
        assert low <= _cjk(typical), typical
        longest = "\n\n".join(_fill(p, LONGEST) for p in combo)
        assert _all(longest) <= high, longest
        for para in _paragraphs(longest):
            assert _all(para) <= tpl.paragraph_max, para


# -- A3 returning greetings and B7 anti-dependence prompts, every persona -------------------


@pytest.mark.parametrize("persona", PersonaSpectrum)
@pytest.mark.parametrize("pool", ["returning_after_crisis", "returning_after_check"])
def test_returning_greetings_reveal_nothing(
    lang: LanguageData, persona: PersonaSpectrum, pool: str
) -> None:
    variants: tuple[str, ...] = getattr(lang.personas[persona], pool)
    assert len(variants) >= 3
    assert any(not SLOT.findall(v) for v in variants), "needs a slot-free variant"
    for variant in variants:
        assert set(SLOT.findall(variant)) <= {"user_name", "agent_name"}, variant
        for word in REVEALING_WORDS:
            assert word not in variant, (word, variant)


@pytest.mark.parametrize("persona", PersonaSpectrum)
def test_wellbeing_groups_follow_the_b7_contract(
    lang: LanguageData, persona: PersonaSpectrum
) -> None:
    tpl = lang.personas[persona]
    for name, variants in _wellbeing(tpl).items():
        assert 2 <= len(variants) <= 5, name
        assert len(set(variants)) == len(variants), name
        assert any(not SLOT.findall(v) for v in variants), name
        for variant in variants:
            assert set(SLOT.findall(variant)) <= {"user_name", "agent_name"}, variant
            assert "\n" not in variant, variant
            for word in [*FORBIDDEN, *ADVICE_WORDS, *SCHEMA_WORDS]:
                assert word not in variant, f"{word!r} in {variant!r}"
            assert not EMOJI.search(variant) and "?" not in variant, variant
            assert not any(ch.isdigit() for ch in variant), variant
    for variant in tpl.late_night:
        assert "夜" in variant and any(w in variant for w in PEOPLE_WORDS), variant
    for variant in tpl.late_night_haven:
        assert "夜" in variant, variant


def _within_haven(tpl: Templates, line: str) -> bool:
    low, high = tpl.haven_window
    return low <= _cjk(line) and _all(line) <= high


@pytest.mark.parametrize("persona", PersonaSpectrum)
def test_wellbeing_lines_fit_the_persona_windows(
    lang: LanguageData, persona: PersonaSpectrum
) -> None:
    tpl = lang.personas[persona]
    # A break or late-night paragraph is added after the reply: it keeps the paragraph
    # limit, and SILENT_ANCHOR's stays inside its own [10, 30] window.
    limit = SILENT_WINDOW[1] if persona is SILENT else tpl.paragraph_max
    for name in ("break_reminder", "late_night", "real_support"):
        for variant in getattr(tpl, name):
            line = _fill(variant, LONGEST)
            assert _all(line) <= limit, line
            if persona is SILENT:
                assert SILENT_WINDOW[0] <= _cjk(_fill(variant, TYPICAL)), line
    for name in HAVEN_GROUPS:
        for variant in getattr(tpl, name):
            line = _fill(variant, TYPICAL)
            assert _within_haven(tpl, line) and "？" not in line, line


@pytest.mark.parametrize("persona", PersonaSpectrum)
def test_real_support_wording(lang: LanguageData, persona: PersonaSpectrum) -> None:
    for variant in lang.personas[persona].real_support:
        assert any(word in variant for word in [*PEOPLE_WORDS, "谁"]), variant
        # SILENT_ANCHOR asks nothing; the others ask exactly one question.
        assert variant.count("？") == (0 if persona is SILENT else 1), variant


@pytest.mark.parametrize("persona", NEW)
@pytest.mark.parametrize("stage", [HelpStage.S_EXPLORE, HelpStage.S_CLARIFY])
def test_real_support_as_the_invite_keeps_the_normal_window(
    lang: LanguageData, persona: PersonaSpectrum, stage: HelpStage
) -> None:
    tpl = lang.personas[persona]
    low, high = tpl.normal_window
    pools = [p.variants for p in tpl.parts[stage] if p.name != "invite"]
    for combo in itertools.product(*pools, tpl.real_support):
        typical = "\n\n".join(_fill(p, TYPICAL) for p in combo)
        assert low <= _cjk(typical), typical
        assert _all("\n\n".join(_fill(p, LONGEST) for p in combo)) <= high, combo
