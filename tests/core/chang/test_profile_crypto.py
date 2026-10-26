"""Profile encryption (B1, ruling 28): sensitive fields always, the whole profile on request."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime

import pytest

from olivia.core.chang.profile import (
    SENSITIVE_FIELDS,
    ProfileCorruptError,
    ProfileLockedError,
    ProfileStore,
)
from olivia.core.crypto.errors import KeychainUnavailableError, NoKeychainError
from olivia.core.crypto.vault import Vault
from olivia.core.models import PersonaProfile, UserRegion
from olivia.core.storage import atomic_write_text, snapshot_paths
from olivia.core.taxonomy import load_taxonomy

NOW = datetime(2026, 10, 22, tzinfo=UTC)
CODES = tuple(load_taxonomy().red_flags())[:2]


def _p(name="小林", history=CODES, encrypt=False):
    return PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        user_name=name,
        region=UserRegion(country_code="HK", timezone="Asia/Hong_Kong"),
        clinical_history=history,
        enable_at_rest_encryption=encrypt,
    )


def _legacy_text(profile: PersonaProfile) -> str:
    """What the pre-B1 store wrote: plaintext JSON including clinical_history."""
    return json.dumps(profile.to_dict(), ensure_ascii=False, indent=2)


def _all_bytes(tmp_path) -> list[tuple[str, bytes]]:
    return [(str(p), p.read_bytes()) for p in tmp_path.rglob("*") if p.is_file()]


def _assert_nowhere(tmp_path, *needles: str) -> None:
    for path, raw in _all_bytes(tmp_path):
        for needle in needles:
            assert needle.encode("utf-8") not in raw, (path, needle)


def test_sensitive_fields_cover_clinical_history_and_contraindications():
    assert SENSITIVE_FIELDS == ("clinical_history", "contraindications")


# -- switch off: sensitive fields are still encrypted -----------------------------------------


def test_clinical_history_is_never_written_in_plaintext(tmp_path):
    store = ProfileStore(tmp_path)
    store.save(_p("阿青"))
    store.save(_p("小林"))  # the first version becomes a snapshot
    raw = store.path.read_bytes()
    assert "小林".encode() in raw  # the rest of the profile stays readable
    _assert_nowhere(tmp_path, "clinical_history", *CODES)
    data = json.loads(raw)
    assert "sealed_fields" in data and "sealed_profile" not in data
    assert ProfileStore(tmp_path).load() == _p("小林")


def test_profile_without_sensitive_data_needs_no_keychain(tmp_path, keychain):
    keychain.broken = NoKeychainError("none")
    store = ProfileStore(tmp_path)
    store.save(_p(history=()))
    assert not (tmp_path / "keys").exists()
    data = json.loads(store.path.read_text(encoding="utf-8"))
    assert "clinical_history" not in data and "sealed_fields" not in data
    assert store.load() == _p(history=())


# -- switch on: the whole profile ---------------------------------------------------------------


def test_switch_on_encrypts_the_whole_profile(tmp_path):
    store = ProfileStore(tmp_path)
    store.save(_p(encrypt=True))
    data = json.loads(store.path.read_text(encoding="utf-8"))
    assert set(data) == {"sealed_profile"}
    _assert_nowhere(tmp_path, "小林", "Asia/Hong_Kong", "clinical_history", *CODES)
    assert ProfileStore(tmp_path).load() == _p(encrypt=True)


def test_turning_the_switch_on_purges_plaintext_snapshots(tmp_path):
    store = ProfileStore(tmp_path)
    store.save(_p("阿青", history=()))
    store.save(_p("阿青", history=()))
    assert snapshot_paths(store.path)
    store.save(_p("小林", encrypt=True))
    _assert_nowhere(tmp_path, "阿青", "小林")
    assert store.load() == _p("小林", encrypt=True)


# -- tampering, wrong keys, shredding ----------------------------------------------------------


def _tamper(store: ProfileStore, key: str) -> None:
    data = json.loads(store.path.read_text(encoding="utf-8"))
    blob = bytearray(base64.b64decode(data[key]))
    blob[-1] ^= 0x01
    data[key] = base64.b64encode(bytes(blob)).decode()
    store.path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


@pytest.mark.parametrize(("encrypt", "key"), [(False, "sealed_fields"), (True, "sealed_profile")])
def test_tampered_ciphertext_is_a_clear_error(tmp_path, encrypt, key):
    store = ProfileStore(tmp_path)
    store.save(_p(encrypt=encrypt))
    _tamper(store, key)
    with pytest.raises(ProfileCorruptError):
        store.load()


def test_tampered_ciphertext_recovers_from_an_encrypted_snapshot(tmp_path):
    store = ProfileStore(tmp_path)
    store.save(_p("阿青"))
    store.save(_p("小林"))
    _tamper(store, "sealed_fields")
    assert store.load() == _p("阿青")


def test_sealed_and_plaintext_sensitive_fields_together_are_rejected(tmp_path):
    store = ProfileStore(tmp_path)
    store.save(_p())
    data = json.loads(store.path.read_text(encoding="utf-8")) | {"clinical_history": []}
    store.path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ProfileCorruptError):
        store.load()


def test_another_devices_keychain_cannot_read_the_profile(tmp_path, new_keychain):
    ProfileStore(tmp_path).save(_p())
    stranger = ProfileStore(tmp_path, Vault(tmp_path, new_keychain()))
    with pytest.raises(ProfileLockedError) as info:
        stranger.load()
    assert info.value.lost


@pytest.mark.parametrize("encrypt", [False, True])
def test_shredding_the_profile_key_makes_it_unreadable(tmp_path, encrypt):
    store = ProfileStore(tmp_path)
    store.save(_p(encrypt=encrypt))
    store.vault.shred("profile")
    with pytest.raises(ProfileLockedError) as info:
        ProfileStore(tmp_path).load()
    assert info.value.lost


# -- keychain unavailable ----------------------------------------------------------------------


@pytest.mark.parametrize("error", [NoKeychainError("none"), KeychainUnavailableError("locked")])
def test_unavailable_keychain_never_falls_back_to_plaintext(tmp_path, keychain, error):
    store = ProfileStore(tmp_path)
    store.save(_p("阿青", history=()))
    before = store.path.read_bytes()
    keychain.broken = error
    assert not store.can_protect_sensitive()
    for profile in (_p(), _p(history=(), encrypt=True)):
        with pytest.raises(ProfileLockedError) as info:
            store.save(profile)
        assert not info.value.lost
    assert store.path.read_bytes() == before
    _assert_nowhere(tmp_path, *CODES)


def test_locked_keychain_blocks_loading_an_encrypted_profile_without_changing_it(
    tmp_path, keychain
):
    store = ProfileStore(tmp_path)
    store.save(_p())
    before = _all_bytes(tmp_path)
    keychain.broken = KeychainUnavailableError("locked")
    with pytest.raises(ProfileLockedError) as info:
        ProfileStore(tmp_path).load()
    assert not info.value.lost
    assert _all_bytes(tmp_path) == before
    keychain.broken = None
    assert ProfileStore(tmp_path).load() == _p()


# -- migration of a pre-B1 plaintext profile ---------------------------------------------------


def _write_legacy(tmp_path, *versions: PersonaProfile) -> ProfileStore:
    store = ProfileStore(tmp_path)
    for profile in versions:
        atomic_write_text(store.path, _legacy_text(profile))
    return store


def test_legacy_plaintext_profile_is_encrypted_and_its_snapshots_purged(tmp_path, keychain):
    store = _write_legacy(tmp_path, _p("阿青"), _p("阿青"), _p("小林"))
    assert len(snapshot_paths(store.path)) == 2
    loaded = store.load()
    assert loaded == _p("小林") and not store.dropped_sensitive_data
    _assert_nowhere(tmp_path, "clinical_history", *CODES)
    assert ProfileStore(tmp_path).load() == _p("小林")


def test_legacy_corrupt_snapshot_with_sensitive_text_is_purged(tmp_path):
    store = _write_legacy(tmp_path, _p("阿青"), _p("小林"))
    snapshot = snapshot_paths(store.path)[0]
    snapshot.write_text(_legacy_text(_p("阿青"))[:-40], encoding="utf-8")  # truncated
    assert store.load() == _p("小林")
    assert snapshot.exists() is False
    _assert_nowhere(tmp_path, "clinical_history", *CODES)


def test_legacy_profile_without_sensitive_data_is_left_alone(tmp_path, keychain):
    store = _write_legacy(tmp_path, _p(history=()))
    before = store.path.read_bytes()
    assert store.load() == _p(history=())
    assert store.path.read_bytes() == before
    assert keychain.writes == []


def test_legacy_migration_from_a_snapshot_when_the_main_file_is_corrupt(tmp_path):
    store = _write_legacy(tmp_path, _p("阿青"), _p("小林"))
    store.path.write_text('{"schema_version": 1, "clinical_history": ["' + CODES[0], "utf-8")
    assert store.load() == _p("阿青")
    _assert_nowhere(tmp_path, "clinical_history", *CODES)
    assert ProfileStore(tmp_path).load() == _p("阿青")


def test_legacy_sensitive_data_is_dropped_on_a_device_without_keychain(tmp_path, keychain):
    store = _write_legacy(tmp_path, _p("阿青"), _p("小林"))
    keychain.broken = NoKeychainError("none")
    loaded = store.load()
    assert loaded == _p("小林", history=())
    assert store.dropped_sensitive_data
    _assert_nowhere(tmp_path, "clinical_history", *CODES)
    later = ProfileStore(tmp_path)
    assert later.load() == _p("小林", history=()) and not later.dropped_sensitive_data


def test_legacy_migration_waits_while_the_keychain_is_locked(tmp_path, keychain):
    store = _write_legacy(tmp_path, _p("阿青"), _p("小林"))
    before = _all_bytes(tmp_path)
    keychain.broken = KeychainUnavailableError("locked")
    assert store.load() == _p("小林")
    assert not store.dropped_sensitive_data
    assert _all_bytes(tmp_path) == before  # nothing is lost while the keychain is locked
    keychain.broken = None
    assert ProfileStore(tmp_path).load() == _p("小林")
    _assert_nowhere(tmp_path, "clinical_history", *CODES)


# -- the shape of the file, read without the keychain (olivia doctor) --------------------------


@pytest.mark.parametrize(
    ("profile", "sealed"),
    [(_p(history=()), False), (_p(), True), (_p(encrypt=True), True)],
    ids=["plain", "fields", "whole"],
)
def test_profile_shape_needs_no_keychain(tmp_path, keychain, profile, sealed):
    from olivia.core.chang.profile import profile_shape

    store = ProfileStore(tmp_path, Vault(tmp_path, keychain))
    store.save(profile)
    reads = len(keychain.reads)
    keychain.broken = KeychainUnavailableError("locked")
    shape = profile_shape(store.path.read_text(encoding="utf-8"))
    assert shape.sealed is sealed
    assert shape.notifications is (None if profile.enable_at_rest_encryption else False)
    assert len(keychain.reads) == reads


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        "[]",
        json.dumps({"sealed_profile": base64.b64encode(b"plain text").decode()}),
        '{"sealed_profile": "AAAA", "user_name": "x"}',
        '{"schema_version": 1}',
    ],
)
def test_profile_shape_refuses_what_is_not_a_profile(text):
    from olivia.core.chang.profile import profile_shape

    with pytest.raises(ValueError):
        profile_shape(text)
