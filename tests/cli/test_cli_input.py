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


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX terminals only")
def test_a_long_pasted_line_in_a_terminal_is_read_whole():
    """400 Chinese characters (1,200 bytes) pasted at once: more than a canonical-mode
    terminal line holds (1,024 bytes on macOS), so before readline it hung."""
    import pty

    code = (
        "import sys; from olivia import cli\n"
        "line = cli._Console(sys.stdin, sys.stdout).ask('> ')\n"
        "print('GOT', len(line), line == '一二三四五六七八九十' * 40)"
    )
    pid, fd = pty.fork()
    if pid == 0:  # pragma: no cover - the child process
        os.chdir(ROOT)
        os.execv(sys.executable, [sys.executable, "-c", code])
    out = b""

    def drain(wait: float) -> bool:
        """Read what is there; False once the child has closed the terminal."""
        nonlocal out
        while select.select([fd], [], [], wait)[0]:
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                return False
            if not chunk:
                return False
            out += chunk
        return True

    try:
        deadline = time.monotonic() + 30
        while b"> " not in out and time.monotonic() < deadline:
            drain(0.1)
        pasted = ("一二三四五六七八九十" * 40).encode() + b"\r"
        while pasted:  # one paste, written as fast as the terminal takes it
            written = os.write(fd, pasted)
            pasted = pasted[written:]
            drain(0)
        while time.monotonic() < deadline and drain(0.1):
            if b"GOT" in out and out.rstrip().endswith((b"True", b"False")):
                break
    finally:
        os.waitpid(pid, 0)
        os.close(fd)
    got = out.decode("utf-8", "replace").split("GOT", 1)[-1].split()[:2]
    assert got == ["400", "True"], out[-300:]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX terminals only")
@pytest.mark.parametrize("locale_name", ["C", "POSIX"])
def test_chinese_is_read_whole_under_a_c_locale(locale_name):
    """``LC_ALL=C`` (SSH, containers): readline once garbled "我不想活了" into "f活了"."""
    import pty

    code = (
        "import sys; from olivia import cli\n"
        "line = cli._Console(sys.stdin, sys.stdout).ask('> ')\n"
        "print('GOT', line.encode('unicode_escape').decode())"
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith(("LC_", "LANG"))}
    env["LC_ALL"] = locale_name
    pid, fd = pty.fork()
    if pid == 0:  # pragma: no cover - the child process
        os.chdir(ROOT)
        os.execve(sys.executable, [sys.executable, "-c", code], env)
    out = b""
    try:
        deadline = time.monotonic() + 30
        while b"> " not in out and time.monotonic() < deadline:
            if select.select([fd], [], [], 0.1)[0]:
                out += os.read(fd, 4096)
        os.write(fd, "我不想活了\r".encode())
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
    assert got == "我不想活了".encode("unicode_escape").decode(), out[-300:]
