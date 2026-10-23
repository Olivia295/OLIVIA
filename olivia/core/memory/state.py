"""Cross-session state: the Thompson posteriors and the kit (next-phase step B3).

Each new session used to start from the priors with an empty kit. The state store keeps
exactly two things between sessions, and nothing the user said:

* the sampler's posteriors (``ThompsonSampler.to_dict()``, which ``Session.snapshot()``
  also reports as ``bandit``): action ids, spectrum ids, two numbers and a time each;
* the kit (PRD SOP 4 "应急锦囊"): the action ids the user shelved with ``/not-now`` (or
  "今天先不做了"), each with the time it was shelved, oldest first, at most
  :data:`KIT_MAX`, the newest kept.

The document inside is versioned JSON::

    {"olivia_state": 1,
     "bandit": {"spectra": {"05": {"30:grounding": {"alpha": 4.0, "beta": 2.0,
                                                     "last_unhelpful_at": "..."}}}},
     "kit": [{"id": "29:pmr_release", "at": "2026-10-22T23:41:00+08:00"}]}

**Always encrypted**, whatever the at-rest switch (ONB-06) says: one file ``state.bin`` in
the app data directory holding the raw blob sealed with the ``state`` data key, written
atomically without snapshots, so no older copy is left behind. The care marker
(``chang/care.py``, A3) is a separate store.

Damage and versions: a file that does not open (tampered, truncated, key shredded) or does
not parse is treated as absent, and the next save overwrites it. A document written by a
later version (``olivia_state`` above :data:`FORMAT_VERSION`) is ignored and never
overwritten, and so is a file that cannot be opened because the keychain is locked right
now. Without any keychain nothing is written (:class:`StateRecorder` stops trying) and
nothing is said: the ledger already tells the user once that memory is unavailable.

:meth:`StateStore.shred` is the hook for ``olivia forget`` (B5). Nothing here logs.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from olivia.core.crypto.errors import (
    CryptoError,
    DecryptionError,
    KeychainUnavailableError,
    KeyMissingError,
    NoKeychainError,
)
from olivia.core.crypto.vault import Vault
from olivia.core.methods.bandit import ThompsonSampler
from olivia.core.storage import app_data_dir, atomic_write_bytes, remove_file
from olivia.core.taxonomy import Taxonomy, TaxonomyError

STATE_STORE: Final = "state"
STATE_FILENAME: Final = "state.bin"
FORMAT_VERSION: Final = 1
KIT_MAX: Final = 10
_LABEL: Final = "state"
_KEYS: Final = frozenset({"olivia_state", "bandit", "kit"})
_ID_MAX: Final = 64


@dataclass(frozen=True)
class KitEntry:
    """One shelved action: its id and when it was shelved (timezone-aware)."""

    action_id: str
    shelved_at: datetime

    def __post_init__(self) -> None:
        if not self.action_id or len(self.action_id) > _ID_MAX:
            raise ValueError("not an action id")
        if self.shelved_at.tzinfo is None or self.shelved_at.utcoffset() is None:
            raise ValueError("shelved_at must be timezone-aware")


@dataclass(frozen=True)
class CarriedState:
    """What one session hands the next: the sampler state and the kit (oldest first)."""

    bandit: Mapping[str, object]
    """``ThompsonSampler.to_dict()``."""
    kit: tuple[KitEntry, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """The stored document; the kit keeps its newest :data:`KIT_MAX` entries."""
        return {
            "olivia_state": FORMAT_VERSION,
            "bandit": dict(self.bandit),
            "kit": [
                {"id": e.action_id, "at": e.shelved_at.isoformat()} for e in self.kit[-KIT_MAX:]
            ],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CarriedState:
        """Parse a version-1 document; ``ValueError`` on anything unexpected."""
        if set(data) != _KEYS or data["olivia_state"] != FORMAT_VERSION:
            raise ValueError("not a state document")
        bandit = data["bandit"]
        if not isinstance(bandit, dict):
            raise ValueError("bandit must be a mapping")
        raw_kit = data["kit"]
        if not isinstance(raw_kit, list):
            raise ValueError("kit must be a list")
        kit = []
        for item in raw_kit:
            if not isinstance(item, dict) or set(item) != {"id", "at"}:
                raise ValueError("bad kit entry")
            if not isinstance(item["id"], str) or not isinstance(item["at"], str):
                raise ValueError("bad kit entry")
            kit.append(KitEntry(item["id"], datetime.fromisoformat(item["at"])))
        return cls(bandit, tuple(kit[-KIT_MAX:]))


def _version(data: object) -> int | None:
    """The document's format version when it is a mapping with an integer one."""
    if not isinstance(data, dict):
        return None
    version = data.get("olivia_state")
    if isinstance(version, bool) or not isinstance(version, int):
        return None
    return version


class StateStore:
    """The sealed state under ``base_dir`` (default: the app data directory).

    Pass the profile store's ``vault`` so every store shares one view of the keys.
    """

    def __init__(self, base_dir: Path | None = None, vault: Vault | None = None) -> None:
        directory = app_data_dir() if base_dir is None else base_dir
        self.path: Path = directory / STATE_FILENAME
        self.vault: Vault = Vault(directory) if vault is None else vault
        self._keep = False
        """A later version's file, or one the keychain could not open: never overwrite."""

    def load(self) -> CarriedState | None:
        """The stored state, or None (no file, damaged, from a later version, locked)."""
        try:
            blob = self.path.read_bytes()
        except FileNotFoundError:
            return None
        try:
            data = json.loads(self.vault.open(STATE_STORE, blob, label=_LABEL))
        except KeychainUnavailableError:
            self._keep = True  # intact, perhaps, and readable again later
            return None
        except (KeyMissingError, DecryptionError, ValueError):
            return None  # damaged or shredded: the next save replaces it
        version = _version(data)
        if version is not None and version > FORMAT_VERSION:
            self._keep = True
            return None
        try:
            return CarriedState.from_dict(data)
        except (ValueError, TypeError):
            return None

    def save(self, state: CarriedState) -> bool:
        """Seal and write ``state``; False when nothing was written.

        Raises :class:`NoKeychainError` when this device has no keychain at all, so the
        caller can stop trying.
        """
        if self._keep:
            return False
        payload = json.dumps(state.to_dict(), ensure_ascii=False, sort_keys=True)
        try:
            blob = self.vault.seal(STATE_STORE, payload.encode("utf-8"), label=_LABEL)
        except NoKeychainError:
            raise
        except CryptoError:
            return False  # locked now, or the store's keys are damaged
        atomic_write_bytes(self.path, blob, snapshot=False)
        return True

    def shred(self) -> None:
        """Make every state ever written unreadable (``olivia forget``, B5)."""
        remove_file(self.path)
        if self.vault.has_data_key(STATE_STORE):
            self.vault.shred(STATE_STORE)


class StateRecorder:
    """Saves a session's state whenever it differs from what was last saved.

    ``baseline`` is the state the session started from, so a session that changes
    nothing writes nothing. Without a keychain it stops quietly; while the keychain is
    only locked it tries again on the next change or at exit.
    """

    def __init__(self, store: StateStore, baseline: CarriedState) -> None:
        self._store = store
        self._saved = baseline.to_dict()
        self.disabled = False

    def observe(self, state: CarriedState) -> None:
        if self.disabled:
            return
        document = state.to_dict()
        if document == self._saved:
            return
        try:
            saved = self._store.save(state)
        except NoKeychainError:
            self.disabled = True  # nothing can be protected here, so nothing is kept
            return
        if saved:
            self._saved = document


def restore_sampler(tax: Taxonomy, bandit: Mapping[str, object] | None) -> ThompsonSampler:
    """A sampler seeded from ``bandit`` (``ThompsonSampler.to_dict()``).

    Arms the taxonomy no longer knows (a removed action or spectrum) or that do not
    parse are dropped one by one, so a taxonomy update keeps the rest of what was
    learned; a state that does not parse at all gives a fresh sampler.
    """
    if not isinstance(bandit, Mapping) or set(bandit) != {"spectra"}:
        return ThompsonSampler(tax)
    spectra = bandit["spectra"]
    if not isinstance(spectra, Mapping):
        return ThompsonSampler(tax)
    kept: dict[str, dict[str, object]] = {}
    for spectrum, arms in spectra.items():
        if not isinstance(arms, Mapping):
            continue
        for aid, arm in arms.items():
            one = {"spectra": {spectrum: {aid: arm}}}
            try:
                ThompsonSampler(tax, one)
            except (ValueError, TypeError, KeyError, TaxonomyError):
                continue
            kept.setdefault(spectrum, {})[aid] = arm
    try:
        return ThompsonSampler(tax, {"spectra": kept})
    except (ValueError, TypeError, KeyError, TaxonomyError):  # two aliases of one action, say
        return ThompsonSampler(tax)
