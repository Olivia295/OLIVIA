"""The one-click launchers in the repo root (owner convention: start.command + start.sh)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
START_SH = ROOT / "start.sh"
START_COMMAND = ROOT / "start.command"

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="bash launchers; not on Windows")


def test_both_launchers_exist() -> None:
    assert START_SH.is_file()
    assert START_COMMAND.is_file()


@posix_only
def test_both_launchers_are_executable() -> None:
    assert os.access(START_SH, os.X_OK)
    assert os.access(START_COMMAND, os.X_OK)


def test_start_command_only_delegates() -> None:
    lines = [ln for ln in START_COMMAND.read_text("utf-8").splitlines() if ln.strip()]
    assert lines[0].startswith("#!")
    assert lines[1:] == ['cd "$(dirname "$0")" && ./start.sh']


def test_start_sh_strict_and_runs_olivia() -> None:
    text = START_SH.read_text("utf-8")
    assert text.startswith("#!/usr/bin/env bash")
    assert "set -euo pipefail" in text
    assert 'exec .venv/bin/olivia "$@"' in text


@posix_only
def test_start_sh_syntax() -> None:
    result = subprocess.run(["bash", "-n", str(START_SH)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
