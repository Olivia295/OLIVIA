"""Application data directory and crash-safe file writes.

``atomic_write_text`` follows the shadow-write order of SDD section 6.5:
snapshot the current file, write a temporary sibling, fsync, then rename it
over the target. A crash at any point leaves either the previous or the new
content intact, and up to :data:`SNAPSHOT_KEEP` older versions can be used to
recover from a corrupted main file.

A writer killed between creating its temporary sibling and renaming it leaves
``.<name>.<random>.tmp`` behind, possibly holding plaintext (robustness finding S4). Every
write removes the stray temporary files of its own target first: all of them while this
process holds the data directory's lock (:mod:`olivia.core.datalock`: no other writer can
be mid-write), otherwise only those older than :data:`STRAY_TEMP_AGE`.

A file the operating system refuses to read (a directory in its place, no permission) is
not "damaged": :func:`read_with_recovery` raises :class:`StorageAccessError` instead of
falling back to an older snapshot, which a later save could then never replace.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import platformdirs

from olivia.core import datalock

SNAPSHOT_KEEP: Final = 3
STRAY_TEMP_AGE: Final = 3600.0
"""Seconds after which a temporary file is a crashed writer's even without the lock."""

_SNAPSHOT_DIR: Final = ".snapshots"
_PRIVATE_MODE: Final = 0o600  # user data is owner-only on POSIX (ignored on Windows)
_O_BINARY: Final = getattr(os, "O_BINARY", 0)
_SNAPSHOT_SUFFIX: Final = re.compile(r"(\d+)(?:\.(\d+))?")


class StorageCorruptError(Exception):
    """The file and all of its snapshots exist but none is valid."""


class StorageAccessError(OSError):
    """A data file exists but the operating system will not read it (a directory in
    its place, missing permissions); nothing was changed."""


def data_dir_location() -> Path:
    """Where the application data directory is (``OLIVIA_HOME`` or the platform's user
    data directory), without creating it."""
    override = os.environ.get("OLIVIA_HOME")
    return Path(override) if override else platformdirs.user_data_path("olivia", appauthor=False)


def app_data_dir() -> Path:
    """Return the application data directory, creating it (0o700 on POSIX) if absent."""
    path = data_dir_location()
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            path.chmod(0o700)
    return path


def _snapshot_dir(path: Path) -> Path:
    """One private directory per file, so ``log`` and ``log.7`` never share snapshots."""
    return path.parent / _SNAPSHOT_DIR / path.name


def _snapshot_key(snapshot: Path) -> tuple[int, int] | None:
    """Parse ``<ns>[.<counter>]`` into a sortable key; None if it is not ours."""
    match = _SNAPSHOT_SUFFIX.fullmatch(snapshot.name)
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2) or 0)


def snapshot_paths(path: Path) -> list[Path]:
    """Snapshots of ``path``, newest first."""
    directory = _snapshot_dir(path)
    if not directory.is_dir():
        return []
    keyed = [
        (key, entry)
        for entry in directory.iterdir()
        if entry.is_file() and (key := _snapshot_key(entry)) is not None
    ]
    keyed.sort(key=lambda item: item[0], reverse=True)
    return [entry for _, entry in keyed]


def snapshot_time(snapshot: Path) -> datetime | None:
    """When ``snapshot`` was taken (UTC); None if it is not one of ours."""
    if snapshot.parent.parent.name != _SNAPSHOT_DIR:
        return None
    key = _snapshot_key(snapshot)
    return None if key is None else datetime.fromtimestamp(key[0] / 1e9, UTC)


def _temp_prefix(path: Path) -> str:
    return f".{path.name}."


def remove_stray_temps(path: Path) -> None:
    """Delete the temporary siblings a killed write of ``path`` left behind (only names
    :func:`atomic_write_bytes` makes for this very file). Without the data directory's
    lock, a fresh one may be another process's write in progress, so it stays."""
    directory = path.parent
    if not directory.is_dir():
        return
    locked = datalock.held(directory)
    prefix = _temp_prefix(path)
    try:
        candidates = [p for p in directory.iterdir() if p.name.startswith(prefix)]
    except OSError:
        return
    now = time.time()
    for stray in candidates:
        if not stray.name.endswith(".tmp") or len(stray.name) <= len(prefix) + len(".tmp"):
            continue
        with contextlib.suppress(OSError):
            if locked or now - stray.lstat().st_mtime > STRAY_TEMP_AGE:
                stray.unlink()


def _take_snapshot(path: Path) -> None:
    directory = _snapshot_dir(path)
    directory.parent.mkdir(mode=0o700, exist_ok=True)
    directory.mkdir(mode=0o700, exist_ok=True)
    stamp = time.time_ns()
    counter = 0
    existing = snapshot_paths(path)
    if existing:
        # Never sort below an existing snapshot, even if the clock stalls or steps back.
        newest = _snapshot_key(existing[0])
        if newest is not None and newest[0] >= stamp:
            stamp, counter = newest[0], newest[1] + 1
    while True:
        suffix = f"{stamp}" if counter == 0 else f"{stamp}.{counter}"
        target = directory / suffix
        try:
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_BINARY, _PRIVATE_MODE)
        except FileExistsError:
            counter += 1
            continue
        with os.fdopen(fd, "wb") as dst, open(path, "rb") as src:
            shutil.copyfileobj(src, dst)
            dst.flush()
            os.fsync(dst.fileno())
        break
    for stale in snapshot_paths(path)[SNAPSHOT_KEEP:]:
        with contextlib.suppress(FileNotFoundError):
            stale.unlink()


def _fsync_directory(directory: Path) -> None:
    if os.name == "nt":  # directories cannot be opened for fsync on Windows
        return
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write_text(path: Path, text: str) -> None:
    """Write ``text`` (UTF-8) to ``path`` without ever losing the previous version."""
    atomic_write_bytes(path, text.encode("utf-8"))


def atomic_write_bytes(path: Path, data: bytes, *, snapshot: bool = True) -> None:
    """Write ``data`` to ``path`` atomically; ``snapshot=False`` keeps no older version.

    Key files use ``snapshot=False``: a snapshot of a wrapped data key would survive
    crypto-shredding.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    remove_stray_temps(path)
    if snapshot and path.exists():
        _take_snapshot(path)
    # mkstemp creates the file 0o600 and uniquely named; os.replace carries that mode over.
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=_temp_prefix(path), suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise
    _fsync_directory(path.parent)


def remove_file(path: Path) -> None:
    """Delete ``path`` if present and make the removal durable.

    On SSDs and copy-on-write file systems the old blocks may survive until reused;
    this is why secrets on disk are only ever ciphertext (see ``olivia.core.crypto``).
    """
    try:
        path.unlink()
    except FileNotFoundError:
        return
    _fsync_directory(path.parent)


def read_bytes_if_present(path: Path) -> bytes | None:
    """The file's bytes; None when it does not exist.

    Raises :class:`StorageAccessError` when it exists but cannot be read.
    """
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise StorageAccessError(f"{path.name} exists but cannot be read") from exc


def _read_utf8(path: Path) -> str | None:
    """File contents, or None if the file is missing or not valid UTF-8 (a snapshot that
    cannot be read counts as missing)."""
    try:
        return path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def read_with_recovery(path: Path, is_valid: Callable[[str], bool]) -> tuple[str, Path]:
    """The main file if valid, else the newest valid snapshot; and which one it was.

    Raises ``FileNotFoundError`` if neither the file nor any snapshot exists,
    :class:`StorageAccessError` if the main file exists but cannot be read (no snapshot
    is used then: the file is not damaged and a later save could not replace it), and
    :class:`StorageCorruptError` if versions exist but none is valid.
    """
    main = read_bytes_if_present(path)
    found_any = main is not None
    if main is not None:
        try:
            text = main.decode("utf-8")
        except UnicodeDecodeError:
            pass
        else:
            if is_valid(text):
                return text, path
    for candidate in snapshot_paths(path):
        snap = _read_utf8(candidate)
        if snap is None:
            found_any = found_any or candidate.exists()
            continue
        found_any = True
        if is_valid(snap):
            return snap, candidate
    if not found_any:
        raise FileNotFoundError(path)
    raise StorageCorruptError(f"no valid version of {path} or its snapshots")


def read_text_with_recovery(path: Path, is_valid: Callable[[str], bool]) -> str:
    """:func:`read_with_recovery` without saying which version it read."""
    return read_with_recovery(path, is_valid)[0]
