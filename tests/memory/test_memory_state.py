"""The cross-session state store: format, encryption at rest, damage, versions (B3)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from olivia.core.crypto.errors import CryptoError, KeychainUnavailableError, NoKeychainError
from olivia.core.crypto.vault import Vault
from olivia.core.memory.state import (
    FORMAT_VERSION,
    KIT_MAX,
    STATE_FILENAME,
    STATE_STORE,
    CarriedState,
    KitEntry,
    StateRecorder,
    StateStore,
    restore_sampler,
)
from olivia.core.methods.bandit import Feedback, ThompsonSampler
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
NOW = datetime(2026, 10, 22, 23, 30, tzinfo=UTC)
# Action ids long enough that a chance match inside ciphertext is out of the question.
LONG_IDS = ("12:tipp_breathing", "30:grounding", "29:pmr_release")


def _bandit() -> dict[str, object]:
    sampler = ThompsonSampler(TAX)
    sampler.update("30:grounding", "05", Feedback.UNHELPFUL, NOW)
    sampler.update("12:tipp_breathing", "05", Feedback.HELPFUL, NOW)
    return sampler.to_dict()


def _state(kit: tuple[str, ...] = ("29:pmr_release",)) -> CarriedState:
    entries = tuple(KitEntry(aid, NOW + timedelta(minutes=i)) for i, aid in enumerate(kit))
    return CarriedState(_bandit(), entries)


@pytest.fixture
def store(tmp_path, keychain):
    return StateStore(tmp_path, Vault(tmp_path, keychain))


def _write_plain(store: StateStore, payload: object) -> None:
    """Seal an arbitrary document with the store's own key, as a damaged or future file."""
    raw = json.dumps(payload).encode("utf-8")
    store.path.write_bytes(store.vault.seal(STATE_STORE, raw, label="state"))


# -- round trip and format -------------------------------------------------------------------


def test_round_trip(store):
    state = _state(LONG_IDS)
    assert store.load() is None
    assert store.save(state) is True
    assert store.path.name == STATE_FILENAME
    again = StateStore(store.path.parent, store.vault).load()
    assert again == state
    # The sampler restores to the same posteriors.
    restored = restore_sampler(TAX, again.bandit)
    assert restored.to_dict() == state.bandit
    assert restored.posterior("30:grounding", "05", NOW) != ThompsonSampler(TAX).posterior(
        "30:grounding", "05", NOW
    )


def test_document_holds_only_the_sampler_and_the_kit(store):
    store.save(_state(LONG_IDS))
    document = json.loads(store.vault.open(STATE_STORE, store.path.read_bytes(), label="state"))
    assert set(document) == {"olivia_state", "bandit", "kit"}
    assert document["olivia_state"] == FORMAT_VERSION
    assert document["kit"][0] == {"id": LONG_IDS[0], "at": NOW.isoformat()}
    assert all(set(item) == {"id", "at"} for item in document["kit"])


def test_kit_keeps_the_newest_entries_only(store):
    ids = tuple(f"{n:02d}" for n in range(1, KIT_MAX + 4))
    state = _state(ids)
    store.save(state)
    loaded = store.load()
    assert loaded is not None
    assert [e.action_id for e in loaded.kit] == list(ids[-KIT_MAX:])


def test_encrypted_at_rest(store):
    store.save(_state(LONG_IDS))
    raw = store.path.read_bytes()
    for needle in (*LONG_IDS, "spectra", "alpha", "olivia_state", "kit"):
        assert needle.encode() not in raw
    # Moved under another store's key, it does not open.
    with pytest.raises(CryptoError):
        store.vault.open("ledger", raw, label="state")


def test_naive_kit_times_are_refused():
    with pytest.raises(ValueError):
        KitEntry("30", datetime(2026, 10, 22, 23, 30))


# -- damage, versions, keychain --------------------------------------------------------------


@pytest.mark.parametrize(
    "damage",
    [
        lambda path: path.write_bytes(b"not a sealed blob"),
        lambda path: path.write_bytes(path.read_bytes()[:-3] + b"xyz"),
    ],
)
def test_corrupt_file_starts_fresh_and_is_overwritten(store, damage):
    store.save(_state())
    damage(store.path)
    assert store.load() is None
    assert store.save(_state(LONG_IDS)) is True
    assert store.load() == _state(LONG_IDS)


@pytest.mark.parametrize(
    "payload",
    [
        {"olivia_state": FORMAT_VERSION, "bandit": {"spectra": {}}},
        {"olivia_state": FORMAT_VERSION, "bandit": {"spectra": {}}, "kit": "30"},
        {"olivia_state": FORMAT_VERSION, "bandit": [], "kit": []},
        {"olivia_state": FORMAT_VERSION, "bandit": {"spectra": {}}, "kit": [{"id": "30"}]},
        {"olivia_state": FORMAT_VERSION, "bandit": {"spectra": {}}, "kit": [{"id": 3, "at": ""}]},
        {
            "olivia_state": FORMAT_VERSION,
            "bandit": {"spectra": {}},
            "kit": [{"id": "30", "at": "2026-10-22T23:30:00"}],  # naive time
        },
        {"olivia_state": "1", "bandit": {"spectra": {}}, "kit": []},
        {"olivia_state": 0, "bandit": {"spectra": {}}, "kit": []},
        ["not", "a", "mapping"],
    ],
)
def test_malformed_document_is_corrupt(store, payload):
    _write_plain(store, payload)
    assert store.load() is None
    assert store.save(_state()) is True  # overwritten
    assert store.load() == _state()


def test_future_version_is_ignored_and_never_overwritten(store):
    _write_plain(store, {"olivia_state": FORMAT_VERSION + 1, "something": "new"})
    before = store.path.read_bytes()
    assert store.load() is None
    assert store.save(_state()) is False
    assert store.path.read_bytes() == before


def test_shredded_key_is_corrupt(store):
    store.save(_state())
    store.vault.shred(STATE_STORE)
    assert store.load() is None
    assert store.save(_state(LONG_IDS)) is True
    assert store.load() == _state(LONG_IDS)


def test_locked_keychain_keeps_the_file(store, keychain):
    store.save(_state())
    before = store.path.read_bytes()
    keychain.broken = KeychainUnavailableError("locked")
    fresh = StateStore(store.path.parent, Vault(store.path.parent, keychain))
    assert fresh.load() is None
    assert fresh.save(_state(LONG_IDS)) is False
    keychain.broken = None
    assert fresh.save(_state(LONG_IDS)) is False  # loaded while locked: never overwrite
    assert store.path.read_bytes() == before


def test_no_keychain_writes_nothing(tmp_path, keychain):
    keychain.broken = NoKeychainError("none")
    store = StateStore(tmp_path, Vault(tmp_path, keychain))
    assert store.load() is None
    with pytest.raises(NoKeychainError):
        store.save(_state())
    assert list(tmp_path.rglob("*")) == []


def test_shred_removes_the_file_and_the_key(store):
    store.save(_state())
    store.shred()
    assert not store.path.exists()
    assert not store.vault.has_data_key(STATE_STORE)
    assert store.load() is None
    store.shred()  # twice is fine


# -- the sampler restore ---------------------------------------------------------------------


def test_restore_without_state_is_a_fresh_sampler():
    assert restore_sampler(TAX, None).to_dict() == ThompsonSampler(TAX).to_dict()


def test_restore_drops_arms_the_taxonomy_no_longer_knows():
    bandit = _bandit()
    spectra = bandit["spectra"]
    assert isinstance(spectra, dict)
    spectra["05"]["99:gone"] = {"alpha": 1.0, "beta": 1.0, "last_unhelpful_at": None}
    spectra["zz"] = {"30": {"alpha": 1.0, "beta": 1.0, "last_unhelpful_at": None}}
    spectra["02"] = {"30": {"alpha": -1.0, "beta": 1.0, "last_unhelpful_at": None}}
    restored = restore_sampler(TAX, bandit).to_dict()
    assert restored == _bandit()


@pytest.mark.parametrize("bandit", [{}, {"spectra": []}, {"spectra": {}, "x": 1}, "nope"])
def test_restore_of_a_malformed_sampler_is_fresh(bandit):
    assert restore_sampler(TAX, bandit).to_dict() == ThompsonSampler(TAX).to_dict()


# -- the recorder ----------------------------------------------------------------------------


def test_recorder_saves_only_changes(store, monkeypatch):
    baseline = _state()
    recorder = StateRecorder(store, baseline)
    recorder.observe(baseline)
    assert not store.path.exists()
    changed = _state(LONG_IDS)
    recorder.observe(changed)
    assert store.load() == changed
    writes = []
    monkeypatch.setattr(store, "save", lambda state: writes.append(state) or True)
    recorder.observe(changed)
    assert writes == []


def test_recorder_stops_without_a_keychain(tmp_path, keychain):
    keychain.broken = NoKeychainError("none")
    store = StateStore(tmp_path, Vault(tmp_path, keychain))
    recorder = StateRecorder(store, _state())
    recorder.observe(_state(LONG_IDS))  # no exception, nothing written
    assert recorder.disabled
    assert list(tmp_path.rglob("*")) == []


def test_recorder_retries_after_a_locked_keychain(store, keychain):
    recorder = StateRecorder(store, _state())
    keychain.broken = KeychainUnavailableError("locked")
    recorder.observe(_state(LONG_IDS))
    assert not store.path.exists()
    keychain.broken = None
    recorder.observe(_state(LONG_IDS))
    assert store.load() == _state(LONG_IDS)
