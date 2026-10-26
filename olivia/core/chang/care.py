"""The cross-session care marker: a gentle check-in after a crisis (PRD §9, step A3).

A session that entered the crisis flow (S_crisis, at L2 or L3) leaves a marker; so does,
more lightly, a session whose direct question about intent (decision D3) was answered
with a no (``Session.snapshot()["gentle_care"]``). The next ``olivia chat`` within
:data:`MAX_AGE` opens with the ``returning_after_crisis`` greeting (``returning_after_check``
for a no), exactly once, and the marker is removed. Older markers are dropped silently.
Crisis handling in the returning session is unchanged.

The marker holds a time and a kind (:class:`CareKind`) and nothing else, never any text.
It is crisis history, so it is always sealed with its own data key (store ``care``),
whatever the at-rest switch says. Without a keychain it is not stored at all and nothing
extra is said: the in-session behaviour stays as it is. ``CareStore.shred`` is the hook
for ``olivia forget`` (B5).

File: ``care.bin`` in the app data directory, the raw sealed blob, written atomically
without snapshots, so taking a marker leaves no older copy behind.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Final

from olivia.core.crypto.errors import (
    DecryptionError,
    KeychainUnavailableError,
    KeyMissingError,
    NoKeychainError,
)
from olivia.core.crypto.vault import Vault
from olivia.core.models import CrisisLevel, HelpStage
from olivia.core.session import TurnResult
from olivia.core.storage import app_data_dir, atomic_write_bytes, remove_file

CARE_STORE: Final = "care"
CARE_FILENAME: Final = "care.bin"
MAX_AGE: Final = timedelta(days=7)
_LABEL: Final = "marker"


class CareKind(StrEnum):
    """Why the next session checks in; ordered from lightest to strongest."""

    ASK_DENIED = "ASK_DENIED"
    L2 = "L2"
    L3 = "L3"


_RANK: Final = {CareKind.ASK_DENIED: 0, CareKind.L2: 1, CareKind.L3: 2}


@dataclass(frozen=True)
class CareMarker:
    at: datetime
    """When it was written (timezone-aware)."""
    kind: CareKind

    @property
    def light(self) -> bool:
        """The lighter greeting: the question was answered with a no, no crisis followed."""
        return self.kind is CareKind.ASK_DENIED


def care_kind(result: TurnResult, snapshot: Mapping[str, object]) -> CareKind | None:
    """What this turn calls for: the crisis level of an S_crisis turn (at least L2), else
    ASK_DENIED once the session's gentle-care flag is set, else None."""
    if result.stage is HelpStage.S_CRISIS:
        level = max(CrisisLevel.L2, result.crisis_level)
        if result.resource_card is not None:
            level = max(level, result.resource_card.level)
        return CareKind.L3 if level >= CrisisLevel.L3 else CareKind.L2
    if snapshot.get("gentle_care") is True:
        return CareKind.ASK_DENIED
    return None


def _stronger(a: CareKind, b: CareKind) -> CareKind:
    return a if _RANK[a] >= _RANK[b] else b


class CareStore:
    """The sealed marker under ``base_dir`` (default: the app data directory).

    Pass the profile store's ``vault`` so both stores share one view of the keys.
    """

    def __init__(self, base_dir: Path | None = None, vault: Vault | None = None) -> None:
        directory = app_data_dir() if base_dir is None else base_dir
        self.path: Path = directory / CARE_FILENAME
        self.vault: Vault = Vault(directory) if vault is None else vault

    def save(self, marker: CareMarker) -> bool:
        """Seal and write ``marker``; False (nothing written) when the keychain is unusable.

        A still-unread stronger marker keeps its kind, so a later, lighter event never
        lowers the next greeting. Raises :class:`NoKeychainError` when this device has no
        keychain at all, so the caller can stop trying.
        """
        kind = marker.kind
        try:
            existing = self._read()
        except (KeychainUnavailableError, KeyMissingError, DecryptionError, ValueError, OSError):
            existing = None  # unreadable now or ever: the new marker replaces it
        if existing is not None:
            kind = _stronger(kind, existing.kind)
        payload = json.dumps({"at": marker.at.isoformat(), "kind": kind.value}).encode("utf-8")
        try:
            blob = self.vault.seal(CARE_STORE, payload, label=_LABEL)
        except NoKeychainError:
            raise
        except KeychainUnavailableError:
            return False
        except (KeyMissingError, DecryptionError):
            return False  # the store's keys are damaged; never overwrite anything else
        try:
            atomic_write_bytes(self.path, blob, snapshot=False)
        except OSError:
            return False  # the file cannot be replaced (robustness C2)
        return True

    def take(self, now: datetime) -> CareMarker | None:
        """The marker if it is at most :data:`MAX_AGE` old, removed so it is used once.

        An expired, damaged or unopenable marker is removed and None returned; while the
        keychain is only unavailable the file is kept for a later session.
        """
        try:
            marker = self._read()
        except (KeychainUnavailableError, OSError):
            return None  # locked, or a file the system will not read: kept for later
        except (KeyMissingError, DecryptionError, ValueError):
            with contextlib.suppress(OSError):
                remove_file(self.path)
            return None
        if marker is None:
            return None
        try:
            remove_file(self.path)
        except OSError:
            return None  # a marker that cannot be removed would greet every time
        if now - marker.at > MAX_AGE:
            return None
        return marker

    def shred(self) -> None:
        """Make every marker ever written unreadable (``olivia forget``, B5)."""
        remove_file(self.path)
        if self.vault.has_data_key(CARE_STORE):
            self.vault.shred(CARE_STORE)

    def _read(self) -> CareMarker | None:
        try:
            blob = self.path.read_bytes()
        except FileNotFoundError:
            return None
        data = json.loads(self.vault.open(CARE_STORE, blob, label=_LABEL))
        if not isinstance(data, dict) or set(data) != {"at", "kind"}:
            raise ValueError("not a care marker")
        at, kind = data["at"], data["kind"]
        if not isinstance(at, str) or not isinstance(kind, str):
            raise ValueError("not a care marker")
        moment = datetime.fromisoformat(at)
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise ValueError("care marker time must be timezone-aware")
        return CareMarker(moment, CareKind(kind))


class CareRecorder:
    """Watches one session's turns and writes the marker as soon as it is called for.

    Writing on the turn itself means an interrupted session still leaves its marker. A
    marker is rewritten only when a stronger kind appears (ASK_DENIED < L2 < L3).
    """

    def __init__(self, store: CareStore, clock: Callable[[], datetime]) -> None:
        self._store = store
        self._clock = clock
        self._written: CareKind | None = None
        self._disabled = False

    def observe(self, result: TurnResult, snapshot: Mapping[str, object]) -> None:
        kind = care_kind(result, snapshot)
        if kind is None or self._disabled:
            return
        if self._written is not None and _stronger(self._written, kind) is self._written:
            return
        try:
            saved = self._store.save(CareMarker(self._clock(), kind))
        except NoKeychainError:
            self._disabled = True  # nothing can be protected here, so nothing is kept
            return
        if saved:
            self._written = kind
