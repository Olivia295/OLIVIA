"""What ``olivia doctor`` looks at: a read-only check of this computer's setup.

:func:`examine` gathers facts only; the CLI turns them into one marked line each
(``cli.py``, the ``DOCTOR_*`` texts). Every check is read-only and offline:

* the data directory: where it is, whether it exists (it is never created) and, on
  POSIX, whether every directory is 0700 and every file 0600 (the signed hotline update
  folder ``resources/`` is placed there by the user and holds no personal data, so it is
  not counted);
* the keychain: :func:`keychain.probe` resolves the backend and touches no item, so a
  locked keychain is not noticed (that would take an item read, which may prompt);
* the profile and every sealed store, **without decrypting anything**: a file must
  exist and look sealed (``aead.looks_sealed``: header and length), its wrapped data
  key must be there and well formed (``vault.key_file_intact``), and the keychain must be
  there. A blob altered after its header, or a master key gone from the keychain, is
  only noticed when the store is opened for real;
* the packaged perception student, loaded and verified as ``chat`` would
  (``student.try_load_student``; nothing is cached);
* the built-in hotline data's signature and compiled date, and whether a signed update
  in ``<data dir>/resources/`` is used (``bundle.load_hotlines_bytes``);
* whether the reminder job is installed (``jobs.installed``);
* what the data directory's markers say (robustness fixes): another OLIVIA holding the
  data directory's lock (``datalock.held_elsewhere``: tried and let go, nothing created),
  a ``forget --all`` that did not finish (``forget-all.pending``), and a profile recovered
  from a snapshot that the user has not been told about yet (``profile.recovered``). The
  lock file and both markers are OLIVIA's own and hold no user data.

Nothing here reads a store's contents or a keychain item, so no user text, name, topic,
health code or plan can reach the report: it holds states, dates, counts and versions.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Final, Literal

from olivia.core.chang.care import CARE_FILENAME, CARE_STORE
from olivia.core.chang.profile import (
    PROFILE_FILENAME,
    PROFILE_STORE,
    profile_shape,
    recovery_pending,
)
from olivia.core.chang.safety_plan import SAFETY_PLAN_FILENAME, SAFETY_PLAN_STORE
from olivia.core.crypto import aead, keychain
from olivia.core.crypto.vault import key_file_intact
from olivia.core.datalock import held_elsewhere
from olivia.core.memory.forget import forget_all_unfinished
from olivia.core.memory.ledger import LEDGER_STORE, entry_files
from olivia.core.memory.state import STATE_FILENAME, STATE_STORE
from olivia.core.perception import student
from olivia.core.resources import bundle
from olivia.core.storage import StorageCorruptError, read_text_with_recovery
from olivia.notify import jobs
from olivia.notify.system import Host

HOTLINE_MAX_AGE_DAYS: Final = 90
"""Older hotline data gets a warning; the same limit as the quarterly review
(``scripts/check_hotline_freshness.py``)."""
PRIVATE_DIR_MODE: Final = 0o700
PRIVATE_FILE_MODE: Final = 0o600

_PARSE_ERRORS: Final = (ValueError, TypeError, OverflowError, RecursionError)
_SEALED_FILES: Final = (
    ("state", STATE_FILENAME, STATE_STORE),
    ("care", CARE_FILENAME, CARE_STORE),
    ("safety_plan", SAFETY_PLAN_FILENAME, SAFETY_PLAN_STORE),
)


class StoreState(StrEnum):
    ABSENT = "absent"
    READY = "ready"
    """Every file and its key look intact and the keychain is there."""
    PARTLY = "partly"
    """Some ledger entries look damaged; the others are intact."""
    BROKEN = "broken"
    """The data or its wrapped key is damaged or gone: it cannot be opened."""
    LOCKED = "locked"
    """Intact, but the keychain it needs is not there now."""


@dataclass(frozen=True)
class DataDir:
    location: Path
    kind: Literal["absent", "dir", "other"]
    mismatched: int | None
    """Paths whose mode is not 0700 / 0600; None when not checked (Windows, or no dir)."""


@dataclass(frozen=True)
class ProfileFacts:
    state: StoreState
    onboarded: bool | None
    """A profile was saved (first visit done); None when the file cannot be read."""
    notifications: bool | None
    """The reminders switch, when it is readable without the keychain."""


@dataclass(frozen=True)
class HotlineFacts:
    builtin_ok: bool
    builtin_on: date | None
    used: Literal["builtin", "override"] | None
    """None when the built-in data failed, so the update was not looked at."""
    reason: str | None
    """Why an update that is there is not used (``bundle.REASON_*``)."""
    override_on: date | None


@dataclass(frozen=True)
class Activity:
    busy: bool = False
    """Another OLIVIA holds the data directory's lock now."""
    forget_unfinished: bool = False
    """A ``forget --all`` was interrupted and waits to be run again."""
    recovered: bool = False
    """The profile was recovered from a snapshot and the user has not been told yet."""


@dataclass(frozen=True)
class Report:
    data_dir: DataDir
    keychain: keychain.Probe
    profile: ProfileFacts
    stores: dict[str, StoreState]
    """``ledger``, ``state``, ``care``, ``safety_plan``, in that order."""
    model_reason: str | None
    """Why the packaged student is unavailable; None when it loaded and verified."""
    hotlines: HotlineFacts
    reminders: bool | None
    activity: Activity = Activity()


def examine(base: Path, *, today: date, host: Callable[[], Host]) -> Report:
    """Look at the data directory ``base`` and the installed package (module docstring)."""
    kind: Literal["absent", "dir", "other"] = (
        "dir" if base.is_dir() else "other" if base.exists() else "absent"
    )
    found = keychain.probe()
    keychain_there = found in (keychain.Probe.READY, keychain.Probe.UNCHECKED)
    stores = {"ledger": _sealed(base, entry_files(base), LEDGER_STORE, keychain_there)}
    for name, filename, store in _SEALED_FILES:
        path = base / filename
        stores[name] = _sealed(base, [path] if path.exists() else [], store, keychain_there)
    return Report(
        data_dir=DataDir(base, kind, _mismatched(base) if kind == "dir" else None),
        keychain=found,
        profile=_profile(base, keychain_there),
        stores=stores,
        model_reason=student.try_load_student().reason,
        hotlines=_hotlines(base, today),
        reminders=jobs.installed(host()),
        activity=_activity(base) if kind == "dir" else Activity(),
    )


def _activity(base: Path) -> Activity:
    return Activity(
        busy=held_elsewhere(base),
        forget_unfinished=forget_all_unfinished(base),
        recovered=recovery_pending(base),
    )


def _looks_sealed(path: Path) -> bool:
    try:
        return aead.looks_sealed(path.read_bytes())
    except OSError:
        return False


def _sealed(base: Path, files: list[Path], store: str, keychain_there: bool) -> StoreState:
    if not files:
        return StoreState.ABSENT
    intact = [_looks_sealed(path) for path in files]
    if not any(intact) or not key_file_intact(base, store):
        return StoreState.BROKEN
    if not keychain_there:
        return StoreState.LOCKED
    return StoreState.READY if all(intact) else StoreState.PARTLY


def _profile(base: Path, keychain_there: bool) -> ProfileFacts:
    """The profile file (or, as ``ProfileStore.load`` would, its newest valid snapshot)."""

    def is_valid(text: str) -> bool:
        try:
            profile_shape(text)
        except _PARSE_ERRORS:
            return False
        return True

    try:
        text = read_text_with_recovery(base / PROFILE_FILENAME, is_valid)
    except FileNotFoundError:
        return ProfileFacts(StoreState.ABSENT, onboarded=False, notifications=None)
    except (StorageCorruptError, OSError):
        return ProfileFacts(StoreState.BROKEN, onboarded=None, notifications=None)
    shape = profile_shape(text)
    state = StoreState.READY
    if shape.sealed:
        if not key_file_intact(base, PROFILE_STORE):
            state = StoreState.BROKEN
        elif not keychain_there:
            state = StoreState.LOCKED
    return ProfileFacts(state, onboarded=True, notifications=shape.notifications)


def _mismatched(base: Path) -> int | None:
    """How many paths are not 0700 (directories) / 0600 (files); None on Windows."""
    if os.name == "nt":
        return None
    count = 0
    for path in (base, *base.rglob("*")):
        relative = path.relative_to(base).parts
        if relative and relative[0] == bundle.OVERRIDE_DIR_NAME:
            continue  # placed there by the user, holds no personal data
        try:
            info = path.lstat()
        except OSError:
            continue
        if stat.S_ISLNK(info.st_mode):
            continue
        want = PRIVATE_DIR_MODE if stat.S_ISDIR(info.st_mode) else PRIVATE_FILE_MODE
        count += stat.S_IMODE(info.st_mode) != want
    return count


def _hotlines(base: Path, today: date) -> HotlineFacts:
    try:
        builtin = bundle.load_hotlines_bytes(None, today=today)
    except (bundle.BundleIntegrityError, OSError):
        return HotlineFacts(False, None, None, None, None)
    builtin_on = bundle.compiled_on_of(builtin.data)
    loaded = bundle.load_hotlines_bytes(base / bundle.OVERRIDE_DIR_NAME, today=today)
    if loaded.source == "override":
        return HotlineFacts(True, builtin_on, "override", None, bundle.compiled_on_of(loaded.data))
    reason = None if loaded.reason == bundle.REASON_NO_OVERRIDE else loaded.reason
    return HotlineFacts(True, builtin_on, "builtin", reason, None)
