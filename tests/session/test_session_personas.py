"""Golden dialogues for every persona in rules mode (PRD ONB-03, SOP 2 and SOP 4; plan D-1).

Like ``tests/cli/test_cli_golden.py`` these assert stages, reply kinds, saved state and
that the wording comes from the profile's own template file and fits its word window,
not the exact text. Crisis turns are checked for identical safety content: the resource
lines (numbers, order, headings) do not depend on the persona.
"""

from __future__ import annotations

import random
import re
from datetime import UTC, datetime

import pytest

from olivia.core.language.data import LanguageData, Templates, load_language_data
from olivia.core.language.engine import count_all, count_cjk, paragraphs
from olivia.core.models import CrisisLevel, HelpStage, PersonaProfile, PersonaSpectrum, UserRegion
from olivia.core.perception.signals import Command
from olivia.core.session import ReplyKind, Session, TurnResult
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
LANG: LanguageData = load_language_data(TAX)
NOW = datetime(2026, 10, 22, 15, 30, tzinfo=UTC)
USER = "小林"
AGENT = "Olivia"
PERSONAS = list(PersonaSpectrum)
SILENT = PersonaSpectrum.SILENT_ANCHOR
SEEDS = (3, 11, 29)
NUMBER = re.compile(r"\d(?:[ \-]?\d)+")

HAVEN_SCRIPT = ("[5%] 好累，今天不想动脑，只想躺着", "嗯", "[60%] 好一点了")
METHOD_REQUEST = "最近拖延很严重，给我一个方法"
HESITATION = "我今天真的提不起劲做这个"
TO_CLARIFY = (
    "最近和男朋友总吵架，很难过",
    "他总说我太黏人",
    "我也不知道该怎么办，每次吵完都很失落",
)


def _open(persona: PersonaSpectrum, seed: int = 3) -> Session:
    profile = PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        user_name=USER,
        persona_spectrum=persona,
        region=UserRegion("CN", "Asia/Shanghai"),
    )
    return Session.open(TAX, profile, rng=random.Random(seed), now=lambda: NOW)


def _names(template: str) -> str:
    return template.replace("{user_name}", USER).replace("{agent_name}", AGENT)


def _tpl(persona: PersonaSpectrum) -> Templates:
    return LANG.personas[persona]


def _within(text: str, window: tuple[int, int]) -> bool:
    low, high = window
    return low <= count_cjk(text) and count_all(text) <= high


# -- SOP 2: the 5% haven ---------------------------------------------------------------------


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("persona", PERSONAS)
def test_sop2_haven_in_the_personas_voice(persona: PersonaSpectrum, seed: int) -> None:
    session = _open(persona, seed)
    haven, still, back = (session.turn(text) for text in HAVEN_SCRIPT)
    tpl = _tpl(persona)
    lines = {_names(v) for v in tpl.haven}
    for result in (haven, still):
        assert result.stage is HelpStage.S_HAVEN and result.reply_kind is ReplyKind.HAVEN
        assert result.inspect["assessed_level"] == "L0" and not result.in_crisis
        assert result.inspect["battery"] <= 0.20
        # No questions, no reframing, no action (CHANG-02), in this persona's words.
        assert "？" not in result.reply and "?" not in result.reply
        assert result.action_id is None and result.inspect["candidates"] == []
        assert result.reply in lines
        assert _within(result.reply, tpl.haven_window), result.reply
    assert haven.inspect["reason"] == "HAVEN_ENTER"
    assert back.stage is HelpStage.S_EXPLORE and back.inspect["reason"] == "HAVEN_EXIT"
    assert back.reply_kind is ReplyKind.NORMAL
    assert _within(back.reply, tpl.normal_window), back.reply
    if persona is SILENT:
        assert "？" not in back.reply and len(paragraphs(back.reply)) == 1


def test_silent_anchor_haven_window_is_the_narrower_one() -> None:
    assert _tpl(SILENT).haven_window == (15, 30)
    assert _tpl(PersonaSpectrum.GENTLE_HOLDING).haven_window == (15, 40)


# -- SOP 4: card, then the hesitation shelves it without penalty ------------------------------


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("persona", PERSONAS)
def test_sop4_card_then_hesitation_in_the_personas_voice(
    persona: PersonaSpectrum, seed: int
) -> None:
    session = _open(persona, seed)
    card = session.turn(METHOD_REQUEST)
    tpl = _tpl(persona)
    assert card.stage is HelpStage.S_EMPOWER and card.reply_kind is ReplyKind.CARD
    shown = card.action_id
    assert shown is not None
    for command in Command:
        assert command.value in card.reply
    blocks = paragraphs(card.reply)
    assert blocks[-1] in {_names(v) for v in tpl.after_card}
    bridges = {v for v in (*tpl.parts[HelpStage.S_EMPOWER][0].variants, *tpl.light_bridge)}
    first = blocks[0]
    assert any(re.fullmatch(_pattern(v), first) for v in bridges), first

    shelved = session.turn(HESITATION)
    assert shelved.inspect["feedback"] == "NOT_NOW"
    assert shelved.inspect["feedback_source"] == "phrase"
    assert shelved.stage is HelpStage.S_CLOSING and shelved.action_id is None
    assert shelved.reply in {_names(v) for v in tpl.closing}
    assert _within(shelved.reply, tpl.normal_window), shelved.reply
    snapshot = session.snapshot()
    assert snapshot["user_shelved_actions"] == [shown]
    assert snapshot["bandit"] == {"spectra": {}}
    if persona is SILENT:
        assert "？" not in shelved.reply


def _pattern(template: str) -> str:
    """A regex for a filled template: name slots literal, other slots any text."""
    parts = re.split(r"(\{[^{}]*\})", _names(template))
    return "".join(".+?" if p.startswith("{") else re.escape(p) for p in parts)


@pytest.mark.parametrize("persona", PERSONAS)
def test_unclear_reply_gets_the_personas_clarification(persona: PersonaSpectrum) -> None:
    session = _open(persona)
    session.turn(METHOD_REQUEST)
    asked = session.turn("唉")
    tpl = _tpl(persona)
    assert asked.reply in {_names(v) for v in tpl.clarify_feedback}
    assert asked.stage is HelpStage.S_EMPOWER
    yes = session.turn("好")
    assert yes.inspect["feedback"] == "NOT_NOW" and yes.inspect["feedback_source"] == "confirmed"


# -- crisis: identical safety content for every persona ---------------------------------------


def _crisis_parts(result: TurnResult) -> tuple[str, str]:
    lead, _, resources = result.reply.partition("\n\n")
    return lead, resources


@pytest.mark.parametrize("text", ["我不想活了", "我写了一封遗书"])
def test_crisis_turn_has_the_same_safety_content_for_every_persona(text: str) -> None:
    results = {p: _open(p).turn(text) for p in PERSONAS}
    gentle = results[PersonaSpectrum.GENTLE_HOLDING]
    _, gentle_resources = _crisis_parts(gentle)
    assert gentle_resources and NUMBER.search(gentle_resources)
    for persona, result in results.items():
        assert result.stage is HelpStage.S_CRISIS and result.reply_kind is ReplyKind.CRISIS
        assert result.crisis_level == gentle.crisis_level >= CrisisLevel.L2
        assert result.resource_card == gentle.resource_card
        lead, resources = _crisis_parts(result)
        # Same numbers, same order, same headings and hours: only the lead line differs.
        assert resources == gentle_resources, persona
        assert NUMBER.findall(result.reply) == NUMBER.findall(gentle.reply), persona
        assert lead in {_names(v) for v in _tpl(persona).crisis}, persona
        assert result.inspect["gate"] == []


def test_l3_card_keeps_emergency_numbers_first_for_every_persona() -> None:
    for persona in PERSONAS:
        result = _open(persona).turn("我写了一封遗书")
        assert result.crisis_level is CrisisLevel.L3
        card = result.resource_card
        assert card is not None and card.emergency
        found = NUMBER.findall(result.reply)
        assert found[: len(card.emergency)] == [e.number for e in card.emergency], persona


def test_d3_question_and_its_lines_are_persona_free() -> None:
    gentle_questions = {_names(v) for v in _tpl(PersonaSpectrum.GENTLE_HOLDING).safety_check}
    resources: set[str] = set()
    for persona in PERSONAS:
        result = _open(persona).turn("有没有最快的办法离开")
        assert result.reply_kind is ReplyKind.SAFETY_CHECK and not result.in_crisis
        question, _, lines = result.reply.partition("\n\n")
        assert question in gentle_questions, persona
        assert "12356" in lines
        resources.add(lines)
    assert len(resources) == 1


# -- SILENT_ANCHOR: listens, never auto-advances, offers no unasked perspective ----------------


def test_silent_anchor_only_listens() -> None:
    gentle = _open(PersonaSpectrum.GENTLE_HOLDING)
    gentle_results = [gentle.turn(text) for text in TO_CLARIFY]
    # The same script gives GENTLE_HOLDING a Grade B perspective in S_clarify ...
    assert gentle_results[-1].stage is HelpStage.S_CLARIFY
    assert gentle_results[-1].reply_kind is ReplyKind.INFO

    silent = _open(SILENT)
    more = ("嗯", "还是很难过", "说不清楚", "就是很累", "他也不理我", "嗯")
    results = [silent.turn(text) for text in (*TO_CLARIFY, *more)]
    # ... but SILENT_ANCHOR stays with short presence lines and never moves on by itself.
    assert results[2].stage is HelpStage.S_CLARIFY
    assert all(r.stage in {HelpStage.S_EXPLORE, HelpStage.S_CLARIFY} for r in results)
    for result in results:
        assert result.reply_kind is ReplyKind.NORMAL and result.inspect["info"] is None
        assert result.action_id is None
        assert "？" not in result.reply, result.reply
        assert _within(result.reply, (10, 30)), result.reply


def test_silent_anchor_still_gets_a_card_on_request() -> None:
    result = _open(SILENT).turn(METHOD_REQUEST)
    assert result.stage is HelpStage.S_EMPOWER and result.reply_kind is ReplyKind.CARD


@pytest.mark.parametrize("persona", PERSONAS)
def test_high_arousal_stabilization_card_uses_the_personas_framing(
    persona: PersonaSpectrum,
) -> None:
    session = _open(persona)
    session.turn("最近工作压力很大，有点焦虑，晚上总睡不着")
    result = session.turn("被领导催进度，心慌得要命")
    assert result.stage is HelpStage.S_EXPLORE and result.reply_kind is ReplyKind.CARD
    blocks = paragraphs(result.reply)
    tpl = _tpl(persona)
    assert blocks[-1] in {_names(v) for v in tpl.after_card}
    reflect = tpl.parts[HelpStage.S_EXPLORE][0].variants
    assert any(re.fullmatch(_pattern(v), blocks[0]) for v in reflect), blocks[0]
    if persona is SILENT:
        assert count_all(blocks[0]) <= 30
