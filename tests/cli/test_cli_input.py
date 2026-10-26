"""Reading a line: a half-deleted Chinese character or a stray byte never reaches a reply."""

from __future__ import annotations

import io
import os
import select
import subprocess
import sys
import time
from pathlib import Path

import pytest

from olivia import cli

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("你好", "你好"),
        # "你好" with one byte-wise backspace: two of 好's three bytes are left.
        ("你\udce5\udca5吗", "你吗"),
        ("是\udcff", "是"),
        ("我\ud800们", "我?们"),
        ("", ""),
    ],
)
def test_clean_input_drops_broken_characters(text, expected):
    assert cli.clean_input(text) == expected


def test_piped_invalid_bytes_are_dropped():
    raw = io.BytesIO("你好\n".encode()[:-2] + b"\n" + "是\n".encode() + b"\xff\n")
    console = cli._Console(
        io.TextIOWrapper(raw, encoding="utf-8", errors="surrogateescape"), io.StringIO()
    )
    assert console.ask("") == "你"
    assert console.ask("") == "是"
    assert console.ask("") == ""
    assert console.ask("") is None


def test_an_invalid_byte_on_real_stdin_does_not_stop_the_program(tmp_path):
    done = subprocess.run(
        [sys.executable, "-m", "olivia.cli", "chat"],
        cwd=ROOT,
        input="是".encode() + b"\xff\n",
        capture_output=True,
        env={
            **os.environ,
            "OLIVIA_HOME": str(tmp_path / "home"),
            "PYTHON_KEYRING_BACKEND": "keyring.backends.fail.Keyring",
        },
        check=False,
        timeout=60,
    )
    assert b"Traceback" not in done.stderr, done.stderr.decode("utf-8", "replace")
    assert done.returncode == 1  # input ended before setup was done


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX terminals only")
def test_backspace_in_a_terminal_deletes_a_whole_character():
    import pty

    code = (
        "import sys; from olivia import cli\n"
        "line = cli._Console(sys.stdin, sys.stdout).ask('> ')\n"
        "print('GOT', line.encode('unicode_escape').decode())"
    )
    pid, fd = pty.fork()
    if pid == 0:  # pragma: no cover - the child process
        os.chdir(ROOT)
        os.execv(sys.executable, [sys.executable, "-c", code])
    out = b""
    try:
        deadline = time.monotonic() + 30
        while b"> " not in out and time.monotonic() < deadline:
            if select.select([fd], [], [], 0.1)[0]:
                out += os.read(fd, 4096)
        # Two backspaces delete both characters; byte-wise they would leave 你 and a byte of 好.
        for keys in ("你好".encode(), b"\x7f", b"\x7f", "吗\r".encode()):
            os.write(fd, keys)
            time.sleep(0.2)
        while time.monotonic() < deadline:  # until the child exits and the pty closes
            if select.select([fd], [], [], 0.1)[0]:
                try:
                    chunk = os.read(fd, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                out += chunk
    finally:
        os.waitpid(pid, 0)
        os.close(fd)
    got = out.decode("utf-8", "replace").split("GOT", 1)[-1].split()[0]
    assert got == "\\u5417"  # 吗
