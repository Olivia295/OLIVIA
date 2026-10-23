"""Quality fix F3 in whole sessions (rules mode): no fallback 「平静安详」, no verbatim
repeats, one plain line for medication and diagnosis questions, named practices, lenses
that fit, and cards framed by the local time."""

from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest

from olivia.core.language.engine import paragraphs
from olivia.core.models import CrisisLevel, PersonaProfile, PersonaSpectrum, UserRegion
from olivia.core.session import ReplyKind, Session, TurnResult
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
EVENING = datetime(2026, 10, 22, 13, 0, tzinfo=UTC)  # Thursday 21:00 in Shanghai
OFFICE = datetime(2026, 10, 22, 2, 0, tzinfo=UTC)  # Thursday 10:00 in Shanghai
PERSONAS = list(PersonaSpectrum)
CALM_NAME = "平静安详"


def _session(
    persona: PersonaSpectrum = PersonaSpectrum.GENTLE_HOLDING,
    *,
    seed: int = 1,
    now: datetime = EVENING,
) -> Session:
    profile = PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=now,
        updated_at=now,
        region=UserRegion("CN", "Asia/Shanghai"),
        persona_spectrum=persona,
    )
    return Session.open(TAX, profile, rng=random.Random(seed), now=lambda: now)


def _run(session: Session, script: list[str]) -> list[TurnResult]:
    return [session.turn(text) for text in script]


# The hands-on transcripts where half the replies called the user 「平静安详」.
TRANSCRIPT_LINES = [
    "我们分手了，在一起五年",
    "他说他累了，不想再继续。我到现在都不敢相信",
    "每天下班回到家，看到他留下的杯子就忍不住哭",
    "上个月外婆也走了，我觉得身边的人一个个都在离开",
    "😭😭😭",
    "老板下午又临时加了个需求，晚上十点还在改PPT，感觉自己像个陀螺",
    "其实也不是第一次了，每次都这样，我都不知道自己在坚持什么",
    "谢谢你听我说",
    "嗯",
    "……",
]


@pytest.mark.parametrize("persona", PERSONAS)
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_no_reply_names_a_fallback_calm(persona: PersonaSpectrum, seed: int) -> None:
    for result in _run(_session(persona, seed=seed), TRANSCRIPT_LINES):
        assert CALM_NAME not in result.reply, result.reply


@pytest.mark.parametrize("persona", PERSONAS)
def test_an_l1_turn_never_says_calm(persona: PersonaSpectrum) -> None:
    session = _session(persona)
    result = session.turn("我最近总想消失")
    assert result.inspect["assessed_level"] == CrisisLevel.L1.name
    assert CALM_NAME not in result.reply


def test_tiredness_at_work_is_tiredness_not_sadness() -> None:
    result = _session().turn("今天上班好累")
    assert "疲惫" in result.reply
    assert "悲伤" not in result.reply
    assert "你今天上班好累" in result.reply


@pytest.mark.parametrize("persona", PERSONAS)
def test_no_two_adjacent_replies_share_a_paragraph(persona: PersonaSpectrum) -> None:
    script = ["今天上班好累", "嗯", "嗯", "好", "谢谢你", "嗯", "😭", "我不知道", "嗯", "好"] * 3
    for seed in (1, 2):
        results = _run(_session(persona, seed=seed), script)
        assert len(results) == 30
        for before, after in zip(results, results[1:], strict=False):
            if before.reply_kind is ReplyKind.CRISIS or after.reply_kind is ReplyKind.CRISIS:
                continue
            shared = set(paragraphs(before.reply)) & set(paragraphs(after.reply))
            assert not shared, (persona, seed, shared)


@pytest.mark.parametrize("persona", [PersonaSpectrum.GENTLE_HOLDING, PersonaSpectrum.RATIONAL_PEER])
def test_a_one_word_answer_gets_a_short_reply(persona: PersonaSpectrum) -> None:
    session = _session(persona)
    session.turn("今天上班好累，老板又在群里点我的名")
    result = session.turn("嗯")
    assert result.reply_kind is ReplyKind.NORMAL
    assert len(paragraphs(result.reply)) == 2
    assert len(result.reply) < 200


def test_mirrors_keep_who_did_what() -> None:
    session = _session()
    assert "你妈今天又打电话骂你" in session.turn("我妈今天又打电话骂我").reply
    reply = session.turn("你别给我建议，我只想说说话").reply
    assert "对方别给你建议" not in reply
    thanks = session.turn("谢谢你一直在").reply
    assert "你感到谢谢" not in thanks and "谢谢对方" not in thanks


# -- medication and diagnosis -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("我在吃舍曲林，最近效果不好，我能自己把剂量加倍吗", "medication"),
        ("褪黑素一次吃多少比较好", "medication"),
        ("你觉得我是不是抑郁症", "diagnosis"),
        ("我是不是有焦虑症啊，你帮我判断一下", "diagnosis"),
    ],
)
def test_medication_and_diagnosis_questions_are_acknowledged_first(text: str, kind: str) -> None:
    session = _session()
    line = session._engine.data.utterances.boundaries[kind].line
    result = session.turn(text)
    assert result.reply.startswith(line + "\n\n")
    assert len(result.reply) > len(line) + 2  # then the reply it would give anyway


def test_a_crisis_turn_gets_no_boundary_line() -> None:
    session = _session()
    result = session.turn("我不想活了，药一次吃多少能结束")
    assert result.reply_kind is ReplyKind.CRISIS
    for b in session._engine.data.utterances.boundaries.values():
        assert b.line not in result.reply


# -- named practices --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("script", "card"),
    [
        (["能带我做一下正念吗"], "15"),
        (["今天上班好累", "带我做一下呼吸练习吧"], "28"),
        (["最近心里很乱", "教我练一下肌肉放松"], "29"),
    ],
)
def test_asking_for_a_named_practice_offers_its_card(script: list[str], card: str) -> None:
    result = _run(_session(), script)[-1]
    assert result.reply_kind is ReplyKind.CARD
    assert result.action_id == card


def test_asking_what_a_practice_is_gets_its_explainer() -> None:
    result = _session().turn("CBT是什么")
    assert result.reply_kind is ReplyKind.INFO
    assert result.inspect["info"] == "01"
    assert "认知行为疗法（CBT）" in result.reply


def test_a_red_flag_user_gets_no_practice_explainer() -> None:
    session = _session()
    session.turn("我有双相，最近几天睡得很少")
    result = session.turn("正念是什么")
    assert result.reply_kind is not ReplyKind.INFO


# -- lenses and cards -------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(6))
def test_a_breakup_never_gets_a_relationship_lens(seed: int) -> None:
    session = _session(PersonaSpectrum.ZEN_PHILOSOPHER, seed=seed)
    for result in _run(session, TRANSCRIPT_LINES[:5]):
        assert result.inspect["info"] not in {"35", "40", "53", "54"}


@pytest.mark.parametrize(("now", "office"), [(OFFICE, True), (EVENING, False)])
def test_the_card_context_line_follows_the_local_time(now: datetime, office: bool) -> None:
    session = _session(now=now)
    result = session.turn("能带我做一下正念吗")
    assert result.reply_kind is ReplyKind.CARD
    render = session._engine.data.render
    assert (render.card_stealth_label in result.reply) is office
    assert (render.card_home_line in result.reply) is not office


def test_cards_show_exercise_names() -> None:
    result = _session().turn("能带我做一下正念吗")
    assert "「身体扫描小练习（源自正念减压疗法）」" in result.reply
