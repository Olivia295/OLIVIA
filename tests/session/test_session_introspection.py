"""Introspection in the session (decision D4, step C2; PRD 特性三 / MIYI-03, C_2).

* Both modes: distortions, schemas and the yearning fill the perception context and
  ``inspect``; the yearning picks the metaphor (spectrum x yearning) and the need phrase.
* Model mode only: once per session, an S_clarify reply ends with a gentle question that
  mirrors the belief behind the schema seen most; never at high arousal, in a crisis, in
  S_haven, on an L1 screen, with a red flag active or under the listening lock. A yes on
  the next turn is the C_2 "核心信念识别" and moves to S_empower.

The gating tests switch the mirror on in a rules session (``_enable_mirror``) so the
rule stub's perception, not the student's, decides arousal and risk; the MIYI-03 dialogue
at the end runs the real student.
"""

from __future__ import annotations

import random
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from olivia.core.fsm import Reason
from olivia.core.language.data import load_language_data
from olivia.core.models import HelpStage, PersonaProfile, UserRegion
from olivia.core.perception.introspector import load_mirror_lines
from olivia.core.session import ReplyKind, Session, TurnResult
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
LANG = load_language_data(TAX)
LINES = load_mirror_lines(TAX)
ALL_LINES = frozenset(line for lines in LINES.values() for line in lines)
NOW = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)
# Two S_explore turns, then S_clarify; APPROVAL_SEEKING is seen on turns 2 and 3,
# SUBJUGATION on turn 4. Every turn screens L0 in both modes.
TO_CLARIFY = (
    "最近工作压力有点大",
    "我很在意别人怎么看我",
    "一直在讨好别人，挺累的",
)
MORE_SCHEMA = "我的意见不重要，总是顺着别人"


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


def _enable_mirror(session: Session) -> Session:
    """Model mode's mirror over rule perception (deterministic gating tests)."""
    session._mirror.enabled = True
    return session


def _mirrored(result: TurnResult) -> bool:
    return any(line in result.reply for line in ALL_LINES)


def _run(session: Session, texts: tuple[str, ...]) -> list[TurnResult]:
    return [session.turn(text) for text in texts]


def _asked(results: list[TurnResult]) -> list[int]:
    return [i for i, r in enumerate(results) if r.inspect["schema_mirror"] == "asked"]


def _to_mirror(session: Session) -> list[TurnResult]:
    """Reach S_clarify and keep talking until the mirror asks (the lens may come first)."""
    results = _run(session, TO_CLARIFY)
    for _ in range(3):
        if _asked(results):
            break
        results.append(session.turn(MORE_SCHEMA))
    assert _asked(results), [r.inspect["stage"] for r in results]
    return results


# -- both modes: the fields ------------------------------------------------------------------


@pytest.mark.parametrize("student", [False, True], ids=["rules", "model"])
def test_inspect_carries_introspection_ids(student):
    result = _open(student=student).turn("都是我的错，我一无是处")
    data = result.inspect
    assert data["distortions"] == ["PERSONALIZATION"]
    assert data["schemas"] == ["DEFECTIVENESS"]
    assert data["yearning"] == "ACCEPTANCE"
    assert data["schema_mirror"] is None


def test_yearning_picks_the_metaphor_and_need():
    # S_explore weaves {metaphor} from the spectrum x yearning cell (WILLOW-02).
    session = _open()
    result = session.turn("和男朋友总吵架，其实就是想有人懂我")
    spectrum = result.inspect["spectrum"]
    assert isinstance(spectrum, str) and result.inspect["yearning"] == "CONNECTION"
    cell = LANG.metaphors.by_spectrum_yearning[spectrum]["CONNECTION"]
    assert any(image in result.reply for image in cell)


def test_without_evidence_the_yearning_stays_the_default():
    result = _open().turn("今天上班好累")
    assert result.inspect["yearning"] == TAX.values("satir_yearnings")[0]
    assert result.inspect["distortions"] == [] and result.inspect["schemas"] == []


# -- rules mode never mirrors (ruling 25) ----------------------------------------------------


def test_rules_mode_never_mirrors_and_c2_is_unchanged():
    session = _open()
    results = _run(session, (*TO_CLARIFY, MORE_SCHEMA, "对", MORE_SCHEMA, "是的"))
    assert results[1].inspect["schemas"] == ["APPROVAL_SEEKING"]
    assert all(r.inspect["schema_mirror"] is None for r in results)
    assert not any(_mirrored(r) for r in results)
    assert all(r.inspect["reason"] != Reason.CLARIFY_CORE_BELIEF.value for r in results)
    assert results[4].stage is HelpStage.S_CLARIFY
    assert session.snapshot()["schema_mirror"] is None


# -- model mode: the question and its answer -------------------------------------------------


def test_mirror_replaces_the_closing_question_of_an_s_clarify_reply():
    session = _enable_mirror(_open())
    results = _to_mirror(session)
    (index,) = _asked(results)
    asked = results[index]
    assert asked.stage is HelpStage.S_CLARIFY and asked.reply_kind is ReplyKind.NORMAL
    paragraphs = asked.reply.split("\n\n")
    assert len(paragraphs) == 3
    # The schema seen on the most calm turns.
    assert paragraphs[-1] in LINES["APPROVAL_SEEKING"]
    assert asked.inspect["gate"] == []


def test_mirror_is_asked_at_most_once_per_session():
    session = _enable_mirror(_open())
    results = _to_mirror(session)
    results += _run(session, ("没有", MORE_SCHEMA, "我一无是处", MORE_SCHEMA))
    assert len(_asked(results)) == 1
    assert sum(_mirrored(r) for r in results) == 1


def test_yes_is_the_c2_core_belief_and_opens_s_empower():
    session = _enable_mirror(_open())
    _to_mirror(session)
    result = session.turn("是的，一直都是这样")
    assert result.inspect["schema_mirror"] == "confirmed"
    assert result.stage is HelpStage.S_EMPOWER
    assert result.inspect["reason"] == Reason.CLARIFY_CORE_BELIEF.value
    assert result.reply_kind is ReplyKind.CARD
    assert session.snapshot()["schema_mirror"] == "confirmed"


def test_no_leaves_the_flow_as_it_was():
    session = _enable_mirror(_open())
    _to_mirror(session)
    result = session.turn("没有")
    assert result.inspect["schema_mirror"] == "declined"
    assert result.stage is HelpStage.S_CLARIFY and result.inspect["reason"] == "STAY"


def test_an_unclear_reply_is_no_answer():
    session = _enable_mirror(_open())
    _to_mirror(session)
    result = session.turn("今天外面下雨了")
    assert result.inspect["schema_mirror"] is None
    assert result.stage is HelpStage.S_CLARIFY
    # The question waited one turn only: a later yes is just a yes.
    later = session.turn("是的")
    assert later.inspect["schema_mirror"] is None and later.stage is HelpStage.S_CLARIFY


def test_a_yes_on_a_crisis_turn_is_not_read():
    session = _enable_mirror(_open())
    _to_mirror(session)
    result = session.turn("是的，我不想活了")
    assert result.in_crisis and result.inspect["schema_mirror"] is None
    assert result.inspect["reason"] != Reason.CLARIFY_CORE_BELIEF.value


# -- model mode: gating ----------------------------------------------------------------------


def _clarify_then_enable() -> Session:
    """S_clarify with schema evidence and the mirror still off, then switched on: the next
    turn is the first one on which it could ask."""
    session = _open()
    results = _run(session, TO_CLARIFY)
    assert results[-1].stage is HelpStage.S_CLARIFY and not _asked(results)
    return _enable_mirror(session)


def test_never_at_high_arousal():
    session = _clarify_then_enable()
    for i in range(3):
        hot = session.turn("心慌得要命，手一直在抖，我很在意别人怎么看我")
        # Fix F2a: the first hot turn leaves S_clarify for S_explore's stabilization channel.
        assert hot.stage is HelpStage.S_EXPLORE
        if i == 0:
            assert hot.inspect["reason"] == "CLARIFY_AROUSAL_RETREAT"
        assert hot.inspect["arousal"] >= TAX.threshold("arousal.thresholds.somatic_priority")
        assert hot.inspect["schema_mirror"] is None and not _mirrored(hot)
    # Calm again: back in S_clarify it may ask.
    calm = session.turn("今天外面下雨了")
    assert calm.stage is HelpStage.S_CLARIFY
    assert calm.inspect["schema_mirror"] == "asked"


def test_evidence_from_high_arousal_turns_does_not_count():
    session = _open()
    _run(session, ("最近工作压力有点大", "心慌得要命，手一直在抖，我很在意别人怎么看我"))
    _enable_mirror(session)
    results = _run(session, ("今天开了一整天会，有点累", "嗯，还好", "就是有点累"))
    assert results[0].stage is HelpStage.S_CLARIFY
    assert all(r.inspect["schema_mirror"] is None for r in results)


@pytest.mark.parametrize(
    "text,stage",
    [
        ("我想消失，我的意见不重要，总是顺着别人", HelpStage.S_CLARIFY),  # L1 screen
        ("[10%] 我的意见不重要，总是顺着别人", HelpStage.S_HAVEN),
        ("我不想活了，我的意见不重要", HelpStage.S_CRISIS),
        ("你听我说就好，不用给建议，我的意见不重要", HelpStage.S_CLARIFY),  # listening lock
    ],
)
def test_never_on_a_risky_or_resting_turn(text, stage):
    session = _clarify_then_enable()
    result = session.turn(text)
    assert result.stage is stage
    assert result.inspect["schema_mirror"] is None and not _mirrored(result)


def test_an_l1_turn_only_postpones_the_mirror():
    session = _clarify_then_enable()
    assert session.turn("我想消失").inspect["schema_mirror"] is None
    assert session.turn("今天外面下雨了").inspect["schema_mirror"] == "asked"


def test_never_while_a_red_flag_is_active():
    session = _enable_mirror(_open(clinical_history=("SIT-02-06",)))
    results = _run(session, (*TO_CLARIFY, MORE_SCHEMA, MORE_SCHEMA, MORE_SCHEMA))
    assert any(r.stage is HelpStage.S_CLARIFY for r in results)
    assert not _asked(results) and not any(_mirrored(r) for r in results)


def test_inspect_and_snapshot_hold_no_text():
    session = _enable_mirror(_open())
    results = _to_mirror(session)
    for result in results:
        for key in ("distortions", "schemas"):
            value = result.inspect[key]
            assert isinstance(value, list)
            assert all(
                item in TAX.values("cognitive_distortions") + TAX.values("schemas")
                for item in value
            )
    snapshot = session.snapshot()
    assert snapshot["schema_mirror"] == "asked"
    assert not any("别人" in str(v) for v in snapshot.values())


# -- MIYI-03 golden dialogue with the real student ------------------------------------------


def test_miyi03_dialogue_in_model_mode():
    session = _open(student=True)
    assert session.turn(TO_CLARIFY[0]).inspect["risk_model"] != "rules-only"
    results = [session.turn(text) for text in (*TO_CLARIFY[1:], MORE_SCHEMA)]
    assert [r.stage for r in results] == [
        HelpStage.S_EXPLORE,
        HelpStage.S_CLARIFY,
        HelpStage.S_CLARIFY,
    ]
    asked = results[-1]
    assert asked.inspect["schema_mirror"] == "asked"
    assert asked.inspect["arousal"] < TAX.threshold("arousal.thresholds.somatic_priority")
    assert asked.reply.split("\n\n")[-1] in LINES["APPROVAL_SEEKING"]
    confirmed = session.turn("对")
    assert confirmed.inspect["schema_mirror"] == "confirmed"
    assert confirmed.stage is HelpStage.S_EMPOWER
    assert confirmed.inspect["reason"] == Reason.CLARIFY_CORE_BELIEF.value
