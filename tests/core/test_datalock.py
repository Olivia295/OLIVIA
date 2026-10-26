"""The data-directory process lock (robustness findings D1-D3)."""

import os
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from olivia.core import datalock
from olivia.core.datalock import LOCK_FILENAME, DataDirBusyError, DataDirLock


def test_a_second_holder_is_refused_at_once(tmp_path):
    with DataDirLock(tmp_path), pytest.raises(DataDirBusyError):
        DataDirLock(tmp_path).acquire()


def test_release_lets_the_next_one_in_and_leaves_no_file(tmp_path):
    lock = DataDirLock(tmp_path)
    lock.acquire()
    lock.release()
    with DataDirLock(tmp_path) as again:
        assert again.locked
    if os.name != "nt":
        assert not (tmp_path / LOCK_FILENAME).exists()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
def test_lock_file_is_owner_only(tmp_path):
    with DataDirLock(tmp_path):
        mode = stat.S_IMODE((tmp_path / LOCK_FILENAME).stat().st_mode)
    assert mode == 0o600


def test_held_covers_the_directory_and_below(tmp_path):
    assert not datalock.held(tmp_path)
    with DataDirLock(tmp_path):
        assert datalock.held(tmp_path)
        assert datalock.held(tmp_path / "keys" / "ledger.key")
        assert not datalock.held(tmp_path.parent)
    assert not datalock.held(tmp_path)


def test_another_process_is_refused_and_a_crash_releases_it(tmp_path):
    script = textwrap.dedent(
        """
        import os, sys
        from pathlib import Path
        from olivia.core.datalock import DataDirBusyError, DataDirLock
        lock = DataDirLock(Path(sys.argv[1]))
        try:
            lock.acquire()
        except DataDirBusyError:
            print("busy", flush=True)
            sys.exit(0)
        print("locked", flush=True)
        if sys.argv[2] == "crash":
            os._exit(137)
        """
    )
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2])}

    def child(mode: str) -> str:
        done = subprocess.run(
            [sys.executable, "-c", script, str(tmp_path), mode],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
            check=False,
        )
        return done.stdout.strip()

    with DataDirLock(tmp_path):
        assert child("hold") == "busy"
    assert child("crash") == "locked"  # killed while holding it
    assert child("hold") == "locked"  # the operating system dropped it
