"""The journal in the profile's persona voice (PRD Q-6) and its battery line (CHANG-04).

The four personas each have their own opening, bridge and closing pools, in the everyday
and the steadier (crisis-week) voice; the facts, the numbers and the line structure stay
the same. An old profile or an unknown persona reads as GENTLE_HOLDING. The battery line
counts the week's sessions that gave a ``[NN%]`` prefix and those where it was very low,
with last week's count beside it; without battery data there is no line.

Every test uses the in-memory keychain from conftest; nothing reaches the OS keychain.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from olivia.core.chang.journal import (
    LOW_BATTERY,
    WINDOW,
    Week,
    gather,
    is_due,
    load_journal_text,
    render_journal,
)
from olivia.core.crypto.vault import Vault
from olivia.core.memory.ledger import Ledger, MethodRecord, SessionSummary
from olivia.core.memory.text import load_memory_text
from olivia.core.methods.bandit import Feedback
from olivia.core.models import CrisisLevel, HelpStage, PersonaSpectrum
from olivia.core.taxonomy import load_taxonomy

SHANGHAI = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 25, 20, 30, tzinfo=SHANGHAI)
TEXT = load_journal_text()
MEMORY = load_memory_text()
TITLES = {"12:tipp_breathing": "冷水呼吸"}
PATH = (HelpStage.S_READY, HelpStage.S_EXPLORE, HelpStage.S_CLOSING)
COUNTS: dict[str, object] = {"turns": 5, "real_support_turns": 0, "late_night": False}


def _summary(days_ago: float, **overrides: object) -> SessionSummary:
    start = NOW - timedelta(days=days_ago)
    fields: dict[str, object] = {
        "started_at": start,
        "ended_at": start + timedelta(minutes=20),
        "stage_path": PATH,
        "spectra": ("05",),
        "methods": (MethodRecord("12:tipp_breathing", Feedback.HELPFUL),),
        "self_rating_before": 4,
        "self_rating_after": 6,
    }
    fields.update(overrides)
    return SessionSummary(**fields)  # type: ignore[arg-type]


def _battery(days_ago: float, low: float | None, *, haven: bool = False, **extra: object):
    return _summary(
        days_ago,
        **COUNTS,
        battery_prefix=low is not None,
        battery_min=low,
        haven=haven,
        **extra,
    )


def _week(*sessions: SessionSummary, previous: tuple[SessionSummary, ...] = ()) -> Week:
    return Week(NOW, sessions, 0, (), previous)


def _facts(card: str) -> list[str]:
    """The card's fact lines (the ``- `` items): what no voice may change."""
    return [line for line in card.splitlines() if line.startswith("- ")]


# -- persona voices ---------------------------------------------------------------------------


@pytest.mark.parametrize("persona", list(PersonaSpectrum))
@pytest.mark.parametrize("solemn", [False, True])
def test_each_persona_has_its_own_voice_around_the_same_facts(persona, solemn):
    level = CrisisLevel.L2 if solemn else None
    week = _week(_summary(3, crisis_level=level), _summary(1))
    card = render_journal(week, TEXT, MEMORY, TITLES, persona=persona).splitlines()
    voice = TEXT.voice(persona)
    intro, bridge, closing = (
        (voice.intro_solemn, voice.bridge_solemn, voice.closing_solemn)
        if solemn
        else (voice.intro, voice.bridge, voice.closing)
    )
    assert card[0] == TEXT.card["heading"]
    assert card[1] in intro and card[2] in bridge and card[-1] in closing
    gentle = render_journal(week, TEXT, MEMORY, TITLES, persona=PersonaSpectrum.GENTLE_HOLDING)
    assert _facts("\n".join(card)) == _facts(gentle)
    assert len(card) == len(gentle.splitlines())
    if solemn:
        assert "olivia resources" in card[-1]


def test_the_four_voices_differ_from_each_other():
    for solemn in (False, True):
        openings = set()
        for persona in PersonaSpectrum:
            voice = TEXT.voice(persona)
            pools = (
                (voice.intro_solemn, voice.closing_solemn)
                if solemn
                else (voice.intro, voice.closing)
            )
            openings.add(pools)
        assert len(openings) == len(PersonaSpectrum)


def test_every_steadier_closing_points_to_the_resources():
    for persona in PersonaSpectrum:
        for line in TEXT.voice(persona).closing_solemn:
            assert "olivia resources" in line, (persona, line)


def test_the_silent_anchor_says_the_least():
    silent = TEXT.voice(PersonaSpectrum.SILENT_ANCHOR)
    others = [TEXT.voice(p) for p in PersonaSpectrum if p is not PersonaSpectrum.SILENT_ANCHOR]
    for slot in ("intro", "bridge", "closing", "intro_solemn", "bridge_solemn", "closing_solemn"):
        own: tuple[str, ...] = getattr(silent, slot)
        assert len(own) == 1, slot
        for other in others:
            theirs: tuple[str, ...] = getattr(other, slot)
            assert len(own) <= len(theirs), slot
            assert max(map(len, own)) <= min(map(len, theirs)), slot


@pytest.mark.parametrize("persona", [None, "SOMETHING_NEW", ""])
def test_an_old_profile_or_unknown_persona_reads_as_gentle_holding(persona):
    week = _week(_summary(2), _summary(1))
    gentle = render_journal(week, TEXT, MEMORY, TITLES, persona=PersonaSpectrum.GENTLE_HOLDING)
    assert render_journal(week, TEXT, MEMORY, TITLES, persona=persona) == gentle
    assert render_journal(week, TEXT, MEMORY, TITLES) == gentle
    assert TEXT.voice(persona) == TEXT.voice(PersonaSpectrum.GENTLE_HOLDING)


def test_the_variant_is_stable_for_a_day_and_changes_between_weeks():
    voice = TEXT.voice(PersonaSpectrum.ZEN_PHILOSOPHER)
    assert len(voice.intro) >= 2
    zen = PersonaSpectrum.ZEN_PHILOSOPHER
    same_day = {
        render_journal(
            Week(NOW + timedelta(hours=h), (_summary(1),), 0, ()), TEXT, MEMORY, persona=zen
        )
        for h in (-1, 0, 1)
    }
    assert len(same_day) == 1
    seen = {
        render_journal(
            Week(NOW + timedelta(days=d), (_summary(1 - d),), 0, ()),
            TEXT,
            MEMORY,
            persona=PersonaSpectrum.ZEN_PHILOSOPHER,
        ).splitlines()[1]
        for d in range(len(voice.intro))
    }
    assert seen == set(voice.intro)


# -- the battery line -------------------------------------------------------------------------


def _battery_lines(card: str) -> list[str]:
    head = TEXT.card["battery_low"].split("{")[0]
    return [line for line in card.splitlines() if line.startswith(head)]


def test_the_threshold_is_the_haven_threshold():
    assert load_taxonomy().threshold("battery.thresholds.haven_enter") == LOW_BATTERY


def test_low_battery_sessions_are_counted_beside_last_week():
    week = _week(
        _battery(5, 0.1, haven=True),
        _battery(3, 0.5),
        _battery(1, LOW_BATTERY),
        _battery(0.5, None),  # said nothing about the battery this time
        _summary(0.2),  # an older summary: unknown
        previous=(_battery(9, 0.05, haven=True), _battery(8, 0.7)),
    )
    (line,) = _battery_lines(render_journal(week, TEXT, MEMORY, TITLES))
    expected = TEXT.card["battery_low"].format(known=3, count=2)
    assert line == expected + TEXT.card["battery_last_week"].format(count=1)


def test_no_low_battery_this_week_and_none_said_last_week():
    week = _week(_battery(2, 0.6), _battery(1, 0.45))
    (line,) = _battery_lines(render_journal(week, TEXT, MEMORY, TITLES))
    assert line == TEXT.card["battery_fine"].format(known=2)


def test_last_week_without_battery_data_is_left_out():
    week = _week(_battery(1, 0.15), previous=(_battery(9, None), _summary(10)))
    (line,) = _battery_lines(render_journal(week, TEXT, MEMORY, TITLES))
    assert line == TEXT.card["battery_low"].format(known=1, count=1)


@pytest.mark.parametrize(
    "sessions",
    [
        (_summary(2), _summary(1)),  # summaries from before the battery figures
        (_battery(2, None), _battery(1, None)),  # no prefix given all week
    ],
)
def test_no_battery_data_means_no_battery_line(sessions):
    week = _week(*sessions, previous=(_battery(9, 0.05, haven=True),))
    card = render_journal(week, TEXT, MEMORY, TITLES)
    assert _battery_lines(card) == []
    assert "电量" not in card


def test_the_battery_line_sits_after_the_ratings_in_every_voice():
    week = _week(_battery(2, 0.1, haven=True), _battery(1, 0.5))
    for persona in PersonaSpectrum:
        card = render_journal(week, TEXT, MEMORY, TITLES, persona=persona).splitlines()
        (line,) = _battery_lines("\n".join(card))
        rose = TEXT.card["rose"].format(count=2)
        assert card.index(line) == card.index(rose) + 1


def test_gather_splits_this_week_from_last_week(tmp_path, keychain):
    ledger = Ledger(tmp_path, Vault(tmp_path, keychain))
    for key, days in (("a", 1), ("b", 6.9), ("c", 7.5), ("d", 13.9), ("e", 15)):
        ledger.append_summary(_battery(days, 0.1), key=key)
    week = gather(ledger, NOW)
    assert [s.started_at for s in week.sessions] == [NOW - timedelta(days=6.9), NOW - timedelta(1)]
    assert [s.started_at for s in week.previous] == [
        NOW - timedelta(days=13.9),
        NOW - timedelta(days=7.5),
    ]
    assert all(s.started_at < NOW - WINDOW for s in week.previous)
    # Only this week's sessions count for the offer.
    assert is_due(week)
