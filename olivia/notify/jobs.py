"""The one scheduled job per user, and the notification it may show (next-phase B9, D5).

The job runs ``olivia notify-check`` daily at 20:30 local time (:data:`HOUR`, :data:`MINUTE`):

* **macOS** -- a LaunchAgent, ``~/Library/LaunchAgents/com.olivia.notify.plist``
  (:func:`launchd_plist`), loaded with ``launchctl bootstrap gui/<uid>``;
* **Windows** -- a Task Scheduler task named :data:`TASK_NAME` (:func:`schtasks_create`);
* **Linux** -- a systemd user timer, ``olivia-notify.service`` + ``olivia-notify.timer``
  under ``$XDG_CONFIG_HOME/systemd/user`` (:func:`systemd_service`, :func:`systemd_timer`)
  when ``systemctl --user`` answers; otherwise one crontab line ending in
  :data:`CRON_MARKER` (:func:`cron_line`).

:func:`uninstall` removes exactly these (the plist, the task, the two unit files, the
marked crontab lines) and nothing else; it is also what ``olivia forget --all`` runs.
Program paths are passed as argv lists and quoted for each format, never through a shell.

The notification (:func:`notify_argv`): ``osascript`` with the texts as script arguments
(macOS); a toast through PowerShell and the built-in ``Windows.UI.Notifications`` API,
falling back to ``msg <user>`` (Windows; BurntToast is not installed by default);
``notify-send`` (Linux).
"""

from __future__ import annotations

import base64
import plistlib
import subprocess
from enum import StrEnum
from pathlib import Path
from typing import Final

from olivia.notify.system import Host, RunResult, System

HOUR: Final = 20
MINUTE: Final = 30
CHECK_COMMAND: Final = "notify-check"
LAUNCHD_LABEL: Final = "com.olivia.notify"
TASK_NAME: Final = "OLIVIA-notify"
SYSTEMD_UNIT: Final = "olivia-notify"
CRON_MARKER: Final = "# olivia-notify"
APP_NAME: Final = "OLIVIA"
WINDOWS_APP_ID: Final = (
    r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"
)
"""PowerShell's own AppUserModelID, registered on every Windows 10/11, so a toast shows
without registering anything."""


class Mechanism(StrEnum):
    LAUNCHD = "launchd"
    SCHTASKS = "schtasks"
    SYSTEMD = "systemd"
    CRON = "cron"


class Unsupported(StrEnum):
    """Why reminders cannot be turned on here."""

    SYSTEM = "system"
    """Not macOS, Windows or Linux."""
    NOTIFIER = "notifier"
    """Linux without ``notify-send``."""
    SCHEDULER = "scheduler"
    """Linux with neither ``systemctl --user`` nor ``crontab``."""


class UnsafePathError(ValueError):
    """A path holds a newline or NUL, which no job format can carry safely."""


# -- where things go ---------------------------------------------------------------------------


def plist_path(host: Host) -> Path:
    return host.home / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"


def systemd_dir(host: Host) -> Path:
    return host.config_home / "systemd" / "user"


def unit_paths(host: Host) -> tuple[Path, Path]:
    """(service, timer)."""
    base = systemd_dir(host)
    return base / f"{SYSTEMD_UNIT}.service", base / f"{SYSTEMD_UNIT}.timer"


def job_argv(host: Host) -> tuple[str, ...]:
    argv = (*host.command, CHECK_COMMAND)
    for arg in argv:
        if "\n" in arg or "\r" in arg or "\0" in arg:
            raise UnsafePathError("a job argument holds a line break or NUL")
    return argv


# -- the artifacts -----------------------------------------------------------------------------


def launchd_plist(argv: tuple[str, ...]) -> bytes:
    """The LaunchAgent: run ``argv`` daily at HOUR:MINUTE, as a background process."""
    job = {
        "Label": LAUNCHD_LABEL,
        "ProgramArguments": list(argv),
        "StartCalendarInterval": {"Hour": HOUR, "Minute": MINUTE},
        "ProcessType": "Background",
    }
    return plistlib.dumps(job, fmt=plistlib.FMT_XML, sort_keys=False)


def schtasks_create(argv: tuple[str, ...]) -> list[str]:
    """``schtasks /Create`` for the daily task (``/TR`` quoted the Windows way)."""
    action = subprocess.list2cmdline(list(argv))
    return [
        "schtasks",
        "/Create",
        "/TN",
        TASK_NAME,
        "/TR",
        action,
        "/SC",
        "DAILY",
        "/ST",
        f"{HOUR:02d}:{MINUTE:02d}",
        "/F",
    ]


def _systemd_quote(arg: str) -> str:
    """One ExecStart word: double-quoted, with systemd's ``\\``, ``"``, ``%`` and ``$``
    escaped, so a path is never split or expanded."""
    escaped = arg.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%").replace("$", "$$")
    return f'"{escaped}"'


def systemd_service(argv: tuple[str, ...]) -> str:
    return (
        "[Unit]\n"
        "Description=OLIVIA reminder check\n"
        "\n"
        "[Service]\n"
        "Type=oneshot\n"
        f"ExecStart={' '.join(_systemd_quote(a) for a in argv)}\n"
    )


def systemd_timer() -> str:
    return (
        "[Unit]\n"
        "Description=OLIVIA daily reminder check\n"
        "\n"
        "[Timer]\n"
        f"OnCalendar=*-*-* {HOUR:02d}:{MINUTE:02d}:00\n"
        f"Unit={SYSTEMD_UNIT}.service\n"
        "\n"
        "[Install]\n"
        "WantedBy=timers.target\n"
    )


def _sh_quote(arg: str) -> str:
    """POSIX single quotes; cron turns an unescaped ``%`` into a newline, so escape it."""
    return ("'" + arg.replace("'", "'\"'\"'") + "'").replace("%", "\\%")


def cron_line(argv: tuple[str, ...]) -> str:
    return f"{MINUTE} {HOUR} * * * {' '.join(_sh_quote(a) for a in argv)} {CRON_MARKER}"


# -- choosing ----------------------------------------------------------------------------------


def _systemd_user_available(host: Host) -> bool:
    if host.which("systemctl") is None:
        return False
    return host.run(["systemctl", "--user", "show-environment"], None).ok


def choose(host: Host) -> Mechanism | Unsupported:
    """The mechanism this machine uses, or why there is none."""
    if host.system is System.MACOS:
        return Mechanism.LAUNCHD
    if host.system is System.WINDOWS:
        return Mechanism.SCHTASKS
    if host.system is not System.LINUX:
        return Unsupported.SYSTEM
    if host.which("notify-send") is None:
        return Unsupported.NOTIFIER
    if _systemd_user_available(host):
        return Mechanism.SYSTEMD
    if host.which("crontab") is not None:
        return Mechanism.CRON
    return Unsupported.SCHEDULER


def where(host: Host, mechanism: Mechanism) -> str:
    """Where the job lives, for the confirmation text."""
    if mechanism is Mechanism.LAUNCHD:
        return str(plist_path(host))
    if mechanism is Mechanism.SCHTASKS:
        return TASK_NAME
    if mechanism is Mechanism.SYSTEMD:
        service, timer = unit_paths(host)
        return f"{service}、{timer}"
    return CRON_MARKER


# -- installing and removing -------------------------------------------------------------------


def _launchd_domain(host: Host) -> str:
    return f"gui/{host.uid}"


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _remove(path: Path) -> None:
    path.unlink(missing_ok=True)


def install(host: Host, mechanism: Mechanism) -> bool:
    """Install the job (replacing an earlier copy of it); False and nothing left on failure."""
    try:
        argv = job_argv(host)
    except UnsafePathError:
        return False
    try:
        if mechanism is Mechanism.LAUNCHD:
            return _install_launchd(host, argv)
        if mechanism is Mechanism.SCHTASKS:
            return host.run(schtasks_create(argv), None).ok
        if mechanism is Mechanism.SYSTEMD:
            return _install_systemd(host, argv)
        return _install_cron(host, argv)
    except OSError:
        uninstall(host)
        return False


def _install_launchd(host: Host, argv: tuple[str, ...]) -> bool:
    path = plist_path(host)
    host.run(["launchctl", "bootout", f"{_launchd_domain(host)}/{LAUNCHD_LABEL}"], None)
    _write(path, launchd_plist(argv))
    if host.run(["launchctl", "bootstrap", _launchd_domain(host), str(path)], None).ok:
        return True
    _remove(path)
    return False


def _install_systemd(host: Host, argv: tuple[str, ...]) -> bool:
    service, timer = unit_paths(host)
    _write(service, systemd_service(argv).encode("utf-8"))
    _write(timer, systemd_timer().encode("utf-8"))
    host.run(["systemctl", "--user", "daemon-reload"], None)
    if host.run(["systemctl", "--user", "enable", "--now", timer.name], None).ok:
        return True
    _remove(service)
    _remove(timer)
    host.run(["systemctl", "--user", "daemon-reload"], None)
    return False


def _crontab_lines(host: Host) -> list[str] | None:
    """The current crontab's lines ([] when there is none); None when it cannot be read."""
    listed = host.run(["crontab", "-l"], None)
    if listed.ok:
        return listed.stdout.splitlines()
    return [] if listed.returncode == 1 else None  # 1: "no crontab for <user>"


def _is_ours(line: str) -> bool:
    return line.rstrip().endswith(CRON_MARKER)


def _write_crontab(host: Host, lines: list[str]) -> RunResult:
    return host.run(["crontab", "-"], "".join(f"{line}\n" for line in lines))


def _install_cron(host: Host, argv: tuple[str, ...]) -> bool:
    lines = _crontab_lines(host)
    if lines is None:
        return False
    kept = [line for line in lines if not _is_ours(line)]
    return _write_crontab(host, [*kept, cron_line(argv)]).ok


def uninstall(host: Host) -> bool:
    """Remove whatever of the job is installed; True when nothing of it remains."""
    try:
        if host.system is System.MACOS:
            return _uninstall_launchd(host)
        if host.system is System.WINDOWS:
            return _uninstall_schtasks(host)
        if host.system is System.LINUX:
            systemd = _uninstall_systemd(host)
            cron = _uninstall_cron(host)
            return systemd and cron
    except OSError:
        return False
    return True


def _uninstall_launchd(host: Host) -> bool:
    path = plist_path(host)
    # Not loaded is fine (bootout then fails harmlessly); it only ever names our label.
    host.run(["launchctl", "bootout", f"{_launchd_domain(host)}/{LAUNCHD_LABEL}"], None)
    _remove(path)
    return True


def _uninstall_schtasks(host: Host) -> bool:
    if not host.run(["schtasks", "/Query", "/TN", TASK_NAME], None).ok:
        return True  # no such task
    return host.run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"], None).ok


def _uninstall_systemd(host: Host) -> bool:
    service, timer = unit_paths(host)
    if not service.exists() and not timer.exists():
        return True
    host.run(["systemctl", "--user", "disable", "--now", timer.name], None)
    _remove(service)
    _remove(timer)
    host.run(["systemctl", "--user", "daemon-reload"], None)
    return True


def _uninstall_cron(host: Host) -> bool:
    if host.which("crontab") is None:
        return True
    lines = _crontab_lines(host)
    if lines is None:
        return False
    if not any(_is_ours(line) for line in lines):
        return True
    kept = [line for line in lines if not _is_ours(line)]
    if any(line.strip() for line in kept):
        return _write_crontab(host, kept).ok
    return host.run(["crontab", "-r"], None).ok


# -- the notification --------------------------------------------------------------------------

_APPLESCRIPT: Final = (
    "on run argv",
    "display notification (item 2 of argv) with title (item 1 of argv)",
    "end run",
)


def _ps_literal(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def windows_toast_script(title: str, body: str) -> str:
    """PowerShell that shows a toast through the built-in Windows.UI.Notifications API.

    The texts become text nodes (no XML is parsed from them) inside single-quoted
    PowerShell literals.
    """
    return "\n".join(
        (
            "$ErrorActionPreference = 'Stop'",
            "$m = [Windows.UI.Notifications.ToastNotificationManager,"
            " Windows.UI.Notifications, ContentType = WindowsRuntime]",
            "$xml = $m::GetTemplateContent("
            "[Windows.UI.Notifications.ToastTemplateType]::ToastText02)",
            "$texts = $xml.GetElementsByTagName('text')",
            f"$null = $texts.Item(0).AppendChild($xml.CreateTextNode({_ps_literal(title)}))",
            f"$null = $texts.Item(1).AppendChild($xml.CreateTextNode({_ps_literal(body)}))",
            "$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)",
            f"$m::CreateToastNotifier({_ps_literal(WINDOWS_APP_ID)}).Show($toast)",
        )
    )


def notify_argv(host: Host, title: str, body: str) -> list[list[str]]:
    """The commands to try in order (the first that succeeds shows the notification)."""
    if host.system is System.MACOS:
        script = [part for line in _APPLESCRIPT for part in ("-e", line)]
        return [["osascript", *script, title, body]]
    if host.system is System.WINDOWS:
        encoded = base64.b64encode(windows_toast_script(title, body).encode("utf-16-le"))
        toast = [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-WindowStyle",
            "Hidden",
            "-EncodedCommand",
            encoded.decode("ascii"),
        ]
        return [toast, ["msg", host.user, f"{title}：{body}"]]
    if host.system is System.LINUX:
        return [["notify-send", f"--app-name={APP_NAME}", title, body]]
    return []


def send(host: Host, title: str, body: str) -> bool:
    """Show one notification; True when a command reported success."""
    return any(host.run(argv, None).ok for argv in notify_argv(host, title, body))
