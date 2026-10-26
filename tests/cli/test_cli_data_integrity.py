"""Data integrity under faults (robustness findings D1-D6, S4, S5, C2, C3, E1-E4).

One writer per data directory, no silent rollback of the profile, clocks that step back,
leftover temporary files, files the operating system will not open, an interrupted
``forget --all``, and what ``memory`` and ``health`` say about data that does not open.
"""

from __future__ import annotations

import io
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cli_support import L3_SENTENCE, NOW, ONBOARD_CN, files_under, save_profile

from olivia import cli
from olivia.core.chang.profile import (
    PROFILE_FILENAME,
    RECOVERED_FILENAME,
    ProfileLockedError,
    ProfileStore,
)
from olivia.core.chang.safety_plan import SAFETY_PLAN_FILENAME, SafetyPlan, SafetyPlanStore
from olivia.core.crypto.errors import NoKeychainError
from olivia.core.crypto.vault import KEYS_DIRNAME, MASTER_ITEM
from olivia.core.datalock import DataDirLock
from olivia.core.memory.forget import FORGET_ALL_MARKER, load_forget_text
from olivia.core.memory.ledger import Ledger
from olivia.core.memory.state import STATE_FILENAME
from olivia.core.storage import snapshot_paths

TEXT = load_forget_text()
M, F = TEXT.memory, TEXT.forget
HEALTH = {"contraindications": ("CARDIORESPIRATORY_INSTABILITY",)}
POSIX = pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")


def _held(home: Path) -> DataDirLock:
    home.mkdir(parents=True, exist_ok=True)
    lock = DataDirLock(home)
    lock.acquire()
    return lock


# -- D1-D3: one writer per data directory ---------------------------------------------------


@pytest.mark.parametrize(
    ("argv", "lines"),
    [
        (["chat", "--rules"], ["你好", "/exit"]),
        (["health"], []),
        (["safety-plan"], []),
        (["settings"], []),
        (["profile"], []),
        (["persona", "2"], []),
        (["region", "US"], []),
        (["region", "--clear"], []),
        (["forget", "--all", "--yes"], []),
        (["forget", "--ledger", "--yes"], []),
        (["memory", "--edit", "1"], []),
        (["journal"], []),
    ],
)
def test_a_writing_command_waits_for_the_other_olivia(run_cli, data_home, argv, lines):
    save_profile(data_home)
    before = {p: p.read_bytes() for p in files_under(data_home)}
    lock = _held(data_home)
    try:
        run = run_cli(argv, lines)
    finally:
        lock.release()
    assert run.code == 1
    assert run.lines == [cli.DATA_DIR_BUSY]
    assert "olivia resources" in cli.DATA_DIR_BUSY
    assert not run.results
    assert {p: p.read_bytes() for p in files_under(data_home)} == before


@pytest.mark.parametrize(
    "argv",
    [["resources"], ["privacy"], ["memory"], ["stats"], ["persona"], ["region"]],
)
def test_reading_commands_run_beside_a_chat(run_cli, data_home, argv):
    save_profile(data_home)
    lock = _held(data_home)
    try:
        run = run_cli(argv)
    finally:
        lock.release()
    assert cli.DATA_DIR_BUSY not in run.out
    assert run.code == 0


def test_the_scheduled_check_skips_quietly_while_a_chat_runs(run_cli, data_home):
    save_profile(data_home, notifications=True)
    lock = _held(data_home)
    try:
        run = run_cli(["notify-check"])
    finally:
        lock.release()
    assert run.code == 0 and run.out == ""


def test_the_lock_is_released_and_leaves_nothing_behind(run_cli, data_home):
    assert run_cli(["chat", "--rules"], [*ONBOARD_CN, "你好", "/exit"]).code == 0
    assert run_cli(["chat", "--rules"], ["你好", "/exit"]).code == 0
    assert all(".lock" not in p.name for p in files_under(data_home))


# -- D4, C3: a damaged profile is never silently rolled back ----------------------------------


def _health_then_damage(data_home: Path) -> None:
    save_profile(data_home)
    save_profile(data_home, **HEALTH)  # the earlier, plain version is now a snapshot
    assert snapshot_paths(data_home / PROFILE_FILENAME)


def test_a_truncated_profile_is_recovered_and_said_once(run_cli, data_home):
    _health_then_damage(data_home)
    main = data_home / PROFILE_FILENAME
    main.write_bytes(main.read_bytes()[:50])
    first = run_cli(["persona"])
    assert first.code == 0
    (notice,) = [line for line in first.lines if line.startswith("设置文件坏了")]
    assert "olivia health" in notice and "olivia profile" in notice
    second = run_cli(["persona"])
    assert not any(line.startswith("设置文件坏了") for line in second.lines)


def test_the_chat_says_it_before_the_conversation(run_cli, data_home):
    _health_then_damage(data_home)
    main = data_home / PROFILE_FILENAME
    main.write_bytes(main.read_bytes()[:50])
    run = run_cli(["chat", "--rules"], ["你好", "/exit"])
    assert run.code == 0
    notice = next(i for i, line in enumerate(run.lines) if line.startswith("设置文件坏了"))
    assert notice < run.lines.index(cli.CHAT_HINT)


def test_a_recovered_profile_is_marked_before_anything_overwrites_it(data_home):
    _health_then_damage(data_home)
    main = data_home / PROFILE_FILENAME
    main.write_bytes(b"{")
    store = ProfileStore(data_home)
    profile = store.load()
    assert profile is not None and store.recovered_at is not None
    assert (data_home / RECOVERED_FILENAME).is_file()
    store.save(profile)  # the marker stays until the CLI has said it
    assert (data_home / RECOVERED_FILENAME).is_file()
    assert store.take_recovery_notice() is not None
    assert store.take_recovery_notice() is None


def test_a_damaged_profile_key_is_not_a_damaged_file(run_cli, data_home):
    _health_then_damage(data_home)
    key = data_home / KEYS_DIRNAME / "profile.key"
    key.write_bytes(b"OLVK")
    before = (data_home / PROFILE_FILENAME).read_bytes()
    with pytest.raises(ProfileLockedError) as caught:
        ProfileStore(data_home).load()
    assert caught.value.lost
    for argv, lines in (
        (["health"], []),
        (["persona", "2"], []),
        (["settings"], ["2", "1"]),
        (["chat", "--rules"], ["你好"]),
    ):
        run = run_cli(argv, lines)
        assert run.code == 1, argv
        # one way of saying it: the keys are gone or damaged, and how to start over
        assert cli.PROFILE_KEYS_LOST in run.out and cli.PROFILE_START_OVER in run.out, argv
        assert run.out.count(cli.PROFILE_START_OVER) == 1, argv
    chat = run_cli(["chat", "--rules"], ["你好"])
    assert chat.out.index("12356") < chat.out.index(cli.PROFILE_KEYS_LOST)  # numbers first
    assert (data_home / PROFILE_FILENAME).read_bytes() == before
    assert not (data_home / RECOVERED_FILENAME).exists()


def test_a_stale_damaged_key_under_a_plain_profile_does_not_block_settings(run_cli, data_home):
    save_profile(data_home)  # plain: opens without any key
    keys = data_home / KEYS_DIRNAME
    keys.mkdir(mode=0o700)
    (keys / "profile.key").write_bytes(b"OLVK")  # a stale, damaged key file
    run = run_cli(["settings"], ["2", "1", "确认"])
    assert run.code == 0  # the plain profile's load shreds the stale key first
    loaded = ProfileStore(data_home).load()
    assert loaded is not None and loaded.enable_at_rest_encryption


# -- D5, D6: clocks that step back ----------------------------------------------------------


class _SteppingInput(io.StringIO):
    """Input whose clock steps back once the line after the first turn is read."""

    def __init__(self, text: str, clock: list[datetime], at_line: int) -> None:
        super().__init__(text)
        self.clock, self.at_line, self.read = clock, at_line, 0

    def readline(self, *args: object) -> str:  # type: ignore[override]
        self.read += 1
        if self.read == self.at_line:
            self.clock[0] = self.clock[0] - timedelta(seconds=1)
        return super().readline()


def test_a_clock_stepped_back_between_turns_keeps_the_summary(data_home):
    save_profile(data_home)
    clock = [NOW]
    lines = ["", "今天上班好累", "还是很累", "/exit", ""]
    source = _SteppingInput("".join(f"{x}\n" for x in lines), clock, at_line=3)
    out = io.StringIO()
    code = cli.main(["chat", "--rules"], stdin=source, stdout=out, clock=lambda: clock[0])
    assert code == 0
    assert "Traceback" not in out.getvalue()
    assert "这次聊天的小结没能保存下来" not in out.getvalue()
    (entry,) = Ledger(data_home).entries()
    summary = entry.summary  # type: ignore[attr-defined]
    assert summary.ended_at.astimezone(UTC) >= summary.started_at.astimezone(UTC)


# -- S4: leftover temporary files ------------------------------------------------------------


def test_a_crashed_save_leaves_no_plaintext_copy_after_the_next_write(run_cli, data_home):
    save_profile(data_home)
    stray = data_home / f".{PROFILE_FILENAME}.abcd1234.tmp"
    stray.write_text('{"user_name": "小林"}', encoding="utf-8")
    other = data_home / ".notes.txt.tmp"  # not a temporary file of ours: kept
    other.write_text("x", encoding="utf-8")
    assert run_cli(["persona", "2"]).code == 0
    assert not stray.exists()
    assert other.exists()


# -- S5, E2: forget --all ---------------------------------------------------------------------


def test_forget_all_without_a_keychain_says_the_key_could_not_be_reached(
    run_cli, data_home, keychain
):
    save_profile(data_home, **HEALTH)  # a master key and a profile key exist
    assert MASTER_ITEM in keychain.items
    keychain.broken = NoKeychainError("none")
    run = run_cli(["forget", "--all", "--yes"])
    assert run.code == 1
    assert run.lines == [F["keychain_unreachable"]]
    assert "olivia forget --all" in F["keychain_unreachable"]
    assert files_under(data_home) == []
    keychain.broken = None
    assert run_cli(["forget", "--all", "--yes"]).code == 0
    assert keychain.items == {}


def test_an_interrupted_forget_all_is_named_and_finished_by_running_it_again(
    run_cli, data_home, keychain
):
    save_profile(data_home, **HEALTH)
    (data_home / FORGET_ALL_MARKER).write_bytes(b"")
    (data_home / KEYS_DIRNAME / "profile.key").unlink()  # killed half-way
    for argv in (["chat", "--rules"], ["persona"], ["health"], ["memory"]):
        run = run_cli(argv, ["你好", "/exit"])
        assert run.code == 1, argv
        assert run.lines == [F["unfinished"]], argv
    resources = run_cli(["resources"])  # runs (its numbers are another fix's business)
    assert resources.lines[-1] == F["unfinished"]
    assert run_cli(["forget", "--all", "--yes"]).code == 0
    assert files_under(data_home) == [] and keychain.items == {}
    assert run_cli(["chat", "--rules"], []).code == 1  # onboarding from the start


# -- C2: files the operating system will not open ----------------------------------------------


def _chat_with_crisis(run_cli):
    return run_cli(["chat", "--rules"], [L3_SENTENCE, "/exit"])


def test_a_directory_in_place_of_the_state_file(run_cli, data_home):
    save_profile(data_home)
    (data_home / STATE_FILENAME).mkdir()
    run = _chat_with_crisis(run_cli)
    assert run.code == 0 and run.results
    assert "12356" in run.out


@POSIX
def test_an_unreadable_safety_plan(run_cli, data_home):
    save_profile(data_home)
    SafetyPlanStore(data_home).save(SafetyPlan(coping=("出去走走",)))
    plan = data_home / SAFETY_PLAN_FILENAME
    plan.chmod(0)
    try:
        run = _chat_with_crisis(run_cli)
        assert run.code == 0 and "12356" in run.out
        shown = run_cli(["safety-plan"], [])
        assert shown.code == 1 and "olivia doctor" in shown.out
    finally:
        plan.chmod(0o600)


@POSIX
def test_an_unreadable_ledger_key(run_cli, data_home):
    save_profile(data_home)
    assert run_cli(["chat", "--rules"], ["今天上班好累", "/exit"]).code == 0
    key = data_home / KEYS_DIRNAME / "ledger.key"
    key.chmod(0)
    try:
        run = run_cli(["chat", "--rules"], ["今天上班好累", "/exit"])
    finally:
        key.chmod(0o600)
    assert run.code == 0
    assert "这次聊天的小结没能保存下来" in run.out


def test_a_directory_in_place_of_the_profile(run_cli, data_home):
    data_home.mkdir()
    (data_home / PROFILE_FILENAME).mkdir()
    run = run_cli(["chat", "--rules"], ["你好"])
    assert run.code == 1
    assert "olivia doctor" in run.out


def test_an_unexpected_error_ends_without_a_traceback(run_cli, data_home, monkeypatch):
    save_profile(data_home)

    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("injected")

    monkeypatch.setattr(cli, "_persona", boom)
    run = run_cli(["persona"])
    assert run.code == 1
    assert run.lines == [cli.UNEXPECTED_ERROR]
    assert "olivia doctor" in cli.UNEXPECTED_ERROR


def test_ctrl_c_still_says_goodbye(run_cli, data_home, monkeypatch):
    save_profile(data_home)

    def interrupt(*_args: object, **_kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "_persona", interrupt)
    run = run_cli(["persona"])
    assert run.code == 0 and run.lines[-1] == cli.GOODBYE


# -- E3, E4 -----------------------------------------------------------------------------------


def test_memory_says_a_plan_that_does_not_open_is_unreadable(run_cli, data_home):
    save_profile(data_home)
    SafetyPlanStore(data_home).save(SafetyPlan(coping=("出去走走",)))
    plan = data_home / SAFETY_PLAN_FILENAME
    plan.write_bytes(plan.read_bytes()[:20])
    run = run_cli(["memory"])
    assert f"- {M['safety_plan_unreadable']}" in run.lines
    assert f"- {M['safety_plan']}" not in run.lines


def test_health_says_legacy_health_information_was_removed(run_cli, data_home, keychain):
    save_profile(data_home)
    path = data_home / PROFILE_FILENAME
    data = json.loads(path.read_text(encoding="utf-8"))
    data["clinical_history"] = ["SIT-02-04"]
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    keychain.broken = NoKeychainError("none")
    run = run_cli(["health"])
    assert cli.HEALTH_NOT_SAVED in run.out
    assert b"SIT-02-04" not in path.read_bytes()


def test_no_lock_file_survives_forget_all(run_cli, data_home):
    save_profile(data_home)
    assert run_cli(["forget", "--all", "--yes"]).code == 0
    assert files_under(data_home) == []
    assert not any(name.endswith(".lock") for name in os.listdir(data_home))
