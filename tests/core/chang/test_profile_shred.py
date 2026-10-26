"""Changing or deleting health information crypto-shreds every older copy of it.

``olivia health`` promises that ``0`` deletes everything (``templates/privacy.yaml``). A
save that changes the sensitive fields therefore re-keys the profile store: no snapshot,
staging copy or stale file left in the data directory may still open, under the keys the
keychain holds now, to health information that was deleted or replaced, and recovering
from a damaged main file must never bring it back (SDD §6.5, §6.6).
"""

from __future__ import annotations

import base64
import binascii
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from olivia.core.chang.profile import (
    PROFILE_STORE,
    ProfileCorruptError,
    ProfileLockedError,
    ProfileStore,
)
from olivia.core.crypto.errors import CryptoError, KeychainUnavailableError
from olivia.core.crypto.vault import Vault
from olivia.core.models import PROFILE_CONTRAINDICATIONS, PersonaProfile, UserRegion
from olivia.core.storage import atomic_write_text, snapshot_paths
from olivia.core.taxonomy import load_taxonomy

NOW = datetime(2026, 10, 22, tzinfo=UTC)
CODES = tuple(load_taxonomy().red_flags())[:2]
ITEM = PROFILE_CONTRAINDICATIONS[0]
LABELS = ("", "fields", "whole", "staged")


def _p(name="小林", history=CODES, contra=(ITEM,), encrypt=False):
    return PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        user_name=name,
        region=UserRegion(country_code="HK", timezone="Asia/Hong_Kong"),
        clinical_history=history,
        contraindications=contra,
        enable_at_rest_encryption=encrypt,
    )


def _blobs(raw: bytes) -> list[bytes]:
    """Every ciphertext a file may hold: the file itself, or base64 values in JSON."""
    found = [raw]
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return found
    if isinstance(data, dict):
        for value in data.values():
            if isinstance(value, str):
                try:
                    found.append(base64.b64decode(value, validate=True))
                except (binascii.Error, ValueError):
                    continue
    return found


def _openable(home: Path) -> list[tuple[str, bytes]]:
    """``(file, plaintext)`` for every blob in ``home`` that opens under the current keys
    (a fresh vault: nothing cached from the store under test)."""
    vault = Vault(home)
    stores = sorted(p.stem for p in (home / "keys").glob("*.key"))
    opened = []
    for path in sorted(home.rglob("*")):
        if not path.is_file() or path.parent.name == "keys":
            continue
        for blob in _blobs(path.read_bytes()):
            for store in stores:
                for label in LABELS:
                    try:
                        plain = vault.open(store, blob, label=label)
                    except (CryptoError, ValueError):
                        continue
                    opened.append((path.relative_to(home).as_posix(), plain))
    return opened


def _readable(home: Path, *values: str) -> list[str]:
    """Files that still open, under the current keys, to any of ``values``."""
    return [
        rel
        for rel, plain in _openable(home)
        if any(json.dumps(v, ensure_ascii=False).encode("utf-8") in plain for v in values)
    ]


def _corrupt_main(store: ProfileStore) -> None:
    store.path.write_text("{ not json", encoding="utf-8")


def _rekeys(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    shredded: list[str] = []
    original = Vault.shred

    def spy(self: Vault, store: str) -> None:
        shredded.append(store)
        original(self, store)

    monkeypatch.setattr(Vault, "shred", spy)
    return shredded


# -- the reported defect: FIELDS -> PLAIN ----------------------------------------------------


def test_clearing_health_leaves_no_snapshot_that_opens_to_it(tmp_path):
    store = ProfileStore(tmp_path)
    store.save(_p())
    assert _readable(tmp_path, *CODES, ITEM)  # the check sees sealed health data
    store.save(_p(history=(), contra=()))
    assert _readable(tmp_path, *CODES, ITEM) == []


def test_a_damaged_main_file_never_brings_cleared_health_back(tmp_path):
    store = ProfileStore(tmp_path)
    store.save(_p())
    store.save(_p(history=(), contra=()))
    _corrupt_main(store)
    try:
        loaded = ProfileStore(tmp_path).load()
    except ProfileCorruptError:
        loaded = None  # nothing left to recover from: an honest "damaged", not old data
    assert loaded is None or (loaded.clinical_history == () and loaded.contraindications == ())


def test_clearing_health_shreds_the_profile_key(tmp_path):
    store = ProfileStore(tmp_path)
    store.save(_p())
    store.save(_p(history=(), contra=()))
    assert not store.vault.has_data_key(PROFILE_STORE)
    for snapshot in snapshot_paths(store.path):
        data = json.loads(snapshot.read_bytes())
        assert "sealed_fields" not in data and "sealed_profile" not in data
    assert ProfileStore(tmp_path).load() == _p(history=(), contra=())


# -- FIELDS -> FIELDS: one item deleted ------------------------------------------------------


def test_deleting_one_item_makes_the_old_copies_unreadable(tmp_path):
    store = ProfileStore(tmp_path)
    store.save(_p())
    store.save(_p(history=CODES[:1]))
    assert _readable(tmp_path, CODES[1]) == []
    assert _readable(tmp_path, CODES[0])  # the item kept is still there, re-sealed
    assert ProfileStore(tmp_path).load() == _p(history=CODES[:1])


def test_after_deleting_one_item_recovery_skips_the_old_snapshots(tmp_path):
    store = ProfileStore(tmp_path)
    store.save(_p("阿青"))
    store.save(_p("阿青", history=CODES[:1]))
    _corrupt_main(store)
    with pytest.raises(ProfileCorruptError):
        ProfileStore(tmp_path).load()


# -- WHOLE -> WHOLE: health changed under the ONB-06 switch ----------------------------------


def test_changing_health_with_the_switch_on_shreds_the_whole_profile_copies(tmp_path):
    store = ProfileStore(tmp_path)
    store.save(_p(encrypt=True))
    store.save(_p(history=CODES[1:], contra=(), encrypt=True))
    assert _readable(tmp_path, CODES[0], ITEM) == []
    assert ProfileStore(tmp_path).load() == _p(history=CODES[1:], contra=(), encrypt=True)
    _corrupt_main(store)
    with pytest.raises(ProfileCorruptError):
        ProfileStore(tmp_path).load()


def test_clearing_health_with_the_switch_on_keeps_the_profile_sealed(tmp_path):
    store = ProfileStore(tmp_path)
    store.save(_p(encrypt=True))
    store.save(_p(history=(), contra=(), encrypt=True))
    assert _readable(tmp_path, *CODES, ITEM) == []
    assert set(json.loads(store.path.read_bytes())) == {"sealed_profile"}
    assert ProfileStore(tmp_path).load() == _p(history=(), contra=(), encrypt=True)


# -- non-sensitive changes do not re-key ----------------------------------------------------


@pytest.mark.parametrize("encrypt", [False, True])
def test_a_non_sensitive_change_keeps_the_key(tmp_path, monkeypatch, encrypt):
    store = ProfileStore(tmp_path)
    store.save(_p("阿青", encrypt=encrypt))
    key = (tmp_path / "keys" / "profile.key").read_bytes()
    shredded = _rekeys(monkeypatch)
    store.save(_p("小林", encrypt=encrypt))
    ProfileStore(tmp_path).load()
    assert shredded == []
    assert (tmp_path / "keys" / "profile.key").read_bytes() == key
    assert snapshot_paths(store.path)  # the older version stays as a usable snapshot
    _corrupt_main(store)
    assert ProfileStore(tmp_path).load() == _p("阿青", encrypt=encrypt)


def test_switching_the_form_without_changing_health_keeps_the_key(tmp_path, monkeypatch):
    store = ProfileStore(tmp_path)
    store.save(_p())
    shredded = _rekeys(monkeypatch)
    store.save(_p(encrypt=True))
    store.save(_p())
    assert shredded == []


def test_a_change_re_keys_only_once(tmp_path, monkeypatch):
    store = ProfileStore(tmp_path)
    store.save(_p())
    shredded = _rekeys(monkeypatch)
    store.save(_p(history=CODES[:1]))
    assert shredded.count(PROFILE_STORE) == 1
    shredded.clear()
    ProfileStore(tmp_path).load()
    store.save(_p("阿青", history=CODES[:1]))
    assert shredded == []


# -- interruptions and a locked keychain -----------------------------------------------------


def test_an_interrupted_re_key_is_finished_on_the_next_load(tmp_path, monkeypatch):
    store = ProfileStore(tmp_path)
    store.save(_p())
    original = Vault.shred

    def crash(self: Vault, name: str) -> None:
        if name == PROFILE_STORE:
            raise RuntimeError("power cut")
        original(self, name)

    monkeypatch.setattr(Vault, "shred", crash)
    with pytest.raises(RuntimeError):
        store.save(_p(history=CODES[:1]))
    monkeypatch.setattr(Vault, "shred", original)
    assert ProfileStore(tmp_path).load() == _p(history=CODES[:1])
    assert _readable(tmp_path, CODES[1]) == []
    assert not (tmp_path / "profile.rekey").exists()


def test_a_crash_after_clearing_but_before_shredding_is_healed_on_load(tmp_path, monkeypatch):
    store = ProfileStore(tmp_path)
    store.save(_p())
    monkeypatch.setattr(Vault, "shred", lambda self, name: (_ for _ in ()).throw(OSError()))
    with pytest.raises(OSError):
        store.save(_p(history=(), contra=()))
    monkeypatch.undo()
    assert ProfileStore(tmp_path).load() == _p(history=(), contra=())
    assert _readable(tmp_path, *CODES, ITEM) == []


def test_stale_snapshots_from_before_the_fix_are_shredded_on_load(tmp_path):
    """A data directory written before the fix: the old health still opens in a snapshot."""
    store = ProfileStore(tmp_path)
    store.save(_p())
    # What the old ``_save`` did: rewrite under the same key, snapshot the old version.
    atomic_write_text(store.path, store._encode(_p(history=CODES[:1])))
    assert _readable(tmp_path, CODES[1])
    assert ProfileStore(tmp_path).load() == _p(history=CODES[:1])
    assert _readable(tmp_path, CODES[1]) == []
    assert ProfileStore(tmp_path).load() == _p(history=CODES[:1])


def test_a_locked_keychain_blocks_clearing_without_changing_anything(tmp_path, keychain):
    store = ProfileStore(tmp_path)
    store.save(_p())
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    keychain.broken = KeychainUnavailableError("locked")
    fresh = ProfileStore(tmp_path)
    with pytest.raises(ProfileLockedError):
        fresh.save(_p(history=(), contra=()))
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before
