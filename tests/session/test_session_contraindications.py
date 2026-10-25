"""The session passes derived contraindications and situations to the solver (A1, D2)."""

from __future__ import annotations

import random
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from olivia.core.methods.solver import M0_ACTION_ID
from olivia.core.models import PersonaProfile, PersonaSpectrum, UserRegion
from olivia.core.session import ReplyKind, Session, TurnResult
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
NOW = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)
REQUEST = "[80%] 给我一个方法"
HINT = "olivia health"
SEEDS = range(12)


def _blocked(enum_id: str) -> set[str]:
    methods, registry = TAX.methods(), TAX.action_registry()
    return {m for m, v in methods.items() if enum_id in v.contraindications} | {
        a for a, v in registry.items() if enum_id in v.contraindications
    }


def _open(seed: int = 7, **overrides: object) -> Session:
    profile = PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        user_name="小林",
        region=UserRegion("CN", "Asia/Shanghai"),
    )
    return Session.open(
        TAX, replace(profile, **overrides), rng=random.Random(seed), now=lambda: NOW
    )


def _offered(result: TurnResult) -> set[str]:
    """Every action the turn could have shown, plus the one it did show."""
    chosen = result.inspect["chosen"]
    candidates = result.inspect["candidates"]
    assert isinstance(candidates, list)
    return {*candidates, *([chosen] if isinstance(chosen, str) else [])}


# -- profile disclosures -------------------------------------------------------------


@pytest.mark.parametrize(
    ("enum_id", "requests"),
    [
        ("CARDIORESPIRATORY_INSTABILITY", (REQUEST, "心慌得要命，喘不上气，直接给我一个方法")),
        ("INTERPERSONAL_SAFETY_HAZARD", (REQUEST,)),
        ("RED_FLAG_PSYCHOSIS", (REQUEST,)),
    ],
)
def test_a_profile_disclosure_is_never_offered_a_contraindicated_action(enum_id, requests):
    blocked = _blocked(enum_id)
    shown_any = False
    for seed in SEEDS:
        for text in requests:
            result = _open(seed, contraindications=(enum_id,)).turn(text)
            assert enum_id in result.inspect["contraindications"]
            assert not _offered(result) & blocked, (seed, text)
            shown_any |= result.reply_kind is ReplyKind.CARD
            assert HINT not in result.reply  # already saved: no hint
    assert shown_any


def test_without_the_disclosure_the_same_requests_can_reach_those_actions():
    reachable: set[str] = set()
    for seed in SEEDS:
        reachable |= _offered(_open(seed).turn(REQUEST))
    assert reachable & _blocked("CARDIORESPIRATORY_INSTABILITY")
    assert reachable & _blocked("INTERPERSONAL_SAFETY_HAZARD")
    assert reachable & _blocked("TOXIC_SHAME_SPIRAL")


def test_clinical_history_sets_its_red_flag_contraindication():
    result = _open(clinical_history=("SIT-02-04",)).turn("今天有点累")
    assert "RED_FLAG_MANIA" in result.inspect["contraindications"]


# -- conversation disclosures --------------------------------------------------------


def test_a_disclosure_in_conversation_holds_for_the_session_and_is_hinted_once():
    blocked = _blocked("CARDIORESPIRATORY_INSTABILITY")
    session = _open(3)
    first = session.turn("我有心脏病，最近工作压力好大")
    assert first.reply.count(HINT) == 1
    assert "CARDIORESPIRATORY_INSTABILITY" in first.inspect["contraindications"]
    for text in (REQUEST, "/done", REQUEST, "我有心脏病"):
        result = session.turn(text)
        assert "CARDIORESPIRATORY_INSTABILITY" in result.inspect["contraindications"]
        assert not _offered(result) & blocked
        assert HINT not in result.reply


def test_a_second_kind_of_disclosure_gets_its_own_hint():
    session = _open()
    assert HINT in session.turn("我有哮喘").reply
    assert HINT in session.turn("他又动手打我了").reply
    assert HINT not in session.turn("家暴好几年了").reply


def test_a_safety_disclosure_keeps_the_crisis_reply_unchanged():
    plain = _open(5).turn("我不想活了")
    with_disclosure = _open(5).turn("他又动手打我了，我不想活了")
    assert with_disclosure.reply_kind is ReplyKind.CRISIS
    assert with_disclosure.reply == plain.reply
    assert with_disclosure.resource_card == plain.resource_card
    assert HINT not in with_disclosure.reply
    assert "INTERPERSONAL_SAFETY_HAZARD" in with_disclosure.inspect["contraindications"]
    assert "CRISIS_ACTIVE_RISK" in with_disclosure.inspect["contraindications"]


def test_a_safety_disclosure_keeps_the_red_flag_referral():
    plain = _open(5).turn("我是边缘型人格")
    with_disclosure = _open(5).turn("我是边缘型人格，他又动手打我了")
    assert with_disclosure.referral_flags == plain.referral_flags == ("SIT-09-01",)
    assert with_disclosure.reply_kind is plain.reply_kind
    assert HINT in with_disclosure.reply


# -- m0 situations -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "situation"),
    [
        ("[80%] 我奶奶刚去世，给我一个方法", "SIT-06-04"),
        ("[80%] 感觉一切都没有意义，给我一个方法", "SIT-11-01"),
    ],
)
def test_m0_situations_yield_m0(text, situation):
    for seed in SEEDS:
        result = _open(seed).turn(text)
        assert result.inspect["situations"] == [situation]
        assert result.inspect["candidates"] == []
        assert result.action_id == M0_ACTION_ID
        assert result.reply_kind is ReplyKind.NORMAL


def test_prolonged_grief_asking_for_a_method_gets_m0():
    """COLBO-06b: grief a year on, asked for a method, gets m0 and no exercise card."""
    for seed in SEEDS:
        result = _open(seed).turn("[80%] 妈妈去世一年多了，我还是走不出来，给我一个方法")
        assert result.inspect["situations"] == ["SIT-06-04"]
        assert result.inspect["candidates"] == []
        assert result.action_id == M0_ACTION_ID
        assert result.reply_kind is ReplyKind.NORMAL


def test_a_settled_loss_still_gets_an_ordinary_card():
    result = _open().turn("[80%] 外婆去世好几年了，现在想起来更多是温暖，给我一个方法")
    assert result.inspect["situations"] == []
    assert result.reply_kind is ReplyKind.CARD


def test_prolonged_grief_never_masks_a_crisis():
    result = _open().turn("妈妈去世一年多了，我还是走不出来，我不想活了")
    assert result.reply_kind is ReplyKind.CRISIS
    assert result.inspect["situations"] == ["SIT-06-04"]


def test_a_situation_holds_for_the_session():
    session = _open()
    session.turn("我奶奶刚去世")
    result = session.turn(REQUEST)
    assert result.inspect["situations"] == ["SIT-06-04"]
    assert "ACUTE_BEREAVEMENT_SHOCK" in result.inspect["contraindications"]
    assert result.action_id == M0_ACTION_ID


def test_meaninglessness_never_masks_a_crisis():
    result = _open().turn("一切都没有意义，我不想活了")
    assert result.reply_kind is ReplyKind.CRISIS
    assert result.inspect["situations"] == ["SIT-11-01"]


def test_self_attack_removes_its_contraindicated_actions():
    blocked = _blocked("TOXIC_SHAME_SPIRAL")
    for seed in SEEDS:
        result = _open(seed).turn("[80%] 我就是个废物，给我一个方法")
        assert "TOXIC_SHAME_SPIRAL" in result.inspect["contraindications"]
        assert not _offered(result) & blocked
        assert HINT not in result.reply


def test_inspect_lists_arousal_overload_with_the_derived_ids():
    result = _open().turn("心慌得要命，喘不上气")
    assert result.inspect["contraindications"] == ["ACUTE_AROUSAL_OVERLOAD"]
    assert result.inspect["situations"] == []


# -- F10: the m0 answer to a grief request is explained -------------------------------------


def _grief_lines(session: Session, *, prolonged: bool | None = None) -> set[str]:
    """The persona's grief lines: acute, prolonged (F13) or, with None, both."""
    templates = session._engine.data.templates
    variants = {
        False: templates.grief_request,
        True: templates.grief_request_prolonged,
        None: (*templates.grief_request, *templates.grief_request_prolonged),
    }[prolonged]
    return {v.replace("{user_name}", "小林") for v in variants}


PROLONGED_REQUEST = "[80%] 妈妈去世一年多了，我还是走不出来，给我一个方法"
ACUTE_REQUEST = "[80%] 我奶奶刚去世，给我一个方法"


@pytest.mark.parametrize("persona", list(PersonaSpectrum))
@pytest.mark.parametrize(("text", "prolonged"), [(PROLONGED_REQUEST, True), (ACUTE_REQUEST, False)])
def test_a_grief_request_on_m0_is_heard_and_points_at_grief_counselling(persona, text, prolonged):
    session = _open(persona_spectrum=persona)
    result = session.turn(text)
    assert result.action_id == M0_ACTION_ID and result.reply_kind is ReplyKind.NORMAL
    first, _, rest = result.reply.partition("\n\n")
    assert first in _grief_lines(session, prolonged=prolonged) and rest, result.reply
    assert first not in _grief_lines(session, prolonged=not prolonged)
    assert result.resource_card is None  # not a crisis: no hotline card
    acute_enum = "ACUTE_BEREAVEMENT_SHOCK" in result.inspect["contraindications"]
    assert acute_enum is not prolonged  # F13: only the early phase sets the acute enum


def test_an_acute_loss_later_in_the_session_switches_to_the_acute_line():
    session = _open()
    session.turn("[80%] 妈妈去世一年多了，我还是走不出来")
    session.turn("[80%] 昨天外婆也刚去世")
    result = session.turn("[80%] 给我一个方法")
    assert result.action_id == M0_ACTION_ID
    assert result.reply.partition("\n\n")[0] in _grief_lines(session, prolonged=False)


def test_grief_without_a_request_gets_no_grief_line():
    session = _open()
    result = session.turn("[80%] 妈妈去世一年多了，我还是走不出来")
    assert not any(line in result.reply for line in _grief_lines(session))
    # A later turn on m0 with no request of its own gets none either.
    session = _open()
    session.turn("[80%] 妈妈去世一年多了，我还是走不出来，给我一个方法")
    later = session.turn("嗯")
    assert not any(line in later.reply for line in _grief_lines(session))


def test_meaninglessness_on_m0_gets_no_grief_line():
    session = _open()
    result = session.turn("[80%] 感觉一切都没有意义，给我一个方法")
    assert result.action_id == M0_ACTION_ID
    assert not any(line in result.reply for line in _grief_lines(session))
