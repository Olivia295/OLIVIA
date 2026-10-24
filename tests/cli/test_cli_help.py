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
)
COMMANDS = sorted(
    name
    for name in cli.build_parser()._subparsers._group_actions[0].choices  # type: ignore[union-attr]
    if name != "notify-check"
)


def _help(argv: list[str], capsys: pytest.CaptureFixture[str]) -> str:
    with pytest.raises(SystemExit) as exc:
        cli.main(argv, stdin=io.StringIO(), stdout=io.StringIO())
    assert exc.value.code == 0
    return capsys.readouterr().out


@pytest.mark.parametrize("argv", [["--help"], ["-h"], *([c, "-h"] for c in COMMANDS)], ids=str)
def test_help_is_in_chinese(argv, capsys):
    out = _help(argv, capsys)
    assert out.startswith(cli.HELP_USAGE)
    assert f"{cli.HELP_OPTIONS}:" in out and cli.HELP_HELP in out
    lowered = out.casefold()
    assert not [word for word in ENGLISH if word in lowered], out


def test_main_help_lists_the_commands_but_not_the_hidden_one(capsys):
    out = _help(["--help"], capsys)
    assert f"{cli.HELP_COMMANDS}:" in out
    for command in COMMANDS:
        assert f"    {command}" in out
    assert "notify-check" not in out


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        ([], "还缺少：<命令>"),
        (["bogus"], "不能是「bogus」"),
        (["forget", "--kit", "--all"], "--all 不能和 --kit 一起用"),
        (["forget", "--entry", "x"], "--entry 要跟一个整数，「x」不是"),
        (["privacy", "--now"], "没有认出这些内容：--now"),
        (["region", "--timezone"], "--timezone 后面要跟一个值"),
    ],
)
def test_argparse_errors_are_in_chinese(argv, expected, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(argv, stdin=io.StringIO(), stdout=io.StringIO())
    assert exc.value.code == 2
    err = capsys.readouterr().err
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
    assert "--model" in readme
