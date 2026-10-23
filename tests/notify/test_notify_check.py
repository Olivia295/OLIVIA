"""``olivia notify-check``: when a reminder is due, what it says, and when nothing is sent
(next-phase B9; PRD SOP 5's Sunday 20:30 reminder, RSK-07).

The ledger uses the in-memory keychain from conftest and the notification goes to the
suite's :class:`FakeMachine`; nothing reaches the OS.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from olivia.core.chang.journal import Week
from olivia.core.chang.profile import ProfileStore
from olivia.core.crypto.errors import KeychainUnavailableError, NoKeychainError
from olivia.core.language.data import ContentKind, load_language_data
from olivia.core.language.filters import apply_willow
from olivia.core.language.gate import OutputGate
from olivia.core.memory.ledger import JournalEntry, Ledger, SessionSummary
from olivia.core.models import HelpStage, PersonaProfile, UserRegion
from olivia.core.taxonomy import load_taxonomy
from olivia.notify.check import (
    STATE_FILENAME,
    NotifyState,
    Reminder,
    decide,
    load_state,
    run_check,
    save_state,
)
from olivia.notify.system import RunResult
from olivia.notify.text import NotifyTextError, load_notify_text

SHANGHAI = ZoneInfo("Asia/Shanghai")
SUNDAY = datetime(2026, 10, 25, 20, 30, tzinfo=SHANGHAI)
SATURDAY = SUNDAY - timedelta(days=1)
LONG_AGO = SUNDAY - timedelta(days=60)
TEXT = load_notify_text()
PATH = (HelpStage.S_READY, HelpStage.S_CLOSING)


def _session(start: datetime) -> SessionSummary:
    return SessionSummary(start, start + timedelta(minutes=20), PATH, (), ())


def _week(now: datetime, *days_ago: float, journal: bool = False) -> Week:
    sessions = tuple(_session(now - timedelta(days=d)) for d in days_ago)
    journals = (JournalEntry("a" * 24, now - timedelta(days=1), shown=True),) if journal else ()
    return Week(until=now, sessions=sessions, notes=0, journals=journals)


# -- the decision ------------------------------------------------------------------------------


def test_journal_reminder_only_on_sunday():
    assert SUNDAY.weekday() == 6
    assert decide(SUNDAY, _week(SUNDAY, 1, 3), LONG_AGO, NotifyState()) is Reminder.JOURNAL
    assert decide(SATURDAY, _week(SATURDAY, 1, 3), LONG_AGO, NotifyState()) is None


def test_journal_reminder_follows_the_b6_due_rule():
    # One session is not enough; a journal already offered in the window settles it.
    assert decide(SUNDAY, _week(SUNDAY, 1), LONG_AGO, NotifyState()) is None
    assert decide(SUNDAY, _week(SUNDAY, 1, 3, journal=True), LONG_AGO, NotifyState()) is None


def test_journal_reminder_at_most_once_a_day():
    sent_today = NotifyState(journal=SUNDAY.date())
    assert decide(SUNDAY, _week(SUNDAY, 1, 3), LONG_AGO, sent_today) is None
    last_week = NotifyState(journal=SUNDAY.date() - timedelta(days=7))
    assert decide(SUNDAY, _week(SUNDAY, 1, 3), LONG_AGO, last_week) is Reminder.JOURNAL


def test_absence_after_seven_days_not_six():
    six = timedelta(days=6, hours=23, minutes=59)
    week = Week(until=SATURDAY, sessions=(_session(SATURDAY - six),), notes=0, journals=())
    assert decide(SATURDAY, week, LONG_AGO, NotifyState()) is None
    # A session exactly seven days ago is no longer "in the last seven days".
    week = Week(until=SATURDAY, sessions=(_session(SATURDAY - timedelta(7)),), notes=0, journals=())
    assert decide(SATURDAY, week, LONG_AGO, NotifyState()) is Reminder.ABSENCE
    assert decide(SATURDAY, _week(SATURDAY), LONG_AGO, NotifyState()) is Reminder.ABSENCE


def test_absence_counts_from_arrival_when_there_is_no_session():
    arrived = SATURDAY - timedelta(days=6)
    assert decide(SATURDAY, _week(SATURDAY), arrived, NotifyState()) is None
    arrived = SATURDAY - timedelta(days=7)
    assert decide(SATURDAY, _week(SATURDAY), arrived, NotifyState()) is Reminder.ABSENCE


def test_absence_at_most_once_per_seven_days():
    today = SATURDAY.date()
    for days, expected in ((0, None), (6, None), (7, Reminder.ABSENCE), (30, Reminder.ABSENCE)):
        state = NotifyState(absence=today - timedelta(days=days))
        assert decide(SATURDAY, _week(SATURDAY), LONG_AGO, state) is expected, days


# -- the texts ---------------------------------------------------------------------------------


def test_notifications_are_content_free():
    # No name at all: neither the default address nor anything a user could choose
    # ("olivia chat" is the command, not the companion's name).
    profile_names = {"朋友", "小林", "阿青"}
    for key in ("journal", "absence"):
        body = TEXT.notifications[key]
        assert not re.search(r"\d", body), body
        assert not re.search(r"[{}]", body), body
        assert not any(name.casefold() in body.casefold() for name in profile_names), body
        assert "！" not in body and "!" not in body
    assert TEXT.notifications["title"] == "OLIVIA"
    assert TEXT.notifications["journal"] == "这周的小结写好了，想看的时候运行 olivia chat。"
    assert TEXT.notifications["absence"] == "很久没聊了，想说说话的时候我都在。"


def test_texts_pass_willow_and_the_output_gate():
    tax = load_taxonomy()
    data = load_language_data(tax)
    gate = OutputGate(tax, data)
    for text in TEXT.all_texts():
        assert apply_willow(text, ContentKind.NORMAL, data.willow) == text, text
        assert gate.reasons(text, kind=ContentKind.NORMAL, stage=HelpStage.S_EXPLORE) == (), text
        assert "！" not in text and "!" not in text


def test_text_file_is_a_g0_draft_and_validated(tmp_path):
    source = Path(__file__).resolve().parents[2] / "olivia/data/templates/notify.yaml"
    raw = source.read_text(encoding="utf-8")
    assert raw.splitlines()[0].startswith("# 草稿：待 G-0")
    (tmp_path / "notify.yaml").write_text(
        raw.replace("absence: 很久没聊了", "absence: {user_name}很久没聊了"), encoding="utf-8"
    )
    with pytest.raises(NotifyTextError):
        load_notify_text(tmp_path)
    (tmp_path / "notify.yaml").write_text(
        raw.replace("很久没聊了，想说说话的时候我都在。", '"{state}"'), encoding="utf-8"
    )
    with pytest.raises(NotifyTextError, match="content-free"):
        load_notify_text(tmp_path)
    (tmp_path / "notify.yaml").write_text("version: 2\n", encoding="utf-8")
    with pytest.raises(NotifyTextError):
        load_notify_text(tmp_path)


# -- the state file ----------------------------------------------------------------------------


def test_state_file_holds_two_dates_and_nothing_else(tmp_path):
    assert load_state(tmp_path) == NotifyState()
    save_state(tmp_path, NotifyState(journal=date(2026, 10, 25)))
    data = json.loads((tmp_path / STATE_FILENAME).read_text(encoding="utf-8"))
    assert data == {"version": 1, "journal": "2026-10-25", "absence": None}
    assert load_state(tmp_path) == NotifyState(journal=date(2026, 10, 25))
    for damaged in ("not json", "[]", '{"version": 1, "journal": "yesterday"}'):
        (tmp_path / STATE_FILENAME).write_text(damaged, encoding="utf-8")
        assert load_state(tmp_path).journal is None


# -- the whole check ---------------------------------------------------------------------------


@pytest.fixture
def base(tmp_path: Path) -> Path:
    return tmp_path / "data"


def _profile(base: Path, **overrides: object) -> PersonaProfile:
    fields: dict[str, object] = {
        "age_confirmed_18_plus": True,
        "created_at": LONG_AGO,
        "updated_at": LONG_AGO,
        "user_name": "小林",
        "region": UserRegion("CN", "Asia/Shanghai"),
        "notifications": True,
    }
    fields.update(overrides)
    profile = PersonaProfile(**fields)  # type: ignore[arg-type]
    ProfileStore(base).save(profile)
    return profile


def _sessions(base: Path, *days_ago: float) -> None:
    store = ProfileStore(base)
    ledger = Ledger(base, store.vault)
    for i, days in enumerate(days_ago):
        ledger.append_summary(_session(SUNDAY - timedelta(days=days)), key=f"s{i}")


def _bodies(machine) -> list[str]:
    return [argv[-1] for argv in machine.argvs]


def test_sunday_journal_reminder_is_sent_once(base, machine):
    _profile(base)
    _sessions(base, 1, 3)
    # The clock may be in UTC: the day is the profile's (Sunday 20:30 in Shanghai).
    now = SUNDAY.astimezone(ZoneInfo("UTC"))
    assert run_check(machine.host(), base, now) is Reminder.JOURNAL
    assert _bodies(machine) == [TEXT.notifications["journal"]]
    assert machine.argvs[0][0] == "osascript" and machine.argvs[0][-2] == "OLIVIA"
    assert run_check(machine.host(), base, now + timedelta(minutes=5)) is None
    assert len(machine.calls) == 1


def test_absence_reminder_is_sent_then_waits_seven_days(base, machine):
    _profile(base)
    _sessions(base, 9)
    assert run_check(machine.host(), base, SATURDAY) is Reminder.ABSENCE
    assert _bodies(machine) == [TEXT.notifications["absence"]]
    for day in range(1, 7):
        assert run_check(machine.host(), base, SATURDAY + timedelta(days=day)) is None
    assert run_check(machine.host(), base, SATURDAY + timedelta(days=7)) is Reminder.ABSENCE
    assert len(machine.calls) == 2


def test_nothing_is_sent_while_off_by_default(base, machine):
    profile = _profile(base, notifications=False)
    assert (
        PersonaProfile.from_dict(
            {k: v for k, v in profile.to_dict().items() if k != "notifications"}
        ).notifications
        is False
    )
    _sessions(base, 9)
    assert run_check(machine.host(), base, SATURDAY) is None
    assert machine.calls == []


def test_nothing_is_sent_without_a_profile(base, machine):
    assert run_check(machine.host(), base, SATURDAY) is None
    assert machine.calls == []


@pytest.mark.parametrize("broken", [KeychainUnavailableError("locked"), NoKeychainError("none")])
def test_a_locked_or_missing_keychain_sends_nothing(base, machine, keychain, broken):
    _profile(base)
    _sessions(base, 9)
    keychain.broken = broken
    assert run_check(machine.host(), base, SATURDAY) is None
    assert machine.calls == []
    assert not (base / STATE_FILENAME).exists()


def test_a_whole_encrypted_profile_that_is_locked_sends_nothing(base, machine, keychain):
    _profile(base, enable_at_rest_encryption=True)
    keychain.broken = KeychainUnavailableError("locked")
    assert run_check(machine.host(), base, SATURDAY) is None
    assert machine.calls == []


def test_a_failed_notification_is_not_remembered(base, machine):
    _profile(base)
    machine.results[("osascript",)] = RunResult(1)
    assert run_check(machine.host(), base, SATURDAY) is None
    assert not (base / STATE_FILENAME).exists()
    machine.results.clear()
    assert run_check(machine.host(), base, SATURDAY) is Reminder.ABSENCE


def test_profile_setting_round_trips_and_a_refusal_record_cannot_hold_it():
    adult = PersonaProfile(True, LONG_AGO, LONG_AGO, notifications=True)
    assert PersonaProfile.from_dict(adult.to_dict()).notifications is True
    assert PersonaProfile(True, LONG_AGO, LONG_AGO).notifications is False
    with pytest.raises(ValueError):
        PersonaProfile(False, LONG_AGO, LONG_AGO, age_gate_refused_at=LONG_AGO, notifications=True)
