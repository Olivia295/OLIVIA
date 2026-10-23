"""Forgetting one ledger entry re-keys the ledger (``Ledger.forget_entry``, B5).

The forgotten entry's old ciphertext, and the old key file, never open again; the other
entries survive under a fresh key. An interruption at any step leaves every surviving
entry readable under some key, and the next read or write finishes (or, before the
commit marker, discards) the re-key.
"""

from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from olivia.core.crypto.errors import KeychainUnavailableError
from olivia.core.crypto.vault import KEYS_DIRNAME, Vault
from olivia.core.memory import ledger as ledger_module
from olivia.core.memory.ledger import (
    LEDGER_DIRNAME,
    LEDGER_STORE,
    REKEY_STORE,
    Ledger,
    LedgerUnavailableError,
    NoteEntry,
)

SHANGHAI = timezone(timedelta(hours=8))
START = datetime(2026, 10, 22, 23, 30, tzinfo=SHANGHAI)
TEXTS = ("第一条", "第二条", "第三条")


class Interrupted(Exception):
    """Stands in for a crash."""


def _setup(home: Path) -> tuple[Ledger, list[str]]:
    ledger = Ledger(home, Vault(home))
    ids = [ledger.add_note(text, now=START + timedelta(minutes=i)) for i, text in enumerate(TEXTS)]
    return ledger, ids


def _texts(home: Path) -> list[str]:
    """The notes a fresh process reads (which also finishes an interrupted re-key)."""
    return [e.text for e in Ledger(home, Vault(home)).entries() if isinstance(e, NoteEntry)]


def _staging_gone(home: Path) -> bool:
    vault = Vault(home)
    return not (home / LEDGER_DIRNAME / ".rekey").exists() and not vault.has_data_key(REKEY_STORE)


def _entry(home: Path, entry_id: str) -> Path:
    return home / LEDGER_DIRNAME / f"{entry_id}.olv"


def test_the_forgotten_entry_never_opens_again_and_the_rest_survive(tmp_path, keychain):
    ledger, ids = _setup(tmp_path)
    old_entry = _entry(tmp_path, ids[1]).read_bytes()
    old_key = (tmp_path / KEYS_DIRNAME / f"{LEDGER_STORE}.key").read_bytes()

    assert ledger.forget_entry(ids[1]) == 0
    assert not _entry(tmp_path, ids[1]).exists()
    assert _texts(tmp_path) == ["第一条", "第三条"]
    assert _staging_gone(tmp_path)

    # The old ciphertext, copied back, does not open under the new key ...
    _entry(tmp_path, ids[1]).write_bytes(old_entry)
    fresh = Ledger(tmp_path, Vault(tmp_path))
    assert [e.entry_id for e in fresh.entries()] == [ids[0], ids[2]] and fresh.skipped == 1
    # ... nor with the old key file: the master key it was wrapped with is gone.
    (tmp_path / KEYS_DIRNAME / f"{LEDGER_STORE}.key").write_bytes(old_key)
    fresh = Ledger(tmp_path, Vault(tmp_path))
    assert fresh.entries() == () and fresh.skipped == 3


def test_entries_that_do_not_open_are_dropped_and_counted(tmp_path):
    ledger, ids = _setup(tmp_path)
    junk = tmp_path / LEDGER_DIRNAME / f"{'ab' * 12}.olv"
    junk.write_bytes(b"not sealed")
    assert ledger.forget_entry(ids[0]) == 1
    assert not junk.exists()
    assert _texts(tmp_path) == ["第二条", "第三条"]


def test_forgetting_the_only_entry_leaves_an_empty_ledger(tmp_path):
    ledger = Ledger(tmp_path, Vault(tmp_path))
    only = ledger.add_note("唯一一条", now=START)
    assert ledger.forget_entry(only) == 0
    assert ledger.entry_paths() == [] and _texts(tmp_path) == []
    assert not Vault(tmp_path).has_data_key(LEDGER_STORE)


def test_a_locked_keychain_changes_nothing(tmp_path, keychain):
    ledger, ids = _setup(tmp_path)
    keychain.broken = KeychainUnavailableError("locked")
    with pytest.raises(LedgerUnavailableError):
        Ledger(tmp_path, Vault(tmp_path)).forget_entry(ids[0])
    keychain.broken = None
    assert _texts(tmp_path) == list(TEXTS)


def test_not_an_entry_id(tmp_path):
    with pytest.raises(ValueError):
        Ledger(tmp_path, Vault(tmp_path)).forget_entry("../profile")


# -- interruptions ----------------------------------------------------------------------------


# Each crash is simulated inside its own ``pytest.MonkeyPatch.context()``: calling
# ``monkeypatch.undo()`` instead would also undo the suite's in-memory keychain and let a
# later Vault reach the real OS keychain.


def _fail_writes(mp: pytest.MonkeyPatch, when) -> None:
    real = ledger_module.atomic_write_bytes

    def write(path: Path, data: bytes, *, snapshot: bool = True) -> None:
        if when(path):
            raise Interrupted
        real(path, data, snapshot=snapshot)

    mp.setattr(ledger_module, "atomic_write_bytes", write)


def _fail_shred(mp: pytest.MonkeyPatch, store: str) -> None:
    real = Vault.shred

    def shred(self: Vault, name: str) -> None:
        if name == store:
            raise Interrupted
        real(self, name)

    mp.setattr(Vault, "shred", shred)


def test_interrupted_before_the_commit_marker_changes_nothing(tmp_path):
    ledger, ids = _setup(tmp_path)
    with pytest.MonkeyPatch.context() as mp, pytest.raises(Interrupted):
        _fail_writes(mp, lambda p: p.name == "complete")
        ledger.forget_entry(ids[1])
    assert (tmp_path / LEDGER_DIRNAME / ".rekey").is_dir()  # left behind by the crash
    assert _texts(tmp_path) == list(TEXTS)  # discarded: the entry was not forgotten
    assert _staging_gone(tmp_path)


def test_interrupted_right_after_the_commit_marker_is_finished_on_the_next_read(tmp_path):
    ledger, ids = _setup(tmp_path)
    old_entry = _entry(tmp_path, ids[1]).read_bytes()
    with pytest.MonkeyPatch.context() as mp, pytest.raises(Interrupted):
        _fail_shred(mp, LEDGER_STORE)
        ledger.forget_entry(ids[1])
    assert _texts(tmp_path) == ["第一条", "第三条"]
    assert _staging_gone(tmp_path)
    _entry(tmp_path, ids[1]).write_bytes(old_entry)
    assert _texts(tmp_path) == ["第一条", "第三条"]


def test_interrupted_while_rewriting_leaves_the_staged_copies_readable(tmp_path):
    ledger, ids = _setup(tmp_path)
    live = tmp_path / LEDGER_DIRNAME
    writes: list[Path] = []

    def second_live_write(path: Path) -> bool:
        if path.parent == live and path.suffix == ".olv":
            writes.append(path)
        return len(writes) == 2

    with pytest.MonkeyPatch.context() as mp, pytest.raises(Interrupted):
        _fail_writes(mp, second_live_write)
        ledger.forget_entry(ids[0])
    # One survivor is back under the new key, the other only staged: nothing is lost.
    assert len(list(live.glob("*.olv"))) == 1
    assert _texts(tmp_path) == ["第二条", "第三条"]
    assert _staging_gone(tmp_path)


def test_interrupted_while_cleaning_up_the_staging(tmp_path):
    ledger, ids = _setup(tmp_path)
    with pytest.MonkeyPatch.context() as mp, pytest.raises(Interrupted):
        _fail_shred(mp, REKEY_STORE)
        ledger.forget_entry(ids[2])
    assert _texts(tmp_path) == ["第一条", "第二条"]
    assert _staging_gone(tmp_path)


def test_a_write_after_an_interruption_finishes_the_rekey_first(tmp_path):
    ledger, ids = _setup(tmp_path)
    with pytest.MonkeyPatch.context() as mp, pytest.raises(Interrupted):
        _fail_shred(mp, LEDGER_STORE)
        ledger.forget_entry(ids[1])
    Ledger(tmp_path, Vault(tmp_path)).add_note("第四条", now=START + timedelta(hours=1))
    assert _texts(tmp_path) == ["第一条", "第三条", "第四条"]


def test_shred_also_removes_an_interrupted_rekey(tmp_path):
    ledger, ids = _setup(tmp_path)
    with pytest.MonkeyPatch.context() as mp, pytest.raises(Interrupted):
        _fail_shred(mp, LEDGER_STORE)
        ledger.forget_entry(ids[1])
    staged = {p.name: p.read_bytes() for p in (tmp_path / LEDGER_DIRNAME / ".rekey").iterdir()}
    Ledger(tmp_path, Vault(tmp_path)).shred()
    assert _staging_gone(tmp_path) and _texts(tmp_path) == []
    # The staged copies, put back, open under no key.
    shutil.rmtree(tmp_path / LEDGER_DIRNAME, ignore_errors=True)
    (tmp_path / LEDGER_DIRNAME / ".rekey").mkdir(parents=True)
    for name, data in staged.items():
        (tmp_path / LEDGER_DIRNAME / ".rekey" / name).write_bytes(data)
    assert _texts(tmp_path) == []
