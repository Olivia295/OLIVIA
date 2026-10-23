"""The operating system as the reminders see it (next-phase B9).

Everything that touches the OS -- the scheduler (``launchctl``, ``schtasks``,
``systemctl --user``, ``crontab``) and the notification itself (``osascript``,
PowerShell, ``notify-send``) -- goes through :attr:`Host.run`, a :data:`Runner` that takes
an argv list (never a shell string), so tests use a fake runner and never install
anything. :func:`current_host` builds the real one.
"""

from __future__ import annotations

import getpass
import os
import platform
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

TIMEOUT_SECONDS: Final = 60
NOT_RUN: Final = 127
"""The return code a runner reports when the program could not be started."""


class System(StrEnum):
    MACOS = "macos"
    WINDOWS = "windows"
    LINUX = "linux"
    OTHER = "other"


@dataclass(frozen=True)
class RunResult:
    returncode: int
    stdout: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0


Runner = Callable[[Sequence[str], str | None], RunResult]
"""Run one program: ``(argv, stdin text or None) -> RunResult``; never raises."""


@dataclass(frozen=True)
class Host:
    """This user's machine: which OS, where things go, and how programs are run."""

    system: System
    home: Path
    config_home: Path
    """``$XDG_CONFIG_HOME`` (or ``~/.config``): where systemd user units live."""
    uid: int
    user: str
    command: tuple[str, ...]
    """How the scheduled job starts this ``olivia`` (absolute paths; argv, not a shell line)."""
    run: Runner
    which: Callable[[str], str | None]


def system_runner(argv: Sequence[str], stdin: str | None = None) -> RunResult:
    """Run ``argv`` without a shell; any failure to start is :data:`NOT_RUN`."""
    try:
        done = subprocess.run(  # argv list, no shell: nothing in it is interpreted
            list(argv),
            input=stdin,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return RunResult(NOT_RUN)
    return RunResult(done.returncode, done.stdout or "")


def detect_system(name: str | None = None) -> System:
    found = platform.system() if name is None else name
    return {"Darwin": System.MACOS, "Windows": System.WINDOWS, "Linux": System.LINUX}.get(
        found, System.OTHER
    )


def olivia_command(
    argv0: str | None = None,
    *,
    which: Callable[[str], str | None] = shutil.which,
    python: str | None = None,
) -> tuple[str, ...]:
    """The absolute command that runs this ``olivia``.

    The console script that started this process (``sys.argv[0]``, resolved), else the
    ``olivia`` on ``PATH``, else this interpreter with ``-m olivia.cli`` (a source checkout).
    """
    first = sys.argv[0] if argv0 is None else argv0
    path = Path(first)
    if path.stem.lower() == "olivia" and path.suffix.lower() in ("", ".exe"):
        located = str(path) if path.parent != Path() else which(first)
        if located is not None and Path(located).is_file():
            return (str(Path(located).resolve()),)
    found = which("olivia")
    if found is not None:
        return (str(Path(found).resolve()),)
    # Not resolved: a virtual environment's python is a symlink to the base interpreter.
    return (str(Path(sys.executable if python is None else python).absolute()), "-m", "olivia.cli")


def current_host() -> Host:
    """The real machine (used by the CLI; tests replace it with a fake)."""
    home = Path.home()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    getuid = getattr(os, "getuid", None)
    try:
        user = getpass.getuser()
    except (OSError, KeyError):
        user = "*"
    return Host(
        system=detect_system(),
        home=home,
        config_home=Path(xdg) if xdg else home / ".config",
        uid=getuid() if getuid is not None else 0,
        user=user,
        command=olivia_command(),
        run=system_runner,
        which=shutil.which,
    )
