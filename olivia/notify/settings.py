"""``olivia settings``: a numbered menu of switches (next-phase B9, decision D5).

For now it holds one item, the system reminders (``PersonaProfile.notifications``, off by
default). Turning them on first says what will be installed and where (one scheduled
job, :mod:`olivia.notify.jobs`) and that turning them off removes it, then asks once
more; the profile is saved only after the job is installed, and a failed save removes
the job again. Turning them off removes the job and the "last notified" file, then saves.
Opening the menu runs nothing on the system: only a confirmed change does.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Final

from olivia.core.models import PersonaProfile
from olivia.notify.check import clear_state
from olivia.notify.jobs import Mechanism, Unsupported, choose, install, uninstall, where
from olivia.notify.system import Host
from olivia.notify.text import NotifyText, fill, load_notify_text

Ask = Callable[[], str | None]
Say = Callable[[str], None]
Save = Callable[[PersonaProfile], bool]
"""Save the profile; False when it could not be saved (the caller has said why)."""

NOTIFICATIONS_ITEM: Final = "1"
CONFIRM_YES: Final = "1"


def _fold(answer: str | None) -> str:
    return unicodedata.normalize("NFKC", answer or "").strip()


def run_settings(
    ask: Ask,
    say: Say,
    profile: PersonaProfile,
    *,
    save: Save,
    host: Callable[[], Host],
    base: Path,
    keychain_ok: Callable[[], bool],
    now: datetime,
    text: NotifyText | None = None,
) -> int:
    """The menu for an adult's ``profile``; the exit status. ``host`` is only called once a
    change is chosen; ``base`` is the data directory (for the "last notified" file)."""
    words = load_notify_text() if text is None else text
    s = words.settings
    state = s["state_on"] if profile.notifications else s["state_off"]
    say(s["heading"])
    say(f"  {NOTIFICATIONS_ITEM}. {fill(s['notifications_item'], state=state)}")
    choice = _fold(ask())
    if not choice:
        return 0
    if choice != NOTIFICATIONS_ITEM:
        say(s["unknown_choice"])
        return 1
    if profile.notifications:
        removed = remove_reminders(host(), base)
        if not save(replace(profile, notifications=False, updated_at=now)):
            return 1
        say(s["turned_off"] if removed else s["off_incomplete"])
        return 0
    return _turn_on(ask, say, profile, save, host, keychain_ok, now, words)


def _turn_on(
    ask: Ask,
    say: Say,
    profile: PersonaProfile,
    save: Save,
    host: Callable[[], Host],
    keychain_ok: Callable[[], bool],
    now: datetime,
    words: NotifyText,
) -> int:
    s = words.settings
    if not keychain_ok():
        say(s["needs_keychain"])
        return 1
    machine = host()
    mechanism = choose(machine)
    if isinstance(mechanism, Unsupported):
        say(s[f"unsupported_{mechanism.value}"])
        return 1
    say(fill(s["about_on"], job=_place(machine, mechanism, words)))
    say("")
    say(s["confirm"])
    say(f"  {CONFIRM_YES}. {s['confirm_yes']}")
    say(f"  2. {s['confirm_no']}")
    if _fold(ask()) != CONFIRM_YES:
        say(s["cancelled"])
        return 0
    if not install(machine, mechanism):
        say(s["install_failed"])
        return 1
    if not save(replace(profile, notifications=True, updated_at=now)):
        uninstall(machine)
        return 1
    say(s["turned_on"])
    return 0


def remove_reminders(host: Host, base: Path) -> bool:
    """Remove the scheduled job and the "last notified" file (turning off, and
    ``olivia forget --all``); True when nothing of the job remains."""
    removed = uninstall(host)
    clear_state(base)
    return removed


def _place(host: Host, mechanism: Mechanism, words: NotifyText) -> str:
    return fill(words.places[mechanism.value], where=where(host, mechanism))
