"""Session gaps (drafts pending G-0): a high distress rating the retreat lines do not move.

SDD §4.2 keeps S_empower unless the arousal reaches 0.85 or rises 0.25 over the stage's
entry (thresholds unchanged here). An 8 can stay below both, so the card keeps waiting; the
reply then used to say "我们先不急着往下做，一起把身体稳一稳" with no steadying card. Now:

* a rating at the somatic line that brings a steadying card (a retreat, or after an
  S_explore card) still leads with ``crisis.suds_high``;
* one that leaves the card waiting in S_empower leads with ``crisis.suds_high_ask``: the
  score is high, and a yes ("好") brings a steadying card instead (the waiting card goes
  into the kit); anything else keeps the waiting card;
* one with no steadying card to offer leads with ``crisis.suds_high_heard``.

Every sentence typed is made up for these tests.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime
from importlib import resources

import pytest

from olivia.core.language.data import load_language_data
from olivia.core.models import HelpStage, PersonaProfile, UserRegion
from olivia.core.session import ReplyKind, Session
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
NOW = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)
RENDER = load_language_data(TAX).render
WHITELIST = frozenset(TAX.stabilization_whitelist())
REQUEST = "最近工作压力好大，能给我一个练习试试吗"
STEADY = "稳一稳"


def _open() -> Session:
    profile = PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        user_name="小林",
        region=UserRegion("CN", "Asia/Shanghai"),
    )
    return Session.open(TAX, profile, rng=random.Random(5), now=lambda: NOW)


def _lead(reply: str) -> str:
    return reply.split("\n\n")[0]


def _rated_eight() -> tuple[Session, str]:
    session = _open()
    card = session.turn(REQUEST)
    assert card.stage is HelpStage.S_EMPOWER and card.action_id is not None
    return session, card.action_id


def test_an_eight_without_a_retreat_says_no_steadying_it_does_not_do():
    session, _ = _rated_eight()
    result = session.turn("8")
    assert result.stage is HelpStage.S_EMPOWER  # 0.80: below 0.85, no 0.25 rise
    assert result.reply_kind is not ReplyKind.CARD
    lead = _lead(result.reply)
    assert lead in RENDER.suds_high_ask
    assert lead not in RENDER.suds_high
    assert "先不急着往下做" not in result.reply


def test_a_yes_to_the_offer_brings_another_steadying_card():
    session, waiting = _rated_eight()
    session.turn("8")
    result = session.turn("好")
    assert result.reply_kind is ReplyKind.CARD
    assert result.action_id in WHITELIST and result.action_id != waiting
    assert waiting in session.state.user_shelved_actions  # the waiting one is in the kit


@pytest.mark.parametrize("answer", ["不用", "不了", "我先做这个"])
def test_anything_but_a_yes_keeps_the_waiting_card(answer):
    session, waiting = _rated_eight()
    session.turn("8")
    result = session.turn(answer)
    assert result.reply_kind is not ReplyKind.CARD
    assert waiting not in session.state.user_shelved_actions


def test_a_yes_counts_only_on_the_turn_right_after_the_offer():
    session, waiting = _rated_eight()
    session.turn("8")
    session.turn("我再想想")
    result = session.turn("好")
    assert result.reply_kind is not ReplyKind.CARD
    assert waiting not in session.state.user_shelved_actions


def test_a_rating_that_retreats_still_steadies_with_a_card():
    session, _ = _rated_eight()
    result = session.turn("9")
    assert result.stage is HelpStage.S_EXPLORE and result.reply_kind is ReplyKind.CARD
    assert _lead(result.reply) in RENDER.suds_high


def test_with_nothing_steadying_left_the_high_score_is_only_heard(monkeypatch):
    session, _ = _rated_eight()
    monkeypatch.setattr(Session, "_steadying_card_left", lambda *_args: False)
    result = session.turn("8")
    lead = _lead(result.reply)
    assert lead in RENDER.suds_high_heard
    assert STEADY not in lead


def test_the_new_lines_are_marked_as_drafts_awaiting_g0():
    text = resources.files("olivia").joinpath("data/language/render.yaml").read_text("utf-8")
    comment = text[: text.index("  suds_high_ask:")].rsplit("  # 草稿：待 G-0", 1)
    assert len(comment) == 2 and "suds_high_ask" in comment[1] and "suds_high_heard" in comment[1]
    for line in RENDER.suds_high_heard:
        assert STEADY not in line
    for line in RENDER.suds_high_ask:
        assert "“好”" in line  # says what to answer to get the steadying card
