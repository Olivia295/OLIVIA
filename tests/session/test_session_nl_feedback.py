"""Natural-language feedback and follow-ups in the session (roadmap R-7b).

A feedback phrase on a waiting card must have exactly the effects of the command it
stands for; outside that state, and on any crisis turn, it must have none.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest

from olivia.core.language.data import load_language_data
from olivia.core.models import HelpStage, PersonaProfile, UserRegion
from olivia.core.session import ReplyKind, Session, TurnResult
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
NOW = datetime(2026, 10, 22, 23, 30, tzinfo=UTC)
NAME = "小林"
TEMPLATES = load_language_data(TAX).templates
REQUEST = "给我一个方法"
STABILIZE = "被领导催进度，心慌得要命"


def _open(seed: int = 7) -> Session:
    profile = PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        user_name=NAME,
        region=UserRegion("CN", "Asia/Shanghai"),
    )
    return Session.open(TAX, profile, rng=random.Random(seed), now=lambda: NOW)


def _filled(variants: tuple[str, ...]) -> set[str]:
    return {v.replace("{user_name}", NAME) for v in variants}


def _effects(session: Session, result: TurnResult) -> tuple[object, ...]:
    snap = session.snapshot()
    return (
        result.stage,
        result.inspect["reason"],
        result.inspect["feedback"],
        snap["user_shelved_actions"],
        snap["pending_action"],
        snap["bandit"],
    )


def _with_card(seed: int = 7, first: str = REQUEST) -> tuple[Session, str]:
    session = _open(seed)
    shown = session.turn(first).action_id
    assert shown is not None
    return session, shown


# -- same effects as the command ------------------------------------------------------------


@pytest.mark.parametrize(
    ("phrase", "command", "feedback"),
    [
        ("做完了", "/done", "HELPFUL"),
        ("试过了，好多了", "/done", "HELPFUL"),
        ("今天先不做了", "/not-now", "NOT_NOW"),
        ("我今天真的提不起劲做这个", "/not-now", "NOT_NOW"),
        ("先存着吧", "/not-now", "NOT_NOW"),
        ("这个方法对我没用", "/unhelpful", "UNHELPFUL"),
        ("这个不适合我", "/unhelpful", "UNHELPFUL"),
    ],
)
@pytest.mark.parametrize("first", [REQUEST, STABILIZE])
def test_phrase_has_the_commands_effects(
    phrase: str, command: str, feedback: str, first: str
) -> None:
    by_command, _ = _with_card(first=first)
    by_phrase, _ = _with_card(first=first)
    expected = _effects(by_command, by_command.turn(command))
    result = by_phrase.turn(phrase)
    assert _effects(by_phrase, result) == expected
    assert result.inspect["feedback"] == feedback
    assert result.inspect["feedback_source"] == "phrase"


def test_command_feedback_is_marked_as_command() -> None:
    session, _ = _with_card()
    assert session.turn("/done").inspect["feedback_source"] == "command"


def test_aversion_is_marked_as_a_phrase() -> None:
    session, _ = _with_card()
    result = session.turn("我不想做这个练习")
    assert result.inspect["reason"] == "EMPOWER_AVERSION"
    assert result.inspect["feedback"] == "UNHELPFUL"
    assert result.inspect["feedback_source"] == "phrase"


def test_no_feedback_means_no_source() -> None:
    session, _ = _with_card()
    result = session.turn("嗯，我看看")
    assert result.inspect["feedback"] is None and result.inspect["feedback_source"] is None


# -- only while a card waits ----------------------------------------------------------------


@pytest.mark.parametrize("phrase", ["做完了", "今天先不做了", "这个不适合我", "唉"])
def test_phrases_mean_nothing_without_a_waiting_card(phrase: str) -> None:
    session = _open()
    session.turn("今天上班好累")
    result = session.turn(phrase)
    assert result.inspect["feedback"] is None
    assert result.reply not in _filled(TEMPLATES.clarify_feedback)
    snap = session.snapshot()
    assert snap["user_shelved_actions"] == [] and snap["bandit"] == {"spectra": {}}


def test_phrases_mean_nothing_once_the_card_is_answered() -> None:
    session, _ = _with_card()
    session.turn("/done")
    bandit = session.snapshot()["bandit"]
    result = session.turn("这个不适合我")
    assert result.inspect["feedback"] is None
    assert session.snapshot()["bandit"] == bandit


@pytest.mark.parametrize(
    "text",
    [
        "我真没用",
        "我就是个废物",
        "我什么都做不好",
        "我根本没用",
        "我觉得自己一点用都没有",
        "我连这个都做不好，我真没用",
        "不是没用，就是还没开始",
        "我没有不想做了，只是有点累",
        "今天下雨了",
    ],
)
def test_self_criticism_negation_and_chat_are_not_feedback(text: str) -> None:
    session, shown = _with_card()
    result = session.turn(text)
    assert result.inspect["feedback"] is None
    snap = session.snapshot()
    assert snap["user_shelved_actions"] == [] and snap["bandit"] == {"spectra": {}}
    if result.stage is HelpStage.S_EMPOWER:
        assert snap["pending_action"] == shown


def test_slash_command_answers_the_clarification_as_a_command() -> None:
    session, _ = _with_card()
    session.turn("唉")
    result = session.turn("/done")
    assert result.inspect["feedback"] == "HELPFUL"
    assert result.inspect["feedback_source"] == "command"


# -- clarification --------------------------------------------------------------------------


@pytest.mark.parametrize("unclear", ["唉", "算了吧。", "再说吧~"])
def test_unclear_reply_gets_one_clarification(unclear: str) -> None:
    session, shown = _with_card()
    asked = session.turn(unclear)
    assert asked.reply in _filled(TEMPLATES.clarify_feedback)
    assert asked.stage is HelpStage.S_EMPOWER and asked.reply_kind is ReplyKind.NORMAL
    assert asked.inspect["feedback"] is None and asked.action_id is None
    snap = session.snapshot()
    assert snap["pending_action"] == shown and snap["awaiting_clarification"] is True


@pytest.mark.parametrize("yes", ["好", "好的！", "可以", "嗯嗯"])
def test_yes_to_the_clarification_records_not_now(yes: str) -> None:
    by_command, shown = _with_card()
    expected = _effects(by_command, by_command.turn("/not-now"))
    session, _ = _with_card()
    session.turn("唉")
    result = session.turn(yes)
    assert _effects(session, result) == expected
    assert result.inspect["feedback_source"] == "confirmed"
    assert session.state.user_shelved_actions == [shown]


@pytest.mark.parametrize("no", ["不用了", "不要", "先不用"])
def test_no_to_the_clarification_keeps_the_card_waiting(no: str) -> None:
    session, shown = _with_card()
    session.turn("唉")
    result = session.turn(no)
    assert result.stage is HelpStage.S_EMPOWER and result.inspect["feedback"] is None
    assert result.reply in _filled(TEMPLATES.after_card)
    snap = session.snapshot()
    assert snap["pending_action"] == shown and snap["user_shelved_actions"] == []
    assert snap["awaiting_clarification"] is False


def test_other_reply_to_the_clarification_is_handled_as_today() -> None:
    session, shown = _with_card()
    session.turn("唉")
    result = session.turn("今天下雨了")
    assert result.inspect["feedback"] is None
    assert result.reply in _filled(TEMPLATES.after_card)
    assert session.snapshot()["pending_action"] == shown


def test_feedback_phrase_answers_the_clarification_too() -> None:
    session, _ = _with_card()
    session.turn("唉")
    result = session.turn("其实做完了")
    assert result.inspect["feedback"] == "HELPFUL"
    assert result.inspect["feedback_source"] == "phrase"


def test_yes_without_a_question_is_not_feedback() -> None:
    session, shown = _with_card()
    result = session.turn("好")
    assert result.inspect["feedback"] is None
    assert session.snapshot()["pending_action"] == shown


def test_clarification_is_asked_once() -> None:
    session, _ = _with_card()
    session.turn("唉")
    again = session.turn("唉")
    assert again.reply in _filled(TEMPLATES.after_card)
    later = session.turn("好")  # the question has lapsed
    assert later.inspect["feedback"] is None


def test_unclear_reply_to_a_stabilization_card_is_clarified_in_explore() -> None:
    session, shown = _with_card(first=STABILIZE)
    asked = session.turn("唉")  # one S_explore turn so far: the stage stays
    assert asked.stage is HelpStage.S_EXPLORE
    assert asked.reply in _filled(TEMPLATES.clarify_feedback)
    result = session.turn("好")
    assert result.inspect["feedback"] == "NOT_NOW"
    assert result.inspect["feedback_source"] == "confirmed"
    assert session.state.user_shelved_actions == [shown]


# -- crisis first ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text", ["做完了，我也不想活了", "今天先不做了，我不想活了", "这个不适合我，不想活了"]
)
@pytest.mark.parametrize("first", [REQUEST, STABILIZE])
def test_crisis_sentence_is_never_feedback(text: str, first: str) -> None:
    session, _ = _with_card(first=first)
    result = session.turn(text)
    assert result.stage is HelpStage.S_CRISIS and result.reply_kind is ReplyKind.CRISIS
    assert result.inspect["feedback"] is None and result.inspect["feedback_source"] is None
    snap = session.snapshot()
    assert snap["user_shelved_actions"] == [] and snap["bandit"] == {"spectra": {}}


def test_crisis_answer_to_the_clarification_is_crisis() -> None:
    session, _ = _with_card()
    session.turn("唉")
    result = session.turn("好，反正我也不想活了")
    assert result.stage is HelpStage.S_CRISIS and result.inspect["feedback"] is None
    assert session.snapshot()["user_shelved_actions"] == []


# -- kit recall (within the session; across sessions waits for P5) --------------------------


@pytest.mark.parametrize(
    "recall", ["锦囊里那个再给我看看", "上次存的那个方法再给我看看", "我想试试锦囊里的"]
)
def test_kit_recall_shows_the_shelved_card_again(recall: str) -> None:
    session, shown = _with_card()
    session.turn("先存着吧")
    assert session.state.user_shelved_actions == [shown]
    result = session.turn(recall)
    assert result.stage is HelpStage.S_EMPOWER and result.reply_kind is ReplyKind.CARD
    assert result.action_id == shown
    snap = session.snapshot()
    assert snap["pending_action"] == shown and snap["user_shelved_actions"] == []
    # Waiting again: /not-now puts it back in the kit.
    session.turn("/not-now")
    assert session.state.user_shelved_actions == [shown]


def test_kit_recall_with_an_empty_kit_says_so_gently() -> None:
    session = _open()
    session.turn("今天上班好累")
    result = session.turn("我想试试锦囊里的")
    assert result.reply in _filled(TEMPLATES.kit_empty)
    assert result.action_id is None and result.reply_kind is ReplyKind.NORMAL


def test_kit_recall_with_a_card_waiting_and_an_empty_kit_keeps_the_card() -> None:
    session, shown = _with_card()
    result = session.turn("锦囊里有什么")
    assert result.reply in _filled(TEMPLATES.kit_empty)
    assert session.snapshot()["pending_action"] == shown


def test_kit_recall_in_a_crisis_is_crisis() -> None:
    session, shown = _with_card()
    session.turn("/not-now")
    result = session.turn("锦囊里那个再给我看看，反正我不想活了")
    assert result.stage is HelpStage.S_CRISIS and result.action_id is None
    assert session.state.user_shelved_actions == [shown]


STABILIZATION = {"28", "29", "29:pmr_release", "30", "30:grounding", "12:tipp_breathing"}


@pytest.mark.parametrize("seed", range(10))
def test_kit_recall_at_high_arousal_respects_the_solver(seed: int) -> None:
    session, shown = _with_card(seed)
    session.turn("/not-now")
    result = session.turn("心跳快炸了，手一直在抖，锦囊里那个再给我看看")
    assert result.action_id is None or result.action_id in STABILIZATION
    if shown not in STABILIZATION:
        assert session.state.user_shelved_actions == [shown]


# -- S_closing and the steps after /done and /unhelpful ------------------------------------


@pytest.mark.parametrize("closing", ["/done", "做完了", "/not-now", "今天先不做了"])
@pytest.mark.parametrize("yes", ["好", "可以的"])
def test_yes_in_closing_confirms_the_intention(closing: str, yes: str) -> None:
    session, _ = _with_card()
    assert session.turn(closing).stage is HelpStage.S_CLOSING
    result = session.turn(yes)
    assert result.stage is HelpStage.S_READY
    assert result.inspect["reason"] == "CLOSING_INTENT_CONFIRMED"


@pytest.mark.parametrize("no", ["不用了", "不了"])
def test_no_in_closing_is_acknowledged(no: str) -> None:
    session, _ = _with_card()
    session.turn("/done")
    result = session.turn(no)
    assert result.stage is HelpStage.S_CLOSING
    assert result.reply in _filled(TEMPLATES.closing_declined)


def test_after_unhelpful_there_is_no_question_to_answer() -> None:
    session, _ = _with_card()
    session.turn("/unhelpful")
    bandit = session.snapshot()["bandit"]
    result = session.turn("好")
    assert result.stage in (HelpStage.S_EXPLORE, HelpStage.S_CLARIFY)
    assert result.inspect["feedback"] is None and session.snapshot()["bandit"] == bandit


def test_snapshot_and_inspect_still_hold_no_user_text() -> None:
    session, _ = _with_card()
    results = [session.turn("唉"), session.turn("锦囊里那个再给我看看")]
    dumped = repr([r.inspect for r in results] + [session.snapshot()])
    for fragment in ("唉", "锦囊"):
        assert fragment not in dumped
