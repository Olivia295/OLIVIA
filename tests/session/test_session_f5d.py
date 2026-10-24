"""Fix F5d through the session: leaving for now with no card waiting, in both modes.

Usage testing: in S_explore and S_clarify, with no practice card waiting for feedback,
"我想睡觉了", "我去睡了", "我想试着睡一下" and "嗯，今天就到这里吧" got an ordinary
listening reply, and in S_clarify sometimes the once-per-session lens card as well. Such
a turn now gets one ``S_ready.after_close`` line, with no card and no information card;
the state machine is unchanged (S_closing follows a practice only, SDD §4.2). A turn the
screen rates L1 or above keeps its own reply (safety first), and a waiting card still
reads the phrase as not_now (F5a).
"""

from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest

from olivia.core.models import HelpStage, PersonaProfile, PersonaSpectrum, UserRegion
from olivia.core.session import ReplyKind, Session, TurnResult
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
NOW = datetime(2026, 10, 24, 21, 0, tzinfo=UTC)
MODES = [pytest.param(False, id="rules"), pytest.param(True, id="model")]
LEAVING = ["我想睡觉了", "我去睡了", "我想试着睡一下", "嗯，今天就到这里吧"]
# Turns before the goodbye, and the stage the goodbye turn lands in.
BEFORE = {
    "explore": (["今天上班好累"], HelpStage.S_EXPLORE),
    "clarify": (["今天上班好累", "领导一直催我"], HelpStage.S_CLARIFY),
}


def _open(student: bool, persona: PersonaSpectrum = PersonaSpectrum.GENTLE_HOLDING) -> Session:
    profile = PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        region=UserRegion("CN", "Asia/Shanghai"),
        persona_spectrum=persona,
    )
    return Session.open(TAX, profile, rng=random.Random(5), now=lambda: NOW, student=student)


def _is_goodbye(session: Session, result: TurnResult) -> bool:
    """The reply is one ``after_close`` line, with no card of any kind."""
    pool = session._engine.data.templates.after_close
    tails = [variant.rsplit("}", 1)[-1] for variant in pool]
    return (
        result.reply_kind in (ReplyKind.NORMAL, ReplyKind.HAVEN)
        and result.action_id is None
        and result.resource_card is None
        and result.inspect["info"] is None
        and "\n" not in result.reply
        and any(result.reply.endswith(tail) for tail in tails)
    )


@pytest.mark.parametrize("student", MODES)
@pytest.mark.parametrize("where", sorted(BEFORE))
@pytest.mark.parametrize("text", LEAVING)
def test_leaving_with_no_card_waiting_gets_a_goodbye(student: bool, where: str, text: str) -> None:
    turns, stage = BEFORE[where]
    session = _open(student)
    for before in turns:
        session.turn(before)
    result = session.turn(text)
    assert not result.in_crisis
    if result.inspect["assessed_level"] != "L0":
        # Model mode: the student rates "嗯，今天就到这里吧" L1 (score band, no rule cue);
        # an L1 turn keeps the L1 reply.
        assert student, text
        assert not _is_goodbye(session, result), text
        return
    assert result.stage is stage  # the state machine moves as before: no closing
    assert _is_goodbye(session, result), (text, result.reply)


@pytest.mark.parametrize("text", LEAVING)
def test_every_leaving_sentence_is_l0_in_rules_mode(text: str) -> None:
    result = _open(False).turn(text)
    assert result.inspect["assessed_level"] == "L0"


@pytest.mark.parametrize("persona", list(PersonaSpectrum))
def test_every_persona_says_goodbye(persona: PersonaSpectrum) -> None:
    session = _open(False, persona)
    session.turn("今天上班好累")
    result = session.turn("我去睡了")
    assert _is_goodbye(session, result), (persona, result.reply)


def test_the_lens_is_not_attached_and_stays_for_later() -> None:
    # The lens came with the goodbye turn before; it is not used up by it either.
    session = _open(False)
    session.turn("今天上班好累")
    session.turn("领导一直催我")
    assert _is_goodbye(session, session.turn("我想试着睡一下"))
    later = [session.turn(text) for text in ("其实还有件事想说", "我总觉得自己做得不够好")]
    assert any(r.reply_kind is ReplyKind.INFO for r in later)


@pytest.mark.parametrize("student", MODES)
@pytest.mark.parametrize("text", ["孩子去睡了", "今天就到这里？我还没说完"])
def test_look_alikes_get_the_ordinary_reply(student: bool, text: str) -> None:
    session = _open(student)
    session.turn("今天上班好累")
    result = session.turn(text)
    assert not _is_goodbye(session, result), text
    assert "\n\n" in result.reply  # the stage's composed reply


@pytest.mark.parametrize("student", MODES)
def test_an_l1_turn_keeps_the_l1_reply(student: bool) -> None:
    session = _open(student)
    session.turn("今天上班好累")
    result = session.turn("活着好累，我去睡了")
    assert result.inspect["assessed_level"] == "L1"
    assert not _is_goodbye(session, result)


@pytest.mark.parametrize("student", MODES)
def test_a_waiting_card_still_reads_it_as_not_now(student: bool) -> None:
    session = _open(student)
    session.turn("今天上班好累")
    shown = session.turn("给我一个方法").action_id
    assert shown is not None
    result = session.turn("我想睡觉了")
    assert result.stage is HelpStage.S_CLOSING
    assert result.inspect["reason"] == "EMPOWER_TO_CLOSING"
    assert result.inspect["feedback"] == "NOT_NOW"
    assert shown in session.snapshot()["user_shelved_actions"]
