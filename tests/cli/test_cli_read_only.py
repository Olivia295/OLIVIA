"""Session gaps (drafts pending G-0): ``olivia chat`` on a data directory it may read but
not write.

PRD and SDD say nothing about a data directory that cannot be written (SDD §6.5 only says a
state file that cannot be saved is left alone), so the chat goes on: it says once that
nothing from this chat can be saved and why (permissions, or a read-only disk), writes
nothing at all (no summary, rating, note, kit or care marker), and ends without an error.
The crisis flow and its numbers are unchanged. A first visit, which must save the profile,
still stops with the numbers first, as before.

Every case runs in a temporary data directory with the in-memory keychain; every sentence
typed is made up for these tests.
"""

from __future__ import annotations

import errno
import os
import sys
from pathlib import Path

import pytest
from cli_support import L3_SENTENCE, ONBOARD_CN

from olivia import cli
from olivia.core.datalock import DataDirLock
from olivia.core.memory.text import load_memory_text

CHAT = [*ONBOARD_CN, "下班路上买了一袋橘子", "/exit"]
TALK = ["周末打算把书架重新整理一下", "最近工作压力好大，能给我一个练习试试吗", "/done", "/exit"]
MEMORY = load_memory_text()
POSIX_ONLY = pytest.mark.skipif(
    sys.platform == "win32" or getattr(os, "geteuid", lambda: 1)() == 0,
    reason="POSIX permissions, and root writes everything",
)


def _set_up(run_cli) -> None:
    assert run_cli(["chat", "--rules"], CHAT).code == 0


def _contents(home: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(home)): path.read_bytes()
        for path in sorted(home.rglob("*"))
        if path.is_file()
    }


@pytest.fixture
def read_only(data_home: Path):
    """Make every folder of the data directory 0500 and every file 0400 (put back after)."""
    changed: list[tuple[Path, int]] = []

    def block() -> None:
        for path in sorted(data_home.rglob("*"), reverse=True) + [data_home]:
            changed.append((path, path.stat().st_mode & 0o777))
            path.chmod(0o500 if path.is_dir() else 0o400)

    yield block
    for path, mode in reversed(changed):
        path.chmod(mode)


def _no_lock(monkeypatch: pytest.MonkeyPatch, exc: OSError) -> None:
    def refuse(self: DataDirLock) -> None:
        raise exc

    monkeypatch.setattr(DataDirLock, "acquire", refuse)


@POSIX_ONLY
def test_a_read_only_data_directory_leaves_the_chat_going(run_cli, data_home, read_only):
    _set_up(run_cli)
    before = _contents(data_home)
    read_only()
    run = run_cli(["chat", "--rules"], TALK)
    assert run.code == 0
    assert len(run.results) == 3  # every message was answered
    notice = cli.CHAT_READ_ONLY.format(reason=cli.READ_ONLY_PERMISSIONS)
    assert run.out.count(notice) == 1
    assert run.out.index(notice) < run.out.index(cli.CHAT_HINT)
    assert cli.DATA_DIR_UNUSABLE not in run.out
    assert cli.UNEXPECTED_ERROR not in run.out
    assert cli.GOODBYE in run.out
    assert _contents(data_home) == before


@POSIX_ONLY
def test_the_crisis_flow_and_its_numbers_are_the_same_read_only(run_cli, data_home, read_only):
    _set_up(run_cli)
    read_only()
    run = run_cli(["chat", "--rules"], [L3_SENTENCE, "/exit"])
    assert run.code == 0
    assert run.results[0].in_crisis
    assert "12356" in run.results[0].reply and "110" in run.results[0].reply
    # The chat ends in the crisis flow: the farewell keeps the numbers on screen.
    tail = run.out[run.out.rindex("你：") :]
    assert "12356" in tail
    assert cli.DATA_DIR_UNUSABLE not in run.out


@POSIX_ONLY
def test_a_first_visit_to_a_read_only_directory_still_stops_with_the_numbers(
    run_cli, data_home, read_only
):
    data_home.mkdir(parents=True)
    read_only()
    run = run_cli(["chat", "--rules"], ONBOARD_CN)
    assert run.code == 1
    assert run.results == []
    assert "110" in run.out
    assert cli.DATA_DIR_UNUSABLE in run.out


def test_a_read_only_disk_is_named_and_nothing_is_written(run_cli, data_home, monkeypatch):
    _set_up(run_cli)
    before = _contents(data_home)
    _no_lock(monkeypatch, OSError(errno.EROFS, "Read-only file system"))
    run = run_cli(["chat", "--rules"], ["记住：周五要去拿快递", *TALK])
    assert run.code == 0
    assert len(run.results) == 4
    assert run.out.count(cli.CHAT_READ_ONLY.format(reason=cli.READ_ONLY_DISK)) == 1
    # No self-rating is asked when it cannot be kept, and no summary is said to be lost.
    assert "0 到 10" not in run.out
    assert "小结没能保存" not in run.out
    assert _contents(data_home) == before


@pytest.mark.parametrize(
    "exc",
    [OSError(errno.EROFS, "Read-only file system"), PermissionError(errno.EACCES, "Denied")],
    ids=["disk", "permissions"],
)
def test_a_note_asked_for_read_only_says_the_directory_cannot_be_written(
    run_cli, data_home, monkeypatch, exc
):
    _set_up(run_cli)
    before = _contents(data_home)
    _no_lock(monkeypatch, exc)
    run = run_cli(["chat", "--rules"], ["记住：周五要去拿快递", "/exit"])
    assert run.code == 0
    # The recorder answers the note in place of the session's reply.
    assert MEMORY.replies["note_read_only"] + MEMORY.replies["note_continue"] in run.out
    assert MEMORY.replies["note_unavailable"] not in run.out
    assert MEMORY.replies["note_saved"] not in run.out
    assert _contents(data_home) == before


def test_permissions_on_the_lock_alone_are_said_the_same_way(run_cli, data_home, monkeypatch):
    _set_up(run_cli)
    before = _contents(data_home)
    _no_lock(monkeypatch, PermissionError(errno.EACCES, "Permission denied"))
    run = run_cli(["chat", "--rules"], TALK)
    assert run.code == 0
    assert run.out.count(cli.CHAT_READ_ONLY.format(reason=cli.READ_ONLY_PERMISSIONS)) == 1
    assert _contents(data_home) == before


def test_other_commands_still_stop_when_the_lock_cannot_be_written(run_cli, data_home, monkeypatch):
    _set_up(run_cli)
    _no_lock(monkeypatch, PermissionError(errno.EACCES, "Permission denied"))
    run = run_cli(["profile"], [""])
    assert run.code == 1
    assert cli.CHAT_READ_ONLY.split("（")[0] not in run.out


def test_another_lock_failure_still_stops_the_chat(run_cli, data_home, monkeypatch):
    _set_up(run_cli)
    _no_lock(monkeypatch, OSError(errno.EIO, "Input/output error"))
    run = run_cli(["chat", "--rules"], TALK)
    assert run.code == 1
    assert run.results == []
    assert "12356" in run.out  # the numbers first, as for any error nothing else handled
