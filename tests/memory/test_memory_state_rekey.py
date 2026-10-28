"""Re-keying the state store never loses the kit or the method preferences
(``StateStore.rekey``, ``olivia forget --method``, RSK-06).

The re-key used to shred the old key first and only then write the new state, so a
crash (or a failed write) in between lost the kit and every method preference. It now
stages the new state under its own store first (the commit point), and only then shreds
the old key and writes the main file; the next load or save finishes an interrupted
re-key, or discards one interrupted before its commit point.

Fault injection: every operation that changes the disk or the keychain (a file renamed
into place, a file deleted, a keychain item set or deleted) is counted, and the re-key is
killed right after the k-th one, for every k. A fresh process then loads the state: it
must be the old state or the new one, never nothing. Killed in-process (an exception no
``except`` clause catches, after which nothing more reaches the disk or the keychain) and
for real, in a child process with ``os._exit`` and a file-backed keychain.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from olivia.core.crypto.errors import KeychainUnavailableError
from olivia.core.crypto.vault import KEYS_DIRNAME, Vault
from olivia.core.memory import forget as forget_module
from olivia.core.memory import state as state_module
from olivia.core.memory.forget import DataStores, Target, forget_all, forget_kit
from olivia.core.memory.state import (
    STATE_REKEY_FILENAME,
    STATE_REKEY_STORE,
    STATE_STORE,
    CarriedState,
    KitEntry,
    StateStore,
)
from olivia.core.methods.bandit import Feedback, ThompsonSampler
from olivia.core.taxonomy import load_taxonomy

ROOT = Path(__file__).resolve().parents[2]
TAX = load_taxonomy()
NOW = datetime(2026, 10, 22, 23, 30, tzinfo=UTC)


def _old() -> CarriedState:
    sampler = ThompsonSampler(TAX)
    sampler.update("30:grounding", "05", Feedback.UNHELPFUL, NOW)
    sampler.update("12:tipp_breathing", "05", Feedback.HELPFUL, NOW)
    kit = (KitEntry("29:pmr_release", NOW), KitEntry("30:grounding", NOW + timedelta(minutes=1)))
    return CarriedState(sampler.to_dict(), kit)


def _new() -> CarriedState:
    """``_old`` with one method's preference reset, the kit kept."""
    sampler = ThompsonSampler(TAX)
    sampler.update("12:tipp_breathing", "05", Feedback.HELPFUL, NOW)
    return CarriedState(sampler.to_dict(), _old().kit)


class Killed(BaseException):
    """The process died: no ``except Exception`` / ``except OSError`` catches it."""


class Injector:
    """Counts the operations that change the disk or the keychain; kills after the k-th.

    Once killed, every further change raises at once without happening: a dead process
    writes nothing, not even from a ``finally`` clause.
    """

    def __init__(self, kill_after: int | None) -> None:
        self.kill_after = kill_after
        self.count = 0
        self.dead = False

    def __call__(self, operation: Any, *args: Any, **kwargs: Any) -> Any:
        if self.dead:
            raise Killed
        result = operation(*args, **kwargs)
        self.count += 1
        if self.kill_after is not None and self.count >= self.kill_after:
            self.dead = True
            raise Killed
        return result


@pytest.fixture
def inject(keychain):
    """Install an :class:`Injector` over ``os.replace``, ``Path.unlink`` and the keychain;
    ``restore()`` (or the end of the test) takes it away again."""
    installed: list[Injector] = []

    def install(kill_after: int | None) -> Injector:
        injector = Injector(kill_after)
        real_replace, real_unlink = os.replace, Path.unlink
        real_set, real_delete = keychain.set, keychain.delete

        def restore() -> None:
            os.replace, Path.unlink = real_replace, real_unlink  # type: ignore[method-assign]
            keychain.set, keychain.delete = real_set, real_delete

        injector.restore = restore  # type: ignore[attr-defined]
        os.replace = lambda *a, **k: injector(real_replace, *a, **k)
        Path.unlink = lambda self, *a, **k: injector(real_unlink, self, *a, **k)  # type: ignore[method-assign]
        keychain.set = lambda *a: injector(real_set, *a)
        keychain.delete = lambda *a: injector(real_delete, *a)
        installed.append(injector)
        return injector

    yield install
    for injector in reversed(installed):
        injector.restore()  # type: ignore[attr-defined]
    installed.clear()


def _setup(home: Path) -> tuple[bytes, bytes]:
    """The old state saved; its file and its key file as they are now."""
    assert StateStore(home, Vault(home)).save(_old())
    return (home / "state.bin").read_bytes(), (home / KEYS_DIRNAME / "state.key").read_bytes()


def _restarted(home: Path) -> CarriedState | None:
    """What a fresh process reads (which also finishes or discards a re-key)."""
    return StateStore(home, Vault(home)).load()


def _staging_gone(home: Path) -> bool:
    return not (home / STATE_REKEY_FILENAME).exists() and not Vault(home).has_data_key(
        STATE_REKEY_STORE
    )


def _old_copies_open(home: Path, old_file: bytes, old_key: bytes) -> bool:
    (home / "state.bin").write_bytes(old_file)
    (home / KEYS_DIRNAME / "state.key").write_bytes(old_key)
    return _restarted(home) is not None


def _operations(tmp_path: Path, inject: Any) -> int:
    home = tmp_path / "count"
    _setup(home)
    counter = inject(None)
    assert StateStore(home, Vault(home)).rekey(_new()) is True
    counter.restore()
    return counter.count


def test_a_rekey_resets_the_preference_and_crypto_shreds_the_old_one(tmp_path):
    old_file, old_key = _setup(tmp_path)
    assert StateStore(tmp_path, Vault(tmp_path)).rekey(_new()) is True
    assert _restarted(tmp_path) == _new()
    assert _staging_gone(tmp_path)
    assert not _old_copies_open(tmp_path, old_file, old_key)


def test_killed_after_every_step_the_state_is_the_old_or_the_new_never_lost(tmp_path, inject):
    steps = _operations(tmp_path, inject)
    assert steps >= 8  # staging, shred, rotation, rewrite, clean-up: not a vacuous loop
    seen = []
    for k in range(1, steps + 1):
        home = tmp_path / f"k{k}"
        old_file, old_key = _setup(home)
        injector = inject(k)
        with pytest.raises(Killed):
            StateStore(home, Vault(home)).rekey(_new())
        assert injector.count == k
        injector.restore()
        loaded = _restarted(home)
        assert loaded in (_old(), _new()), f"state lost when killed after step {k}"
        seen.append(loaded == _new())
        assert _staging_gone(home), f"staging left after step {k}"
        assert _restarted(home) == loaded  # settled: a second start reads the same
        if loaded == _new():  # finished: the old preference never opens again
            assert not _old_copies_open(home, old_file, old_key), f"old opens after step {k}"
    # Both outcomes occur: before the commit point the old state, after it the new.
    assert seen[0] is False and seen[-1] is True


def test_a_save_after_an_interrupted_rekey_finishes_it_first(tmp_path, inject):
    _setup(tmp_path)
    injector = inject(3)  # staging written, then killed
    with pytest.raises(Killed):
        StateStore(tmp_path, Vault(tmp_path)).rekey(_new())
    injector.restore()
    assert (tmp_path / STATE_REKEY_FILENAME).exists()
    later = CarriedState(_new().bandit, (*_new().kit, KitEntry("12:tipp_breathing", NOW)))
    assert StateStore(tmp_path, Vault(tmp_path)).save(later) is True
    assert _restarted(tmp_path) == later
    assert _staging_gone(tmp_path)


def test_a_failed_write_of_the_new_file_keeps_the_staged_state(tmp_path, monkeypatch):
    _setup(tmp_path)
    store = StateStore(tmp_path, Vault(tmp_path))
    real = state_module.atomic_write_bytes

    def full_disk(path: Path, data: bytes, **kwargs: Any) -> None:
        if path.name == "state.bin":
            raise OSError("no space left")
        real(path, data, **kwargs)

    monkeypatch.setattr(state_module, "atomic_write_bytes", full_disk)
    assert store.rekey(_new()) is False
    monkeypatch.setattr(state_module, "atomic_write_bytes", real)
    assert _restarted(tmp_path) == _new()
    assert _staging_gone(tmp_path)


def test_a_staging_copy_that_does_not_open_is_discarded(tmp_path):
    _setup(tmp_path)
    (tmp_path / STATE_REKEY_FILENAME).write_bytes(b"OLVD" + b"\x00" * 40)
    assert _restarted(tmp_path) == _old()
    assert _staging_gone(tmp_path)


def test_a_locked_keychain_changes_nothing(tmp_path, keychain):
    _setup(tmp_path)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    keychain.broken = KeychainUnavailableError("locked")
    with pytest.raises(KeychainUnavailableError):
        StateStore(tmp_path, Vault(tmp_path, keychain)).rekey(_new())
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before


def test_a_locked_keychain_leaves_an_interrupted_rekey_for_later(tmp_path, inject, keychain):
    _setup(tmp_path)
    injector = inject(5)
    with pytest.raises(Killed):
        StateStore(tmp_path, Vault(tmp_path)).rekey(_new())
    injector.restore()
    keychain.broken = KeychainUnavailableError("locked")
    locked = StateStore(tmp_path, Vault(tmp_path, keychain))
    assert locked.load() is None
    assert locked.save(_old()) is False  # never written over while unfinished
    keychain.broken = None
    assert _restarted(tmp_path) == _new()


def test_shred_also_removes_an_interrupted_rekey(tmp_path, inject):
    _setup(tmp_path)
    injector = inject(3)
    with pytest.raises(Killed):
        StateStore(tmp_path, Vault(tmp_path)).rekey(_new())
    injector.restore()
    StateStore(tmp_path, Vault(tmp_path)).shred()
    assert _staging_gone(tmp_path)
    assert not (tmp_path / "state.bin").exists()
    assert not Vault(tmp_path).has_data_key(STATE_STORE)
    assert _restarted(tmp_path) is None


@pytest.mark.parametrize("everything", [False, True])
def test_forget_removes_an_interrupted_rekey(tmp_path, inject, everything):
    """``forget`` option 4 (the kit) and ``--all`` leave no staging copy and no key."""
    _setup(tmp_path)
    injector = inject(3)
    with pytest.raises(Killed):
        StateStore(tmp_path, Vault(tmp_path)).rekey(_new())
    injector.restore()
    stores = DataStores.open(tmp_path)
    assert forget_module._has_any(stores, Target.KIT)
    if everything:
        assert forget_all(stores) is True
        assert list(tmp_path.iterdir()) == []
    else:
        forget_kit(stores)
        assert not forget_module._has_any(stores, Target.KIT)
        assert _staging_gone(tmp_path) and _restarted(tmp_path) is None


# -- a real kill: os._exit in a child process ------------------------------------------------

_CHILD = r"""
import json, os, sys
from pathlib import Path

home, keyfile, kill_after = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])


class FileKeychain:
    def _items(self):
        return json.loads(keyfile.read_text()) if keyfile.exists() else {}

    def _store(self, items):
        tmp = keyfile.with_suffix(".tmp")
        tmp.write_text(json.dumps(items))
        real_replace(tmp, keyfile)

    def get(self, name):
        return self._items().get(name)

    def set(self, name, value):
        items = self._items()
        items[name] = value
        self._store(items)
        step()

    def delete(self, name):
        items = self._items()
        items.pop(name, None)
        self._store(items)
        step()


count = 0


def step():
    global count
    count += 1
    if kill_after and count >= kill_after:
        os._exit(17)


real_replace, real_unlink = os.replace, Path.unlink


def replace(*args, **kwargs):
    real_replace(*args, **kwargs)
    step()


def unlink(self, *args, **kwargs):
    real_unlink(self, *args, **kwargs)
    step()


from olivia.core.crypto.vault import Vault
from olivia.core.memory.state import StateStore, CarriedState

backend = FileKeychain()
document = json.loads(sys.stdin.read())
os.replace, Path.unlink = replace, unlink
done = StateStore(home, Vault(home, backend)).rekey(CarriedState.from_dict(document))
print(json.dumps({"done": done, "count": count}))
"""


class _FileKeychain:
    """The parent's view of the child's file-backed keychain."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _items(self) -> dict[str, str]:
        return json.loads(self.path.read_text()) if self.path.exists() else {}

    def get(self, name: str) -> str | None:
        return self._items().get(name)

    def set(self, name: str, value: str) -> None:
        items = self._items()
        items[name] = value
        self.path.write_text(json.dumps(items))

    def delete(self, name: str) -> None:
        items = self._items()
        items.pop(name, None)
        self.path.write_text(json.dumps(items))


def _child(home: Path, keyfile: Path, kill_after: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", _CHILD, str(home), str(keyfile), str(kill_after)],
        input=json.dumps(_new().to_dict()),
        capture_output=True,
        text=True,
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
        check=False,
    )


def test_killed_for_real_after_every_step_nothing_is_lost(tmp_path):
    def setup(name: str) -> tuple[Path, _FileKeychain]:
        home = tmp_path / name
        keys = _FileKeychain(tmp_path / f"{name}.keychain.json")
        assert StateStore(home, Vault(home, keys)).save(_old())
        return home, keys

    home, keys = setup("full")
    full = _child(home, keys.path, 0)
    assert full.returncode == 0, full.stderr
    steps = json.loads(full.stdout)["count"]
    assert steps >= 8
    assert StateStore(home, Vault(home, keys)).load() == _new()

    outcomes = []
    for k in range(1, steps + 1):
        home, keys = setup(f"k{k}")
        killed = _child(home, keys.path, k)
        assert killed.returncode == 17, killed.stderr
        loaded = StateStore(home, Vault(home, keys)).load()
        assert loaded in (_old(), _new()), f"state lost when killed after step {k}"
        assert not (home / STATE_REKEY_FILENAME).exists()
        assert not Vault(home, keys).has_data_key(STATE_REKEY_STORE)
        outcomes.append(loaded == _new())
    assert outcomes[0] is False and outcomes[-1] is True
