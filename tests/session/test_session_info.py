"""Grade B/C information cards in the session (roadmap next-phase A4, PRD §8.1).

Two paths, both through the solver's masks:

* asked: "EMDR 有用吗" (a Grade C therapy by name) gets the framed information card in
  any ordinary stage; a Grade B therapy by name only in S_clarify.
* lens: once per session, an S_clarify turn may add one Grade B explainer that fits the
  conversation's spectrum (``clarify_lenses``) after the S_clarify reflection.

Never in a crisis, in S_haven, on an L1 screen, at high arousal, or while a red flag is
active (the referral card speaks instead).
"""

from __future__ import annotations

import random
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from olivia.core.language.data import load_language_data
from olivia.core.models import HelpStage, PersonaProfile, SafetyGrade, UserRegion
from olivia.core.session import ReplyKind, Session, TurnResult
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
LANG = load_language_data(TAX)
NOW = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)
RENDER = LANG.render
INFO_LABEL = RENDER.info_who_label  # appears only in information cards
# Three turns that reach S_clarify through the attachment spectrum ("07").
TO_CLARIFY = (
    "最近和男朋友总吵架，很难过",
    "他总说我太黏人",
    "我也不知道该怎么办，每次吵完都很失落",
)


def _profile(**overrides: object) -> PersonaProfile:
    base = PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        user_name="小林",
        region=UserRegion("CN", "Asia/Shanghai"),
    )
    return replace(base, **overrides)


def _open(seed: int = 7, **overrides: object) -> Session:
    return Session.open(
        TAX, _profile(**overrides), rng=random.Random(seed), now=lambda: NOW, student=False
    )


def _no_info(result: TurnResult) -> None:
    assert result.reply_kind is not ReplyKind.INFO
    assert result.inspect["info"] is None
    assert INFO_LABEL not in result.reply


# -- asked: Grade C ---------------------------------------------------------------------------


@pytest.mark.parametrize(("text", "method_id"), [("EMDR 有用吗", "21"), ("暴露疗法是什么？", "05")])
def test_asked_grade_c_gets_the_framed_card(text: str, method_id: str) -> None:
    result = _open().turn(text)
    entry = LANG.info[method_id]
    assert result.stage is HelpStage.S_EXPLORE
    assert result.reply_kind is ReplyKind.INFO
    assert result.inspect["info"] == method_id
    assert result.reply.startswith(RENDER.info_ask_intro)
    assert entry.title in result.reply and RENDER.info_c_closing in result.reply
    assert result.action_id is None and result.inspect["gate"] == []
    assert result.inspect["candidates"] == []


@pytest.mark.parametrize("seed", range(5))
def test_asked_grade_c_in_s_clarify_and_after_a_card(seed: int) -> None:
    session = _open(seed)
    for text in TO_CLARIFY:
        session.turn(text)
    assert session.turn("CPT 有用吗").inspect["info"] == "22"
    # In S_empower with a card waiting, the answer leaves the card waiting.
    card = session.turn("给我一个方法")
    assert card.reply_kind is ReplyKind.CARD
    info = session.turn("那EMDR是什么")
    assert info.reply_kind is ReplyKind.INFO and info.stage is HelpStage.S_EMPOWER
    assert session.snapshot()["pending_action"] == card.action_id
    done = session.turn("/done")
    assert done.inspect["feedback"] == "HELPFUL"


def test_plain_mentions_are_not_info() -> None:
    session = _open()
    for text in ("我在做EMDR，有点累", "我在做正念练习"):
        _no_info(session.turn(text))


@pytest.mark.parametrize(
    ("text", "method_id"), [("认知行为疗法是什么", "01"), ("正念是什么", "15")]
)
def test_a_grade_a_practice_asked_by_name_gets_its_explainer(text: str, method_id: str) -> None:
    # F3: common names of Grade A practices have a short explainer (grade_a_entries).
    result = _open().turn(text)
    assert result.reply_kind is ReplyKind.INFO
    assert result.inspect["info"] == method_id


# -- asked: Grade B -----------------------------------------------------------------------


def test_asked_grade_b_waits_for_s_clarify() -> None:
    session = _open()
    early = session.turn("图式疗法是什么")
    assert early.stage is HelpStage.S_EXPLORE
    _no_info(early)
    for text in TO_CLARIFY[1:]:
        session.turn(text)
    asked = session.turn("图式疗法是什么")
    assert asked.stage is HelpStage.S_CLARIFY
    assert asked.reply_kind is ReplyKind.INFO and asked.inspect["info"] == "19"
    assert asked.reply.startswith(RENDER.info_ask_intro)
    assert asked.reply.endswith(RENDER.info_b_closing)


# -- lens: Grade B in S_clarify -------------------------------------------------------------


@pytest.mark.parametrize("seed", range(10))
def test_s_clarify_offers_one_lens_for_the_spectrum(seed: int) -> None:
    session = _open(seed)
    results = [session.turn(text) for text in TO_CLARIFY]
    lens = results[-1]
    assert lens.stage is HelpStage.S_CLARIFY
    assert lens.reply_kind is ReplyKind.INFO
    mid = lens.inspect["info"]
    assert mid in LANG.info_lenses["07"]
    assert LANG.info[mid].grade is SafetyGrade.GRADE_B
    reflection, offered = lens.reply.split(RENDER.info_lens_intro)
    assert reflection.strip()  # the S_clarify reflection comes first
    assert offered.rstrip().endswith(RENDER.info_b_closing)
    assert lens.action_id is None and lens.inspect["gate"] == []
    # Once per session.
    later = [session.turn(t) for t in ("嗯，是这样", "我也说不清", "就是很累")]
    for result in later:
        if result.stage is HelpStage.S_CLARIFY:
            _no_info(result)


def test_no_lens_without_a_mapped_spectrum() -> None:
    session = _open()
    results = [session.turn(t) for t in ("今天有点烦", "说不上来", "就是不太舒服")]
    assert results[-1].stage is HelpStage.S_CLARIFY
    _no_info(results[-1])


def test_no_lens_or_answer_for_a_taboo_topic() -> None:
    # The lens table offers 35, 40, 53, 54 for "07"; with every one of their titles'
    # key words as taboo topics, no lens can be shown.
    session = _open(taboo_topics=("依恋", "情绪聚焦", "伴侣", "交互分析"))
    results = [session.turn(text) for text in TO_CLARIFY]
    _no_info(results[-1])
    assert results[-1].stage is HelpStage.S_CLARIFY
    _no_info(_open(taboo_topics=("创伤",)).turn("EMDR 有用吗"))


# -- never -----------------------------------------------------------------------------------


@pytest.mark.parametrize("flag", ["SIT-06-01", "SIT-08-04", "SIT-09-01"])
def test_red_flag_gets_the_referral_and_no_info(flag: str) -> None:
    session = _open(clinical_history=(flag,))
    first = session.turn("EMDR 有用吗")
    _no_info(first)
    assert first.reply_kind is ReplyKind.REFERRAL
    _no_info(session.turn("进食障碍强化认知行为疗法是什么"))


def test_red_flag_blocks_the_lens() -> None:
    session = _open(clinical_history=("SIT-02-06",))
    for text in TO_CLARIFY:
        _no_info(session.turn(text))


@pytest.mark.parametrize(
    "text",
    [
        "我不想活了，EMDR 有用吗",  # crisis
        "我想消失，EMDR 有用吗",  # L1 screen
        "心慌得要命，喘不上气，EMDR 有用吗",  # acute arousal
    ],
)
def test_no_info_in_crisis_l1_or_high_arousal(text: str) -> None:
    _no_info(_open().turn(text))


def test_no_info_in_the_haven() -> None:
    result = _open().turn("[5%] EMDR 有用吗")
    assert result.stage is HelpStage.S_HAVEN
    _no_info(result)


def test_inspect_and_snapshot_hold_no_user_text() -> None:
    session = _open()
    text = "EMDR 有用吗"
    result = session.turn(text)
    assert text not in repr(result.inspect) and "EMDR" not in repr(session.snapshot())
