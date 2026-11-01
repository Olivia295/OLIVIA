"""Round 7 (QA q4 re-test of round 6; drafts pending G-0): the command line on damaged data,
the safety plan and the chat's commands.

* B1: a ledger folder that cannot be read leaves the chat going (only the summary is not
  saved), ``olivia memory`` says so, and an error nothing else handled shows the saved
  region's numbers (12356 for CN), not only every region's emergency numbers.
* B2: ``olivia safety-plan`` says at once when a plan could not be saved now (``keys/`` a
  file, the master key gone or changed) instead of after five sections.
* B3: entries that do not open for a reason that can be put right are never called
  damaged nor offered for deletion; ``olivia doctor`` names a changed master key.
* B4: a ``keys/`` folder that cannot be read is named, not "the settings file".
* P1: a profile recovered from a snapshot is written back, so ``olivia doctor`` is ✓.
* P2, S2: a plan entry a crisis reply leaves out is said when it is written; every place
  word counts the same, and a home place named only for a chore is no place.
* P3: a plan that does not open is said before the chat.
* P4: a damaged care marker is removed on its own (``olivia forget --care``).
* P5: one chmod, not two; a folder in a file's place is not also "the wrong mode".
* P9: "/exit" with words ends the chat after the words are answered; ``memory --edit``
  confirms an edit in words of its own.
* P10: Enter at the timezone takes this computer's zone when it is one listed.

Every case runs in a temporary data directory with the in-memory keychain; every
sentence typed is made up for these tests.
"""

from __future__ import annotations

import json
import os
import shutil
import sys

import pytest
from cli_support import L3_SENTENCE, ONBOARD_CN
from test_cli_doctor import doctor  # noqa: F401 (fixture)

from olivia import cli
from olivia.core.chang import onboarding as onboarding_module
from olivia.core.chang.care import CARE_FILENAME
from olivia.core.chang.profile import PROFILE_FILENAME
from olivia.core.chang.safety_plan import SAFETY_PLAN_FILENAME, load_safety_plan_text
from olivia.core.crypto.vault import KEYS_DIRNAME, MASTER_ITEM
from olivia.core.memory.forget import load_forget_text
from olivia.core.memory.ledger import LEDGER_DIRNAME

OK, WARN, FAIL = "✓", "!", "✗"
CHAT = [*ONBOARD_CN, "下班路上买了一袋橘子", "/exit"]
PLAN = ["胸口发闷", "", "听一首老歌", "", "小区的篮球场", "", "阿杰 13700000000", "", ""]
POSIX_ONLY = pytest.mark.skipif(
    sys.platform == "win32" or getattr(os, "geteuid", lambda: 1)() == 0,
    reason="POSIX permissions, and root reads everything",
)
COMMAND = load_safety_plan_text().command
MEMORY = load_forget_text().memory
FORGET = load_forget_text().forget


def _set_up(run_cli, *, plan: bool = True) -> None:
    assert run_cli(["chat", "--rules"], CHAT).code == 0
    if plan:
        assert run_cli(["safety-plan"], PLAN).code == 0


def _store(name: str) -> str:
    return cli.DOCTOR_STORE_NAMES[name] + "："


def _line(run, start: str) -> str:
    found = [line for line in run.lines if line[2:].startswith(start)]
    assert len(found) == 1, (start, run.out)
    return found[0]


@pytest.fixture
def blocked():
    changed: list[tuple[object, int]] = []

    def block(path, mode: int) -> None:
        changed.append((path, path.stat().st_mode & 0o777))
        path.chmod(mode)

    yield block
    for path, mode in reversed(changed):
        path.chmod(mode)  # type: ignore[attr-defined]


def _wrong_master(keychain) -> None:
    """The master key item keeps its id but holds another key (a changed value)."""
    prefix, key_id, _ = keychain.items[MASTER_ITEM].split(":")
    keychain.items[MASTER_ITEM] = f"{prefix}:{key_id}:{'B' * 43}="


def _keys_a_file(data_home) -> None:
    shutil.rmtree(data_home / KEYS_DIRNAME)
    (data_home / KEYS_DIRNAME).write_text("stand-in", encoding="utf-8")


# -- B1: a ledger folder that cannot be read -------------------------------------------------


@POSIX_ONLY
def test_an_unreadable_ledger_leaves_the_chat_going(run_cli, data_home, blocked):
    _set_up(run_cli, plan=False)
    blocked(data_home / LEDGER_DIRNAME, 0o000)
    run = run_cli(["chat", "--rules"], ["3", "周末打算把书架重新整理一下", "/exit"])
    assert run.code == 0
    assert len(run.results) == 1  # the message was answered
    assert cli.DATA_DIR_UNUSABLE not in run.out
    assert cli.GOODBYE in run.out


@POSIX_ONLY
def test_memory_says_an_unreadable_ledger_folder_and_lists_the_rest(run_cli, data_home, blocked):
    _set_up(run_cli)
    blocked(data_home / LEDGER_DIRNAME, 0o000)
    run = run_cli(["memory"])
    assert run.code == 1
    assert MEMORY["ledger_unreadable"] in run.out
    assert MEMORY["safety_plan"] in run.out  # the rest is still listed
    assert cli.DATA_DIR_UNUSABLE not in run.out
    assert "olivia forget" not in MEMORY["ledger_unreadable"]


@POSIX_ONLY
def test_forget_an_entry_says_an_unreadable_ledger_folder(run_cli, data_home, blocked):
    _set_up(run_cli, plan=False)
    blocked(data_home / LEDGER_DIRNAME, 0o000)
    run = run_cli(["forget", "--entry", "1"], [""])
    assert run.code == 1
    assert FORGET["ledger_unreadable"] in run.out


# -- B2: a plan that could not be saved is said first ------------------------------------------


@pytest.mark.parametrize(
    ("fault", "key"),
    [
        ("keys_file", "cannot_save_keys"),
        ("master_gone", "cannot_save_master"),
        ("master_changed", "cannot_save_master"),
    ],
)
def test_a_plan_that_could_not_be_saved_is_not_started(run_cli, data_home, keychain, fault, key):
    _set_up(run_cli)
    if fault == "keys_file":
        _keys_a_file(data_home)
    elif fault == "master_gone":
        keychain.items.clear()
    else:
        _wrong_master(keychain)
    before = (data_home / SAFETY_PLAN_FILENAME).read_bytes()
    run = run_cli(["safety-plan"], PLAN)
    assert run.code == 1
    assert COMMAND[key] in run.out
    assert COMMAND["damaged"] not in run.out  # no "write a new one, it replaces the old"
    assert COMMAND["intro"] not in run.out  # nothing was asked
    assert (data_home / SAFETY_PLAN_FILENAME).read_bytes() == before
    if key == "cannot_save_master":
        assert "不要删" in COMMAND[key]


def test_a_new_plan_is_not_started_when_keys_is_a_file(run_cli, data_home):
    _set_up(run_cli, plan=False)
    _keys_a_file(data_home)
    run = run_cli(["safety-plan"], PLAN)
    assert run.code == 1
    assert COMMAND["cannot_save_keys"] in run.out
    assert not (data_home / SAFETY_PLAN_FILENAME).exists()


def test_a_damaged_plan_with_working_keys_is_still_replaced(run_cli, data_home):
    _set_up(run_cli)
    (data_home / SAFETY_PLAN_FILENAME).write_bytes(b"not a sealed plan")
    run = run_cli(["safety-plan"], PLAN)
    assert run.code == 0
    assert COMMAND["damaged"] in run.out
    assert COMMAND["saved"] in run.out


# -- B3: what can be put right is not called damaged --------------------------------------------


@pytest.mark.parametrize("fault", ["keys_file", "master_gone", "master_changed"])
def test_memory_says_fix_first_for_entries_a_fix_brings_back(run_cli, data_home, keychain, fault):
    _set_up(run_cli, plan=False)
    if fault == "keys_file":
        _keys_a_file(data_home)
    elif fault == "master_gone":
        keychain.items.clear()
    else:
        _wrong_master(keychain)
    run = run_cli(["memory"])
    fixable = MEMORY["unreadable_fixable"].split("{count}")[1]
    assert fixable in run.out
    assert MEMORY["unreadable"].split("{count}")[1] not in run.out
    assert "olivia doctor" in MEMORY["unreadable_fixable"]
    assert "forget" not in MEMORY["unreadable_fixable"]


@POSIX_ONLY
@pytest.mark.parametrize("what", ["keys", "entry"])
def test_memory_says_fix_first_for_permissions(run_cli, data_home, blocked, what):
    _set_up(run_cli, plan=False)
    target = (
        data_home / KEYS_DIRNAME
        if what == "keys"
        else sorted((data_home / LEDGER_DIRNAME).glob("*.olv"))[0]
    )
    blocked(target, 0o000)
    run = run_cli(["memory"])
    assert MEMORY["unreadable_fixable"].split("{count}")[1] in run.out
    assert cli.DATA_DIR_UNUSABLE not in run.out


def test_memory_still_calls_a_damaged_entry_damaged(run_cli, data_home):
    _set_up(run_cli, plan=False)
    entry = sorted((data_home / LEDGER_DIRNAME).glob("*.olv"))[0]
    entry.write_bytes(entry.read_bytes()[:-5] + b"xxxxx")
    run = run_cli(["memory"])
    assert MEMORY["unreadable"].split("{count}")[1] in run.out


def test_doctor_names_a_changed_master_key(
    run_cli,
    doctor,  # noqa: F811
    data_home,
    keychain,
):
    _set_up(run_cli)
    _wrong_master(keychain)
    run = doctor()
    for name in ("ledger", "safety_plan"):
        line = _line(run, _store(name))
        assert line.startswith(FAIL) and "对不上" in line, line
    assert f"  {cli.DOCTOR_MASTER_WRONG_FIX}" in run.lines
    assert not any("olivia forget --ledger" in line for line in run.lines)


def test_the_chat_says_a_changed_master_key_at_the_start(run_cli, keychain):
    _set_up(run_cli)
    _wrong_master(keychain)
    run = run_cli(["chat", "--rules"], ["今天风很大", "/exit"])
    assert cli.CHAT_MASTER_WRONG in run.out
    assert run.out.index(cli.CHAT_MASTER_WRONG) < run.out.index(cli.CHAT_HINT)
    assert cli.CHAT_PLAN_DAMAGED not in run.out  # the line above names the plan already


# -- B4: keys/ that cannot be read -------------------------------------------------------------


@POSIX_ONLY
def test_an_unreadable_keys_folder_is_named_at_the_chat(run_cli, data_home, blocked):
    _set_up(run_cli)
    blocked(data_home / KEYS_DIRNAME, 0o000)
    run = run_cli(["chat", "--rules"], ["今天风很大", "/exit"])
    assert cli.PROFILE_UNREADABLE not in run.out
    assert "设置文件" not in run.out.split(cli.CHAT_HINT)[0]
    assert cli.CHAT_KEYS_UNREADABLE in run.out
    assert run.code == 0


# -- P1: a recovered profile is written back -----------------------------------------------------


def test_a_recovered_profile_is_written_back(
    run_cli,
    doctor,  # noqa: F811
    data_home,
):
    _set_up(run_cli, plan=False)
    assert run_cli(["persona", "2"]).code == 0  # a second save: a snapshot to recover from
    (data_home / PROFILE_FILENAME).write_text("{ not json", encoding="utf-8")
    run = run_cli(["chat", "--rules"], ["今天风很大", "/exit"])
    assert "已经恢复到" in run.out
    assert "） 前后" not in run.out
    json.loads((data_home / PROFILE_FILENAME).read_text(encoding="utf-8"))
    after = doctor()
    assert _line(after, _store("profile")).startswith(OK)
    assert not any(line.startswith(WARN) and "备份" in line for line in after.lines)


# -- P2, S2: the plan's entries in a crisis --------------------------------------------------------


def test_an_entry_a_crisis_leaves_out_is_said_when_written(run_cli):
    assert run_cli(["chat", "--rules"], CHAT).code == 0
    plan = [
        "胸口发闷",
        "",
        "去阳台给那几盆绿萝浇浇水",
        "到江对面那座立交桥底下坐一会儿",
        "",
        "小区的篮球场",
        "",
        "阿杰 13700000000",
        "",
        "",
    ]
    run = run_cli(["safety-plan"], plan)
    assert run.code == 0
    assert run.out.count(COMMAND["crisis_hidden"]) == 1
    crisis = run_cli(["chat", "--rules"], [L3_SENTENCE, "/exit"])
    assert "绿萝浇浇水" in crisis.out
    assert "立交桥" not in crisis.out


# -- P3: a plan that does not open is said before the chat --------------------------------------


@pytest.mark.parametrize("damage", ["truncated", "folder"])
def test_a_plan_that_does_not_open_is_said_at_the_start(run_cli, data_home, damage):
    _set_up(run_cli)
    path = data_home / SAFETY_PLAN_FILENAME
    if damage == "truncated":
        path.write_bytes(path.read_bytes()[:10])
    else:
        path.unlink()
        path.mkdir()
    run = run_cli(["chat", "--rules"], ["今天风很大", "/exit"])
    assert cli.CHAT_PLAN_DAMAGED in run.out
    assert run.out.index(cli.CHAT_PLAN_DAMAGED) < run.out.index(cli.CHAT_HINT)
    memory = run_cli(["memory"])
    assert MEMORY["safety_plan_unreadable"] in memory.out


# -- P4: the care marker alone -------------------------------------------------------------------


def test_a_damaged_care_marker_is_removed_on_its_own(
    run_cli,
    doctor,  # noqa: F811
    data_home,
):
    _set_up(run_cli, plan=False)
    (data_home / CARE_FILENAME).write_bytes(b"garbage")
    run = doctor()
    assert f"  {cli.DOCTOR_CARE_FIX}" in run.lines
    assert "--care" in cli.DOCTOR_CARE_FIX and "--all" not in cli.DOCTOR_CARE_FIX
    entries = sorted((data_home / LEDGER_DIRNAME).glob("*.olv"))
    gone = run_cli(["forget", "--care", "--yes"])
    assert gone.code == 0
    assert FORGET["done_care"] in gone.out
    assert not (data_home / CARE_FILENAME).exists()
    assert sorted((data_home / LEDGER_DIRNAME).glob("*.olv")) == entries
    assert (data_home / PROFILE_FILENAME).exists()


def test_the_care_option_is_not_in_the_menu(run_cli):
    _set_up(run_cli, plan=False)
    run = run_cli(["forget"], [""])
    assert FORGET["about_care"] not in run.out
    assert "  6. " in run.out and "  7. " not in run.out  # the six targets, as before


# -- P5: one fix for permissions ---------------------------------------------------------------


@POSIX_ONLY
def test_an_unwritable_and_loose_directory_gets_one_chmod(
    run_cli,
    doctor,  # noqa: F811
    data_home,
    blocked,
):
    _set_up(run_cli)
    (data_home / SAFETY_PLAN_FILENAME).chmod(0o644)
    blocked(data_home, 0o500)
    run = doctor()
    fixes = [line for line in run.lines if "chmod" in line]
    assert len(fixes) == 1, fixes
    assert "u=rwX,go=" in fixes[0]


def test_a_folder_in_place_of_a_file_is_not_also_the_wrong_mode(
    run_cli,
    doctor,  # noqa: F811
    data_home,
):
    _set_up(run_cli)
    path = data_home / SAFETY_PLAN_FILENAME
    path.unlink()
    path.mkdir(mode=0o755)
    path.chmod(0o755)
    run = doctor()
    assert not any("权限" in line and line.startswith(WARN) for line in run.lines), run.out


# -- P9: /exit with words, memory --edit -----------------------------------------------------------


def test_exit_with_words_answers_them_then_ends(run_cli):
    _set_up(run_cli, plan=False)
    run = run_cli(["chat", "--rules"], ["/exit 那我先撤了"])
    assert run.code == 0
    assert run.texts == ["那我先撤了"]  # screened and answered like any message
    assert cli.GOODBYE in run.out or "电话" in run.out
    assert "12356" in run.out  # the numbers go along


def test_exit_with_a_crisis_sentence_ends_in_the_crisis_farewell(run_cli):
    _set_up(run_cli, plan=False)
    run = run_cli(["chat", "--rules"], [f"/exit {L3_SENTENCE}"])
    assert run.code == 0
    assert run.results[0].in_crisis
    assert "12356" in run.out


def test_an_edit_is_confirmed_in_words_of_its_own(run_cli):
    _set_up(run_cli, plan=False)
    assert run_cli(["chat", "--rules"], ["记住：周四要去取快递", "/exit"]).code == 0
    listing = run_cli(["memory"]).out
    number = next(line.split(".")[0] for line in listing.splitlines() if MEMORY["note"][:6] in line)
    run = run_cli(["memory", "--edit", number], ["周五要去取快递", "不了"])
    assert MEMORY["edit_confirm"] in run.out
    assert MEMORY["edit_unchanged"] in run.out
    assert FORGET["confirm"] not in run.out and FORGET["cancelled"] not in run.out


# -- P10: the timezone of this computer ------------------------------------------------------


def _onboard_au() -> list[str]:
    au = str(onboarding_module.SUPPORTED_REGIONS.index("AU") + 1)
    return ["1", "1", "", "小林", "", "", "", au]


def test_enter_takes_this_computers_zone_when_it_is_listed(run_cli, monkeypatch):
    monkeypatch.setattr(onboarding_module, "system_timezone", lambda: "Australia/Sydney")
    run = run_cli(["chat", "--rules"], [*_onboard_au(), "", "跳过", "/exit"])
    assert "我没有认出这个时区" not in run.out
    assert "Australia/Sydney" in run.out
    shown = run_cli(["region"])
    assert "Australia/Sydney" in shown.out


def test_enter_without_a_listed_zone_asks_for_one_plainly(run_cli):
    run = run_cli(["chat", "--rules"], [*_onboard_au(), "", "1", "跳过", "/exit"])
    hints = onboarding_module.load_onboarding_text().hints
    assert hints["timezone_needed"] in run.out
    assert "我没有认出这个时区" not in run.out
