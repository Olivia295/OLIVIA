"""Narrative externalization in the session (PRD 特性四, step C3).

Model mode only, under the schema mirror's gates (decision D4): once per session an
inner-critic pattern gets a gentle offer to name it, in place of an S_clarify reply's
closing question, never on the mirror's turn or the turn reading its answer. A number or
a name accepts, a clear no declines, anything else is no answer. After a yes, ordinary
S_explore / S_clarify replies may call the pattern by its name when it shows up again, at
most once every three turns, never in a crisis, S_haven or a card.

As in ``test_session_introspection.py``, the gating tests switch the mirror and the offer
on in a rules session (``_enable``) so the rule stub's perception decides arousal and risk;
the 特性四 dialogue at the end runs the real student.
"""

from __future__ import annotations

import random
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from olivia.core.models import HelpStage, PersonaProfile, PersonaSpectrum, UserRegion
from olivia.core.perception.externalize import NAMING_GAP, Offer, load_externalize_text
from olivia.core.session import ReplyKind, Session, TurnResult
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
TEXT = load_externalize_text(TAX)
NOW = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)
SOMATIC = TAX.threshold("arousal.thresholds.somatic_priority")
# S_explore twice (DEFECTIVENESS on the second), S_clarify with the Grade B lens, the
# mirror's question, an unclear answer to it. Every turn screens L0 under the rules.
READY = (
    "最近工作压力有点大",
    "我总觉得自己不够好",
    "领导说的话我很在意",
    "今天又加班了",
    "我也说不清",
)
CALM = "今天外面下雨了"
CRITIC = "我不够好"
LOCK = "你听我说就好，不用给建议"
ASK = "有没有最快的办法离开"
ALL_NAMES = frozenset(TEXT.names.values())


def _profile(**overrides: object) -> PersonaProfile:
    base = PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        user_name="小林",
        region=UserRegion("CN", "Asia/Shanghai"),
    )
    return replace(base, **overrides)


def _open(seed: int = 7, *, student: bool = False, **overrides: object) -> Session:
    return Session.open(
        TAX, _profile(**overrides), rng=random.Random(seed), now=lambda: NOW, student=student
    )


def _enable(session: Session) -> Session:
    """Model mode's mirror and offer over rule perception (deterministic gating tests)."""
    session._mirror.enabled = True
    session._externalize.enabled = True
    return session


def _run(session: Session, texts: tuple[str, ...]) -> list[TurnResult]:
    return [session.turn(text) for text in texts]


def _offer_in(result: TurnResult) -> Offer | None:
    return next((o for o in TEXT.offers if o.line in result.reply), None)


def _named(result: TurnResult) -> bool:
    return any(f"「{name}」" in result.reply for name in ALL_NAMES)


def _ready(**overrides: object) -> Session:
    """Up to the turn on which the offer is due; nothing offered before it."""
    session = _enable(_open(**overrides))
    results = _run(session, READY)
    stages = [r.stage for r in results]
    assert stages == [HelpStage.S_EXPLORE] * 2 + [HelpStage.S_CLARIFY] * 3
    # The pattern showed in S_explore: no offer outside S_clarify.
    assert results[1].inspect["schemas"] == ["DEFECTIVENESS"]
    # The mirror first, and never on the same turn or the turn reading its answer.
    assert [r.inspect["schema_mirror"] for r in results] == [None, None, None, "asked", None]
    assert all(r.inspect["externalize"] is None for r in results)
    assert not any(_offer_in(r) for r in results)
    return session


def _offered(**overrides: object) -> tuple[Session, Offer]:
    session = _ready(**overrides)
    result = session.turn(CALM)
    assert result.inspect["externalize"] == "offered", result.inspect
    offer = _offer_in(result)
    assert offer is not None
    return session, offer


# -- the offer ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "persona",
    [
        PersonaSpectrum.GENTLE_HOLDING,
        PersonaSpectrum.ZEN_PHILOSOPHER,
        PersonaSpectrum.RATIONAL_PEER,
    ],
)
def test_the_offer_replaces_the_closing_question_of_an_s_clarify_reply(persona):
    session = _ready(persona_spectrum=persona)
    result = session.turn(CALM)
    assert result.stage is HelpStage.S_CLARIFY and result.reply_kind is ReplyKind.NORMAL
    assert result.inspect["externalize"] == "offered"
    assert result.inspect["externalize_name"] is None
    assert result.inspect["gate"] == []
    paragraphs = result.reply.split("\n\n")
    assert len(paragraphs) == 3
    assert paragraphs[-1] in {o.line for o in TEXT.offers}
    assert session.snapshot()["externalize"] == "offered"


def test_offered_at_most_once_per_session():
    session, _ = _offered()
    results = _run(session, (CALM, CRITIC, LOCK, CRITIC, CALM, CRITIC))
    assert all(r.inspect["externalize"] is None for r in results)
    assert not any(_offer_in(r) for r in results)


# -- gates -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,stage",
    [
        # High arousal leaves S_clarify for S_explore's stabilization channel (fix F2a).
        ("心慌得要命，手一直在抖，我很在意别人怎么看我", HelpStage.S_EXPLORE),
        ("我想消失", HelpStage.S_CLARIFY),  # L1 screen
        ("[10%] 今天外面下雨了", HelpStage.S_HAVEN),
        ("我不想活了", HelpStage.S_CRISIS),
        (LOCK, HelpStage.S_CLARIFY),  # listening lock
    ],
    ids=["arousal", "l1", "haven", "crisis", "lock"],
)
def test_never_on_a_risky_resting_or_listening_turn(text, stage):
    session = _ready()
    result = session.turn(text)
    assert result.stage is stage
    assert result.inspect["externalize"] is None and _offer_in(result) is None


def test_l1_only_postpones_the_offer():
    session = _ready()
    assert session.turn("每天都好绝望").inspect["externalize"] is None
    assert session.turn(CALM).inspect["externalize"] == "offered"


def test_high_arousal_postpones_the_offer_until_back_in_clarify():
    # The arousal retreat (fix F2a) goes back to S_explore with a stabilization card; the
    # offer waits for the ordinary S_explore -> S_clarify advance.
    session = _ready()
    retreat = session.turn("心慌得要命，手一直在抖")
    assert retreat.stage is HelpStage.S_EXPLORE and retreat.action_id is not None
    assert retreat.inspect["externalize"] is None
    assert session.turn(CALM).inspect["externalize"] is None
    back = session.turn(CALM)
    assert back.stage is HelpStage.S_CLARIFY and back.inspect["externalize"] == "offered"


def test_never_on_the_d3_question_or_its_answer():
    session = _ready()
    asked = session.turn(ASK)
    assert asked.reply_kind is ReplyKind.SAFETY_CHECK
    answer = session.turn("不是，我就是随便问问")
    assert answer.inspect["safety_check"] == "denied"
    for result in (asked, answer):
        assert result.inspect["externalize"] is None and _offer_in(result) is None


def test_never_while_a_red_flag_is_active():
    session = _enable(_open(clinical_history=("SIT-02-06",)))
    results = _run(session, (*READY, CALM, CRITIC, CALM))
    assert any(r.stage is HelpStage.S_CLARIFY for r in results)
    assert all(r.inspect["externalize"] is None for r in results)
    assert not any(_offer_in(r) or _named(r) for r in results)


def test_never_for_silent_anchor():
    session = _enable(_open(persona_spectrum=PersonaSpectrum.SILENT_ANCHOR))
    results = _run(session, (*READY, CALM, CRITIC, CALM, CRITIC, CALM))
    assert any(r.stage is HelpStage.S_CLARIFY for r in results)
    assert all(r.inspect["externalize"] is None for r in results)
    assert not any(_offer_in(r) for r in results)


def test_not_after_a_no_to_the_mirror():
    session = _enable(_open())
    results = _run(session, READY[:4])
    assert results[-1].inspect["schema_mirror"] == "asked"
    declined = session.turn("没有")
    assert declined.inspect["schema_mirror"] == "declined"
    later = _run(session, (CALM, CRITIC))
    assert all(r.inspect["externalize"] is None for r in later)


def test_a_critic_distortion_needs_two_calm_turns():
    session = _enable(_open())
    # No schema at all, so the mirror has nothing to ask.
    results = _run(
        session, ("最近工作压力有点大", "今天又加班了", "我应该做得更好", CALM, "我应该做得更好")
    )
    assert [r.stage for r in results][2:] == [HelpStage.S_CLARIFY] * 3
    assert all(r.inspect["schema_mirror"] is None for r in results)
    assert [r.inspect["externalize"] for r in results] == [None, None, None, None, "offered"]


def test_other_schemas_are_not_the_pattern():
    session = _enable(_open())
    texts = (
        "最近工作压力有点大",
        "我很在意别人怎么看我",
        "一直在讨好别人，挺累的",
        "嗯",
        CALM,
        CALM,
    )
    results = _run(session, texts)
    assert any(r.inspect["schema_mirror"] == "asked" for r in results)
    assert all(r.inspect["externalize"] is None for r in results)


def test_rules_mode_never_offers_or_names():
    session = _open()
    results = _run(session, (*READY, CALM, "2", CRITIC, CALM, CRITIC))
    assert all(r.inspect["externalize"] is None for r in results)
    assert all(r.inspect["externalize_name"] is None for r in results)
    assert not any(_offer_in(r) or _named(r) for r in results)
    assert session.snapshot()["externalize"] is None


# -- the answer --------------------------------------------------------------------------------


@pytest.mark.parametrize("pick", [1, 2, 3])
def test_a_number_accepts_and_the_reply_acknowledges_the_name(pick):
    session, offer = _offered()
    result = session.turn(str(pick))
    name = offer.names[pick - 1]
    assert result.inspect["externalize"] == "accepted"
    assert result.inspect["externalize_name"] == name
    assert result.stage is HelpStage.S_CLARIFY and result.reply_kind is ReplyKind.NORMAL
    middle = result.reply.split("\n\n")[1]
    assert middle in {TEXT.fill(line, name) for line in TEXT.accepted}
    # The pick is not mirrored back ("你感到2").
    assert f"你感到{pick}" not in result.reply
    snapshot = session.snapshot()
    assert (snapshot["externalize"], snapshot["externalize_name"]) == ("accepted", name)


def test_a_name_accepts():
    session, offer = _offered()
    name = offer.names[-1]
    result = session.turn(f"{TEXT.names[name]}吧")
    assert result.inspect["externalize"] == "accepted"
    assert result.inspect["externalize_name"] == name


def test_a_no_declines_and_nothing_is_named_later():
    session, _ = _offered()
    result = session.turn("不用了")
    assert result.inspect["externalize"] == "declined"
    assert result.inspect["externalize_name"] is None
    assert result.reply.split("\n\n")[1] in TEXT.declined
    later = _run(session, (LOCK, CRITIC, CRITIC, CRITIC, CRITIC))
    assert not any(_named(r) for r in later)
    assert session.snapshot()["externalize"] == "declined"


def test_anything_else_is_no_answer_and_the_offer_lapses():
    session, _ = _offered()
    result = session.turn("今天的饭很好吃")
    assert result.inspect["externalize"] is None
    assert result.stage is HelpStage.S_CLARIFY and not _named(result)
    later = session.turn("2")
    assert later.inspect["externalize"] is None and later.inspect["externalize_name"] is None
    assert session.snapshot()["externalize"] == "offered"


def test_an_answer_on_a_crisis_turn_is_not_read():
    session, _ = _offered()
    result = session.turn("2，我不想活了")
    assert result.in_crisis and result.inspect["externalize"] is None
    assert result.inspect["externalize_name"] is None and not _named(result)


# -- using the name later ----------------------------------------------------------------------


def _accepted() -> tuple[Session, str]:
    session, offer = _offered()
    result = session.turn("1")
    assert result.inspect["externalize"] == "accepted"
    return session, TEXT.names[offer.names[0]]


def test_the_name_comes_back_with_the_pattern_at_most_once_every_three_turns():
    session, name = _accepted()
    # The lock keeps the session in S_clarify; a reflection is not a question.
    results = _run(session, (LOCK, CRITIC, CALM, CALM, CRITIC, CRITIC, CRITIC, CRITIC))
    assert all(r.stage is HelpStage.S_CLARIFY for r in results)
    turns = [i + 1 for i, r in enumerate(results) if f"「{name}」" in r.reply]
    # The acknowledgement was turn 0. Turn 2 is too soon; on turns 3 and 4 the gap has
    # passed but the pattern is not there; then turn 5 and, three turns on, turn 8.
    assert turns == [NAMING_GAP + 2, 2 * NAMING_GAP + 2]
    for i in turns:
        middle = results[i - 1].reply.split("\n\n")[1]
        assert middle in {line.replace("{name}", name) for line in TEXT.callbacks}
    assert all(r.inspect["externalize"] is None for r in results)


@pytest.mark.parametrize(
    "text,stage",
    [
        ("我不够好，我不想活了", HelpStage.S_CRISIS),
        ("[10%] 我不够好", HelpStage.S_HAVEN),
    ],
    ids=["crisis", "haven"],
)
def test_never_named_in_a_crisis_or_haven_reply(text, stage):
    session, _ = _accepted()
    _run(session, (LOCK, CALM, CALM))
    result = session.turn(text)
    assert result.stage is stage and not _named(result)


def test_never_named_on_a_card():
    session, _ = _accepted()
    results = _run(session, (CALM, CALM, CRITIC, CRITIC, CRITIC))
    cards = [r for r in results if r.reply_kind is ReplyKind.CARD]
    assert cards and not any(_named(r) for r in cards)
    assert all(not _named(r) for r in results if r.stage is HelpStage.S_EMPOWER)


def test_inspect_and_snapshot_hold_ids_only():
    session, _ = _accepted()
    results = _run(session, (LOCK, CRITIC, CRITIC, CRITIC))
    for result in results:
        assert result.inspect["externalize_name"] in TEXT.names
    snapshot = session.snapshot()
    assert snapshot["externalize_name"] in TEXT.names
    assert not any(name in str(snapshot) for name in ALL_NAMES)


# -- 特性四 golden dialogue with the real student ----------------------------------------------


def test_feature4_dialogue_in_model_mode():
    session = _open(student=True)
    script = (
        "最近工作压力有点大",
        "对自己要求太高了",  # UNRELENTING_STANDARDS
        "工作上一点错都不能有",  # S_clarify, with the Grade B lens
        "今天开会被领导点名了",  # the mirror
        CALM,  # no answer to it
        "我应该做得更好",  # the offer
        "第二个",  # accepted
        LOCK,
        "我不允许自己犯错",  # too soon to use the name
        "工作上一点错都不能有",  # the name comes back
    )
    results = _run(session, script)
    assert results[0].inspect["risk_model"] != "rules-only"
    assert all(r.inspect["assessed_level"] == "L0" for r in results)
    assert all(r.inspect["arousal"] < SOMATIC for r in results)
    assert [r.stage for r in results] == [HelpStage.S_EXPLORE] * 2 + [HelpStage.S_CLARIFY] * 8
    assert [r.inspect["schema_mirror"] for r in results][3] == "asked"
    assert [r.inspect["externalize"] for r in results] == [
        None, None, None, None, None, "offered", "accepted", None, None, None,
    ]  # fmt: skip
    offer = _offer_in(results[5])
    assert offer is not None and results[5].reply.split("\n\n")[-1] == offer.line
    chosen = offer.names[1]
    assert results[6].inspect["externalize_name"] == chosen
    name = TEXT.names[chosen]
    assert results[6].reply.split("\n\n")[1] in {TEXT.fill(t, chosen) for t in TEXT.accepted}
    named = [i for i, r in enumerate(results[6:], start=6) if f"「{name}」" in r.reply]
    assert named == [6, 9]
    assert results[9].reply.split("\n\n")[1] in {TEXT.fill(t, chosen) for t in TEXT.callbacks}
    assert all(r.inspect["gate"] == [] for r in results)
