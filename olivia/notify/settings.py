"""``olivia settings``: a numbered menu of switches (next-phase B9, decision D5; F11).

1. The system reminders (``PersonaProfile.notifications``, off by default). Turning them
   on first says what will be installed and where (one scheduled job,
   :mod:`olivia.notify.jobs`) and that turning them off removes it, then asks once more;
   the profile is saved only after the job is installed, and a failed save removes the
   job again. Turning them off removes the job and the "last notified" file, then saves.
2. The storage choice of onboarding (``enable_at_rest_encryption``, ONB-06; changing it
   after the first visit is F11): only health information encrypted (the default) or
   the whole profile. Either way the change is explained and confirmed once; the save
   goes through ``ProfileStore``, which rewrites the file in its new form atomically and,
   when it is now sealed whole, deletes every snapshot that still holds plaintext.
   Encrypting the whole profile needs the keychain: when it does not answer, nothing is
   asked and nothing changes. The chat records, the kit and the safety plan are always
   encrypted, whatever this says.

Opening the menu runs nothing on the system and writes nothing: only a confirmed change does.
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
ENCRYPTION_ITEM: Final = "2"
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
    storage = s[
        "encryption_state_all" if profile.enable_at_rest_encryption else "encryption_state_health"
    ]
    say(f"  {ENCRYPTION_ITEM}. {fill(s['encryption_item'], state=storage)}")
    choice = _fold(ask())
    if not choice:
        return 0
    if choice == ENCRYPTION_ITEM:
        return _switch_encryption(ask, say, profile, save, keychain_ok, now, words)
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


def _switch_encryption(
    ask: Ask,
    say: Say,
    profile: PersonaProfile,
    save: Save,
    keychain_ok: Callable[[], bool],
    now: datetime,
    words: NotifyText,
) -> int:
    """Item 2: whole-profile encryption on (from the default) or back off (ONB-06, F11)."""
    s = words.settings
    whole = not profile.enable_at_rest_encryption
    if whole and not keychain_ok():
        say(s["encryption_needs_keychain"])
        return 1
    target = "all" if whole else "health"
    say(s[f"about_encrypt_{target}"])
    say("")
    say(s[f"confirm_encrypt_{target}"])
    say(f"  {CONFIRM_YES}. {s[f'encrypt_{target}_yes']}")
    say(f"  2. {s['encryption_no']}")
    if _fold(ask()) != CONFIRM_YES:
        say(s["cancelled"])
        return 0
    if not save(replace(profile, enable_at_rest_encryption=whole, updated_at=now)):
        return 1
    say(s[f"encrypted_{target}"])
    return 0


def remove_reminders(host: Host, base: Path) -> bool:
    """Remove the scheduled job and the "last notified" file (turning off, and
    ``olivia forget --all``); True when nothing of the job remains."""
    removed = uninstall(host)
    clear_state(base)
    return removed


def _place(host: Host, mechanism: Mechanism, words: NotifyText) -> str:
    return fill(words.places[mechanism.value], where=where(host, mechanism))
