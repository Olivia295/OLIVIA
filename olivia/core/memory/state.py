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
now, or that the operating system will not read (a directory in its place, no permission;
robustness C2): such a store is left alone for this session. Without any keychain
nothing is written (:class:`StateRecorder` stops trying) and nothing is said: the ledger
already tells the user once that memory is unavailable.

:meth:`StateStore.shred` is the hook for ``olivia forget`` (B5); :meth:`StateStore.rekey`
rewrites the state under a fresh key after one method's preference is reset
(``olivia forget --method``, RSK-06). Order, so that an interruption never loses the kit
or the other methods' preferences (the same order as the profile's re-key, #112):

1. seal the new state under the staging store :data:`STATE_REKEY_STORE` into
   :data:`STATE_REKEY_FILENAME` (an atomic write: the commit point);
2. delete ``state.bin`` and ``Vault.shred`` the ``state`` key (the master key rotates);
3. write ``state.bin`` under a fresh ``state`` key;
4. delete the staging file and shred the staging store.

Interrupted before step 1 nothing changed (a staging key without its file is shredded);
from step 1 on, the next ``load``, ``save`` or ``rekey`` finishes steps 2-4 first. A
staging copy that does not open is discarded and ``state.bin`` stays authoritative.
While the keychain does not answer, an unfinished re-key is left as it is and nothing is
written over it. Nothing here logs.
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
STATE_REKEY_STORE: Final = "state_rekey"
"""The staging store a re-key seals the new state under (used, then shredded)."""
STATE_REKEY_FILENAME: Final = "state.rekey"
"""The staging copy of a re-key; it exists only while one is under way."""
FORMAT_VERSION: Final = 1
KIT_MAX: Final = 10
_LABEL: Final = "state"
_STAGED_LABEL: Final = "state_rekey"
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
        self.staging: Path = directory / STATE_REKEY_FILENAME
        self.vault: Vault = Vault(directory) if vault is None else vault
        self._keep = False
        """A later version's file, or one the keychain could not open: never overwrite."""

    def load(self) -> CarriedState | None:
        """The stored state, or None (no file, damaged, from a later version, locked)."""
        try:
            self._finish_rekey()
        except (CryptoError, OSError):
            self._keep = True  # an unfinished re-key holds the newest state: leave it
            return None
        try:
            blob = self.path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError:
            self._keep = True  # not ours to replace: perhaps intact, readable again later
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
        try:
            self._finish_rekey()
            blob = self.vault.seal(STATE_STORE, _payload(state), label=_LABEL)
        except NoKeychainError:
            raise
        except (CryptoError, OSError):
            return False  # locked now, the store's keys are damaged, or the disk refused
        try:
            atomic_write_bytes(self.path, blob, snapshot=False)
        except OSError:
            return False  # the file cannot be replaced; tried again at the next change
        return True

    def rekey(self, state: CarriedState) -> bool:
        """Crypto-shred every state written so far and seal ``state`` under a fresh key
        (``olivia forget --method``, RSK-06): a copy of the old file, or of the old key
        file, never opens again. Steps 1-4 of the module docstring, so an interruption
        leaves the old state or the new one, never neither. A state with neither
        posteriors nor kit is only shredded.

        False when ``state.bin`` could not be written: the new state then stays staged
        and the next load finishes the re-key; if even the staging copy cannot be written
        (a disk that refuses every write), the old state is shredded anyway, as asked.

        Raises :class:`KeychainUnavailableError` (nothing changed, or an interrupted
        re-key left to finish later) while the keychain does not answer, and
        :class:`NoKeychainError` without one.
        """
        self.vault.check()
        self._finish_rekey()
        self._keep = False
        if not state.kit and not _has_arms(state.bandit):
            self.shred()
            return True
        try:
            blob = self.vault.seal(STATE_REKEY_STORE, _payload(state), label=_STAGED_LABEL)
            atomic_write_bytes(self.staging, blob, snapshot=False)  # the commit point
        except KeychainUnavailableError:
            raise
        except (CryptoError, OSError):
            self.shred()
            return False
        return self._apply_rekey(state)

    def shred(self) -> None:
        """Make every state ever written unreadable (``olivia forget``, B5), an
        unfinished re-key's staging copy included."""
        self._shred_main()
        self._discard_staging()

    # -- re-keying -------------------------------------------------------------------------

    def _shred_main(self) -> None:
        remove_file(self.path)
        if self.vault.has_data_key(STATE_STORE):
            self.vault.shred(STATE_STORE)

    def _apply_rekey(self, state: CarriedState) -> bool:
        """Steps 2-4; each is safe to repeat. False (the staging copy kept, so the next
        load tries again) when ``state.bin`` cannot be written."""
        self._shred_main()
        blob = self.vault.seal(STATE_STORE, _payload(state), label=_LABEL)
        try:
            atomic_write_bytes(self.path, blob, snapshot=False)
        except OSError:
            return False
        self._discard_staging()
        return True

    def _finish_rekey(self) -> None:
        """Complete a re-key interrupted after its commit point, or discard one
        interrupted before it. Raises :class:`CryptoError` (a keychain that does not
        answer, say) or :class:`OSError` (a staging copy the system will not read, or a
        ``state.bin`` that cannot be written) with the staging copy left in place."""
        try:
            blob = self.staging.read_bytes()
        except FileNotFoundError:
            if self.vault.has_data_key(STATE_REKEY_STORE):
                self.vault.shred(STATE_REKEY_STORE)
            return
        try:
            data = json.loads(self.vault.open(STATE_REKEY_STORE, blob, label=_STAGED_LABEL))
            staged = CarriedState.from_dict(data)
        except (KeyMissingError, DecryptionError, ValueError, TypeError):
            self._discard_staging()  # does not open: ``state.bin`` stays authoritative
            return
        if not self._apply_rekey(staged):
            raise OSError("the re-keyed state cannot be written yet")

    def _discard_staging(self) -> None:
        remove_file(self.staging)
        if self.vault.has_data_key(STATE_REKEY_STORE):
            self.vault.shred(STATE_REKEY_STORE)


def _payload(state: CarriedState) -> bytes:
    return json.dumps(state.to_dict(), ensure_ascii=False, sort_keys=True).encode("utf-8")


def _has_arms(bandit: Mapping[str, object]) -> bool:
    spectra = bandit.get("spectra")
    return isinstance(spectra, Mapping) and any(
        isinstance(arms, Mapping) and arms for arms in spectra.values()
    )


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
