"""The scheduled job and the notification command (next-phase B9, decision D5).

Everything runs against the suite's :class:`FakeMachine` (``machine`` fixture): files go
under a temporary home and every program is recorded, never run.
"""

from __future__ import annotations

import base64
import plistlib
from pathlib import Path

import pytest

from olivia.notify import jobs
from olivia.notify.jobs import Mechanism, Unsupported
from olivia.notify.system import RunResult, System, olivia_command

OLIVIA = "/Applications/OLIVIA Tools/bin/olivia"
ARGV = (OLIVIA, "notify-check")

PLIST = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>Label</key>
	<string>com.olivia.notify</string>
	<key>ProgramArguments</key>
	<array>
		<string>/Applications/OLIVIA Tools/bin/olivia</string>
		<string>notify-check</string>
	</array>
	<key>StartCalendarInterval</key>
	<dict>
		<key>Hour</key>
		<integer>20</integer>
		<key>Minute</key>
		<integer>30</integer>
	</dict>
	<key>ProcessType</key>
	<string>Background</string>
</dict>
</plist>
"""

SERVICE = """\
[Unit]
Description=OLIVIA reminder check

[Service]
Type=oneshot
ExecStart="/Applications/OLIVIA Tools/bin/olivia" "notify-check"
"""

TIMER = """\
[Unit]
Description=OLIVIA daily reminder check

[Timer]
OnCalendar=*-*-* 20:30:00
Unit=olivia-notify.service

[Install]
WantedBy=timers.target
"""


@pytest.fixture
def mac(machine):
    machine.system = System.MACOS
    machine.command = (OLIVIA,)
    return machine


@pytest.fixture
def windows(machine):
    machine.system = System.WINDOWS
    machine.command = (r"C:\Program Files\OLIVIA\olivia.exe",)
    return machine


@pytest.fixture
def linux(machine):
    machine.system = System.LINUX
    machine.command = (OLIVIA,)
    machine.found = {"systemctl", "notify-send", "crontab"}
    return machine


def _plist(machine) -> Path:
    return machine.home / "Library" / "LaunchAgents" / "com.olivia.notify.plist"


# -- the artifacts, exactly --------------------------------------------------------------------


def test_launchd_plist_is_exact():
    assert jobs.launchd_plist(ARGV).decode("utf-8") == PLIST
    assert plistlib.loads(jobs.launchd_plist(ARGV))["ProgramArguments"] == list(ARGV)


def test_plist_escapes_xml_in_paths():
    odd = ("/Users/a&b/<olivia>", "notify-check")
    raw = jobs.launchd_plist(odd)
    assert b"/Users/a&amp;b/&lt;olivia&gt;" in raw
    assert plistlib.loads(raw)["ProgramArguments"] == list(odd)


def test_schtasks_create_argv_is_exact():
    argv = (r"C:\Program Files\OLIVIA\olivia.exe", "notify-check")
    assert jobs.schtasks_create(argv) == [
        "schtasks",
        "/Create",
        "/TN",
        "OLIVIA-notify",
        "/TR",
        r'"C:\Program Files\OLIVIA\olivia.exe" notify-check',
        "/SC",
        "DAILY",
        "/ST",
        "20:30",
        "/F",
    ]


def test_systemd_units_are_exact():
    assert jobs.systemd_service(ARGV) == SERVICE
    assert jobs.systemd_timer() == TIMER


def test_systemd_exec_start_escapes_quotes_specifiers_and_variables():
    service = jobs.systemd_service(('/home/a"b\\c/100%/$HOME/olivia', "notify-check"))
    assert 'ExecStart="/home/a\\"b\\\\c/100%%/$$HOME/olivia" "notify-check"\n' in service


def test_cron_line_is_exact_and_quoted():
    assert jobs.cron_line(ARGV) == (
        "30 20 * * * '/Applications/OLIVIA Tools/bin/olivia' 'notify-check' # olivia-notify"
    )
    odd = jobs.cron_line(("/home/it's/50%/olivia", "notify-check"))
    assert odd.startswith("30 20 * * * '/home/it'\"'\"'s/50\\%/olivia' 'notify-check'")


def test_a_path_with_a_line_break_installs_nothing(mac):
    mac.command = ("/tmp/evil\n/olivia",)
    assert jobs.install(mac.host(), Mechanism.LAUNCHD) is False
    assert mac.calls == [] and not _plist(mac).exists()


# -- macOS -------------------------------------------------------------------------------------


def test_macos_install_writes_the_plist_and_bootstraps_it(mac):
    assert jobs.choose(mac.host()) is Mechanism.LAUNCHD
    assert jobs.install(mac.host(), Mechanism.LAUNCHD) is True
    assert mac.argvs == [
        ("launchctl", "bootout", "gui/501/com.olivia.notify"),
        ("launchctl", "bootstrap", "gui/501", str(_plist(mac))),
    ]
    assert _plist(mac).read_text(encoding="utf-8") == PLIST


def test_macos_uninstall_removes_only_our_plist(mac):
    jobs.install(mac.host(), Mechanism.LAUNCHD)
    other = _plist(mac).with_name("com.example.other.plist")
    other.write_text("keep", encoding="utf-8")
    mac.calls.clear()
    assert jobs.uninstall(mac.host()) is True
    assert mac.argvs == [("launchctl", "bootout", "gui/501/com.olivia.notify")]
    assert not _plist(mac).exists() and other.read_text(encoding="utf-8") == "keep"


def test_a_failed_bootstrap_leaves_nothing_and_turning_off_still_works(mac):
    mac.results[("launchctl", "bootstrap")] = RunResult(5)
    assert jobs.install(mac.host(), Mechanism.LAUNCHD) is False
    assert not _plist(mac).exists()
    mac.calls.clear()
    assert jobs.uninstall(mac.host()) is True
    assert mac.argvs == [("launchctl", "bootout", "gui/501/com.olivia.notify")]


# -- Windows -----------------------------------------------------------------------------------


def test_windows_install_and_uninstall(windows):
    assert jobs.choose(windows.host()) is Mechanism.SCHTASKS
    assert jobs.install(windows.host(), Mechanism.SCHTASKS) is True
    argv = (r"C:\Program Files\OLIVIA\olivia.exe", "notify-check")
    assert windows.argvs == [tuple(jobs.schtasks_create(argv))]
    windows.calls.clear()
    assert jobs.uninstall(windows.host()) is True
    assert windows.argvs == [
        ("schtasks", "/Query", "/TN", "OLIVIA-notify"),
        ("schtasks", "/Delete", "/TN", "OLIVIA-notify", "/F"),
    ]


def test_windows_failed_create_and_uninstall_without_a_task(windows):
    windows.results[("schtasks", "/Create")] = RunResult(1)
    assert jobs.install(windows.host(), Mechanism.SCHTASKS) is False
    windows.results[("schtasks", "/Query")] = RunResult(1)
    windows.calls.clear()
    assert jobs.uninstall(windows.host()) is True
    assert windows.argvs == [("schtasks", "/Query", "/TN", "OLIVIA-notify")]


def test_windows_delete_failure_is_reported(windows):
    windows.results[("schtasks", "/Delete")] = RunResult(1)
    assert jobs.uninstall(windows.host()) is False


# -- Linux: systemd ----------------------------------------------------------------------------


def test_linux_prefers_a_systemd_user_timer(linux):
    host = linux.host()
    assert jobs.choose(host) is Mechanism.SYSTEMD
    assert linux.argvs == [("systemctl", "--user", "show-environment")]
    linux.calls.clear()
    assert jobs.install(host, Mechanism.SYSTEMD) is True
    service, timer = jobs.unit_paths(host)
    assert service == linux.config_home / "systemd/user/olivia-notify.service"
    assert service.read_text(encoding="utf-8") == SERVICE
    assert timer.read_text(encoding="utf-8") == TIMER
    assert linux.argvs == [
        ("systemctl", "--user", "daemon-reload"),
        ("systemctl", "--user", "enable", "--now", "olivia-notify.timer"),
    ]


def test_linux_systemd_uninstall_removes_both_units(linux):
    host = linux.host()
    jobs.install(host, Mechanism.SYSTEMD)
    linux.calls.clear()
    linux.results[("crontab", "-l")] = RunResult(0, "0 7 * * * backup\n")
    assert jobs.uninstall(host) is True
    assert linux.argvs == [
        ("systemctl", "--user", "disable", "--now", "olivia-notify.timer"),
        ("systemctl", "--user", "daemon-reload"),
        ("crontab", "-l"),
    ]
    assert not any(p.exists() for p in jobs.unit_paths(host))


def test_linux_failed_enable_removes_the_units(linux):
    linux.results[("systemctl", "--user", "enable")] = RunResult(1)
    host = linux.host()
    assert jobs.install(host, Mechanism.SYSTEMD) is False
    assert not any(p.exists() for p in jobs.unit_paths(host))
    assert linux.argvs[-1] == ("systemctl", "--user", "daemon-reload")


# -- Linux: crontab ----------------------------------------------------------------------------


def test_linux_falls_back_to_crontab(linux):
    linux.results[("systemctl", "--user", "show-environment")] = RunResult(1)
    assert jobs.choose(linux.host()) is Mechanism.CRON
    linux.found.discard("systemctl")
    assert jobs.choose(linux.host()) is Mechanism.CRON


def test_cron_install_keeps_other_lines_and_replaces_ours(linux):
    old = "30 20 * * * '/old/olivia' 'notify-check' # olivia-notify"
    linux.results[("crontab", "-l")] = RunResult(0, f"0 7 * * * backup\n{old}\n")
    assert jobs.install(linux.host(), Mechanism.CRON) is True
    assert linux.calls[-1] == (("crontab", "-"), f"0 7 * * * backup\n{jobs.cron_line(ARGV)}\n")


def test_cron_install_without_a_crontab(linux):
    linux.results[("crontab", "-l")] = RunResult(1)
    assert jobs.install(linux.host(), Mechanism.CRON) is True
    assert linux.calls == [
        (("crontab", "-l"), None),
        (("crontab", "-"), f"{jobs.cron_line(ARGV)}\n"),
    ]


def test_cron_install_fails_when_the_crontab_cannot_be_read(linux):
    linux.results[("crontab", "-l")] = RunResult(2)
    assert jobs.install(linux.host(), Mechanism.CRON) is False
    assert linux.argvs == [("crontab", "-l")]


def test_cron_uninstall_removes_only_our_line(linux):
    mine = jobs.cron_line(ARGV)
    linux.results[("crontab", "-l")] = RunResult(0, f"0 7 * * * backup\n{mine}\n")
    assert jobs.uninstall(linux.host()) is True
    assert linux.calls == [(("crontab", "-l"), None), (("crontab", "-"), "0 7 * * * backup\n")]


def test_cron_uninstall_removes_a_crontab_that_held_only_our_line(linux):
    linux.results[("crontab", "-l")] = RunResult(0, f"{jobs.cron_line(ARGV)}\n")
    assert jobs.uninstall(linux.host()) is True
    assert linux.argvs == [("crontab", "-l"), ("crontab", "-r")]


def test_cron_uninstall_without_our_line_changes_nothing(linux):
    linux.results[("crontab", "-l")] = RunResult(0, "0 7 * * * backup\n")
    assert jobs.uninstall(linux.host()) is True
    assert linux.argvs == [("crontab", "-l")]


# -- what this machine can do ------------------------------------------------------------------


def test_unsupported_machines(linux, machine):
    linux.found = {"systemctl", "crontab"}
    assert jobs.choose(linux.host()) is Unsupported.NOTIFIER
    linux.found = {"notify-send"}
    assert jobs.choose(linux.host()) is Unsupported.SCHEDULER
    machine.system = System.OTHER
    assert jobs.choose(machine.host()) is Unsupported.SYSTEM
    assert jobs.uninstall(machine.host()) is True
    assert jobs.notify_argv(machine.host(), "OLIVIA", "x") == []


# -- the notification --------------------------------------------------------------------------


def test_macos_notification_passes_the_texts_as_arguments(mac):
    assert jobs.notify_argv(mac.host(), 'OL"IVIA', "很久没聊了") == [
        [
            "osascript",
            "-e",
            "on run argv",
            "-e",
            "display notification (item 2 of argv) with title (item 1 of argv)",
            "-e",
            "end run",
            'OL"IVIA',
            "很久没聊了",
        ]
    ]
    assert jobs.send(mac.host(), "OLIVIA", "很久没聊了") is True
    assert len(mac.calls) == 1


def test_linux_notification(linux):
    assert jobs.notify_argv(linux.host(), "OLIVIA", "很久没聊了") == [
        ["notify-send", "--app-name=OLIVIA", "OLIVIA", "很久没聊了"]
    ]


def test_windows_toast_then_msg_fallback(windows):
    toast, fallback = jobs.notify_argv(windows.host(), "OLIVIA", "it's 很久没聊了")
    assert toast[:6] == [
        "powershell",
        "-NoProfile",
        "-NonInteractive",
        "-WindowStyle",
        "Hidden",
        "-EncodedCommand",
    ]
    script = base64.b64decode(toast[6]).decode("utf-16-le")
    assert script == jobs.windows_toast_script("OLIVIA", "it's 很久没聊了")
    assert "CreateTextNode('it''s 很久没聊了')" in script
    assert "Windows.UI.Notifications" in script and "BurntToast" not in script
    assert fallback == ["msg", "tester", "OLIVIA：it's 很久没聊了"]
    windows.results[("powershell",)] = RunResult(1)
    assert jobs.send(windows.host(), "OLIVIA", "x") is True
    assert [argv[0] for argv in windows.argvs] == ["powershell", "msg"]
    windows.results[("msg",)] = RunResult(1)
    assert jobs.send(windows.host(), "OLIVIA", "x") is False


# -- the command the job runs ------------------------------------------------------------------


def test_olivia_command_uses_the_running_console_script(tmp_path):
    script = tmp_path / "bin" / "olivia"
    script.parent.mkdir()
    script.write_text("#!/bin/sh\n", encoding="utf-8")
    assert olivia_command(str(script), which=lambda _: None) == (str(script.resolve()),)


def test_olivia_command_falls_back_to_path_then_the_module(tmp_path):
    found = tmp_path / "olivia"
    found.write_text("", encoding="utf-8")
    assert olivia_command("/src/olivia/cli.py", which=lambda _: str(found)) == (
        str(found.resolve()),
    )
    python = tmp_path / "venv" / "bin" / "python"
    assert olivia_command("/src/olivia/cli.py", which=lambda _: None, python=str(python)) == (
        str(python),
        "-m",
        "olivia.cli",
    )


# -- is it installed? (olivia doctor: read only) -----------------------------------------------


def test_macos_installed_looks_for_the_plist_and_runs_nothing(mac):
    assert jobs.installed(mac.host()) is False
    _plist(mac).parent.mkdir(parents=True)
    _plist(mac).write_bytes(b"<plist/>")
    assert jobs.installed(mac.host()) is True
    assert mac.calls == []


def test_windows_installed_queries_the_task(windows):
    assert jobs.installed(windows.host()) is True
    assert windows.argvs == [("schtasks", "/Query", "/TN", jobs.TASK_NAME)]
    windows.results[("schtasks", "/Query")] = RunResult(1)
    assert jobs.installed(windows.host()) is False
    windows.results[("schtasks", "/Query")] = RunResult(127)  # schtasks could not start
    assert jobs.installed(windows.host()) is None


def test_linux_installed_finds_a_unit_or_our_crontab_line(linux):
    linux.results[("crontab", "-l")] = RunResult(0, "0 1 * * * backup\n")
    assert jobs.installed(linux.host()) is False
    linux.results[("crontab", "-l")] = RunResult(0, f"30 20 * * * x {jobs.CRON_MARKER}\n")
    assert jobs.installed(linux.host()) is True
    linux.results[("crontab", "-l")] = RunResult(2)
    assert jobs.installed(linux.host()) is None
    service, _ = jobs.unit_paths(linux.host())
    service.parent.mkdir(parents=True)
    service.write_text("x", encoding="utf-8")
    assert jobs.installed(linux.host()) is True
    assert all(argv == ("crontab", "-l") for argv in linux.argvs)


def test_linux_without_crontab_and_units_is_not_installed(linux):
    linux.found = set()
    assert jobs.installed(linux.host()) is False
    assert linux.calls == []


def test_other_systems_have_nothing_installed(machine):
    machine.system = System.OTHER
    assert jobs.installed(machine.host()) is False
