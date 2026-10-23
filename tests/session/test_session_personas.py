"""Golden dialogues for every persona in rules mode (PRD ONB-03, SOP 2 and SOP 4; plan D-1).

Like ``tests/cli/test_cli_golden.py`` these assert stages, reply kinds, saved state and
that the wording comes from the profile's own template file and fits its word window,
not the exact text. Crisis turns are checked for identical safety content: the resource
lines (numbers, order, headings) do not depend on the persona.
"""

from __future__ import annotations

import random
import re
from datetime import UTC, datetime, timedelta

import pytest

from olivia.core.language.data import LanguageData, Templates, load_language_data
from olivia.core.language.engine import count_all, count_cjk, paragraphs
from olivia.core.models import CrisisLevel, HelpStage, PersonaProfile, PersonaSpectrum, UserRegion
from olivia.core.perception.introspector import load_mirror_lines
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
# tests/session/test_session_introspection.py: reaches S_clarify with a schema seen.
SCHEMA_SCRIPT = ("最近工作压力有点大", "我很在意别人怎么看我", "一直在讨好别人，挺累的")
SCHEMA_MORE = "我的意见不重要，总是顺着别人"


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


def test_silent_anchor_never_asks_the_schema_mirror() -> None:
    # Decision D4's mirror is a question and replaces a three-paragraph reply's invite; the
    # FSM already keeps SILENT_ANCHOR out of C_2 (CLARIFY_CORE_BELIEF).
    lines = frozenset(line for group in load_mirror_lines(TAX).values() for line in group)
    script = (*SCHEMA_SCRIPT, SCHEMA_MORE, SCHEMA_MORE, SCHEMA_MORE)
    gentle = _open(PersonaSpectrum.GENTLE_HOLDING, 7)
    gentle._mirror.enabled = True  # model mode's mirror over rule perception
    asked = [gentle.turn(text).inspect["schema_mirror"] for text in script]
    assert "asked" in asked  # the script does reach the mirror for other personas
    silent = _open(SILENT, 7)
    silent._mirror.enabled = True
    for text in script:
        result = silent.turn(text)
        assert result.inspect["schema_mirror"] != "asked"
        assert not any(line in result.reply for line in lines), result.reply
        assert "？" not in result.reply and result.stage is not HelpStage.S_EMPOWER


# -- B7 anti-dependence prompts and the A3 greeting, every persona ------------------------------


class Clock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now


DAY = datetime(2026, 10, 22, 14, 0, tzinfo=UTC)  # 22:00 in Shanghai
MIDNIGHT = datetime(2026, 10, 22, 16, 0, tzinfo=UTC)  # 00:00 in Shanghai
CALM = (
    "今天上班好累",
    "最近和室友有点小矛盾",
    "工作上的事情让我有点烦",
    "回家以后也提不起劲",
    "周末也不太想出门",
    "感觉自己一直在硬撑",
    "说不上来哪里不对劲",
    "就是心里有点堵",
)


def _clocked(persona: PersonaSpectrum, clock: Clock) -> Session:
    profile = PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=DAY,
        updated_at=DAY,
        user_name=USER,
        persona_spectrum=persona,
        region=UserRegion("CN", "Asia/Shanghai"),
    )
    return Session.open(TAX, profile, rng=random.Random(7), now=clock)


def _head_and_tail(reply: str) -> tuple[str, str]:
    head, _, tail = reply.rpartition("\n\n")
    return head, tail


def _check_ordinary(persona: PersonaSpectrum, text: str) -> None:
    assert _within(text, _tpl(persona).normal_window), text
    if persona is SILENT:
        assert "？" not in text and len(paragraphs(text)) == 1, text


@pytest.mark.parametrize("persona", PERSONAS)
def test_break_reminder_after_45_minutes_keeps_the_window(persona: PersonaSpectrum) -> None:
    clock = Clock(DAY)
    session = _clocked(persona, clock)
    first = session.turn(CALM[0])
    assert first.inspect["reminder"] == "none"
    clock.now = DAY + timedelta(minutes=46)
    later = session.turn(CALM[1])
    assert later.inspect["reminder"] == "break" and later.reply_kind is ReplyKind.NORMAL
    head, tail = _head_and_tail(later.reply)
    assert tail in {_names(v) for v in _tpl(persona).break_reminder}
    _check_ordinary(persona, head)
    if persona is SILENT:
        assert count_all(tail) <= 30 and "？" not in tail


@pytest.mark.parametrize("persona", PERSONAS)
def test_late_night_line_keeps_the_window(persona: PersonaSpectrum) -> None:
    session = _clocked(persona, Clock(MIDNIGHT))
    result = session.turn(CALM[0])
    assert result.inspect["reminder"] == "late_night"
    head, tail = _head_and_tail(result.reply)
    assert tail in {_names(v) for v in _tpl(persona).late_night}
    _check_ordinary(persona, head)
    if persona is SILENT:
        assert count_all(tail) <= 30 and "？" not in tail


@pytest.mark.parametrize("persona", PERSONAS)
def test_haven_reminders_replace_the_haven_line_in_its_window(persona: PersonaSpectrum) -> None:
    tpl = _tpl(persona)
    clock = Clock(DAY)
    session = _clocked(persona, clock)
    assert session.turn(HAVEN_SCRIPT[0]).reply in {_names(v) for v in tpl.haven}
    clock.now = DAY + timedelta(minutes=46)
    rest = session.turn("嗯")
    assert rest.stage is HelpStage.S_HAVEN and rest.inspect["reminder"] == "break"
    assert rest.reply in {_names(v) for v in tpl.break_reminder_haven}
    night = _clocked(persona, Clock(MIDNIGHT)).turn(HAVEN_SCRIPT[0])
    assert night.inspect["reminder"] == "late_night"
    assert night.reply in {_names(v) for v in tpl.late_night_haven}
    for result in (rest, night):
        assert _within(result.reply, tpl.haven_window) and "？" not in result.reply


@pytest.mark.parametrize("persona", PERSONAS)
def test_real_support_guidance_in_the_personas_voice(persona: PersonaSpectrum) -> None:
    session = _clocked(persona, Clock(DAY))
    support = {_names(v) for v in _tpl(persona).real_support}
    carried = []
    for text in CALM:
        result = session.turn(text)
        if result.reply_kind is not ReplyKind.NORMAL:
            continue
        _check_ordinary(persona, result.reply)
        if paragraphs(result.reply)[-1] in support:
            carried.append(result)
    if persona is SILENT:
        # One-paragraph replies have no invite to replace: SILENT_ANCHOR only listens.
        assert carried == []
    else:
        assert carried, "no real-support line in eight calm turns"


@pytest.mark.parametrize("light", [False, True], ids=["crisis", "ask-denied"])
@pytest.mark.parametrize("persona", PERSONAS)
def test_returning_greeting_comes_from_the_persona_and_reveals_nothing(
    persona: PersonaSpectrum, light: bool
) -> None:
    tpl = _tpl(persona)
    pool = tpl.returning_after_check if light else tpl.returning_after_crisis
    greeting = _open(persona).care_greeting(light=light)
    assert greeting in {_names(v) for v in pool}
    assert "\n" not in greeting
    for word in ("危机", "自杀", "轻生", "生命", "死", "伤害", "热线", "风险", "L2", "L3", "求助"):
        assert word not in greeting, (word, greeting)
    if persona is SILENT:
        assert count_all(greeting) <= 30
        if light:
            assert "？" not in greeting


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
