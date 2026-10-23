"""Cross-session state in the session: posteriors and the kit carried in (B3)."""

from __future__ import annotations

import json
import random
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from olivia.core.memory.state import KIT_MAX, CarriedState, KitEntry
from olivia.core.methods.bandit import ThompsonSampler
from olivia.core.models import HelpStage, PersonaProfile, UserRegion
from olivia.core.session import ReplyKind, Session
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
NOW = datetime(2026, 10, 22, 23, 30, tzinfo=UTC)
LATER = NOW + timedelta(days=1)
REQUEST = "给我一个方法"
# High arousal: exploit-only, so the highest posterior mean wins (no sampling noise).
HIGH = "心慌得要命，喘不上气，直接给我一个方法"
CARDIO = "CARDIORESPIRATORY_INSTABILITY"


def _open(
    seed: int = 7,
    carried: CarriedState | None = None,
    now: datetime = NOW,
    **overrides: object,
) -> Session:
    profile = PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        user_name="小林",
        region=UserRegion("CN", "Asia/Shanghai"),
    )
    return Session.open(
        TAX,
        replace(profile, **overrides),
        rng=random.Random(seed),
        now=lambda: now,
        carried=carried,
    )


def _blocked(enum_id: str) -> set[str]:
    methods, registry = TAX.methods(), TAX.action_registry()
    return {m for m, v in methods.items() if enum_id in v.contraindications} | {
        a for a, v in registry.items() if enum_id in v.contraindications
    }


def _shelved_in_a_session(seed: int = 7) -> tuple[str, CarriedState]:
    session = _open(seed)
    shown = session.turn(REQUEST).action_id
    assert shown is not None
    session.turn("今天先不做了")
    return shown, session.carried_state()


# -- the sampler -----------------------------------------------------------------------------


def test_second_session_choice_reflects_the_first_sessions_feedback():
    first = _open()
    shown = first.turn(HIGH)
    assert shown.reply_kind is ReplyKind.CARD and shown.action_id is not None
    spectrum = shown.inspect["spectrum"]
    assert isinstance(spectrum, str)
    first.turn("/unhelpful")
    carried = first.carried_state()
    assert carried.bandit == first.snapshot()["bandit"]

    fresh = _open(now=LATER)
    second = _open(carried=carried, now=LATER)
    prior = fresh._sampler.posterior(shown.action_id, spectrum, LATER)  # noqa: SLF001
    moved = second._sampler.posterior(shown.action_id, spectrum, LATER)  # noqa: SLF001
    assert moved[0] == prior[0] and moved[1] > prior[1]  # the penalty came along, decaying

    # Same seed, same words: a fresh session shows the same card again, the carried one not.
    assert fresh.turn(HIGH).action_id == shown.action_id
    again = second.turn(HIGH)
    assert again.reply_kind is ReplyKind.CARD and again.action_id != shown.action_id


def test_helpful_feedback_is_carried_too():
    first = _open()
    shown = first.turn(REQUEST)
    first.turn("/done")
    spectrum = shown.inspect["spectrum"] or "02"  # no cue: the low-mood fallback
    assert isinstance(shown.action_id, str) and isinstance(spectrum, str)
    second = _open(carried=first.carried_state())
    a_before, _ = ThompsonSampler(TAX).posterior(shown.action_id, spectrum, NOW)
    a_after, _ = second._sampler.posterior(shown.action_id, spectrum, NOW)  # noqa: SLF001
    assert a_after == a_before + 1.0


def test_without_carried_state_the_session_starts_from_the_priors():
    session = _open()
    assert session.carried_state() == CarriedState(ThompsonSampler(TAX).to_dict(), ())
    assert session.kit() == ()


def test_carried_state_is_json_and_holds_no_text():
    session = _open()
    session.turn("我想起我奶奶了，给我一个方法")
    session.turn("今天先不做了")
    document = json.dumps(session.carried_state().to_dict(), ensure_ascii=False)
    for needle in ("奶奶", "小林", "今天先不做"):
        assert needle not in document


# -- the kit ---------------------------------------------------------------------------------


@pytest.mark.parametrize("recall", ["上次存的那个再给我看看", "锦囊里那个再给我看看"])
def test_kit_recall_in_a_new_session(recall):
    shown, carried = _shelved_in_a_session()
    assert [e.action_id for e in carried.kit] == [shown]
    assert carried.kit[0].shelved_at == NOW
    session = _open(seed=3, carried=carried, now=LATER)
    assert [e.action_id for e in session.kit()] == [shown]
    result = session.turn(recall)
    assert result.stage is HelpStage.S_EMPOWER and result.reply_kind is ReplyKind.CARD
    assert result.action_id == shown
    # Shown again, it leaves the kit; /not-now puts it back with the new time.
    assert session.kit() == ()
    session.turn("/not-now")
    assert session.kit() == (KitEntry(shown, LATER),)


def test_recall_shows_the_most_recent_kit_card_first():
    older = KitEntry("01", NOW - timedelta(days=2))
    newer = KitEntry("44", NOW - timedelta(days=1))
    session = _open(carried=CarriedState(ThompsonSampler(TAX).to_dict(), (older, newer)))
    result = session.turn("上次存的那个再给我看看")
    assert result.action_id == "44"
    assert session.kit() == (older,)


def test_this_sessions_shelves_come_after_the_carried_kit():
    shown, carried = _shelved_in_a_session()
    session = _open(seed=11, carried=carried, now=LATER)
    new = session.turn(REQUEST).action_id
    assert new is not None
    session.turn("/not-now")
    if new == shown:  # the carried card was sampled again and shelved again
        assert session.kit() == (KitEntry(shown, LATER),)
    else:
        assert session.kit() == (KitEntry(shown, NOW), KitEntry(new, LATER))
    assert session.carried_state().kit == session.kit()


def test_carried_kit_is_not_masked_from_sampling():
    _, carried = _shelved_in_a_session()
    session = _open(carried=carried)
    result = session.turn(REQUEST)
    assert carried.kit[0].action_id in result.inspect["candidates"]


def test_kit_is_capped_with_the_newest_kept():
    entries = tuple(KitEntry(f"{n:02d}", NOW + timedelta(minutes=n)) for n in range(1, 13))
    session = _open(carried=CarriedState(ThompsonSampler(TAX).to_dict(), entries))
    assert session.carried_state().kit == entries[-KIT_MAX:]


def test_contraindicated_or_missing_kit_entries_are_skipped():
    blocked = sorted(_blocked(CARDIO) & {"12:tipp_breathing", "29", "29:pmr_release", "30"})
    assert blocked, "the taxonomy no longer blocks any breathing or relaxation action"
    kit = (
        KitEntry("44", NOW - timedelta(days=3)),
        KitEntry(blocked[0], NOW - timedelta(days=2)),
        KitEntry("12:tipp_cold_water", NOW - timedelta(days=1)),  # not in the deck
    )
    carried = CarriedState(ThompsonSampler(TAX).to_dict(), kit)
    session = _open(carried=carried, contraindications=(CARDIO,))
    result = session.turn("锦囊里那个再给我看看")
    assert result.action_id == "44"
    assert [e.action_id for e in session.kit()] == [blocked[0], "12:tipp_cold_water"]


def test_recall_with_only_unusable_entries_samples_and_keeps_them():
    kit = (KitEntry("12:tipp_cold_water", NOW - timedelta(days=1)),)
    session = _open(carried=CarriedState(ThompsonSampler(TAX).to_dict(), kit))
    result = session.turn("上次存的那个再给我看看")
    assert result.stage is HelpStage.S_EMPOWER
    assert result.action_id != "12:tipp_cold_water"
    assert session.kit() == kit


def test_recall_in_a_crisis_is_crisis_and_keeps_the_kit():
    _, carried = _shelved_in_a_session()
    session = _open(carried=carried)
    result = session.turn("上次存的那个再给我看看，反正我不想活了")
    assert result.stage is HelpStage.S_CRISIS and result.action_id is None
    assert session.kit() == carried.kit


def test_an_unknown_kit_id_or_arm_never_breaks_a_session():
    bandit = {"spectra": {"05": {"99:gone": {"alpha": 1, "beta": 1, "last_unhelpful_at": None}}}}
    kit = (KitEntry("99:gone", NOW),)
    session = _open(carried=CarriedState(bandit, kit))
    assert session.turn("锦囊里那个再给我看看").stage is HelpStage.S_EMPOWER
    assert session.carried_state().bandit == ThompsonSampler(TAX).to_dict()
