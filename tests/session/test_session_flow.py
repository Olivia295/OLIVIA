"""Session flow fixes found by the audit and the hands-on usage test (batch F2b).

Each section names the fix: the SDD §10.1 fallback, stale waiting cards, the bandit
spectrum, the closing ritual and what follows it, feedback commands with nothing waiting,
the capped model L3, leaving S_haven on a request, the memory-wipe request and the crisis
safety confirmation.
"""

from __future__ import annotations

import logging
import random
from dataclasses import replace
from datetime import UTC, datetime

import pytest

import olivia.core.session as session_module
from olivia.core.fsm.machine import Reason, Transition
from olivia.core.language.data import Templates, load_language_data
from olivia.core.models import CrisisLevel, HelpStage, PersonaProfile, UserRegion
from olivia.core.safety.crisis import RiskPrediction
from olivia.core.session import CLOSING_REOPEN, DEGRADED, ReplyKind, Session, TurnResult
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
NOW = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)
NAME = "小林"
AGENT = "Olivia"
TEMPLATES: Templates = load_language_data(TAX).templates
REQUEST = "给我一个方法"
STABILIZE = "被领导催进度，心慌得要命"
L2_TEXT = "我不想活了"
SECRET = "蓝色风筝和外婆的院子"


def _profile(**overrides: object) -> PersonaProfile:
    base = PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        user_name=NAME,
        region=UserRegion("CN", "Asia/Shanghai"),
    )
    return replace(base, **overrides)


def _open(seed: int = 7, **kwargs: object) -> Session:
    return Session.open(TAX, _profile(), rng=random.Random(seed), now=lambda: NOW, **kwargs)  # type: ignore[arg-type]


def _names(text: str) -> str:
    return text.replace("{user_name}", NAME).replace("{agent_name}", AGENT)


def _filled(variants: tuple[str, ...]) -> set[str]:
    return {_names(v) for v in variants}


def _first(reply: str) -> str:
    return reply.split("\n\n", 1)[0]


def _with_card(seed: int = 7, first: str = REQUEST) -> tuple[Session, str]:
    session = _open(seed)
    shown = session.turn(first).action_id
    assert shown is not None
    return session, shown


def _boom(*_args: object, **_kwargs: object) -> object:
    raise RuntimeError(SECRET)


# -- fix 1: SDD §10.1 fallback ----------------------------------------------------------------


@pytest.mark.parametrize("part", ["tracker", "stub", "engine"])
def test_failure_after_the_screen_on_a_calm_turn_gives_the_presence_line(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, part: str
) -> None:
    session = _open()
    session.turn("今天上班好累")
    if part == "tracker":
        monkeypatch.setattr(session._tracker, "observe", _boom)
    elif part == "stub":
        monkeypatch.setattr(session_module, "dominant_spectrum", _boom)
    else:
        monkeypatch.setattr(session._engine, "compose", _boom)
    with caplog.at_level(logging.DEBUG):
        result = session.turn(f"{SECRET}，有点累")
    assert result.reply == session._engine.gate.fallback
    assert result.reply_kind is ReplyKind.HAVEN and not result.in_crisis
    assert result.inspect["reason"] == DEGRADED
    assert result.inspect["degraded"] == "RuntimeError"
    assert SECRET not in caplog.text
    assert all(SECRET not in str(value) for value in result.inspect.values())


def test_failure_on_an_l2_turn_gives_the_minimal_card_with_every_number(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _open()
    monkeypatch.setattr(session._tracker, "observe", _boom)
    result = session.turn(L2_TEXT)
    assert result.reply_kind is ReplyKind.CRISIS and result.in_crisis
    assert result.stage is HelpStage.S_CRISIS
    assert result.reply.startswith(load_language_data(TAX).render.crisis_minimal)
    assert "12356" in result.reply
    assert result.resource_card is not None and result.resource_card.region_used == "CN"


def test_failure_inside_a_crisis_still_lists_every_number(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _open()
    session.turn("我写好了遗书")  # Stage 1: an L3 crisis
    monkeypatch.setattr(session._engine, "render_crisis", _boom)
    result = session.turn("嗯")
    assert result.reply_kind is ReplyKind.CRISIS and result.in_crisis
    for number in ("110", "120", "12356"):
        assert number in result.reply
    assert result.reply.index("110") < result.reply.index("12356")


def test_failure_on_the_answer_to_the_d3_question_is_a_crisis_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _open()
    asked = session.turn("有没有最快的办法离开")
    assert asked.reply_kind is ReplyKind.SAFETY_CHECK
    monkeypatch.setattr(session._tracker, "observe", _boom)
    result = session.turn("嗯")
    assert result.reply_kind is ReplyKind.CRISIS and "12356" in result.reply


# -- fix 2: a stale stabilization card --------------------------------------------------------


@pytest.mark.parametrize("seed", range(5))
def test_request_after_an_ordinary_turn_gets_a_new_card(seed: int) -> None:
    session, shown = _with_card(seed, first=STABILIZE)
    ordinary = session.turn("刚才在工位上坐了一会儿")
    assert ordinary.stage is HelpStage.S_EXPLORE and ordinary.inspect["feedback"] is None
    asked = session.turn("给我一个方法吧")
    assert asked.stage is HelpStage.S_EMPOWER
    assert asked.reply_kind is ReplyKind.CARD and asked.action_id is not None
    assert asked.reply not in _filled(TEMPLATES.after_card)
    assert session.snapshot()["pending_action"] == asked.action_id


def test_request_straight_after_the_card_still_gets_the_feedback_prompt() -> None:
    session, shown = _with_card(first=STABILIZE)
    probe = session.turn("能给我一个练习试试吗")
    assert probe.action_id is None and probe.reply in _filled(TEMPLATES.after_card)
    assert session.snapshot()["pending_action"] == shown


# -- fix 3: the bandit's spectrum -------------------------------------------------------------


def test_feedback_is_filed_under_the_last_known_spectrum() -> None:
    session = _open()
    first = session.turn("最近工作压力很大，有点焦虑，晚上总睡不着")
    spectrum = first.inspect["spectrum"]
    assert isinstance(spectrum, str) and spectrum != session_module.FALLBACK_SPECTRUM
    card = session.turn(REQUEST)
    assert card.inspect["spectrum"] is None and card.action_id is not None
    assert session.snapshot()["pending_spectrum"] == spectrum
    session.turn("/done")
    bandit = session.snapshot()["bandit"]
    assert isinstance(bandit, dict)
    assert set(bandit["spectra"]) == {spectrum}


def test_without_any_spectrum_the_fallback_is_used() -> None:
    session = _open()
    session.turn(REQUEST)
    assert session.snapshot()["pending_spectrum"] == session_module.FALLBACK_SPECTRUM


# -- fixes 4, 6 and 9: the closing ritual and what follows it ---------------------------------


def test_done_gets_the_done_ritual_and_not_now_the_kit_ritual() -> None:
    done, _ = _with_card()
    after_done = done.turn("/done")
    assert after_done.stage is HelpStage.S_CLOSING
    assert _first(after_done.reply) in {_first(r) for r in _filled(TEMPLATES.closing)}
    assert "锦囊" not in after_done.reply and "不想试" not in after_done.reply
    # Nothing was shelved, so the kit is honestly empty.
    recall = done.turn("锦囊里那个再给我看看")
    assert recall.reply in _filled(TEMPLATES.kit_empty)

    shelved, shown = _with_card()
    after_not_now = shelved.turn("/not-now")
    assert _first(after_not_now.reply) in {
        _first(r) for r in _filled(TEMPLATES.closing_after_not_now)
    }
    recalled = shelved.turn("锦囊里那个再给我看看")
    assert recalled.action_id == shown


@pytest.mark.parametrize("seed", range(5))
def test_new_topic_after_the_ritual_returns_to_listening(seed: int) -> None:
    session, _ = _with_card(seed)
    ritual = session.turn("/done")
    assert ritual.stage is HelpStage.S_CLOSING
    thanks = session.turn("还挺有用的，谢谢")
    assert thanks.stage is HelpStage.S_CLOSING
    assert thanks.reply in _filled(TEMPLATES.after_close)
    new = session.turn("其实我也很想家，已经两年没回国了")
    assert new.stage is HelpStage.S_EXPLORE and new.inspect["reason"] == CLOSING_REOPEN
    assert new.inspect["previous_stage"] == "S_closing"
    assert _first(new.reply) not in {_first(r) for r in _filled(TEMPLATES.closing)}
    assert new.reply not in _filled(TEMPLATES.after_close)
    again = session.turn("爸妈总说让我别太累，可我不敢停下来")
    assert again.stage in (HelpStage.S_EXPLORE, HelpStage.S_CLARIFY)


@pytest.mark.parametrize("seed", range(5))
def test_the_same_closing_text_is_never_sent_twice_in_a_row(seed: int) -> None:
    session, _ = _with_card(seed)
    replies = [session.turn("/done").reply]
    for _ in range(6):
        result = session.turn("谢谢你")
        assert result.stage is HelpStage.S_CLOSING
        replies.append(result.reply)
    for earlier, later in zip(replies, replies[1:], strict=False):
        assert earlier != later


def test_yes_after_the_ritual_gets_the_after_close_line_not_a_greeting() -> None:
    session, _ = _with_card()
    session.turn("/done")
    result = session.turn("好")
    assert result.stage is HelpStage.S_READY
    assert result.reply in _filled(TEMPLATES.after_close)
    assert result.reply not in _filled(TEMPLATES.greeting)
    assert "？" not in result.reply


# -- fix 5: feedback commands -----------------------------------------------------------------


@pytest.mark.parametrize("command", ["/done", "/not-now", "/unhelpful"])
@pytest.mark.parametrize("turns", [1, 3])
def test_feedback_command_without_a_waiting_card_gets_one_line(command: str, turns: int) -> None:
    session = _open()
    stages = [session.turn("今天上班好累").stage]
    for _ in range(turns - 1):
        stages.append(session.turn("老板又临时加了需求").stage)
    before = session.state.current_stage
    result = session.turn(command)
    assert result.reply in _filled(TEMPLATES.no_pending_feedback)
    assert result.action_id is None and result.inspect["info"] is None
    assert result.inspect["feedback"] is None
    assert result.stage is before  # the command does not move the conversation on
    assert session.snapshot()["bandit"] == {"spectra": {}}
    assert session.state.user_shelved_actions == []


def test_feedback_command_after_the_ritual_gets_one_line() -> None:
    session, _ = _with_card()
    session.turn("/done")
    result = session.turn("/done")
    assert result.reply in _filled(TEMPLATES.no_pending_feedback)
    assert result.stage is HelpStage.S_CLOSING


@pytest.mark.parametrize("first", [REQUEST, STABILIZE])
def test_unhelpful_on_a_waiting_card_is_acknowledged(first: str) -> None:
    session, _ = _with_card(first=first)
    result = session.turn("/unhelpful")
    assert result.inspect["feedback"] == "UNHELPFUL"
    assert _first(result.reply) in _filled(TEMPLATES.unhelpful_ack)


def test_feedback_command_in_a_crisis_is_still_the_crisis_card() -> None:
    session = _open()
    session.turn(L2_TEXT)
    result = session.turn("/done")
    assert result.reply_kind is ReplyKind.CRISIS and "12356" in result.reply


# -- fix 7: a capped model L3 still shows the emergency numbers first ------------------------


class _StubModel:
    """Scores L3 on the sentences it is told to, L0 on everything else."""

    def __init__(self, l3: set[str]) -> None:
        self.l3 = l3

    def predict(self, text: str) -> RiskPrediction:
        if text in self.l3:
            return RiskPrediction(CrisisLevel.L3, 0.96, ())
        return RiskPrediction(CrisisLevel.L0, 0.05, ())


def test_model_l3_capped_at_l2_shows_emergency_numbers_first() -> None:
    sentence = "我已经把想说的话都写下来留给家人了"
    session = _open(model=_StubModel({sentence}))
    result = session.turn(sentence)
    assert result.inspect["model_level"] == "L3"
    assert result.crisis_level is CrisisLevel.L2 and result.stage is HelpStage.S_CRISIS
    reply = result.reply
    render = load_language_data(TAX).render
    assert render.crisis_emergency_heading[CrisisLevel.L3] in reply
    assert reply.index("110") < reply.index("120") < reply.index("12356")
    assert render.crisis_contact_people in reply
    card = result.resource_card
    assert card is not None and card.level is CrisisLevel.L2
    assert [e.number for e in card.emergency] == ["110", "120"]
    assert [ln.number for ln in card.lines] == ["12356"]
    # The rest of the flow is the L2 flow, and the numbers stay for the whole crisis.
    later = session.turn("嗯")
    assert later.in_crisis and later.inspect["model_level"] == "L0"
    assert later.reply.index("110") < later.reply.index("12356")


def test_model_l3_keeps_every_l2_line_of_the_region() -> None:
    sentence = "我已经把想说的话都写下来留给家人了"
    session = Session.open(
        TAX,
        _profile(region=UserRegion("TW", "Asia/Taipei")),
        rng=random.Random(3),
        now=lambda: NOW,
        model=_StubModel({sentence}),
    )
    reply = session.turn(sentence).reply
    for number in ("110", "119", "1925", "1995", "1980"):
        assert number in reply, number
    assert reply.index("119") < reply.index("1925")


def test_model_l2_alone_shows_no_emergency_numbers() -> None:
    session = _open(model=_StubModel(set()))
    result = session.turn(L2_TEXT)
    assert result.crisis_level is CrisisLevel.L2
    assert "110" not in result.reply and "12356" in result.reply


def test_the_emergency_framing_ends_with_the_crisis() -> None:
    sentence = "我已经把想说的话都写下来留给家人了"
    session = _open(model=_StubModel({sentence}))
    session.turn(sentence)
    assert session._urgent
    session._tracker = type(session._tracker)(TAX, session._shared.lexicons)  # crisis over
    session.turn("今天天气不错")
    assert not session._urgent


# -- fix 8: leaving S_haven on a direct request -----------------------------------------------


def test_card_that_leaves_haven_says_how_to_get_back(monkeypatch: pytest.MonkeyPatch) -> None:
    # The session side, whatever the state machine decides: a card shown on a turn that
    # left S_haven ends with the haven_return line.
    session = _open()
    session.turn("[5%] 好累，今天不想动脑，只想躺着")
    real_step = session_module.step

    def leaving_haven(*args: object, **kwargs: object) -> Transition:
        moved = real_step(*args, **kwargs)  # type: ignore[arg-type]
        state = replace(moved.state, current_stage=HelpStage.S_EMPOWER, stage_turn_count=1)
        return Transition(HelpStage.S_HAVEN, state, Reason.DIRECT_REQUEST)

    monkeypatch.setattr(session_module, "step", leaving_haven)
    result = session.turn("给我一个方法吧")
    assert result.reply_kind is ReplyKind.CARD
    assert result.reply.rsplit("\n\n", 1)[1] in _filled(TEMPLATES.haven_return)


@pytest.mark.xfail(
    strict=False,
    reason="F2a moves a direct request out of S_haven; on this branch the FSM keeps haven",
)
def test_direct_request_in_haven_gets_a_card_and_the_way_back() -> None:
    session = _open()
    session.turn("[5%] 好累，今天不想动脑，只想躺着")
    result = session.turn("给我一个方法吧")
    assert result.stage is HelpStage.S_EMPOWER and result.reply_kind is ReplyKind.CARD
    assert result.reply.rsplit("\n\n", 1)[1] in _filled(TEMPLATES.haven_return)


# -- fix 10: a memory-wipe request in the chat ------------------------------------------------


@pytest.mark.parametrize("text", ["清空所有记忆", "帮我删除所有聊天记录", "把记忆都删了吧"])
def test_wipe_request_gets_the_commands_and_is_never_mirrored(text: str) -> None:
    session = _open()
    session.turn("今天上班好累")
    before = session.state.current_stage
    result = session.turn(text)
    assert result.reply in _filled(TEMPLATES.forget_hint)
    assert "olivia forget --all" in result.reply and "olivia memory" in result.reply
    assert text not in result.reply
    assert result.stage is before


@pytest.mark.parametrize("text", ["我想清空关于他的记忆", "那些记忆怎么也删不掉，我好难受"])
def test_memories_of_someone_are_ordinary_conversation(text: str) -> None:
    session = _open()
    result = session.turn(text)
    assert result.reply not in _filled(TEMPLATES.forget_hint)


def test_wipe_request_in_a_crisis_sentence_is_crisis() -> None:
    result = _open().turn("清空所有记忆，我不想活了")
    assert result.reply_kind is ReplyKind.CRISIS


# -- fix 11: the crisis safety confirmation ---------------------------------------------------


def test_safety_confirmation_is_acknowledged_before_the_card() -> None:
    session = _open()
    session.turn(L2_TEXT)
    confirmed = session.turn("我现在安全了")
    assert confirmed.reply_kind is ReplyKind.CRISIS and confirmed.in_crisis
    assert _first(confirmed.reply) in _filled(TEMPLATES.safety_confirmed)
    assert "12356" in confirmed.reply
    after = session.turn("嗯")
    assert _first(after.reply) not in _filled(TEMPLATES.safety_confirmed)


def test_no_acknowledgement_without_a_confirmation() -> None:
    session = _open()
    session.turn(L2_TEXT)
    result: TurnResult = session.turn("我不知道")
    assert _first(result.reply) not in _filled(TEMPLATES.safety_confirmed)


# -- fix 12: the repeated crisis card ---------------------------------------------------------


def test_every_crisis_turn_repeats_the_full_card() -> None:
    # No compact card exists (render.yaml has only the gate-fallback minimal card), so
    # every crisis turn shows the full card: every number, every hours line.
    session = _open()
    replies = [session.turn(text).reply for text in ("我写好了遗书", "嗯", "我不知道")]
    for reply in replies:
        for part in ("110", "120", "12356", "服务时间："):
            assert part in reply
