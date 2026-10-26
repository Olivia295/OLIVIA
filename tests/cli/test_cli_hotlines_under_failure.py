"""No failure hides the hotlines: a locked or missing keychain, a profile that cannot be
opened, damaged packaged hotline data, a missing perception model or GBK input.

``olivia resources`` always shows numbers: the saved region's when its plaintext part can
be read without the keychain, the global (ZZ) resources otherwise. ``olivia chat`` that
cannot open the profile prints the same numbers before it says why and what to do next.
Packaged hotline data that fails verification is never shown; a fixed fallback written in
the code (``resources/fallback.py``) takes its place.
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
from pathlib import Path

import pytest
from cli_support import L3_SENTENCE, files_under, save_profile

from olivia import cli
from olivia.core import session as session_module
from olivia.core.chang.profile import PROFILE_FILENAME
from olivia.core.crypto.errors import KeychainUnavailableError, NoKeychainError
from olivia.core.models import UserRegion
from olivia.core.perception.student import RULES_ONLY, RiskChoice
from olivia.core.resources import bundle
from olivia.core.resources.fallback import fallback_text
from olivia.core.safety.crisis import SafetyScreen
from olivia.core.taxonomy import load_taxonomy

ROOT = Path(__file__).resolve().parents[2]
CRISIS = "我不想活了"


def _with_health(home: Path, **overrides: object) -> None:
    save_profile(home, clinical_history=(next(iter(load_taxonomy().red_flags())),), **overrides)


def _lock(keychain, how: str) -> None:
    if how == "locked":
        keychain.broken = KeychainUnavailableError("locked")
    elif how == "no keychain":
        keychain.broken = NoKeychainError("none")
    else:  # the keychain item was deleted: the keys are gone for good
        keychain.items.clear()


# -- S1: olivia resources ----------------------------------------------------------------


@pytest.mark.parametrize("how", ["locked", "no keychain", "deleted"])
def test_resources_reads_the_plaintext_region_when_health_data_is_locked(
    run_cli, data_home, keychain, how
):
    _with_health(data_home, region=UserRegion("HK", "Asia/Hong_Kong"))
    before = {p: p.read_bytes() for p in files_under(data_home)}
    _lock(keychain, how)
    run = run_cli(["resources"])
    assert run.code == 0
    assert run.lines[0] == "求助资源 · 中国香港（HK）"
    for number in ("999", "18111"):
        assert number in run.out
    assert "12356" not in run.out  # R8: still only the saved region's entries
    assert {p: p.read_bytes() for p in files_under(data_home)} == before


@pytest.mark.parametrize(
    ("how", "reason", "start_over"),
    [
        ("locked", cli.PROFILE_LOCKED_NOW, False),
        ("no keychain", cli.PROFILE_LOCKED_NOW, False),
        ("deleted", cli.PROFILE_KEYS_LOST, True),
    ],
)
def test_resources_with_a_sealed_profile_shows_the_global_resources(
    run_cli, data_home, keychain, how, reason, start_over
):
    save_profile(data_home, enable_at_rest_encryption=True)
    before = {p: p.read_bytes() for p in files_under(data_home)}
    _lock(keychain, how)
    run = run_cli(["resources"])
    assert run.code == 1  # README: saved data could not be read
    assert run.lines[0] == "求助资源 · 其他地区（ZZ）"
    assert "112" in run.out and "findahelpline.com" in run.out
    assert "12356" not in run.out  # nothing guessed from outside the sealed profile
    tail = run.out.split("资料来源：随程序附带\n", 1)[1]
    assert cli.RESOURCES_REGION_UNREADABLE in tail
    assert reason in tail
    assert (cli.PROFILE_START_OVER in tail) is start_over
    assert cli.RESOURCES_SET_REGION not in run.out
    assert {p: p.read_bytes() for p in files_under(data_home)} == before


def test_resources_with_an_unreadable_profile_and_snapshots(run_cli, data_home):
    data_home.mkdir(parents=True)
    (data_home / PROFILE_FILENAME).write_text("{not json", encoding="utf-8")
    run = run_cli(["resources"])
    assert run.code == 1
    assert run.lines[0] == "求助资源 · 其他地区（ZZ）"
    assert "112" in run.out
    tail = run.out.split("资料来源：随程序附带\n", 1)[1]
    assert cli.RESOURCES_REGION_UNREADABLE in tail
    assert cli.PROFILE_CORRUPT in tail and cli.PROFILE_START_OVER in tail
    assert (data_home / PROFILE_FILENAME).read_text(encoding="utf-8") == "{not json"


def test_damaged_profile_key_still_shows_the_plaintext_region(run_cli, data_home):
    _with_health(data_home)
    (data_home / "keys" / "profile.key").write_bytes(b"garbage")
    run = run_cli(["resources"])
    assert run.code == 0
    assert run.lines[0] == "求助资源 · 中国大陆（CN）"
    for number in ("110", "120", "12356"):
        assert number in run.out


# -- S1: olivia chat ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("how", "reason", "start_over"),
    [
        ("locked", cli.PROFILE_LOCKED_NOW, False),
        ("no keychain", cli.PROFILE_LOCKED_NOW, False),
        ("deleted", cli.PROFILE_KEYS_LOST, True),
    ],
)
def test_chat_that_cannot_open_the_profile_shows_the_hotlines_first(
    run_cli, data_home, keychain, how, reason, start_over
):
    _with_health(data_home)
    before = {p: p.read_bytes() for p in files_under(data_home)}
    _lock(keychain, how)
    run = run_cli(["chat", "--rules"], [CRISIS, "/exit"])
    assert run.code == 1 and run.sessions == []
    assert run.lines[0] == cli.CHAT_CANNOT_START
    assert "求助资源 · 中国大陆（CN）" in run.out
    for number in ("110", "120", "12356"):
        assert number in run.out
    numbers_at = run.out.index("12356")
    assert run.out.index(reason) > numbers_at  # numbers first, then why and what next
    assert (cli.PROFILE_START_OVER in run.out) is start_over
    assert cli.RESOURCES_REGION_UNREADABLE not in run.out
    assert {p: p.read_bytes() for p in files_under(data_home)} == before


def test_chat_with_a_sealed_locked_profile_shows_the_global_resources(run_cli, data_home, keychain):
    save_profile(data_home, enable_at_rest_encryption=True)
    keychain.broken = KeychainUnavailableError("locked")
    run = run_cli(["chat", "--rules"], [CRISIS, "/exit"])
    assert run.code == 1
    assert "求助资源 · 其他地区（ZZ）" in run.out
    assert "112" in run.out and "findahelpline.com" in run.out
    tail = run.out.split("资料来源：随程序附带\n", 1)[1]
    assert tail.index(cli.RESOURCES_REGION_UNREADABLE) < tail.index(cli.PROFILE_LOCKED_NOW)
    assert cli.PROFILE_START_OVER not in run.out


def test_chat_with_an_unreadable_profile_shows_the_global_resources(run_cli, data_home):
    data_home.mkdir(parents=True)
    (data_home / PROFILE_FILENAME).write_text("{not json", encoding="utf-8")
    run = run_cli(["chat", "--rules"], [CRISIS])
    assert run.code == 1
    assert "112" in run.out
    assert cli.PROFILE_CORRUPT in run.out and cli.PROFILE_START_OVER in run.out
    assert run.out.index("112") < run.out.index(cli.PROFILE_CORRUPT)


# -- S3: damaged packaged hotline data ---------------------------------------------------


def _damage_builtin(monkeypatch: pytest.MonkeyPatch, how: str) -> None:
    data = (ROOT / "olivia/data/resources/hotlines.yaml").read_bytes()
    signature = (ROOT / "olivia/data/resources/hotlines.yaml.sig").read_bytes()
    if how == "edited":
        monkeypatch.setattr(
            bundle, "_read_builtin", lambda: (data.replace(b'"12356"', b'"12357"'), signature)
        )
    else:

        def missing() -> tuple[bytes, bytes]:
            raise FileNotFoundError("hotlines.yaml.sig")

        monkeypatch.setattr(bundle, "_read_builtin", missing)


@pytest.mark.parametrize("how", ["edited", "signature missing"])
def test_resources_with_damaged_packaged_data_shows_the_fixed_fallback(
    run_cli, data_home, monkeypatch, how
):
    save_profile(data_home)
    _damage_builtin(monkeypatch, how)
    run = run_cli(["resources"])
    assert run.code == 1
    assert run.out == fallback_text() + "\n"
    assert "12357" not in run.out and "12356" not in run.out  # nothing unverified


@pytest.mark.parametrize("how", ["edited", "signature missing"])
def test_chat_with_damaged_packaged_data_shows_the_fallback_and_does_not_start(
    run_cli, data_home, monkeypatch, how
):
    save_profile(data_home)
    _damage_builtin(monkeypatch, how)
    run = run_cli(["chat", "--rules"], [CRISIS, "/exit"])
    assert run.code == 1 and run.sessions == []
    assert fallback_text() in run.out
    assert run.lines[-1] == cli.CHAT_DATA_DAMAGED
    assert "12357" not in run.out


def test_profile_failure_and_damaged_data_together_still_show_the_fallback(
    run_cli, data_home, keychain, monkeypatch
):
    _with_health(data_home)
    keychain.broken = KeychainUnavailableError("locked")
    _damage_builtin(monkeypatch, "edited")
    run = run_cli(["chat", "--rules"], [CRISIS])
    assert run.code == 1
    assert fallback_text() in run.out and cli.PROFILE_LOCKED_NOW in run.out


def test_a_failed_turn_with_damaged_data_shows_the_fallback(run_cli, data_home, monkeypatch):
    save_profile(data_home)
    original = SafetyScreen.assess

    def assess(self: SafetyScreen, text: str) -> object:
        if text == L3_SENTENCE:
            _damage_builtin(monkeypatch, "edited")  # damaged after the session started
            raise RuntimeError("screen failed")
        return original(self, text)

    monkeypatch.setattr(SafetyScreen, "assess", assess)
    run = run_cli(["chat", "--rules"], [L3_SENTENCE, "/exit"])
    assert run.code == 0
    assert fallback_text() in run.out
    assert "12357" not in run.out
    assert run.lines[-1] == cli.GOODBYE


# -- E5: the perception model fell back to the rules -------------------------------------


def test_chat_says_once_when_the_model_is_unavailable(run_cli, data_home, monkeypatch):
    save_profile(data_home)
    monkeypatch.setattr(
        session_module,
        "choose_risk_model",
        lambda model=None, *, student=False: RiskChoice(
            RULES_ONLY, "missing_file:MANIFEST.json" if student else None, None
        ),
    )
    run = run_cli(["chat"], ["今天上班好累", "还是很累", "/exit"])
    assert run.code == 0
    assert run.out.count(cli.MODEL_UNAVAILABLE) == 1
    assert run.out.index(cli.MODEL_UNAVAILABLE) < run.out.index(cli.CHAT_HINT)
    assert "MANIFEST" not in run.out  # the reason is for --inspect only
    rules = run_cli(["chat", "--rules"], ["今天上班好累", "/exit"])
    assert cli.MODEL_UNAVAILABLE not in rules.out


def test_chat_says_nothing_when_the_model_loads(run_cli, data_home):
    save_profile(data_home)
    run = run_cli(["chat"], ["今天上班好累", "/exit"])
    assert cli.MODEL_UNAVAILABLE not in run.out


# -- GBK / GB18030 input -----------------------------------------------------------------


@pytest.mark.parametrize("encoding", ["gbk", "gb18030"])
def test_clean_input_reads_a_gbk_line(encoding):
    text = CRISIS.encode(encoding).decode("utf-8", "surrogateescape")
    assert cli.clean_input(text) == CRISIS


def test_clean_input_keeps_utf8_with_a_half_deleted_character():
    # Mostly valid UTF-8 with a broken character: the broken bytes go, the rest stays.
    raw = "你好吗".encode()
    text = (raw[:3] + raw[3:5] + raw[6:]).decode("utf-8", "surrogateescape")
    assert cli.clean_input(text) == "你吗"


def test_clean_input_drops_bytes_that_are_neither_utf8_nor_gb18030():
    assert cli.clean_input(b"\xff\xfe".decode("utf-8", "surrogateescape")) == ""


def test_a_gbk_crisis_sentence_on_the_pipe_shows_the_crisis_card(run_cli, data_home):
    save_profile(data_home)
    raw = b"\n" + CRISIS.encode("gbk") + b"\n/exit\n"
    stdin = io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8", errors="surrogateescape")
    run = run_cli(["chat", "--rules"], stdin=stdin)
    assert run.texts == [CRISIS]
    assert "12356" in run.results[0].reply


def test_a_gbk_crisis_sentence_on_real_stdin_shows_the_crisis_card(tmp_path):
    home = tmp_path / "home"
    save_profile(home)
    done = subprocess.run(
        [sys.executable, "-m", "olivia.cli", "chat", "--rules"],
        cwd=ROOT,
        input=b"\n" + CRISIS.encode("gbk") + b"\n/exit\n",
        capture_output=True,
        env={
            **os.environ,
            "OLIVIA_HOME": str(home),
            "PYTHON_KEYRING_BACKEND": "keyring.backends.fail.Keyring",
        },
        check=False,
        timeout=120,
    )
    out = done.stdout.decode("utf-8")
    assert b"Traceback" not in done.stderr, done.stderr.decode("utf-8", "replace")
    assert done.returncode == 0
    assert "12356" in out
