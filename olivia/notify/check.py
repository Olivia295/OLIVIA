"""``olivia notify-check``: what the scheduled job runs each evening (next-phase B9).

It sends at most one notification, and only when every one of these holds: the profile
can be read, belongs to an adult and has ``notifications`` on, and the keychain answers so
the ledger can be read (locked or absent: nothing is sent). Then, in the profile's time
zone:

* :attr:`Reminder.JOURNAL` -- on a Sunday, when B6's due rule holds
  (``chang/journal.is_due``: at least two sessions in the last seven days and no journal
  offered in them), at most once that day;
* :attr:`Reminder.ABSENCE` -- when no session started in the last seven days (counting
  from the profile's creation when there is none), at most once per seven days;
* nothing else.

The texts (``notify.yaml``) say nothing about the conversations. "Last notified" lives in
:data:`STATE_FILENAME` in the data directory: two dates and nothing else, written without
snapshots. It is a file of its own rather than part of B3's encrypted state because a
chat running at 20:30 keeps that state in memory and saves it on every turn, which would
overwrite (or race) the job's write; this file holds no user data, so it needs no key.
Turning reminders off and ``olivia forget --all`` delete it.
"""

from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from olivia.core.chang.journal import WINDOW, Week, gather, is_due
from olivia.core.chang.profile import ProfileCorruptError, ProfileLockedError, ProfileStore
from olivia.core.memory.ledger import Ledger, LedgerUnavailableError
from olivia.core.models import PersonaProfile
from olivia.core.storage import atomic_write_bytes, remove_file
from olivia.notify.jobs import send
from olivia.notify.system import Host
from olivia.notify.text import NotifyText, load_notify_text

STATE_FILENAME: Final = "notify.json"
ABSENCE_EVERY_DAYS: Final = 7
SUNDAY: Final = 6


class Reminder(StrEnum):
    JOURNAL = "journal"
    ABSENCE = "absence"


@dataclass(frozen=True)
class NotifyState:
    """The local dates the last reminders were sent (None: never)."""

    journal: date | None = None
    absence: date | None = None


def state_path(base: Path) -> Path:
    return base / STATE_FILENAME


def _date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def load_state(base: Path) -> NotifyState:
    """The saved dates; a missing or damaged file reads as "never" (at worst one extra
    reminder, never a lost one)."""
    try:
        data = json.loads(state_path(base).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return NotifyState()
    if not isinstance(data, dict) or data.get("version") != 1:
        return NotifyState()
    return NotifyState(_date(data.get("journal")), _date(data.get("absence")))


def save_state(base: Path, state: NotifyState) -> None:
    data = {
        "version": 1,
        "journal": state.journal.isoformat() if state.journal else None,
        "absence": state.absence.isoformat() if state.absence else None,
    }
    atomic_write_bytes(state_path(base), json.dumps(data).encode("utf-8"), snapshot=False)


def clear_state(base: Path) -> None:
    remove_file(state_path(base))


def decide(now: datetime, week: Week, since: datetime, state: NotifyState) -> Reminder | None:
    """The reminder due at ``now`` (local time), if any.

    ``week`` is the ledger's last seven days (``journal.gather``); ``since`` is when the
    user arrived (the profile's creation), the start of the absence count.
    """
    today = now.date()
    if now.weekday() == SUNDAY and is_due(week) and state.journal != today:
        return Reminder.JOURNAL
    start = now - WINDOW
    recent = any(s.started_at > start for s in week.sessions) or since > start
    if recent:
        return None
    if state.absence is not None and (today - state.absence).days < ABSENCE_EVERY_DAYS:
        return None
    return Reminder.ABSENCE


def _local(now: datetime, profile: PersonaProfile) -> datetime:
    if profile.region is None:
        return now
    try:
        return now.astimezone(ZoneInfo(profile.region.timezone))
    except (ZoneInfoNotFoundError, ValueError):
        return now


def run_check(
    host: Host, base: Path, now: datetime, *, text: NotifyText | None = None
) -> Reminder | None:
    """Decide and send; the reminder sent, or None. Never prints and never raises for
    an unreadable profile, a locked keychain or a failed notification."""
    store = ProfileStore(base)
    try:
        profile = store.load()
    except (ProfileCorruptError, ProfileLockedError):
        return None
    if profile is None or profile.is_age_gate_refusal or not profile.notifications:
        return None
    ledger = Ledger(base, store.vault)
    local = _local(now, profile)
    try:
        if not ledger.available():
            return None
        week = gather(ledger, local)
    except LedgerUnavailableError:
        return None
    state = load_state(base)
    reminder = decide(local, week, profile.created_at, state)
    if reminder is None:
        return None
    words = load_notify_text() if text is None else text
    if not send(host, words.notifications["title"], words.notifications[reminder.value]):
        return None
    today = local.date()
    if reminder is Reminder.JOURNAL:
        sent = NotifyState(journal=today, absence=state.absence)
    else:
        sent = NotifyState(journal=state.journal, absence=today)
    with contextlib.suppress(OSError):  # unsaved: at worst the same reminder once more
        save_state(base, sent)
    return reminder
