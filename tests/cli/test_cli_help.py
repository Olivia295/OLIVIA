"""``olivia --help`` and argparse errors in Chinese; the README commands table."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from olivia import cli

ROOT = Path(__file__).resolve().parents[2]
ENGLISH = (
    "usage:",
    "positional arguments",
    "options:",
    "optional arguments",
    "show this help message",
    "show program's version",
    "error:",
    "the following arguments are required",
    "invalid choice",
    "not allowed with argument",
    "ignored explicit argument",
)
COMMANDS = sorted(
    name
    for name in cli.build_parser()._subparsers._group_actions[0].choices  # type: ignore[union-attr]
    if name not in cli.HIDDEN_COMMANDS
)


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    """(exit code, injected stdout, injected stderr); nothing reaches the real streams."""
    out, err = io.StringIO(), io.StringIO()
    with pytest.raises(SystemExit) as exc:
        cli.main(argv, stdin=io.StringIO(), stdout=out, stderr=err)
    real = capsys.readouterr()
    assert (real.out, real.err) == ("", "")
    assert isinstance(exc.value.code, int)
    return exc.value.code, out.getvalue(), err.getvalue()


def _help(argv: list[str], capsys: pytest.CaptureFixture[str]) -> str:
    code, out, err = _run(argv, capsys)
    assert code == 0 and err == ""
    return out


@pytest.mark.parametrize("argv", [["--help"], ["-h"], *([c, "-h"] for c in COMMANDS)], ids=str)
def test_help_is_in_chinese(argv, capsys):
    out = _help(argv, capsys)
    assert out.startswith(cli.HELP_USAGE)
    assert f"{cli.HELP_OPTIONS}：" in out and cli.HELP_HELP in out
    lowered = out.casefold()
    assert not [word for word in ENGLISH if word in lowered], out


@pytest.mark.parametrize("argv", [["--help"], ["region", "-h"], ["persona", "-h"]], ids=str)
def test_help_headings_end_with_a_full_width_colon(argv, capsys):
    out = _help(argv, capsys)
    headings = [
        line.strip() for line in out.splitlines() if line.strip().rstrip(":：") in cli.HELP_HEADINGS
    ]
    assert headings and all(h.endswith("：") for h in headings), headings
    assert not [line for line in out.splitlines() if line.rstrip().endswith(":")], out


def test_main_help_lists_the_commands_but_not_the_hidden_one(capsys):
    out = _help(["--help"], capsys)
    assert f"{cli.HELP_COMMANDS}：" in out
    for command in COMMANDS:
        assert f"    {command}" in out
    for hidden in cli.HIDDEN_COMMANDS:
        assert hidden not in out


def test_help_and_version_go_to_the_injected_stdout(capsys):
    assert "chat" in _help(["--help"], capsys)
    assert _help(["--version"], capsys) == f"olivia {cli.package_version()}\n"


def test_an_unknown_command_does_not_offer_the_hidden_one(capsys):
    code, out, err = _run(["bogus"], capsys)
    assert code == 2 and out == ""
    assert "可以选：" in err and "chat、resources" in err
    for hidden in cli.HIDDEN_COMMANDS:
        assert hidden not in err
    for command in COMMANDS:
        assert command in err


def test_the_hidden_command_still_runs(run_cli):
    for hidden in cli.HIDDEN_COMMANDS:
        assert run_cli([hidden]).code == 0


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        ([], "还缺少：<命令>"),
        (["bogus"], "不能是「bogus」"),
        (["forget", "--kit", "--all"], "--all 不能和 --kit 一起用"),
        (["forget", "--entry", "x"], "--entry 要跟一个整数，「x」不是"),
        (["privacy", "--now"], "没有认出这些内容：--now"),
        (["region", "--timezone"], "--timezone 后面要跟一个值"),
        (["forget", "--yes=1"], "--yes 后面不用跟值，「1」是多出来的"),
    ],
)
def test_argparse_errors_are_in_chinese(argv, expected, capsys):
    code, out, err = _run(argv, capsys)
    assert code == 2 and out == ""
    assert err.startswith(cli.HELP_USAGE)
    assert expected in err and "命令有误" in err
    assert not [word for word in ENGLISH if word in err.casefold()], err


def test_an_unknown_error_message_passes_through():
    assert cli._localise_error("something new") == "something new"


def test_readme_commands_table_lists_every_command_and_the_exit_codes():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for command in COMMANDS:
        assert f"`olivia {command}" in readme, command
    assert "退出码" in readme
    for code in ("`0`", "`1`", "`2`"):
        assert code in readme
    assert "olivia chat --rules" in readme
