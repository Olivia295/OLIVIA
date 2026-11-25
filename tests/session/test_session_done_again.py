"""Session gaps (draft pending G-0): "做完了" right after the card was marked done.

After ``/done`` (or the phrase) on a card, no card waits any more, so a second "做完了" used
to be read as new words: S_explore mirrored it back ("你提到做完了") and moved on to
S_clarify. Within a few turns of the card's done, a short done phrase with no card waiting
is a meta turn like a stray ``/done``: one ``notices.already_done`` line, the stage holds,
no mirror and no card. S_closing keeps its own after-close line; longer messages, or a done
phrase long after the card, are ordinary conversation.

Every sentence typed is made up for these tests.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest

from olivia.core.language.data import load_language_data
from olivia.core.models import HelpStage, PersonaProfile, UserRegion
from olivia.core.session import ReplyKind, Session
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
NOW = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)
ALREADY_DONE = load_language_data(TAX).utterances.notices["already_done"]
REQUEST = "最近工作压力好大，能给我一个练习试试吗"
PANIC = "我现在心跳好快，整个人都在发抖，慌得不行"


def _open() -> Session:
    profile = PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        user_name="小林",
        region=UserRegion("CN", "Asia/Shanghai"),
    )
    return Session.open(TAX, profile, rng=random.Random(5), now=lambda: NOW)


def _done_on_a_stabilization_card(done: str) -> Session:
    session = _open()
    card = session.turn(PANIC)
    assert card.reply_kind is ReplyKind.CARD and card.stage is HelpStage.S_EXPLORE
    assert session.turn(done).inspect["feedback"] == "HELPFUL"
    return session


@pytest.mark.parametrize("done", ["/done", "做完了"])
@pytest.mark.parametrize("again", ["做完了", "我做完啦", "刚做完", "做完了，感觉好多了"])
def test_done_again_after_the_card_is_heard_as_done(done, again):
    session = _done_on_a_stabilization_card(done)
    result = session.turn(again)
    assert result.stage is HelpStage.S_EXPLORE  # held, not moved on to S_clarify
    assert result.inspect["reason"] == "STAY"
    assert result.reply in ALREADY_DONE  # the whole reply: no mirror of the words
    assert result.reply_kind is ReplyKind.NORMAL and result.action_id is None


def test_it_is_heard_again_on_the_next_turns_too():
    session = _done_on_a_stabilization_card("/done")
    first = session.turn("做完了")
    second = session.turn("做完了")
    assert first.reply in ALREADY_DONE and second.reply in ALREADY_DONE
    assert second.stage is HelpStage.S_EXPLORE


def test_done_again_after_closing_keeps_the_closing_and_shows_no_card():
    session = _open()
    session.turn(REQUEST)
    closing = session.turn("/done")
    assert closing.stage is HelpStage.S_CLOSING
    result = session.turn("做完了")
    assert result.stage is HelpStage.S_CLOSING
    assert result.reply_kind is not ReplyKind.CARD and result.action_id is None
    assert result.reply != closing.reply


def test_done_long_after_the_card_is_ordinary():
    session = _done_on_a_stabilization_card("/done")
    for words in ("周末打算把书架重新整理一下", "还想去楼下买点水果", "顺便把阳台也收拾一下"):
        session.turn(words)
    assert session.turn("做完了").reply not in ALREADY_DONE


def test_done_with_words_of_its_own_is_ordinary():
    session = _done_on_a_stabilization_card("/done")
    result = session.turn("做完了，可是一想到明天还要见那个客户，心里又开始发紧")
    assert result.reply not in ALREADY_DONE


def test_done_with_no_card_ever_shown_is_ordinary():
    assert _open().turn("做完了").reply not in ALREADY_DONE


def test_leaving_after_the_card_still_gets_the_goodbye():
    session = _done_on_a_stabilization_card("/done")
    assert session.turn("做完了，我去睡了").reply not in ALREADY_DONE
