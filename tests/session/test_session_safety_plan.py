"""The user's safety plan inside a session (next-phase B10, decision D8).

Crisis golden dialogues with a plan: the block order at L2 and L3, every hotline number on
screen, emergency numbers first, section 5 never shown; the gate fallbacks; the D3
question without the plan; the one-time ``olivia safety-plan`` suggestion. Names and
numbers are made up.
"""

from __future__ import annotations

import random
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from olivia.core.chang.safety_plan import (
    Contact,
    SafetyPlan,
    Section,
    crisis_block,
    crisis_reminder,
    load_safety_plan_text,
)
from olivia.core.language.data import load_language_data
from olivia.core.language.gate import GateResult, OutputGate
from olivia.core.models import CrisisLevel, HelpStage, PersonaProfile, UserRegion
from olivia.core.resources.card import ResourceCard
from olivia.core.session import ReplyKind, Session, TurnResult
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
NOW = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)
L2_SENTENCE = "我不想活了"
L3_SENTENCE = "我写了一封遗书"
ASK = "有没有最快的办法离开"
TEXT = load_safety_plan_text()
PLAN = SafetyPlan(
    warning_signs=("整夜睡不着觉",),
    coping=("听一首喜欢的歌", "洗个热水澡"),
    distraction=("楼下的小公园",),
    people=(Contact("阿青", "138-0000-0000"), Contact("小周", "139 0000 0001")),
    environment=("把那盒东西交给阿青保管",),
)
HIDDEN = (*PLAN.warning_signs, *PLAN.environment)
REGIONS = pytest.mark.parametrize("region", ["CN", "US", "ZZ"])


def _open(region: str = "CN", seed: int = 3, **kwargs: object) -> Session:
    profile = PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        user_name="小林",
        region=UserRegion(region, "Asia/Shanghai"),
    )
    return Session.open(TAX, profile, rng=random.Random(seed), now=lambda: NOW, **kwargs)  # type: ignore[arg-type]


def _numbers(card: ResourceCard) -> list[str]:
    return [e.number for e in card.emergency] + [ln.number for ln in card.lines]


def _assert_card_intact(result: TurnResult) -> None:
    card = result.resource_card
    assert card is not None
    for number in _numbers(card):
        assert number in result.reply, number
    for hidden in HIDDEN:
        assert hidden not in result.reply


def _plan_at(reply: str) -> int:
    return reply.index(TEXT.crisis_intro)


def _first_number_at(reply: str, card: ResourceCard) -> int:
    return min(reply.index(n) for n in _numbers(card))


# -- crisis golden dialogues ------------------------------------------------------------------


@REGIONS
def test_l2_opening_then_plan_then_hotline_card(region):
    plain = _open(region).turn(L2_SENTENCE)
    result = _open(region, safety_plan=PLAN).turn(L2_SENTENCE)
    card = result.resource_card
    assert result.reply_kind is ReplyKind.CRISIS and card is not None
    assert card.level is CrisisLevel.L2
    assert result.inspect["safety_plan_shown"] is True
    assert plain.inspect["safety_plan_shown"] is False
    _assert_card_intact(result)
    block = crisis_block(PLAN)
    assert block in result.reply
    opening, rest = plain.reply.split("\n\n", 1)
    if card.emergency:
        # A region without an L2 line shows emergency numbers at L2: they stay first.
        assert result.reply == f"{opening}\n\n{rest}\n\n{block}"
    else:
        assert result.reply == f"{opening}\n\n{block}\n\n{rest}"
        assert _plan_at(result.reply) < _first_number_at(result.reply, card)


@REGIONS
def test_l3_opening_then_emergency_card_then_plan(region):
    plain = _open(region).turn(L3_SENTENCE)
    result = _open(region, safety_plan=PLAN).turn(L3_SENTENCE)
    card = result.resource_card
    assert card is not None and card.level is CrisisLevel.L3 and card.emergency
    assert result.inspect["safety_plan_shown"] is True
    _assert_card_intact(result)
    assert result.reply == f"{plain.reply}\n\n{crisis_block(PLAN)}"
    # Emergency numbers come before anything else that carries a number.
    first_emergency = min(result.reply.index(e.number) for e in card.emergency)
    assert first_emergency < _plan_at(result.reply)
    assert first_emergency == _first_number_at(result.reply, card)
    assert result.reply.index("138-0000-0000") > first_emergency


def test_the_plan_is_shown_once_per_crisis_then_one_reminder_line():
    """S5 (2026-10-26): the full plan once per crisis; later crisis replies carry one line
    that names the plan's people (no numbers), and every card stays whole."""
    session = _open(safety_plan=PLAN)
    first, *later = [session.turn(t) for t in (L3_SENTENCE, "嗯", "我现在安全了")]
    assert first.inspect["safety_plan_shown"] is True and crisis_block(PLAN) in first.reply
    reminder = crisis_reminder(PLAN)
    assert "阿青" in reminder and "小周" in reminder and "138" not in reminder
    for result in [first, *later]:
        assert result.stage is HelpStage.S_CRISIS
        _assert_card_intact(result)
    for result in later:
        assert result.inspect["safety_plan_shown"] is False
        assert result.inspect["safety_plan_reminded"] is True
        assert TEXT.crisis_intro not in result.reply and "138-0000-0000" not in result.reply
        assert result.reply.count(reminder) == 1


def test_a_new_crisis_shows_the_plan_in_full_again():
    session = _open(safety_plan=PLAN)
    session.turn(L2_SENTENCE)
    assert session.turn("嗯").inspect.get("safety_plan_reminded") is True
    for text in ("我现在安全了", "今天天气还行", "去楼下买了杯奶茶"):
        session.turn(text)
    assert session.snapshot()["in_crisis"] is False
    again = session.turn(L2_SENTENCE)
    assert again.inspect["safety_plan_shown"] is True and crisis_block(PLAN) in again.reply


def test_the_reminder_without_people_points_back_at_the_plan():
    plan = SafetyPlan(coping=("听一首喜欢的歌",))
    session = _open(safety_plan=plan)
    session.turn(L2_SENTENCE)
    later = session.turn("嗯")
    assert crisis_reminder(plan) == TEXT.crisis_reminder
    assert TEXT.crisis_reminder in later.reply and "听一首喜欢的歌" not in later.reply


def test_section_five_and_warning_signs_never_reach_a_crisis_reply():
    plan = SafetyPlan(warning_signs=("一个预警信号",), environment=("把药交给别人",))
    result = _open(safety_plan=plan).turn(L2_SENTENCE)
    assert result.inspect["safety_plan_shown"] is False
    assert TEXT.crisis_intro not in result.reply
    for word in ("一个预警信号", "把药交给别人", TEXT.titles[Section.ENVIRONMENT]):
        assert word not in result.reply
    assert result.reply == _open().turn(L2_SENTENCE).reply


def test_without_a_plan_the_crisis_reply_is_unchanged():
    for sentence in (L2_SENTENCE, L3_SENTENCE):
        assert _open().turn(sentence).reply == _open(safety_plan=None).turn(sentence).reply


@pytest.mark.parametrize("number", ["12356", "110", "120", "112"])
def test_a_plan_number_that_looks_like_a_hotline_still_works(number):
    plan = SafetyPlan(people=(Contact("阿青", number), Contact("小周", "139-0000-0002")))
    for sentence in (L2_SENTENCE, L3_SENTENCE):
        result = _open(safety_plan=plan).turn(sentence)
        assert result.inspect["safety_plan_shown"] is True, result.inspect["gate"]
        assert f"阿青：{number}" in result.reply and "139-0000-0002" in result.reply
        _assert_card_intact(result)


def test_digits_in_the_users_own_words_are_allowed():
    plan = SafetyPlan(coping=("慢慢数到100",), people=(Contact("阿青", "+86 138 0000 0003"),))
    result = _open(safety_plan=plan).turn(L2_SENTENCE)
    assert result.inspect["safety_plan_shown"] is True
    assert "慢慢数到100" in result.reply and "+86 138 0000 0003" in result.reply


# -- gate fallbacks ---------------------------------------------------------------------------


def test_a_plan_the_gate_blocks_is_dropped_and_the_card_kept():
    term = load_language_data(TAX).willow.diagnosis_terms[0]
    plan = replace(PLAN, coping=(f"想起{term}的事",))
    for sentence in (L2_SENTENCE, L3_SENTENCE):
        result = _open(safety_plan=plan).turn(sentence)
        assert result.inspect["safety_plan_shown"] is False
        assert "diagnosis" in result.inspect["gate"]
        assert TEXT.crisis_intro not in result.reply and "阿青" not in result.reply
        assert result.reply == _open().turn(sentence).reply
        _assert_card_intact(result)


def test_minimal_card_fallback_keeps_every_hotline_number(monkeypatch):
    def blocked(self, text, **_kwargs):
        return GateResult(False, self.fallback, ("number:999",))

    monkeypatch.setattr(OutputGate, "check", blocked)
    minimal = load_language_data(TAX).render.crisis_minimal
    for sentence in (L2_SENTENCE, L3_SENTENCE):
        result = _open(safety_plan=PLAN).turn(sentence)
        card = result.resource_card
        assert card is not None
        assert result.reply.startswith(minimal)
        _assert_card_intact(result)
        assert "阿青" not in result.reply and "138-0000-0000" not in result.reply
        assert result.inspect["safety_plan_shown"] is False


# -- never outside crisis replies -------------------------------------------------------------


def test_no_plan_on_the_d3_question_or_ordinary_turns():
    session = _open(safety_plan=PLAN)
    ordinary = session.turn("今天上班好累")
    asked = session.turn(ASK)
    assert asked.reply_kind is ReplyKind.SAFETY_CHECK
    for result in (ordinary, asked):
        assert result.inspect["safety_plan_shown"] is False
        assert TEXT.crisis_intro not in result.reply
        assert "阿青" not in result.reply and "138-0000-0000" not in result.reply
    # An unclear answer enters the crisis flow, which shows the plan.
    answered = session.turn("嗯")
    assert answered.reply_kind is ReplyKind.CRISIS
    assert answered.inspect["safety_plan_shown"] is True


# -- the olivia safety-plan suggestion --------------------------------------------------------

CLOSING_SCRIPT = ("今天上班好累", "给我一个方法吧", "/done")


def _to_closing(session: Session) -> list[TurnResult]:
    return [session.turn(text) for text in CLOSING_SCRIPT]


def test_the_first_closing_reply_suggests_the_command_once():
    session = _open(suggest_safety_plan=True)
    results = _to_closing(session)
    closing = results[-1]
    assert closing.stage is HelpStage.S_CLOSING
    assert closing.reply.endswith(f"\n\n{TEXT.suggestion}")
    assert session.safety_plan_suggested
    assert all(TEXT.suggestion not in r.reply for r in results[:-1])
    later = [session.turn(t) for t in ("好", "给我一个方法吧", "/done", "嗯")]
    assert all(TEXT.suggestion not in r.reply for r in later)


def test_no_suggestion_unless_asked_for():
    session = _open()
    plain = _to_closing(session)
    assert not session.safety_plan_suggested
    assert all(TEXT.suggestion not in r.reply for r in plain)
    suggested = _to_closing(_open(suggest_safety_plan=True))
    assert suggested[-1].reply == f"{plain[-1].reply}\n\n{TEXT.suggestion}"


def test_never_in_a_crisis_reply():
    session = _open(suggest_safety_plan=True)
    for text in (L3_SENTENCE, "我现在安全了", "嗯", "嗯", "嗯"):
        result = session.turn(text)
        assert TEXT.suggestion not in result.reply
    assert not session.safety_plan_suggested


def test_not_in_the_care_greeting():
    session = _open(suggest_safety_plan=True)
    assert TEXT.suggestion not in session.care_greeting()
    assert not session.safety_plan_suggested


def test_an_l2_card_with_emergency_numbers_keeps_them_before_the_plan():
    """No region shows emergency numbers at L2 today; if one ever does, they stay first."""
    from olivia.core.language.engine import LanguageEngine, Slots

    l3 = _open().turn(L3_SENTENCE).resource_card
    assert l3 is not None and l3.emergency
    card = replace(l3, level=CrisisLevel.L2)
    engine = LanguageEngine(TAX, rng=random.Random(3))
    reply = engine.render_crisis(card, Slots("小林", "Olivia"), plan_block=crisis_block(PLAN))
    assert engine.last_plan_gate is not None and engine.last_plan_gate.ok
    assert _first_number_at(reply, card) < _plan_at(reply)
    for number in _numbers(card):
        assert number in reply
