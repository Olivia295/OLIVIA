"""``olivia chat``: the read-reply loop, exits, the inspect panel, persistence, offline."""

from __future__ import annotations

import io
import json
import os
import socket
import subprocess
import sys
from importlib import metadata
from pathlib import Path

import pytest
from cli_support import (
    L3_SENTENCE,
    NOW,
    ONBOARD_CN,
    PANEL_PREFIXES,
    files_under,
    save_profile,
)

import olivia
from olivia import cli
from olivia.core.chang.care import CARE_FILENAME
from olivia.core.chang.profile import PROFILE_FILENAME, ProfileLockedError, ProfileStore
from olivia.core.crypto.errors import KeychainUnavailableError, NoKeychainError
from olivia.core.language.data import ContentKind, load_language_data
from olivia.core.language.filters import apply_willow
from olivia.core.language.gate import OutputGate
from olivia.core.models import CrisisLevel, HelpStage, PersonaSpectrum, UserRegion
from olivia.core.perception import student as student_module
from olivia.core.perception.student import StudentLoad
from olivia.core.session import ReplyKind
from olivia.core.taxonomy import load_taxonomy

ROOT = Path(__file__).resolve().parents[2]
SECRET = "蓝色风筝和外婆的院子"
SECRET_FRAGMENTS = ("蓝色风筝", "外婆", "院子")


# -- end to end ------------------------------------------------------------------------------


def test_first_visit_talk_crisis_card_exit(run_cli, data_home):
    run = run_cli(["chat", "--rules"], [*ONBOARD_CN, "今天上班好累", L3_SENTENCE, "/exit"])
    assert run.code == 0
    assert run.texts == ["今天上班好累", L3_SENTENCE]  # /exit never reaches the session
    talk, crisis = run.results
    assert talk.reply_kind is ReplyKind.NORMAL and talk.stage is HelpStage.S_EXPLORE
    assert crisis.reply_kind is ReplyKind.CRISIS and crisis.stage is HelpStage.S_CRISIS
    assert crisis.crisis_level is CrisisLevel.L3
    assert crisis.resource_card is not None and crisis.resource_card.region_used == "CN"
    # The card is printed exactly as the session rendered it: same numbers, same order.
    assert f"Olivia：{crisis.reply}" in run.out
    assert run.out.index("110") < run.out.index("120") < run.out.index("12356")
    assert run.lines[-1] == cli.GOODBYE
    assert run.out.count(cli.GOODBYE) == 1
    # The crisis leaves the encrypted care marker for the next visit (step A3).
    top_level = [p.name for p in files_under(data_home) if p.parent == data_home]
    assert top_level == [CARE_FILENAME, PROFILE_FILENAME]


def test_returning_user_skips_onboarding(run_cli, data_home):
    save_profile(data_home)
    run = run_cli(["chat", "--rules"], ["今天上班好累"])
    assert run.code == 0
    assert "欢迎来到这里" not in run.out
    assert [r.reply_kind for r in run.results] == [ReplyKind.NORMAL]
    assert run.lines[-1] == cli.GOODBYE


def test_end_of_input_exits_cleanly(run_cli, data_home):
    save_profile(data_home)
    run = run_cli(["chat", "--rules"], [])
    assert run.code == 0 and run.results == []
    assert run.lines[-1] == cli.GOODBYE


def test_ctrl_c_exits_cleanly(run_cli, data_home):
    save_profile(data_home)

    class Interrupting(io.StringIO):
        def readline(self, size: int | None = -1) -> str:
            raise KeyboardInterrupt

    run = run_cli(["chat", "--rules"], stdin=Interrupting())
    assert run.code == 0
    assert run.lines[-1] == cli.GOODBYE


def test_blank_lines_are_skipped_and_commands_reach_the_session(run_cli, data_home):
    save_profile(data_home)
    run = run_cli(
        ["chat", "--rules"], ["", "   ", "给我一个方法", "/done", "/not-now", "/unhelpful", "/exit"]
    )
    assert run.texts == ["给我一个方法", "/done", "/not-now", "/unhelpful"]


def test_end_of_input_during_onboarding_saves_nothing(run_cli, data_home):
    run = run_cli(["chat", "--rules"], ONBOARD_CN[:5])
    assert run.code == 1 and run.lines[-1] == cli.GOODBYE  # nothing was set up
    assert not (data_home / PROFILE_FILENAME).exists()
    assert run.sessions == []


def test_corrupt_profile_is_reported_and_left_alone(run_cli, data_home):
    data_home.mkdir(parents=True)
    (data_home / PROFILE_FILENAME).write_text("{not json", encoding="utf-8")
    run = run_cli(["chat", "--rules"], ["你好"])
    assert run.code == 1
    assert cli.PROFILE_CORRUPT in run.out
    assert (data_home / PROFILE_FILENAME).read_text(encoding="utf-8") == "{not json"
    for argv in (["resources"], ["region"], ["region", "HK"]):
        again = run_cli(argv)
        assert again.code == 1 and cli.PROFILE_CORRUPT in again.out


# -- inspect panel ---------------------------------------------------------------------------


def test_inspect_panel_never_shows_user_text_or_city(run_cli, data_home):
    save_profile(
        data_home,
        region=UserRegion(
            "CN",
            "Asia/Shanghai",
            province_code="330000",
            city_code="330100",
            city_display_name="杭州",
        ),
    )
    run = run_cli(
        ["chat", "--rules", "--inspect"],
        [f"我想起{SECRET}，心里很难受", f"给我一个方法吧，{SECRET}", L3_SENTENCE, "/exit"],
    )
    assert len(run.results) == 3
    panel = "\n".join(run.panel)
    assert panel.count("┌ inspect") == 3
    # The reply may mirror the user's words; the panel must not.
    assert any(f in result.reply for result in run.results for f in SECRET_FRAGMENTS)
    for forbidden in (*SECRET_FRAGMENTS, "难受", "遗书", "杭州", "330000", "330100"):
        assert forbidden not in panel, forbidden
    for forbidden in ("杭州", "330000", "330100"):
        assert forbidden not in run.out
    # Mirrored text and replies stay out of the panel too.
    for result in run.results:
        for paragraph in result.reply.split("\n"):
            if len(paragraph) > 6:
                assert paragraph not in panel


def test_inspect_panel_carries_the_ruling_27_fields(run_cli, data_home):
    save_profile(data_home)
    run = run_cli(["chat", "--inspect"], ["最近压力很大，给我一个方法", L3_SENTENCE])
    card_turn, crisis_turn = run.results
    first, second = run.out.split("┌ inspect")[1:]
    data = card_turn.inspect
    assert f"风险 {data['level']}" in first
    # P6-6a: the student raises this request to L2 today (a false alarm), so the stage is
    # read from the result instead of being S_empower.
    assert f"→ {card_turn.stage.value}" in first
    assert f"唤醒 {data['arousal']:.2f}" in first
    assert f"电量 {data['battery']:.2f}" in first
    assert f"可用动作 {cli._fmt(data['candidates'])}" in first
    assert f"选中 {cli._fmt(data['chosen'])}" in first
    assert f"风险模型 {data['risk_model']}" in first
    assert str(data["risk_model"]).startswith("student:")
    assert f"模型判断 {data['model_level']} · 模型分数 {data['model_score']:.2f}" in first
    assert "风险 L3" in second and "线索 S1_NOTE_WRITTEN" in second
    assert "资源卡 CN L3" in second
    # Stage 1 answered L3 on its own, so the model did not run on that turn.
    assert "模型判断 - · 模型分数 -" in second
    assert "热线数据 builtin（no override）" in second
    assert crisis_turn.inspect["hotline_reason"] == "no override"


@pytest.mark.parametrize("mode_flags", [["--rules"], []], ids=["rules", "model"])
def test_inspect_panel_shows_the_perception_fields(run_cli, data_home, mode_flags):
    save_profile(data_home)
    run = run_cli(["chat", "--inspect", *mode_flags], ["今天上班好累"])
    (result,) = run.results
    data = result.inspect
    assert (
        f"│ 效价 {data['valence']:.2f} · 情绪 {data['emotion']} · 意图 {data['intent']}"
        f" · 姿态 {data['stance']} · 准备度 {data['readiness']:.2f}"
    ) in run.panel
    if mode_flags:  # rules mode: the stub's placeholders
        assert (data["stance"], data["readiness"]) == ("CONGRUENT", 0.5)


@pytest.mark.parametrize("mode_flags", [["--rules"], []], ids=["rules", "model"])
def test_inspect_panel_shows_the_introspection_ids(run_cli, data_home, mode_flags):
    # Decision D4, step C2: ids only, never the matched words.
    save_profile(data_home)
    run = run_cli(["chat", "--inspect", *mode_flags], ["都是我的错，我一无是处"])
    (result,) = run.results
    data = result.inspect
    assert data["distortions"] == ["PERSONALIZATION"]
    assert data["schemas"] == ["DEFECTIVENESS"]
    assert data["yearning"] == "ACCEPTANCE"
    assert data["schema_mirror"] is None
    line = "│ 认知扭曲 PERSONALIZATION · 图式 DEFECTIVENESS · 渴望 ACCEPTANCE"
    assert line in run.panel
    panel = "\n".join(run.panel)
    for forbidden in ("我的错", "一无是处", "图式镜像"):
        assert forbidden not in panel


# -- F7: model mode by default (owner decision 2026-10-24), --rules opts out ------------------


@pytest.mark.parametrize("flags", [[], ["--model"]], ids=["default", "old --model"])
def test_model_mode_by_default_and_says_so(run_cli, data_home, flags):
    save_profile(data_home)
    run = run_cli(["chat", "--inspect", *flags], ["今天上班好累"])
    (result,) = run.results
    label = result.inspect["risk_model"]
    assert isinstance(label, str) and label.startswith("student:")
    assert result.inspect["risk_model_reason"] is None
    assert f"风险模型 {label} · 模型判断" in run.out


def test_rules_flag_screens_with_the_rules_alone_and_says_so(run_cli, data_home):
    save_profile(data_home)
    run = run_cli(["chat", "--rules", "--inspect"], ["最近压力很大，给我一个方法"])
    (result,) = run.results
    assert result.inspect["risk_model"] == "rules-only"
    assert result.inspect["risk_model_reason"] is None
    assert result.inspect["model_level"] is None and result.inspect["model_score"] is None
    assert "风险模型 rules-only · 模型判断 - · 模型分数 -" in run.out
    assert result.stage is HelpStage.S_EMPOWER and result.reply_kind is ReplyKind.CARD


@pytest.mark.parametrize("argv", [["--model", "--rules"], ["--rules", "--model"]])
def test_model_and_rules_together_are_a_command_line_error(data_home, argv):
    save_profile(data_home)
    err = io.StringIO()
    with pytest.raises(SystemExit) as exc:
        cli.main(["chat", *argv], stdin=io.StringIO(""), stdout=io.StringIO(), stderr=err)
    assert exc.value.code == 2
    assert "不能和" in err.getvalue() and "命令有误" in err.getvalue()


def test_unavailable_student_falls_back_to_the_rules_and_says_why(
    run_cli, data_home, monkeypatch: pytest.MonkeyPatch
):
    # A missing or unverifiable packaged student: chat still runs, on the rules alone.
    monkeypatch.setattr(
        student_module, "default_student", lambda: StudentLoad(None, "missing student.npz")
    )
    save_profile(data_home)
    run = run_cli(["chat", "--inspect"], ["最近压力很大，给我一个方法", L3_SENTENCE, "/exit"])
    assert run.code == 0
    card, crisis = run.results
    assert card.inspect["risk_model"] == "rules-only"
    assert card.inspect["risk_model_reason"] == "missing student.npz"
    assert "风险模型 rules-only（missing student.npz） · 模型判断 - · 模型分数 -" in run.out
    assert card.stage is HelpStage.S_EMPOWER and card.reply_kind is ReplyKind.CARD
    # The rule screen still answers a crisis on its own.
    assert crisis.reply_kind is ReplyKind.CRISIS and crisis.crisis_level is CrisisLevel.L3
    assert "12356" in crisis.reply
    # Ordinary users see no notice about the model: only the panel says it.
    assert "missing student.npz" not in "\n".join(
        line for line in run.lines if not line.startswith(PANEL_PREFIXES)
    )


def test_no_panel_without_inspect(run_cli, data_home):
    save_profile(data_home)
    run = run_cli(["chat", "--rules"], ["今天上班好累"])
    assert run.panel == []


def test_locked_keychain_is_reported_and_nothing_changes(run_cli, data_home, keychain):
    save_profile(data_home, clinical_history=(next(iter(load_taxonomy().red_flags())),))
    before = {p: p.read_bytes() for p in files_under(data_home)}
    keychain.broken = KeychainUnavailableError("locked")
    for argv in (
        ["chat", "--rules"],
        ["region"],
        ["region", "HK"],
        ["region", "--clear"],
    ):
        run = run_cli(argv, ["你好"])
        assert run.code == 1 and cli.PROFILE_LOCKED_NOW in run.out
        assert cli.PROFILE_START_OVER not in run.out  # locked for now: nothing is lost
        assert run.sessions == []
    # The region is plaintext (only the health information is sealed), so the numbers
    # need no keychain (S1, tests/cli/test_cli_hotlines_under_failure.py).
    resources = run_cli(["resources"])
    assert resources.code == 0 and "12356" in resources.out
    assert {p: p.read_bytes() for p in files_under(data_home)} == before
    keychain.broken = None
    assert run_cli(["chat", "--rules"], ["今天上班好累"]).code == 0


@pytest.mark.parametrize("argv", [["region", "HK"], ["region", "--clear"]])
def test_region_change_that_cannot_be_encrypted_is_refused(run_cli, data_home, monkeypatch, argv):
    save_profile(data_home, enable_at_rest_encryption=True)
    before = (data_home / PROFILE_FILENAME).read_bytes()

    def locked(self: ProfileStore, profile: object) -> None:
        raise ProfileLockedError("the keychain is unavailable", lost=False)

    monkeypatch.setattr(ProfileStore, "save", locked)  # the keychain locks between load and save
    run = run_cli(argv)
    assert run.code == 1 and cli.PROFILE_LOCKED_NOW in run.out
    assert "已经保存" not in run.out and cli.REGION_CLEARED not in run.out
    assert (data_home / PROFILE_FILENAME).read_bytes() == before


def test_legacy_health_information_is_dropped_without_keychain(run_cli, data_home, keychain):
    code = next(iter(load_taxonomy().red_flags()))
    profile = save_profile(data_home)
    legacy = profile.to_dict() | {"clinical_history": [code]}
    (data_home / PROFILE_FILENAME).write_text(json.dumps(legacy, ensure_ascii=False), "utf-8")
    keychain.broken = NoKeychainError("none")
    run = run_cli(["chat", "--rules"], ["今天上班好累"])
    assert run.code == 0 and cli.HEALTH_NOT_SAVED in run.out
    for path in files_under(data_home):
        assert code.encode() not in path.read_bytes(), path
    again = run_cli(["chat", "--rules"], ["今天上班好累"])
    assert cli.HEALTH_NOT_SAVED not in again.out


# -- persistence -----------------------------------------------------------------------------


def test_only_the_profile_is_written_and_it_holds_no_conversation(run_cli, data_home):
    run = run_cli(
        ["chat", "--rules", "--inspect"],
        [*ONBOARD_CN, f"我想起{SECRET}", "[5%] 好累", L3_SENTENCE, "/done"],
    )
    assert run.code == 0
    files = files_under(data_home)
    # Besides the profile: the sealed care marker (A3), the encrypted ledger (B2) and the
    # wrapped keys, nothing else.
    assert {p.name for p in files if p.parent == data_home} == {PROFILE_FILENAME, CARE_FILENAME}
    assert {p.parent.name for p in files if p.parent != data_home} == {"ledger", "keys"}
    assert (data_home / "keys" / "care.key").exists()
    for path in files:
        raw = path.read_bytes()
        # Ciphertext is random bytes, so only fragments long enough never to occur by chance.
        for forbidden in (*SECRET_FRAGMENTS, "遗书", "S_crisis", '"L3"', "12356"):
            assert forbidden.encode() not in raw, (path, forbidden)
    assert "L3" not in (data_home / PROFILE_FILENAME).read_text(encoding="utf-8")
    saved = json.loads((data_home / PROFILE_FILENAME).read_text(encoding="utf-8"))
    assert set(saved) == {
        "schema_version",
        "age_confirmed_18_plus",
        "created_at",
        "updated_at",
        "user_name",
        "agent_name",
        "persona_spectrum",
        "directiveness_preference",
        "taboo_topics",
        "region",
        "enable_at_rest_encryption",
        "age_gate_refused_at",
        "notifications",
    }
    assert saved["notifications"] is False  # system reminders are off by default (B9, D5)
    profile = ProfileStore(data_home).load()
    assert profile is not None
    assert profile.region == UserRegion("CN", "Asia/Shanghai")
    assert profile.persona_spectrum is PersonaSpectrum.GENTLE_HOLDING
    assert profile.created_at == NOW


# -- offline ---------------------------------------------------------------------------------


def test_full_scripted_chat_makes_no_network_calls(run_cli, data_home, monkeypatch):
    calls: list[str] = []

    def no_network(*_args: object, **_kwargs: object) -> None:
        calls.append("network")
        raise OSError("network access is forbidden in this test")

    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(socket, "getaddrinfo", no_network)
    chat = run_cli(
        ["chat", "--rules", "--inspect"],
        [*ONBOARD_CN, "今天上班好累", "给我一个方法", "/done", L3_SENTENCE, "/exit"],
    )
    assert chat.code == 0
    assert ReplyKind.CRISIS in [r.reply_kind for r in chat.results]
    assert run_cli(["resources"]).code == 0
    assert run_cli(["region", "HK"]).code == 0
    assert run_cli(["region"]).code == 0
    assert calls == []


# -- copy and entry point --------------------------------------------------------------------


def test_cli_copy_passes_willow_and_the_output_gate():
    tax = load_taxonomy()
    data = load_language_data(tax)
    gate = OutputGate(tax, data)
    for text in cli.USER_TEXTS:
        assert apply_willow(text, ContentKind.NORMAL, data.willow) == text, text
        assert gate.reasons(text, kind=ContentKind.NORMAL, stage=HelpStage.S_EXPLORE) == (), text
        assert "！" not in text and "!" not in text


def test_help_runs_as_a_module():
    # A cp1252 locale (common on Windows) must not break the Chinese help text.
    done = subprocess.run(
        [sys.executable, "-m", "olivia.cli", "--help"],
        cwd=ROOT,
        capture_output=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "cp1252"},
        check=False,
    )
    assert done.returncode == 0, done.stderr
    for command in ("chat", "resources", "region"):
        assert command in done.stdout
    assert "开始聊天" in done.stdout


def test_pyproject_declares_the_console_script():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '[project.scripts]\nolivia = "olivia.cli:main"' in text


def test_version_prints_the_package_version(capsys):
    out = io.StringIO()
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"], stdout=out)
    assert exc.value.code == 0
    assert out.getvalue() == f"olivia {cli.package_version()}\n"
    assert capsys.readouterr().out == ""


def test_version_falls_back_to_the_source_tree(monkeypatch):
    def not_installed(name: str) -> str:
        raise metadata.PackageNotFoundError(name)

    monkeypatch.setattr(metadata, "version", not_installed)
    assert cli.package_version() == olivia.__version__


@pytest.mark.parametrize("argv", [[], ["unknown"]])
def test_bad_arguments_exit_with_usage(argv):
    with pytest.raises(SystemExit) as exc:
        cli.main(argv, stdout=io.StringIO())
    assert exc.value.code == 2
