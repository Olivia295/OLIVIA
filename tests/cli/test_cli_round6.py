"""Round 6 (QA q4 re-test of round 5; drafts pending G-0): the command line on damaged data.

* A folder where the safety plan's file should be is a plan that cannot be opened: a
  crisis says so, and ``--inspect`` never calls it "shown" (F1, F20).
* ``olivia doctor``: a keychain that answers the probe but not a read is not "usable"
  (F6); a ``keys/`` folder that cannot be read names that, not a damaged file (F7); every
  ✗ line about stored data is followed by how to fix it (F9); a permission problem names
  the path (F12); a file in place of the data directory checks nothing else (F12).
* The chat says at the start when the session summary cannot be saved because ``keys/``
  is a file or the ledger's key is damaged (F8), and names the safety plan when only its
  file cannot be read (F13).
* Chat commands ignore case; ``/quit`` and ``/退出`` end the chat too (F16).
* The setup screens' crisis line does not talk about "settings" (F19).

Every case runs in a temporary data directory with the in-memory keychain; every
sentence typed is made up for these tests.
"""

from __future__ import annotations

import os
import shutil
import sys

import pytest
from cli_support import L3_SENTENCE, ONBOARD_CN
from test_cli_doctor import doctor  # noqa: F401 (fixture)

from olivia import cli
from olivia.core.chang.safety_plan import SAFETY_PLAN_FILENAME, load_safety_plan_text
from olivia.core.crypto.errors import KeychainUnavailableError
from olivia.core.crypto.vault import KEYS_DIRNAME

OK, WARN, FAIL = "✓", "!", "✗"
CHAT = [*ONBOARD_CN, "下班路上堵了一个小时", "/exit"]
PLAN = ["胸口发闷", "", "听一首老歌", "", "小区的篮球场", "", "阿杰 13700000000", "", ""]
POSIX_ONLY = pytest.mark.skipif(
    sys.platform == "win32" or getattr(os, "geteuid", lambda: 1)() == 0,
    reason="POSIX permissions, and root reads everything",
)


def _set_up(run_cli, *, plan: bool = True) -> None:
    assert run_cli(["chat", "--rules"], CHAT).code == 0
    if plan:
        assert run_cli(["safety-plan"], PLAN).code == 0


def _line(run, start: str) -> str:
    found = [line for line in run.lines if line[2:].startswith(start)]
    assert len(found) == 1, (start, run.out)
    return found[0]


def _store(name: str) -> str:
    return cli.DOCTOR_STORE_NAMES[name] + "："


def _next(run, line: str) -> str:
    return run.lines[run.lines.index(line) + 1]


# -- F1, F20: a folder in place of the plan ---------------------------------------------------


def test_a_folder_in_place_of_the_plan_is_said_in_a_crisis(run_cli, data_home):
    _set_up(run_cli)
    path = data_home / SAFETY_PLAN_FILENAME
    path.unlink()
    path.mkdir()
    run = run_cli(["chat", "--rules", "--inspect"], [L3_SENTENCE, "/exit"])
    unreadable = load_safety_plan_text().crisis_unreadable
    assert unreadable in run.out
    assert "听一首老歌" not in run.out
    assert not any("安全计划 已展示" in line for line in run.panel)
    assert any("安全计划 读不出" in line for line in run.panel)


def test_a_damaged_plan_is_never_called_shown_in_the_panel(run_cli, data_home):
    _set_up(run_cli)
    path = data_home / SAFETY_PLAN_FILENAME
    path.write_bytes(path.read_bytes()[:-7])
    run = run_cli(["chat", "--rules", "--inspect"], [L3_SENTENCE, "/exit"])
    assert load_safety_plan_text().crisis_unreadable in run.out
    assert not any("安全计划 已展示" in line for line in run.panel)


def test_a_readable_plan_is_still_shown_in_the_panel(run_cli):
    _set_up(run_cli)
    run = run_cli(["chat", "--rules", "--inspect"], [L3_SENTENCE, "/exit"])
    assert "听一首老歌" in run.out
    assert any("安全计划 已展示" in line for line in run.panel)


# -- F6: a keychain that answers the probe but not a read -------------------------------------


def test_a_keychain_that_fails_on_reading_is_not_called_usable(
    run_cli,
    doctor,  # noqa: F811
    keychain,
    monkeypatch,
):
    _set_up(run_cli)

    def refuse(name: str) -> str | None:
        raise KeychainUnavailableError("locked")

    monkeypatch.setattr(keychain, "get", refuse)
    run = doctor()
    assert run.code == 1
    assert _line(run, "系统钥匙串") == f"{FAIL} {cli.DOCTOR_KEYCHAIN_UNAVAILABLE}"


# -- F7, F12, F13: permissions ----------------------------------------------------------------


@pytest.fixture
def blocked():
    changed: list[tuple[object, int]] = []

    def block(path, mode: int) -> None:
        changed.append((path, path.stat().st_mode & 0o777))
        path.chmod(mode)

    yield block
    for path, mode in reversed(changed):
        path.chmod(mode)  # type: ignore[attr-defined]


@POSIX_ONLY
def test_an_unreadable_keys_folder_is_named_not_called_damaged(
    run_cli,
    doctor,  # noqa: F811
    data_home,
    blocked,
):
    _set_up(run_cli)
    blocked(data_home / KEYS_DIRNAME, 0o000)
    run = doctor()
    assert run.code == 1
    assert f"{KEYS_DIRNAME}" in _line(run, "数据目录读不了")
    for name in ("ledger", "safety_plan"):
        assert "文件或钥匙不完整" not in _line(run, _store(name))
        assert _line(run, _store(name)).startswith(FAIL)


@POSIX_ONLY
def test_an_unreadable_ledger_folder_names_it(
    run_cli,
    doctor,  # noqa: F811
    data_home,
    blocked,
):
    _set_up(run_cli)
    blocked(data_home / "ledger", 0o000)
    run = doctor()
    line = _line(run, "数据目录读不了")
    assert "ledger" in line and "设置和记录" not in line


@POSIX_ONLY
def test_loose_permissions_name_the_path(
    run_cli,
    doctor,  # noqa: F811
    data_home,
):
    _set_up(run_cli)
    (data_home / SAFETY_PLAN_FILENAME).chmod(0o644)
    run = doctor()
    line = _line(run, "数据目录的权限")
    assert line.startswith(WARN) and SAFETY_PLAN_FILENAME in line
    assert _next(run, line).startswith("  怎么修")


@POSIX_ONLY
def test_an_unreadable_plan_file_is_named_at_the_start_of_a_chat(run_cli, data_home, blocked):
    _set_up(run_cli)
    blocked(data_home / SAFETY_PLAN_FILENAME, 0o000)
    run = run_cli(["chat", "--rules"], ["/exit"])
    assert cli.CHAT_RECORDS_UNSAVED not in run.out
    assert cli.CHAT_PLAN_UNREADABLE in run.out
    assert run.out.index(cli.CHAT_PLAN_UNREADABLE) < run.out.index(cli.CHAT_HINT)


def test_a_file_in_place_of_the_data_directory_checks_nothing_else(
    run_cli,
    data_home,
    keychain,
):
    data_home.parent.mkdir(parents=True, exist_ok=True)
    data_home.write_text("not a folder", encoding="utf-8")
    run = run_cli(["doctor"])
    assert "再运行 olivia chat" not in run.out
    for name in cli.DOCTOR_STORE_NAMES:
        line = _line(run, _store(name))
        assert not line.startswith(OK), line


# -- F8: the summary cannot be saved ----------------------------------------------------------


def test_a_file_in_place_of_the_keys_folder_is_said_at_the_start(run_cli, data_home):
    _set_up(run_cli, plan=False)
    shutil.rmtree(data_home / KEYS_DIRNAME)
    (data_home / KEYS_DIRNAME).write_text("stand-in", encoding="utf-8")
    run = run_cli(["chat", "--rules"], ["今天风很大", "/exit"])
    assert cli.CHAT_KEYS_MISPLACED in run.out
    assert run.out.index(cli.CHAT_KEYS_MISPLACED) < run.out.index(cli.CHAT_HINT)


def test_a_damaged_ledger_key_is_said_at_the_start(run_cli, data_home):
    _set_up(run_cli, plan=False)
    (data_home / KEYS_DIRNAME / "ledger.key").write_bytes(b"garbage")
    run = run_cli(["chat", "--rules"], ["今天风很大", "/exit"])
    assert cli.CHAT_LEDGER_KEY_DAMAGED in run.out
    assert run.out.index(cli.CHAT_LEDGER_KEY_DAMAGED) < run.out.index(cli.CHAT_HINT)


# -- F9: how to fix every ✗ about stored data --------------------------------------------------


@pytest.mark.parametrize(
    ("damage", "name"),
    [("plan", "safety_plan"), ("ledger_key", "ledger"), ("plan_key", "safety_plan")],
)
def test_a_damaged_store_says_how_to_fix_it(
    run_cli,
    doctor,  # noqa: F811
    data_home,
    damage,
    name,
):
    _set_up(run_cli)
    if damage == "plan":
        path = data_home / SAFETY_PLAN_FILENAME
        path.write_bytes(path.read_bytes()[:30])
    elif damage == "ledger_key":
        (data_home / KEYS_DIRNAME / "ledger.key").write_bytes(b"zz")
    else:
        (data_home / KEYS_DIRNAME / "safety_plan.key").unlink()
    run = doctor()
    line = _line(run, _store(name))
    assert line.startswith(FAIL)
    fix = _next(run, line)
    assert fix.startswith("  怎么修"), run.out
    flag = "--safety-plan" if name == "safety_plan" else "--ledger"
    assert flag in fix


def test_a_damaged_plain_profile_says_how_to_fix_it_without_keys(
    doctor,  # noqa: F811
    data_home,
):
    from cli_support import save_profile

    from olivia.core.chang.profile import PROFILE_FILENAME

    save_profile(data_home)
    (data_home / PROFILE_FILENAME).write_text("{ nope", encoding="utf-8")
    shutil.rmtree(data_home / ".snapshots", ignore_errors=True)
    run = doctor()
    line = _line(run, _store("profile"))
    assert line.startswith(FAIL) and "钥匙" not in line
    assert _next(run, line).startswith("  怎么修")


# -- F16: chat commands ignore case -----------------------------------------------------------


@pytest.mark.parametrize("word", ["/EXIT", "/Exit", "／ｅｘｉｔ", "/quit", "/退出"])
def test_exit_ignores_case_and_has_aliases(run_cli, word):
    _set_up(run_cli, plan=False)
    run = run_cli(["chat", "--rules"], [word, "这句不该被读到"])
    assert run.code == 0
    assert "这句不该被读到" not in "".join(run.texts)
    assert cli.GOODBYE in run.out


# -- F19 ---------------------------------------------------------------------------------------


def test_the_setup_crisis_line_names_no_settings():
    assert "设置" not in cli.SETUP_CRISIS


def test_moving_a_damaged_profile_aside_keeps_the_other_records(run_cli, data_home):
    """What ``DOCTOR_PROFILE_FIX`` promises: setting up again keeps the plan."""
    from olivia.core.chang.profile import PROFILE_FILENAME

    _set_up(run_cli)
    path = data_home / PROFILE_FILENAME
    path.write_text("{ nope", encoding="utf-8")
    shutil.rmtree(data_home / ".snapshots", ignore_errors=True)
    path.rename(data_home / "profile-old.json")
    assert run_cli(["chat", "--rules"], [*ONBOARD_CN, "/exit"]).code == 0
    shown = run_cli(["safety-plan"], [""])
    assert "听一首老歌" in shown.out, shown.out
