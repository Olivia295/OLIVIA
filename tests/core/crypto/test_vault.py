"""Envelope encryption and crypto-shredding (B1, ruling 28, MIYI-05)."""

from __future__ import annotations

import os
import shutil

import pytest

from olivia.core.crypto import vault as vault_module
from olivia.core.crypto.errors import (
    DecryptionError,
    KeychainUnavailableError,
    KeyMissingError,
    NoKeychainError,
)
from olivia.core.crypto.vault import MASTER_ITEM, NEXT_MASTER_ITEM, Vault


@pytest.fixture
def vault(tmp_path, keychain):
    return Vault(tmp_path, keychain)


def _master_id(keychain) -> str:
    return keychain.items[MASTER_ITEM].split(":")[1]


def test_round_trip_creates_one_master_and_one_wrapped_key_per_store(tmp_path, vault, keychain):
    assert keychain.items == {} and vault.available()
    assert not (tmp_path / "keys").exists()  # nothing is created before the first seal
    blob = vault.seal("profile", "失眠".encode(), label="fields")
    other = vault.seal("ledger", b"entry")
    assert vault.open("profile", blob, label="fields").decode() == "失眠"
    assert Vault(tmp_path, keychain).open("ledger", other) == b"entry"  # a later process
    assert set(keychain.items) == {MASTER_ITEM}
    assert sorted(p.name for p in (tmp_path / "keys").iterdir()) == ["ledger.key", "profile.key"]
    assert not (tmp_path / "keys" / ".snapshots").exists()  # key files are never snapshotted
    if os.name != "nt":
        assert (tmp_path / "keys").stat().st_mode & 0o777 == 0o700
        assert (tmp_path / "keys" / "profile.key").stat().st_mode & 0o777 == 0o600
    assert vault.has_data_key("profile") and not vault.has_data_key("kit")


def test_each_store_has_its_own_data_key(tmp_path, vault):
    vault.seal("profile", b"x")
    vault.seal("ledger", b"x")
    keys = tmp_path / "keys"
    assert (keys / "profile.key").read_bytes() != (keys / "ledger.key").read_bytes()


def test_opening_without_a_data_key_is_key_missing(vault):
    with pytest.raises(KeyMissingError):
        vault.open("kit", b"anything")


def test_tampered_ciphertext_and_tampered_key_file_are_rejected(tmp_path, vault, keychain):
    blob = bytearray(vault.seal("profile", b"secret"))
    blob[-1] ^= 0x80
    with pytest.raises(DecryptionError):
        vault.open("profile", bytes(blob))
    key_file = tmp_path / "keys" / "profile.key"
    raw = bytearray(key_file.read_bytes())
    raw[-1] ^= 0x80
    key_file.write_bytes(bytes(raw))
    with pytest.raises(DecryptionError):
        Vault(tmp_path, keychain).open("profile", vault.seal("profile", b"x"))


def test_a_key_file_moved_to_another_store_is_rejected(tmp_path, vault, keychain):
    blob = vault.seal("profile", b"secret")
    vault.seal("ledger", b"x")
    keys = tmp_path / "keys"
    shutil.copyfile(keys / "ledger.key", keys / "profile.key")
    with pytest.raises(DecryptionError):
        Vault(tmp_path, keychain).open("profile", blob)


def test_another_devices_keychain_cannot_open_the_data(tmp_path, vault, new_keychain):
    blob = vault.seal("profile", b"secret")
    stranger = Vault(tmp_path, new_keychain())
    with pytest.raises(KeyMissingError):
        stranger.open("profile", blob)


def test_wrong_master_with_the_same_id_is_rejected(tmp_path, vault, keychain):
    blob = vault.seal("profile", b"secret")
    key_id = bytes.fromhex(_master_id(keychain))
    keychain.items[MASTER_ITEM] = vault_module.encode_master(key_id, bytes(32))
    with pytest.raises(DecryptionError):
        Vault(tmp_path, keychain).open("profile", blob)


def test_shred_one_store_makes_it_unreadable_and_keeps_the_others(tmp_path, vault, keychain):
    profile_blob = vault.seal("profile", b"profile data")
    ledger_blob = vault.seal("ledger", b"ledger data")
    remnant = (tmp_path / "keys" / "ledger.key").read_bytes()  # e.g. left on flash storage
    old_id = _master_id(keychain)

    vault.shred("ledger")

    assert not (tmp_path / "keys" / "ledger.key").exists()
    with pytest.raises(KeyMissingError):
        vault.open("ledger", ledger_blob)
    # The master key was rotated, so even a recovered copy of the shredded key file is useless.
    assert _master_id(keychain) != old_id and set(keychain.items) == {MASTER_ITEM}
    (tmp_path / "keys" / "ledger.key").write_bytes(remnant)
    with pytest.raises(KeyMissingError):
        Vault(tmp_path, keychain).open("ledger", ledger_blob)
    (tmp_path / "keys" / "ledger.key").unlink()
    # The surviving store still opens, from this vault and from a fresh process.
    assert vault.open("profile", profile_blob) == b"profile data"
    assert Vault(tmp_path, keychain).open("profile", profile_blob) == b"profile data"


def test_shredding_the_last_store_deletes_the_master_key(vault, keychain):
    blob = vault.seal("profile", b"x")
    vault.shred("profile")
    assert keychain.items == {}
    with pytest.raises(KeyMissingError):
        vault.open("profile", blob)
    vault.shred("profile")  # idempotent


def test_a_new_data_key_after_shredding_cannot_open_old_ciphertext(vault):
    old = vault.seal("profile", b"before")
    vault.shred("profile")
    vault.seal("profile", b"after")
    with pytest.raises(DecryptionError):
        vault.open("profile", old)


def test_shred_all_forgets_everything(tmp_path, vault, keychain):
    blobs = {store: vault.seal(store, store.encode()) for store in ("profile", "ledger", "kit")}
    vault.shred_all()
    assert keychain.items == {}
    assert list((tmp_path / "keys").iterdir()) == []
    for store, blob in blobs.items():
        with pytest.raises(KeyMissingError):
            Vault(tmp_path, keychain).open(store, blob)
    # A fresh start works afterwards, with a brand-new master key.
    assert vault.open("profile", vault.seal("profile", b"new")) == b"new"


def test_shred_all_without_keychain_still_destroys_the_data_keys(tmp_path, vault, keychain):
    blob = vault.seal("profile", b"x")
    keychain.broken = KeychainUnavailableError("locked")
    with pytest.raises(KeychainUnavailableError):
        vault.shred_all()
    assert list((tmp_path / "keys").iterdir()) == []
    keychain.broken = None
    with pytest.raises(KeyMissingError):
        Vault(tmp_path, keychain).open("profile", blob)


def test_interrupted_rotation_is_finished_by_the_next_process(
    tmp_path, vault, keychain, monkeypatch
):
    blobs = {store: vault.seal(store, store.encode()) for store in ("profile", "ledger", "kit")}
    real_write = vault_module.Vault._write_wrapped
    calls = []

    def crash_after_first(self, path, store, dek, master):
        if calls:
            raise OSError("power cut")
        calls.append(store)
        real_write(self, path, store, dek, master)

    monkeypatch.setattr(vault_module.Vault, "_write_wrapped", crash_after_first)
    with pytest.raises(OSError):
        vault.rotate_master_key()
    monkeypatch.setattr(vault_module.Vault, "_write_wrapped", real_write)
    assert NEXT_MASTER_ITEM in keychain.items  # the crash left a half-done rotation

    fresh = Vault(tmp_path, keychain)
    for store, blob in blobs.items():
        assert fresh.open(store, blob) == store.encode()
    assert set(keychain.items) == {MASTER_ITEM}


def test_rotation_keeps_every_store_readable(tmp_path, vault, keychain):
    blobs = {store: vault.seal(store, store.encode()) for store in ("profile", "ledger")}
    before = _master_id(keychain)
    vault.rotate_master_key()
    assert _master_id(keychain) != before and set(keychain.items) == {MASTER_ITEM}
    for store, blob in blobs.items():
        assert Vault(tmp_path, keychain).open(store, blob) == store.encode()


def test_lost_master_with_existing_data_keys_is_never_silently_replaced(tmp_path, vault, keychain):
    vault.seal("profile", b"x")
    keychain.items.clear()  # keychain reset, or the data was copied to another computer
    fresh = Vault(tmp_path, keychain)
    with pytest.raises(KeyMissingError):
        fresh.seal("ledger", b"new")
    assert keychain.items == {}  # no new master was written over the lost one


def test_malformed_master_item_is_not_overwritten(tmp_path, vault, keychain):
    vault.seal("profile", b"x")
    keychain.items[MASTER_ITEM] = "garbage"
    fresh = Vault(tmp_path, keychain)
    with pytest.raises(KeyMissingError):
        fresh.seal("profile", b"y")
    assert keychain.items[MASTER_ITEM] == "garbage"


@pytest.mark.parametrize("error", [NoKeychainError("none"), KeychainUnavailableError("locked")])
def test_unavailable_keychain_writes_nothing(tmp_path, vault, keychain, error):
    keychain.broken = error
    assert not vault.available()
    with pytest.raises(type(error)):
        vault.seal("profile", b"secret")
    assert not (tmp_path / "keys").exists()


def test_keychain_items_never_carry_user_text(tmp_path, vault, keychain):
    for store in ("profile", "ledger", "kit", "safety_plan", "posteriors"):
        vault.seal(store, "小林的秘密".encode())
    vault.shred("kit")
    assert set(keychain.writes) <= {MASTER_ITEM, NEXT_MASTER_ITEM}
    assert all("小林" not in value for value in keychain.items.values())


@pytest.mark.parametrize("store", ["", "../profile", "Profile", "小林"])
def test_store_names_are_validated(vault, store):
    with pytest.raises(ValueError):
        vault.seal(store, b"x")
    with pytest.raises(ValueError):
        vault.shred(store)


def test_key_file_intact_reads_the_file_only(tmp_path, vault, keychain):
    assert not vault_module.key_file_intact(tmp_path, "kit")
    vault.seal("kit", b"x")
    reads, writes = len(keychain.reads), list(keychain.writes)
    keychain.broken = KeychainUnavailableError("locked")  # never asked
    assert vault_module.key_file_intact(tmp_path, "kit")
    assert len(keychain.reads) == reads and keychain.writes == writes
    path = tmp_path / vault_module.KEYS_DIRNAME / "kit.key"
    raw = path.read_bytes()
    path.write_bytes(raw[:-1])
    assert not vault_module.key_file_intact(tmp_path, "kit")
    path.write_bytes(b"XXXX" + raw[4:])
    assert not vault_module.key_file_intact(tmp_path, "kit")
    with pytest.raises(ValueError):
        vault_module.key_file_intact(tmp_path, "../kit")
