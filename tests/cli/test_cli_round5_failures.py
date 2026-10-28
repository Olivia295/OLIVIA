"""Round 5 (QA q4): what ``olivia doctor`` says about damaged data, the chat's opening
notices, the global hotlines when the region cannot be read, the safety plan's edges, and
the fresh-computer and journal details.

Every case runs in a temporary data directory with the in-memory keychain; the sentences
typed are made up for these tests.
"""

from __future__ import annotations

import io
import shutil

import pytest
from cli_support import L3_SENTENCE, ONBOARD_CN, save_profile
from test_cli_doctor import doctor  # noqa: F401 (fixture)

from olivia import cli
from olivia.core.chang.profile import PROFILE_FILENAME
from olivia.core.chang.safety_plan import (
    SAFETY_PLAN_FILENAME,
    SafetyPlanStore,
    load_safety_plan_text,
)
from olivia.core.crypto.errors import KeychainUnavailableError
from olivia.core.crypto.vault import MASTER_ITEM
from olivia.core.models import UserRegion

OK, WARN, FAIL = "✓", "!", "✗"
CMD = load_safety_plan_text().command
CHAT = [*ONBOARD_CN, "这周项目收尾，有点累", "/exit"]
# A plan with sections 1-4 filled, then section 5 skipped.
PLAN = ["手心一直出汗", "", "泡一杯热茶", "", "去河边的步道走走", "", "阿梅 13900000000", "", ""]


def _line(run, start: str) -> str:
    found = [line for line in run.lines if line[2:].startswith(start)]
    assert len(found) == 1, (start, run.out)
    return found[0]


def _store(name: str) -> str:
    return cli.DOCTOR_STORE_NAMES[name] + "："


def _set_up(run_cli, *, plan: bool = True) -> None:
    assert run_cli(["chat", "--rules"], CHAT).code == 0
    if plan:
        assert run_cli(["safety-plan"], PLAN).code == 0


# -- doctor: the profile ----------------------------------------------------------------------


@pytest.mark.parametrize("damage", ["garbled", "deleted"])
def test_a_profile_with_a_valid_snapshot_is_a_warning_that_names_the_restore(
    doctor,  # noqa: F811
    data_home,
    damage,
):
    save_profile(data_home)
    save_profile(data_home, user_name="阿禾")  # the first version becomes a snapshot
    path = data_home / PROFILE_FILENAME
    if damage == "garbled":
        path.write_bytes(b"\x00\xff not a profile")
    else:
        path.unlink()
    run = doctor()
    assert run.code == 0, run.out
    line = _line(run, _store("profile"))
    assert line.startswith(f"{WARN} ") and "自动从备份恢复" in line
    assert _line(run, "第一次设置") == f"{OK} {cli.DOCTOR_ONBOARDED}"


def test_a_folder_in_place_of_the_profile_is_named_not_called_a_permission_problem(
    doctor,  # noqa: F811
    data_home,
):
    save_profile(data_home)
    path = data_home / PROFILE_FILENAME
    path.unlink()
    path.mkdir()
    run = doctor()
    assert run.code == 1
    line = _line(run, _store("profile"))
    assert line.startswith(f"{FAIL} ") and "profile.json" in line and "文件夹" in line
    assert "权限" not in line
    fix = run.lines[run.lines.index(line) + 1]
    assert fix.startswith("  怎么修：") and "profile.json" in fix


# -- doctor: the sealed stores ----------------------------------------------------------------


def test_a_truncated_safety_plan_fails_as_the_command_says(run_cli, doctor, data_home):  # noqa: F811
    _set_up(run_cli)
    path = data_home / SAFETY_PLAN_FILENAME
    path.write_bytes(path.read_bytes()[:50])
    run = doctor()
    assert run.code == 1
    assert _line(run, _store("safety_plan")).startswith(f"{FAIL} ")
    assert _line(run, _store("ledger")).startswith(f"{OK} ")
    assert CMD["damaged"] in run_cli(["safety-plan"], [""]).out


def test_a_ledger_entry_cut_short_is_a_partial_failure(run_cli, doctor, data_home):  # noqa: F811
    _set_up(run_cli, plan=False)
    _set_up(run_cli, plan=False)
    entries = sorted((data_home / "ledger").glob("*.olv"))
    assert len(entries) >= 2
    entries[0].write_bytes(entries[0].read_bytes()[:-3])
    run = doctor()
    assert run.code == 1
    assert _line(run, _store("ledger")).endswith("有一部分打不开")


def test_a_file_in_place_of_the_ledger_folder_fails_with_the_fix(run_cli, doctor, data_home):  # noqa: F811
    _set_up(run_cli)
    shutil.rmtree(data_home / "ledger")
    (data_home / "ledger").write_text("stand-in", encoding="utf-8")
    run = doctor()
    assert run.code == 1
    line = _line(run, _store("ledger"))
    assert line.startswith(f"{FAIL} ") and "ledger" in line and "文件" in line
    assert run.lines[run.lines.index(line) + 1].startswith("  怎么修：")


def test_a_file_in_place_of_the_keys_folder_says_what_and_how(run_cli, doctor, data_home):  # noqa: F811
    _set_up(run_cli)
    shutil.rmtree(data_home / "keys")
    (data_home / "keys").write_text("stand-in", encoding="utf-8")
    run = doctor()
    assert run.code == 1
    assert _line(run, "加密钥匙") == f"{FAIL} {cli.DOCTOR_KEYS_MISPLACED}"
    fix = run.lines[run.lines.index(f"{FAIL} {cli.DOCTOR_KEYS_MISPLACED}") + 1]
    assert fix.startswith("  怎么修：") and "olivia forget --all" in fix
    assert "keys 文件夹" in _line(run, _store("safety_plan"))


def test_a_master_key_gone_from_the_keychain_fails_with_the_fix(run_cli, doctor, keychain):  # noqa: F811
    _set_up(run_cli)
    del keychain.items[MASTER_ITEM]
    run = doctor()
    assert run.code == 1
    for name in ("ledger", "safety_plan"):
        assert _line(run, _store(name)).endswith("系统钥匙串里找不到它的主钥匙")
    assert f"  {cli.DOCTOR_MASTER_FIX}" in run.lines


def test_a_locked_keychain_with_data_is_not_a_lost_key(run_cli, doctor, keychain):  # noqa: F811
    _set_up(run_cli)
    keychain.broken = KeychainUnavailableError("locked")
    run = doctor()
    assert run.code == 1
    assert _line(run, _store("safety_plan")).endswith("现在打不开，要等系统钥匙串能用")
    assert f"  {cli.DOCTOR_MASTER_FIX}" not in run.lines


def test_intact_data_opens_and_its_contents_never_appear(run_cli, doctor):  # noqa: F811
    _set_up(run_cli)
    run = doctor()
    assert run.code == 0, run.out
    for name in ("ledger", "safety_plan"):
        assert _line(run, _store(name)) == f"{OK} {cli.DOCTOR_STORE_NAMES[name]}：能打开"
    for typed in ("手心一直出汗", "泡一杯热茶", "阿梅", "13900000000", "项目收尾"):
        assert typed not in run.out


# -- chat: said at the start, and in a crisis -------------------------------------------------


def test_chat_says_at_the_start_when_the_ledger_folder_is_a_file(run_cli, data_home):
    _set_up(run_cli, plan=False)
    shutil.rmtree(data_home / "ledger")
    (data_home / "ledger").write_text("stand-in", encoding="utf-8")
    run = run_cli(["chat", "--rules"], ["/exit"])
    assert run.out.count(cli.CHAT_LEDGER_MISPLACED) == 1
    assert run.out.index(cli.CHAT_LEDGER_MISPLACED) < run.out.index(cli.CHAT_HINT)


def test_chat_says_at_the_start_and_in_a_crisis_when_the_master_key_is_gone(run_cli, keychain):
    _set_up(run_cli)
    del keychain.items[MASTER_ITEM]
    run = run_cli(["chat", "--rules"], [L3_SENTENCE, "/exit"])
    assert run.out.count(cli.CHAT_MASTER_LOST) == 1
    assert run.out.index(cli.CHAT_MASTER_LOST) < run.out.index(cli.CHAT_HINT)
    unreadable = load_safety_plan_text().crisis_unreadable
    assert unreadable and unreadable in run.out
    assert "110" in run.out[: run.out.index(unreadable) + len(unreadable) + 200]


def test_a_crisis_with_a_damaged_plan_says_it_cannot_be_read(run_cli, data_home):
    _set_up(run_cli)
    path = data_home / SAFETY_PLAN_FILENAME
    path.write_bytes(path.read_bytes()[:-5])
    run = run_cli(["chat", "--rules"], [L3_SENTENCE, "/exit"])
    assert load_safety_plan_text().crisis_unreadable in run.out
    assert "泡一杯热茶" not in run.out


def test_without_a_saved_plan_a_crisis_says_nothing_about_one(run_cli):
    _set_up(run_cli, plan=False)
    run = run_cli(["chat", "--rules"], [L3_SENTENCE, "/exit"])
    assert load_safety_plan_text().crisis_unreadable not in run.out


# -- the global hotlines when the region cannot be read ---------------------------------------


@pytest.mark.parametrize("command", [["resources"], ["chat", "--rules"]])
def test_a_sealed_locked_profile_lists_every_regions_emergency_numbers(
    run_cli, data_home, keychain, command
):
    save_profile(data_home, enable_at_rest_encryption=True)
    keychain.broken = KeychainUnavailableError("locked")
    run = run_cli(command, ["/exit"])
    assert run.code == 1
    assert cli.RESOURCES_EVERYWHERE in run.out
    listed = run.out.split(cli.RESOURCES_EVERYWHERE, 1)[1].split("\n\n", 1)[0]
    for number in ("110", "120", "999", "911", "000"):
        assert number in listed
    assert "112" in run.out
    assert "12356" not in run.out  # emergency numbers only, as the fixed help


def test_a_known_region_shows_only_its_own_card(run_cli, data_home):
    save_profile(data_home, region=UserRegion("HK", "Asia/Hong_Kong"))
    run = run_cli(["resources"])
    assert cli.RESOURCES_EVERYWHERE not in run.out


# -- the safety plan --------------------------------------------------------------------------


def test_a_new_plan_ended_after_its_first_section_keeps_that_section(run_cli, data_home):
    save_profile(data_home)
    run = run_cli(["safety-plan"], ["胸口发紧", "", "数窗外的车"])
    assert run.code == 0
    assert run.lines[-1] == CMD["left_saved"]
    plan = SafetyPlanStore(data_home).load()
    assert plan is not None
    assert plan.warning_signs == ("胸口发紧",) and plan.coping == ("数窗外的车",)


class _InterruptAfter(io.StringIO):
    """Gives ``lines`` one by one, then Ctrl-C."""

    def __init__(self, lines: list[str]) -> None:
        super().__init__()
        self._lines = list(lines)

    def readline(self, size: int | None = -1) -> str:
        if not self._lines:
            raise KeyboardInterrupt
        return self._lines.pop(0) + "\n"


def test_ctrl_c_in_a_new_plan_keeps_what_was_written_and_says_goodbye_its_own_way(
    run_cli, data_home
):
    save_profile(data_home)
    run = run_cli(["safety-plan"], stdin=_InterruptAfter(["胸口发紧", ""]))
    assert run.code == 0
    assert run.lines[-1] == CMD["left_saved"]
    assert cli.GOODBYE not in run.out
    plan = SafetyPlanStore(data_home).load()
    assert plan is not None and plan.warning_signs == ("胸口发紧",)


def test_ctrl_c_before_anything_is_written_saves_nothing(run_cli, data_home):
    save_profile(data_home)
    run = run_cli(["safety-plan"], stdin=_InterruptAfter([]))
    assert run.code == 0 and run.lines[-1] == CMD["left"]
    assert cli.GOODBYE not in run.out
    assert not (data_home / SAFETY_PLAN_FILENAME).exists()


def test_a_line_typed_into_an_edit_before_the_input_ends_is_said_not_saved(run_cli, data_home):
    save_profile(data_home)
    assert run_cli(["safety-plan"], PLAN).code == 0
    run = run_cli(["safety-plan"], ["1", "2", "听雨声的录音"])
    title = load_safety_plan_text().titles[list(load_safety_plan_text().titles)[1]]
    assert CMD["edit_not_saved"].replace("{title}", title) in run.out
    assert run.lines[-1] == CMD["unchanged"]
    plan = SafetyPlanStore(data_home).load()
    assert plan is not None and plan.coping == ("泡一杯热茶",)


@pytest.mark.parametrize("word", ["确认", "确定", "1", "１"])
def test_clearing_the_plan_takes_the_same_words_as_forget(run_cli, data_home, word):
    save_profile(data_home)
    assert run_cli(["safety-plan"], PLAN).code == 0
    run = run_cli(["safety-plan"], ["2", word])
    assert run.lines[-1] == CMD["cleared"]
    assert not (data_home / SAFETY_PLAN_FILENAME).exists()


def test_anything_else_keeps_the_plan(run_cli, data_home):
    save_profile(data_home)
    assert run_cli(["safety-plan"], PLAN).code == 0
    run = run_cli(["safety-plan"], ["2", "算了"])
    assert run.lines[-1] == CMD["unchanged"]
    assert (data_home / SAFETY_PLAN_FILENAME).exists()


# -- a fresh computer, and the journal --------------------------------------------------------


@pytest.mark.parametrize(
    ("argv", "lines"),
    [(["resources"], []), (["profile"], []), (["forget", "--all"], ["确定"])],
)
def test_a_fresh_computer_keeps_no_empty_data_directory(run_cli, data_home, argv, lines):
    run_cli(argv, lines)
    assert not data_home.exists()


def test_a_first_visit_still_makes_the_data_directory(run_cli, data_home):
    assert run_cli(["chat", "--rules"], CHAT).code == 0
    assert (data_home / PROFILE_FILENAME).is_file()


def test_the_journal_prints_no_markdown_heading(run_cli):
    _set_up(run_cli, plan=False)
    run = run_cli(["journal"], ["", ""])
    assert not [line for line in run.lines if line.lstrip().startswith("#")]
