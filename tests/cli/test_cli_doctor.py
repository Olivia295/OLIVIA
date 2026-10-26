"""``olivia doctor``: a read-only check of this computer's setup, safe to paste to us.

Every run must leave the data directory exactly as it was (no file or directory created,
changed or removed), never read, write or delete a keychain item, run no system program
on macOS, and print nothing the user typed: names, taboo topics, health or the plan.
"""

from __future__ import annotations

import shutil
import sys
from datetime import datetime, timedelta
from importlib import resources
from pathlib import Path

import pytest
from cli_support import L3_SENTENCE, NOW, ONBOARD_CN, save_profile
from test_cli_hotline_updates import _sign, _update, _yaml, key  # noqa: F401 (fixture)

from olivia import cli
from olivia.core.chang.profile import PROFILE_FILENAME
from olivia.core.crypto.errors import KeychainUnavailableError, NoKeychainError
from olivia.core.memory.state import STATE_FILENAME
from olivia.core.perception import student
from olivia.core.resources import bundle
from olivia.core.taxonomy import load_taxonomy
from olivia.notify import jobs

OK, WARN, FAIL = "✓", "!", "✗"
CHAT = [*ONBOARD_CN, "今天上班好累", "给我一个方法", "/done", L3_SENTENCE, "/exit"]
TYPED = ("青禾", "阿屿", "老家的房子", "相亲")


def _tree(home: Path) -> dict[str, bytes | None]:
    """Every path under ``home`` (directories as None) with its contents.

    A held lock file is listed but not read: Windows refuses to read a locked byte.
    """
    from olivia.core.datalock import LOCK_FILENAME

    if not home.exists():
        return {}
    return {
        p.relative_to(home).as_posix(): (
            p.read_bytes() if p.is_file() and p.name != LOCK_FILENAME else None
        )
        for p in sorted(home.rglob("*"))
    }


@pytest.fixture
def doctor(run_cli, data_home, keychain, machine):
    """Run ``olivia doctor`` and check it changed nothing anywhere."""

    def run(now: datetime = NOW):
        before = _tree(data_home)
        existed = data_home.exists()
        reads, writes, items = len(keychain.reads), list(keychain.writes), dict(keychain.items)
        calls = len(machine.calls)
        result = run_cli(["doctor"], now=now)
        assert _tree(data_home) == before
        assert data_home.exists() is existed
        assert len(keychain.reads) == reads, "a keychain item was read"
        assert keychain.writes == writes and keychain.items == items
        assert machine.calls[calls:] == []  # macOS: nothing is run, only files looked at
        assert result.lines[-1] == cli.DOCTOR_FOOTER
        return result

    return run


def _line(run, start: str) -> str:
    found = [line for line in run.lines if line[2:].startswith(start)]
    assert len(found) == 1, (start, run.out)
    return found[0]


def _mark(run, start: str) -> str:
    return _line(run, start)[0]


def _marks(run) -> set[str]:
    return {line[0] for line in run.lines if line[:1] in (OK, WARN, FAIL)}


def _store(name: str) -> str:
    return cli.DOCTOR_STORE_NAMES[name] + "："


# -- a fresh computer -------------------------------------------------------------------------


def test_a_fresh_computer_passes_and_creates_nothing(doctor, data_home):
    run = doctor()
    assert run.code == 0, run.out
    assert run.lines[0] == cli.DOCTOR_HEADING
    assert FAIL not in _marks(run)
    assert _line(run, "OLIVIA ").startswith(f"{OK} OLIVIA {cli.package_version()} · Python ")
    assert _mark(run, "数据目录：还没有") == OK
    assert not [line for line in run.lines if "权限" in line]  # nothing to check yet
    assert _line(run, "系统钥匙串") == f"{OK} {cli.DOCTOR_KEYCHAIN_READY}"
    assert _line(run, "第一次设置") == f"{WARN} {cli.DOCTOR_NOT_ONBOARDED}"
    for name in cli.DOCTOR_STORE_NAMES:
        assert _line(run, _store(name)).endswith("：没有")
    assert _line(run, "本机模型") == f"{OK} {cli.DOCTOR_MODEL_OK}"
    assert _mark(run, "随程序附带的热线资料") == OK
    assert _line(run, "热线更新包") == f"{OK} {cli.DOCTOR_UPDATE_NONE}"
    assert _line(run, "系统提醒") == f"{OK} {cli.DOCTOR_REMINDERS_OFF}"
    assert not data_home.exists()


def test_doctor_needs_no_first_visit_and_prints_its_footer_last(doctor):
    run = doctor()
    assert run.lines[-1] == "以上内容不含你的个人信息，可以放心转给我们。"


# -- after a real first visit -----------------------------------------------------------------


def test_after_a_chat_every_store_opens_and_nothing_is_touched(run_cli, doctor, data_home):
    assert run_cli(["chat", "--rules"], CHAT).code == 0
    assert (data_home / STATE_FILENAME).is_file()
    run = doctor()
    assert run.code == 0, run.out
    assert _line(run, "第一次设置") == f"{OK} {cli.DOCTOR_ONBOARDED}"
    for name in ("profile", "ledger", "state", "care"):
        assert _line(run, _store(name)) == f"{OK} {cli.DOCTOR_STORE_NAMES[name]}：能打开"
    assert _line(run, _store("safety_plan")).endswith("：没有")
    assert f"  {cli.DOCTOR_STORES_NOTE}" in run.lines
    permissions = (
        cli.DOCTOR_PERMISSIONS_WINDOWS if sys.platform == "win32" else cli.DOCTOR_PERMISSIONS_OK
    )
    assert _line(run, "数据目录的权限") == f"{OK} {permissions}"
    assert cli._shown_location(data_home) in _line(run, "数据目录：")


def test_names_topics_and_health_never_appear(doctor, data_home):
    flags = tuple(load_taxonomy().red_flags())[:1]
    save_profile(
        data_home,
        user_name=TYPED[0],
        agent_name=TYPED[1],
        taboo_topics=TYPED[2:],
        clinical_history=flags,
    )
    run = doctor()
    assert run.code == 0, run.out
    assert _line(run, _store("profile")).endswith("：能打开")
    for text in (*TYPED, *flags, "小林"):
        assert text not in run.out


def test_the_home_directory_is_shown_as_a_tilde(doctor, data_home, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: data_home.parent))
    run = doctor()
    assert _line(run, "数据目录：").endswith(f"（~/{data_home.name}，第一次设置时会建立）")
    assert str(data_home.parent) not in run.out


# -- the keychain -----------------------------------------------------------------------------


def test_a_locked_keychain_fails_and_so_do_the_stores_that_need_it(run_cli, doctor, keychain):
    assert run_cli(["chat", "--rules"], CHAT).code == 0
    keychain.broken = KeychainUnavailableError("locked")
    run = doctor()
    assert run.code == 1
    assert _line(run, "系统钥匙串") == f"{FAIL} {cli.DOCTOR_KEYCHAIN_UNAVAILABLE}"
    assert _mark(run, _store("ledger")) == FAIL
    assert _line(run, _store("state")).endswith("现在打不开，要等系统钥匙串能用")
    assert _mark(run, _store("profile")) == OK  # plain: no keychain needed


def test_no_keychain_on_a_fresh_computer_is_only_a_warning(doctor, keychain):
    keychain.broken = NoKeychainError("none")
    run = doctor()
    assert run.code == 0
    assert _line(run, "系统钥匙串") == f"{WARN} {cli.DOCTOR_KEYCHAIN_NONE}"


def test_a_keychain_that_cannot_be_probed_is_reported_unchecked(doctor, monkeypatch):
    from olivia.core.crypto import keychain as keychain_module

    class Bare:
        def get(self, name: str) -> str | None:
            raise AssertionError("never read")

        def set(self, name: str, value: str) -> None:
            raise AssertionError("never written")

        def delete(self, name: str) -> None:
            raise AssertionError("never deleted")

    monkeypatch.setattr(keychain_module, "default_backend", Bare)
    run = doctor()
    assert run.code == 0
    assert _line(run, "系统钥匙串") == f"{WARN} {cli.DOCTOR_KEYCHAIN_UNCHECKED}"


# -- damaged storage --------------------------------------------------------------------------


def test_a_damaged_store_fails(run_cli, doctor, data_home):
    assert run_cli(["chat", "--rules"], CHAT).code == 0
    (data_home / STATE_FILENAME).write_bytes(b"not sealed at all")
    run = doctor()
    assert run.code == 1
    assert _line(run, _store("state")).startswith(f"{FAIL} ")
    assert _line(run, _store("ledger")).startswith(f"{OK} ")


def test_a_missing_data_key_fails(run_cli, doctor, data_home):
    assert run_cli(["chat", "--rules"], CHAT).code == 0
    (data_home / "keys" / "ledger.key").unlink()
    run = doctor()
    assert run.code == 1
    assert (
        _line(run, _store("ledger"))
        == f"{FAIL} {cli.DOCTOR_STORE_NAMES['ledger']}：打不开，文件或钥匙不完整"
    )


def test_one_damaged_ledger_entry_is_a_partial_failure(run_cli, doctor, data_home):
    assert run_cli(["chat", "--rules"], CHAT).code == 0
    (data_home / "ledger" / f"{'0' * 24}.olv").write_bytes(b"junk")
    run = doctor()
    assert run.code == 1
    assert _line(run, _store("ledger")).endswith("有一部分打不开")


def test_a_damaged_profile_fails_and_first_visit_is_unknown(doctor, data_home):
    save_profile(data_home)
    (data_home / PROFILE_FILENAME).write_text("{ broken", encoding="utf-8")
    shutil.rmtree(data_home / ".snapshots", ignore_errors=True)
    run = doctor()
    assert run.code == 1
    assert _mark(run, _store("profile")) == FAIL
    assert _line(run, "第一次设置") == f"{WARN} {cli.DOCTOR_ONBOARDED_UNKNOWN}"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions only")
def test_loose_permissions_are_a_warning(doctor, data_home):
    save_profile(data_home)
    data_home.chmod(0o700)  # as the CLI creates it (the helper writes the file directly)
    (data_home / PROFILE_FILENAME).chmod(0o644)
    run = doctor()
    assert run.code == 0
    assert _line(run, "数据目录的权限") == f"{WARN} " + cli.DOCTOR_PERMISSIONS_OFF.format(count=1)


def test_a_signed_update_folder_does_not_count_against_permissions(doctor, data_home):
    save_profile(data_home)
    data_home.chmod(0o700)
    folder = data_home / bundle.OVERRIDE_DIR_NAME
    folder.mkdir(mode=0o755)
    (folder / bundle.DATA_NAME).write_bytes(b"x")
    (folder / bundle.DATA_NAME).chmod(0o644)
    run = doctor()
    assert _mark(run, "数据目录的权限") == OK


# -- the packaged model -----------------------------------------------------------------------


def test_a_model_that_fails_verification_fails_and_says_chat_uses_rules(
    doctor, tmp_path, monkeypatch
):
    copy = tmp_path / "model"
    shutil.copytree(Path(str(resources.files("olivia").joinpath("data/models/perception"))), copy)
    weights = copy / student.WEIGHTS
    raw = bytearray(weights.read_bytes())
    raw[100] ^= 1
    weights.write_bytes(bytes(raw))
    original = student.try_load_student
    monkeypatch.setattr(student, "try_load_student", lambda directory=None: original(copy))
    run = doctor()
    assert run.code == 1
    line = _line(run, "本机模型")
    assert line == f"{FAIL} " + cli.DOCTOR_MODEL_FAILED.format(reason="hash_mismatch:student.npz")
    assert "只用规则" in line


# -- hotline data -----------------------------------------------------------------------------


def test_hotline_data_older_than_90_days_is_a_warning(doctor):
    builtin = bundle.compiled_on_of(bundle._read_builtin()[0])
    later = datetime.combine(builtin + timedelta(days=91), NOW.timetz())
    run = doctor(now=later)
    assert run.code == 0
    line = _line(run, "随程序附带的热线资料")
    assert line.startswith(f"{WARN} ") and "距今 91 天" in line and "90 天" in line
    fresh = doctor(now=datetime.combine(builtin + timedelta(days=90), NOW.timetz()))
    assert _mark(fresh, "随程序附带的热线资料") == OK


def test_a_bad_builtin_signature_fails(doctor, monkeypatch):
    data, sig = bundle._read_builtin()
    monkeypatch.setattr(bundle, "_read_builtin", lambda: (data + b"\n# x", sig))
    run = doctor()
    assert run.code == 1
    assert _line(run, "随程序附带的热线资料") == f"{FAIL} {cli.DOCTOR_HOTLINES_BROKEN}"
    assert _line(run, "热线更新包") == f"{WARN} {cli.DOCTOR_UPDATE_UNCHECKED}"


def test_a_signed_update_in_use_is_reported(doctor, data_home, key):  # noqa: F811
    data = _yaml("2026-02-20")
    _update(data_home, data, _sign(key, data))
    run = doctor(now=datetime(2026, 3, 1, 12, tzinfo=NOW.tzinfo))
    assert run.code == 0
    line = _line(run, "热线更新包")
    assert line.startswith(f"{OK} 热线更新包：在用（整理于 2026-02-20，距今 9 天")


def test_an_update_that_is_not_used_is_a_warning(doctor, data_home, key):  # noqa: F811
    data = _yaml("2026-02-20")
    _update(data_home, data, b"bad signature\n")
    run = doctor(now=datetime(2026, 3, 1, 12, tzinfo=NOW.tzinfo))
    assert run.code == 0
    assert _line(run, "热线更新包") == f"{WARN} " + cli.DOCTOR_UPDATE_UNUSED.format(
        reason=cli.RESOURCES_UPDATE_REASONS[bundle.REASON_SIG_INVALID]
    )


# -- reminders --------------------------------------------------------------------------------


def test_an_installed_reminder_is_reported(doctor, machine):
    plist = jobs.plist_path(machine.host())
    plist.parent.mkdir(parents=True)
    plist.write_bytes(b"<plist/>")
    assert _line(doctor(), "系统提醒") == f"{OK} {cli.DOCTOR_REMINDERS_ON}"


def test_a_reminder_switched_on_but_missing_is_a_warning(doctor, data_home):
    save_profile(data_home, notifications=True)
    run = doctor()
    assert run.code == 0
    assert _line(run, "系统提醒") == f"{WARN} {cli.DOCTOR_REMINDERS_MISSING}"


def test_a_leftover_reminder_is_a_warning(doctor, data_home, machine):
    save_profile(data_home)
    plist = jobs.plist_path(machine.host())
    plist.parent.mkdir(parents=True)
    plist.write_bytes(b"<plist/>")
    assert _line(doctor(), "系统提醒") == f"{WARN} {cli.DOCTOR_REMINDERS_LEFTOVER}"


def test_doctor_is_in_the_sentence_list():
    for text in cli.DOCTOR_TEXTS:
        assert text in cli.USER_TEXTS


# -- the data-integrity markers (robustness fixes) ------------------------------------------


def test_another_olivia_running_is_shown_and_the_lock_is_left_alone(run_cli, doctor, data_home):
    from olivia.core.datalock import LOCK_FILENAME, DataDirLock

    assert run_cli(["chat", "--rules"], CHAT).code == 0
    assert all(cli.DOCTOR_BUSY not in line for line in doctor().lines)
    with DataDirLock(data_home):
        run = doctor()  # read-only and lock-free: it runs beside a chat
        assert _line(run, "另一个 OLIVIA 正在运行") == f"{WARN} {cli.DOCTOR_BUSY}"
        assert (data_home / LOCK_FILENAME).is_file()
        assert run.code == 0, run.out
    assert not (data_home / LOCK_FILENAME).exists()


def test_an_unfinished_forget_all_fails_and_names_the_way_out(run_cli, doctor, data_home):
    from olivia.core.memory.forget import FORGET_ALL_MARKER

    assert run_cli(["chat", "--rules"], CHAT).code == 0
    (data_home / FORGET_ALL_MARKER).write_bytes(b"")
    (data_home / FORGET_ALL_MARKER).chmod(0o600)
    run = doctor()  # not refused like the other commands: it is how to find out
    assert _line(run, "上一次「全部忘掉」") == f"{FAIL} {cli.DOCTOR_FORGET_UNFINISHED}"
    assert run.code == 1


def test_a_recovery_not_yet_told_is_a_warning_and_stays_untold(run_cli, doctor, data_home):
    from olivia.core.chang.profile import RECOVERED_FILENAME

    save_profile(data_home)
    save_profile(data_home, user_name="阿屿")
    main = data_home / PROFILE_FILENAME
    main.write_bytes(main.read_bytes()[:20])
    run_cli(["notify-check"])  # loads the profile, recovers it, tells no one
    assert (data_home / RECOVERED_FILENAME).is_file()
    run = doctor()
    assert _line(run, "设置文件坏过") == f"{WARN} {cli.DOCTOR_RECOVERED}"
    told = run_cli(["persona"])
    assert any(line.startswith("设置文件坏了") for line in told.lines)  # doctor did not take it
    assert all(cli.DOCTOR_RECOVERED not in line for line in doctor().lines)
