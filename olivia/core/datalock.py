"""One writer per data directory: a cross-platform advisory process lock.

Two OLIVIA processes that both write one data directory overwrite each other: the first
master key, the kit, a store key one of them still holds in memory (robustness findings
D1-D3). Every command that writes data takes :class:`DataDirLock` first; a second one
gets :class:`DataDirBusyError` and changes nothing. Read-only commands (``resources``,
``privacy``, ``doctor``, ``memory``, ``stats``, help and version) never take it, so the
hotline numbers are always one command away.

The lock is ``fcntl.flock`` on POSIX and ``msvcrt.locking`` on Windows, held on the file
:data:`LOCK_FILENAME` inside the data directory (created 0600, empty, no user data). The
operating system drops it when the process ends, crashes included, so a stale lock never
blocks the next run. On POSIX the file is removed on release; a process that opened it
just before then notices (the path no longer names the file it locked) and tries again.

:func:`held` tells :mod:`olivia.core.storage` whether this process holds the lock for a
directory, so stray temporary files there can only be another crashed writer's.
"""

from __future__ import annotations

import contextlib
import os
import sys
from pathlib import Path
from types import TracebackType
from typing import Final

LOCK_FILENAME: Final = ".olivia.lock"
_PRIVATE_MODE: Final = 0o600
_RETRIES: Final = 3

_held: set[Path] = set()


class DataDirBusyError(Exception):
    """Another process holds the data directory's lock."""


def held(path: Path) -> bool:
    """Whether this process holds the lock of ``path`` or of a directory above it."""
    try:
        resolved = path.resolve()
    except OSError:
        return False
    return any(resolved == base or base in resolved.parents for base in _held)


def _try_lock(fd: int) -> bool:
    if sys.platform == "win32":  # pragma: no cover - Windows only
        import msvcrt

        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True
    else:
        import fcntl

        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True


def _same_file(fd: int, path: Path) -> bool:
    """Whether ``path`` still names the file open as ``fd`` (not removed or replaced)."""
    try:
        on_disk = path.stat()
    except FileNotFoundError:
        return False
    mine = os.fstat(fd)
    return (on_disk.st_dev, on_disk.st_ino) == (mine.st_dev, mine.st_ino)


class DataDirLock:
    """The exclusive lock of one data directory (which must exist).

    Use as a context manager, or :meth:`acquire` / :meth:`release`. ``acquire`` never
    waits: it raises :class:`DataDirBusyError` at once when another process holds it.
    """

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.path: Path = directory / LOCK_FILENAME
        self._fd: int | None = None

    @property
    def locked(self) -> bool:
        return self._fd is not None

    def acquire(self) -> None:
        if self._fd is not None:
            return
        for _ in range(_RETRIES):
            fd = os.open(self.path, os.O_RDWR | os.O_CREAT, _PRIVATE_MODE)
            if not _try_lock(fd):
                os.close(fd)
                raise DataDirBusyError("another OLIVIA process is using this data directory")
            if os.name == "nt" or _same_file(fd, self.path):  # pragma: no branch
                self._fd = fd
                _held.add(self.directory.resolve())
                return
            os.close(fd)  # the holder removed it while we opened it: try the new one
        raise DataDirBusyError("the data directory's lock keeps changing")

    def release(self) -> None:
        fd = self._fd
        if fd is None:
            return
        self._fd = None
        _held.discard(self.directory.resolve())
        if os.name != "nt":
            with contextlib.suppress(OSError):
                if _same_file(fd, self.path):
                    self.path.unlink()  # while still locked: no one can be holding it
        os.close(fd)

    def __enter__(self) -> DataDirLock:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()
