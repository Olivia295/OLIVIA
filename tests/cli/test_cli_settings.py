"""``olivia settings``, ``olivia notify-check`` and ``forget --all`` (next-phase B9, D5).

System reminders are off by default; turning them on says what is installed and asks
once more; off (or ``forget --all``) removes the job. The scheduler and the notification
go to the suite's :class:`FakeMachine` (macOS by default): nothing is installed.
"""

from __future__ import annotations

import io
from datetime import timedelta

import pytest
from cli_support import NOW, ONBOARD_CN, save_profile

from olivia import cli
from olivia.core.chang.profile import ProfileLockedError, ProfileStore
from olivia.core.crypto.errors import KeychainUnavailableError, NoKeychainError
from olivia.notify.check import STATE_FILENAME
from olivia.notify.system import RunResult, System
from olivia.notify.text import fill, load_notify_text

S = load_notify_text().settings
N = load_notify_text().notifications
BOOTOUT = ("launchctl", "bootout", "gui/501/com.olivia.notify")


def _plist(machine):
    return machine.home / "Library" / "LaunchAgents" / "com.olivia.notify.plist"


def _item(on: bool) -> str:
    return f"  1. {fill(S['notifications_item'], state=S['state_on' if on else 'state_off'])}"


def _saved(home):
    return ProfileStore(home).load()


def test_reminders_are_off_by_default_and_onboarding_mentions_settings(run_cli, data_home, machine):
    chat = run_cli(["chat"], [*ONBOARD_CN, "/exit"])
    assert chat.code == 0 and "olivia settings" in chat.out
    assert _saved(data_home).notifications is False
    assert machine.calls == []
    shown = run_cli(["settings"], [""])
    assert shown.code == 0 and shown.lines[:2] == [S["heading"], _item(False)]
    assert machine.calls == []


def test_turning_on_explains_asks_and_installs_one_job(run_cli, data_home, machine):
    save_profile(data_home)
    run = run_cli(["settings"], ["1", "1"])
    assert run.code == 0, run.out
    job = fill(load_notify_text().places["launchd"], where=str(_plist(machine)))
    assert fill(S["about_on"], job=job) in run.out
    assert S["confirm"] in run.lines and run.lines[-1] == S["turned_on"]
    assert machine.argvs == [BOOTOUT, ("launchctl", "bootstrap", "gui/501", str(_plist(machine)))]
    assert _plist(machine).is_file()
    assert _saved(data_home).notifications is True
    assert run_cli(["settings"], [""]).lines[1] == _item(True)


@pytest.mark.parametrize("answer", ["2", "", "好的"])
def test_anything_but_yes_at_the_confirmation_changes_nothing(run_cli, data_home, machine, answer):
    save_profile(data_home)
    run = run_cli(["settings"], ["1", answer])
    assert run.code == 0 and run.lines[-1] == S["cancelled"]
    assert machine.calls == [] and not _plist(machine).exists()
    assert _saved(data_home).notifications is False


def test_turning_off_removes_the_job_and_the_state_file(run_cli, data_home, machine):
    save_profile(data_home)
    run_cli(["settings"], ["1", "1"])
    (data_home / STATE_FILENAME).write_text('{"version": 1}', encoding="utf-8")
    machine.calls.clear()
    run = run_cli(["settings"], ["1"])
    assert run.code == 0 and run.lines[-1] == S["turned_off"]
    assert machine.argvs == [BOOTOUT]
    assert not _plist(machine).exists() and not (data_home / STATE_FILENAME).exists()
    assert _saved(data_home).notifications is False


def test_a_failed_install_stays_off(run_cli, data_home, machine):
    save_profile(data_home)
    machine.results[("launchctl", "bootstrap")] = RunResult(5)
    run = run_cli(["settings"], ["1", "1"])
    assert run.code == 1 and run.lines[-1] == S["install_failed"]
    assert not _plist(machine).exists()
    assert _saved(data_home).notifications is False


def test_a_failed_removal_still_turns_reminders_off(run_cli, data_home, machine):
    save_profile(data_home)
    machine.system = System.WINDOWS
    run_cli(["settings"], ["1", "1"])
    machine.results[("schtasks", "/Delete")] = RunResult(1)
    run = run_cli(["settings"], ["1"])
    assert run.code == 0 and run.lines[-1] == S["off_incomplete"]
    assert _saved(data_home).notifications is False


def test_a_profile_that_cannot_be_saved_rolls_the_install_back(
    run_cli, data_home, machine, monkeypatch
):
    save_profile(data_home)

    def locked(self: ProfileStore, profile: object) -> None:
        raise ProfileLockedError("the keychain is unavailable", lost=False)

    monkeypatch.setattr(ProfileStore, "save", locked)
    run = run_cli(["settings"], ["1", "1"])
    assert run.code == 1 and cli.PROFILE_LOCKED in run.lines
    assert machine.argvs[-1] == BOOTOUT and not _plist(machine).exists()
    assert _saved(data_home).notifications is False


@pytest.mark.parametrize("broken", [NoKeychainError("none"), KeychainUnavailableError("locked")])
def test_reminders_need_the_keychain(run_cli, data_home, machine, keychain, broken):
    save_profile(data_home)
    keychain.broken = broken
    run = run_cli(["settings"], ["1"])
    assert run.code == 1 and run.lines[-1] == S["needs_keychain"]
    assert machine.calls == []


def test_unsupported_machines_are_told_why(run_cli, data_home, machine):
    save_profile(data_home)
    machine.system = System.LINUX
    machine.found = {"systemctl", "crontab"}
    run = run_cli(["settings"], ["1"])
    assert run.code == 1 and run.lines[-1] == S["unsupported_notifier"]
    machine.system = System.OTHER
    run = run_cli(["settings"], ["1"])
    assert run.code == 1 and run.lines[-1] == S["unsupported_system"]
    assert _saved(data_home).notifications is False


def test_menu_answers(run_cli, data_home):
    save_profile(data_home)
    assert run_cli(["settings"], ["9"]).lines[-1] == S["unknown_choice"]
    assert run_cli(["settings"], []).code == 0


def test_settings_before_onboarding_and_for_a_minor(run_cli, data_home):
    run = run_cli(["settings"])
    assert run.code == 1 and run.lines == [S["not_onboarded"]]
    save_profile(data_home, age_confirmed_18_plus=False, region=None, age_gate_refused_at=NOW)
    run = run_cli(["settings"])
    assert run.code == 1 and run.lines == [S["adults_only"]]


# -- forget --all ------------------------------------------------------------------------------


def test_forget_all_removes_the_job(run_cli, data_home, machine):
    save_profile(data_home)
    run_cli(["settings"], ["1", "1"])
    (data_home / STATE_FILENAME).write_text('{"version": 1}', encoding="utf-8")
    machine.calls.clear()
    assert run_cli(["forget", "--all", "--yes"]).code == 0
    assert machine.argvs == [BOOTOUT]
    assert not _plist(machine).exists() and not (data_home / STATE_FILENAME).exists()


def test_forget_all_with_no_data_still_removes_a_leftover_job(run_cli, data_home, machine):
    _plist(machine).parent.mkdir(parents=True)
    _plist(machine).write_bytes(b"left over")
    run = run_cli(["forget", "--all", "--yes"])
    assert run.code == 0 and not _plist(machine).exists()


# -- notify-check ------------------------------------------------------------------------------


def test_notify_check_is_hidden_and_silent(run_cli, data_home, machine, capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"], stdout=io.StringIO())
    assert "notify-check" not in capsys.readouterr().out
    save_profile(data_home, notifications=True, created_at=NOW - timedelta(days=30))
    run = run_cli(["notify-check"])
    assert run.code == 0 and run.out == ""
    assert machine.argvs[-1][-1] == N["absence"]
    assert run_cli(["notify-check"]).code == 0
    assert len(machine.calls) == 1


def test_notify_check_sends_nothing_while_off(run_cli, data_home, machine):
    save_profile(data_home, created_at=NOW - timedelta(days=30))
    assert run_cli(["notify-check"]).code == 0
    assert machine.calls == []


def test_settings_help_is_listed(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"], stdout=io.StringIO())
    assert "settings" in capsys.readouterr().out
