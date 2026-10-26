import os
import stat
import sys
import time
from pathlib import Path

import pytest

from olivia.core import storage
from olivia.core.datalock import DataDirLock
from olivia.core.storage import (
    SNAPSHOT_KEEP,
    StorageAccessError,
    StorageCorruptError,
    app_data_dir,
    atomic_write_text,
    read_text_with_recovery,
    read_with_recovery,
    snapshot_paths,
    snapshot_time,
)


def test_app_data_dir_respects_env_and_is_private(tmp_path, monkeypatch):
    target = tmp_path / "home"
    monkeypatch.setenv("OLIVIA_HOME", str(target))
    assert app_data_dir() == target and target.is_dir()
    if sys.platform != "win32":
        assert stat.S_IMODE(target.stat().st_mode) == 0o700


def test_app_data_dir_does_not_chmod_existing_directory(tmp_path, monkeypatch):
    target = tmp_path / "home"
    target.mkdir()
    if sys.platform != "win32":
        target.chmod(0o755)
    monkeypatch.setenv("OLIVIA_HOME", str(target))
    assert app_data_dir() == target
    if sys.platform != "win32":
        assert stat.S_IMODE(target.stat().st_mode) == 0o755


def test_app_data_dir_falls_back_to_platformdirs(tmp_path, monkeypatch):
    monkeypatch.delenv("OLIVIA_HOME", raising=False)
    target = tmp_path / "platform" / "olivia"
    monkeypatch.setattr(storage.platformdirs, "user_data_path", lambda *a, **k: target)
    assert app_data_dir() == target and target.is_dir()


def test_write_and_read_chinese_text(tmp_path):
    p = tmp_path / "ledger.md"
    atomic_write_text(p, "今天辛苦了。\n")
    assert read_text_with_recovery(p, lambda s: True) == "今天辛苦了。\n"


def test_keeps_only_three_snapshots(tmp_path):
    p = tmp_path / "ledger.md"
    for i in range(6):
        atomic_write_text(p, f"v{i}")
    snaps = snapshot_paths(p)
    assert len(snaps) == SNAPSHOT_KEEP == 3
    assert [s.read_text(encoding="utf-8") for s in snaps] == ["v4", "v3", "v2"]
    assert p.read_text(encoding="utf-8") == "v5"


def test_snapshot_order_is_stable_when_clock_does_not_advance(tmp_path, monkeypatch):
    monkeypatch.setattr(storage.time, "time_ns", lambda: 1_000)
    p = tmp_path / "ledger.md"
    for i in range(6):
        atomic_write_text(p, f"v{i}")
    snaps = snapshot_paths(p)
    assert [s.read_text(encoding="utf-8") for s in snaps] == ["v4", "v3", "v2"]


def test_snapshot_order_is_numeric_not_lexical(tmp_path):
    p = tmp_path / "ledger.md"
    snap_dir = tmp_path / ".snapshots" / "ledger.md"
    snap_dir.mkdir(parents=True)
    (snap_dir / "999").write_text("old", encoding="utf-8")
    (snap_dir / "1000").write_text("new", encoding="utf-8")
    assert [s.name for s in snapshot_paths(p)] == ["1000", "999"]


def test_snapshot_paths_ignores_other_files_snapshots(tmp_path):
    p = tmp_path / "a.json"
    snap_dir = tmp_path / ".snapshots" / "a.json"
    snap_dir.mkdir(parents=True)
    (snap_dir / "5").write_text("x", encoding="utf-8")
    (snap_dir / "bak.7").write_text("y", encoding="utf-8")
    (snap_dir / "notes.txt").write_text("z", encoding="utf-8")
    other = tmp_path / ".snapshots" / "a.json.bak"
    other.mkdir()
    (other / "7").write_text("w", encoding="utf-8")
    assert [s.name for s in snapshot_paths(p)] == ["5"]
    assert snapshot_paths(tmp_path / "none.json") == []


def test_crash_before_replace_keeps_old_content(tmp_path, monkeypatch):
    p = tmp_path / "ledger.md"
    atomic_write_text(p, "old")

    def boom(*a, **k):
        raise OSError("power loss")

    monkeypatch.setattr(storage.os, "replace", boom)
    with pytest.raises(OSError):
        atomic_write_text(p, "new")
    monkeypatch.undo()
    assert read_text_with_recovery(p, lambda s: True) == "old"
    assert not list(tmp_path.glob("*.tmp"))  # the failed write cleaned up its temp file


def test_leftover_tmp_file_is_ignored(tmp_path):
    p = tmp_path / "ledger.md"
    atomic_write_text(p, "good")
    (tmp_path / ".ledger.md.abc123.tmp").write_text("half-writ", encoding="utf-8")
    (tmp_path / "ledger.md.tmp").write_text("legacy-half", encoding="utf-8")
    assert read_text_with_recovery(p, lambda s: True) == "good"
    atomic_write_text(p, "better")
    assert read_text_with_recovery(p, lambda s: True) == "better"


def test_corrupt_main_falls_back_to_newest_valid_snapshot(tmp_path):
    p = tmp_path / "data.json"
    atomic_write_text(p, '{"v": 1}')
    atomic_write_text(p, '{"v": 2}')
    p.write_text('{"v": 3', encoding="utf-8")  # 截断

    def is_json(s: str) -> bool:
        return s.startswith("{") and s.endswith("}")

    assert read_text_with_recovery(p, is_json) == '{"v": 1}'


def test_non_utf8_main_falls_back_to_snapshot(tmp_path):
    p = tmp_path / "data.txt"
    atomic_write_text(p, "good")
    atomic_write_text(p, "newer")
    p.write_bytes(b"\xff\xfe\x00bad")
    assert read_text_with_recovery(p, lambda s: True) == "good"


def test_missing_main_recovers_from_snapshot(tmp_path):
    p = tmp_path / "data.txt"
    atomic_write_text(p, "one")
    atomic_write_text(p, "two")
    p.unlink()
    assert read_text_with_recovery(p, lambda s: True) == "one"


def test_no_valid_version_raises(tmp_path):
    p = tmp_path / "data.json"
    p.write_text("garbage", encoding="utf-8")
    with pytest.raises(StorageCorruptError):
        read_text_with_recovery(p, lambda s: False)


def test_missing_everything_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_text_with_recovery(tmp_path / "absent.json", lambda s: True)


def test_write_creates_parent_directory(tmp_path):
    p: Path = tmp_path / "sub" / "dir" / "f.txt"
    atomic_write_text(p, "hi")
    assert p.read_text(encoding="utf-8") == "hi"


def test_files_with_overlapping_names_keep_separate_snapshots(tmp_path):
    log = tmp_path / "log"
    log7 = tmp_path / "log.7"
    for i in range(3):
        atomic_write_text(log7, f"seven-{i}")
    before = [s.read_text(encoding="utf-8") for s in snapshot_paths(log7)]
    assert before == ["seven-1", "seven-0"]
    for i in range(6):
        atomic_write_text(log, f"log-{i}")
    assert [s.read_text(encoding="utf-8") for s in snapshot_paths(log7)] == before
    assert [s.read_text(encoding="utf-8") for s in snapshot_paths(log)] == [
        "log-4",
        "log-3",
        "log-2",
    ]
    log.write_text("corrupt", encoding="utf-8")
    recovered = read_text_with_recovery(log, lambda s: s.startswith("log-"))
    assert recovered == "log-4"
    assert read_text_with_recovery(log7, lambda s: True) == "seven-2"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_main_file_and_snapshots_are_owner_only(tmp_path):
    p = tmp_path / "ledger.md"
    for i in range(3):
        atomic_write_text(p, f"v{i}")
    assert stat.S_IMODE(p.stat().st_mode) == 0o600
    snaps = snapshot_paths(p)
    assert snaps
    for snap in snaps:
        assert stat.S_IMODE(snap.stat().st_mode) == 0o600


# -- leftovers of a killed writer (robustness S4) -------------------------------------------


def test_a_writer_holding_the_lock_removes_its_files_stray_temps(tmp_path):
    p = tmp_path / "profile.json"
    atomic_write_text(p, "one")
    stray = tmp_path / ".profile.json.k1ll3d00.tmp"
    stray.write_text('{"user_name": "小林"}', encoding="utf-8")
    others = [tmp_path / ".state.bin.k1ll3d00.tmp", tmp_path / "profile.json.tmp"]
    for other in others:
        other.write_text("x", encoding="utf-8")
    with DataDirLock(tmp_path):
        atomic_write_text(p, "two")
    assert not stray.exists()
    assert all(other.exists() for other in others)


def test_without_the_lock_only_old_stray_temps_are_removed(tmp_path):
    p = tmp_path / "profile.json"
    fresh = tmp_path / ".profile.json.fresh000.tmp"
    old = tmp_path / ".profile.json.old00000.tmp"
    for stray in (fresh, old):
        stray.write_text("x", encoding="utf-8")
    long_ago = time.time() - 2 * storage.STRAY_TEMP_AGE
    os.utime(old, (long_ago, long_ago))
    atomic_write_text(p, "one")
    assert fresh.exists() and not old.exists()


# -- files the operating system will not open (robustness C2) ---------------------------------


def test_a_directory_in_place_of_the_file_is_an_access_error(tmp_path):
    p = tmp_path / "profile.json"
    p.mkdir()
    with pytest.raises(StorageAccessError):
        read_text_with_recovery(p, lambda s: True)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
def test_an_unreadable_file_is_an_access_error_not_a_reason_to_roll_back(tmp_path):
    p = tmp_path / "profile.json"
    atomic_write_text(p, "one")
    atomic_write_text(p, "two")
    p.chmod(0)
    try:
        with pytest.raises(StorageAccessError):
            read_text_with_recovery(p, lambda s: True)
    finally:
        p.chmod(0o600)


def test_recovery_says_which_version_it_read(tmp_path):
    p = tmp_path / "data.txt"
    atomic_write_text(p, "one")
    atomic_write_text(p, "two")
    assert read_with_recovery(p, lambda s: True) == ("two", p)
    p.write_bytes(b"\xff")
    text, source = read_with_recovery(p, lambda s: True)
    assert text == "one" and source == snapshot_paths(p)[0]
    assert snapshot_time(source) is not None and snapshot_time(p) is None
