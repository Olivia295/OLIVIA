"""The exit-code convention of every ``olivia`` command (README "退出码").

0: the command did what was asked (showing something counts). 1: nothing could be done,
because first-time setup has not happened, the profile is an under-18 refusal record, or
the stored data cannot be read now. 2: the command line itself is wrong (argparse, or a
value such as an unknown region, timezone or persona).
"""

from __future__ import annotations

import io

import pytest
from cli_support import NOW, ONBOARD_CN, save_profile

from olivia import cli
from olivia.core.chang.profile import PROFILE_FILENAME, ProfileStore
from olivia.core.models import PersonaProfile

# Every user-facing command with arguments that need nothing typed afterwards.
NEEDS_SETUP = [
    ["region"],
    ["region", "HK"],
    ["region", "--clear"],
    ["health"],
    ["safety-plan"],
    ["journal"],
    ["stats"],
    ["persona"],
    ["persona", "2"],
    ["profile"],
    ["memory"],
    ["forget"],
    ["forget", "--kit"],
    ["forget", "--entry", "1"],
    ["settings"],
]
ALWAYS_WORK = [
    ["resources"],
    ["privacy"],
    ["doctor"],
    ["notify-check"],
    ["forget", "--all", "--yes"],
]


def _refusal_record(home):
    ProfileStore(home).save(
        PersonaProfile(
            age_confirmed_18_plus=False, created_at=NOW, updated_at=NOW, age_gate_refused_at=NOW
        )
    )


@pytest.mark.parametrize("argv", NEEDS_SETUP, ids=" ".join)
def test_not_onboarded_is_exit_1_for_every_command_that_needs_setup(run_cli, data_home, argv):
    run = run_cli(argv, [])
    assert run.code == 1, run.out
    assert run.out.strip()  # always says why
    assert not (data_home / PROFILE_FILENAME).exists()


@pytest.mark.parametrize("argv", NEEDS_SETUP, ids=" ".join)
def test_a_refusal_record_is_exit_1_too(run_cli, data_home, argv):
    _refusal_record(data_home)
    run = run_cli(argv, [])
    assert run.code == 1, run.out
    assert run.out.strip()


@pytest.mark.parametrize("argv", ALWAYS_WORK, ids=" ".join)
def test_commands_that_need_no_setup_succeed_without_it(run_cli, data_home, argv):
    assert run_cli(argv, []).code == 0


@pytest.mark.parametrize("answers", [[], ["2"], ["1", "2", "1"], ["1", "1", "小林"]])
def test_chat_that_ends_without_a_profile_is_exit_1(run_cli, data_home, answers):
    """Input ended, the disclaimer was declined, or the user is under 18."""
    run = run_cli(["chat", "--rules"], answers)
    assert run.code == 1 and run.sessions == []


def test_chat_with_a_refusal_record_is_exit_1(run_cli, data_home):
    _refusal_record(data_home)
    assert run_cli(["chat", "--rules"], ["你好"]).code == 1


@pytest.mark.parametrize(
    "argv",
    [
        ["region"],
        ["persona"],
        ["profile"],
        ["memory"],
        ["privacy"],
        ["resources"],
        ["journal"],
        ["stats"],
    ],
    ids=" ".join,
)
def test_showing_things_after_setup_is_exit_0(run_cli, data_home, argv):
    save_profile(data_home)
    assert run_cli(argv, [""]).code == 0


@pytest.mark.parametrize(
    "argv",
    [
        ["region", "JP"],
        ["region", "US", "--timezone", "Mars/Olympus"],
        ["region", "HK", "--clear"],
        ["persona", "开心果"],
    ],
    ids=" ".join,
)
def test_a_bad_value_on_the_command_line_is_exit_2(run_cli, data_home, argv):
    save_profile(data_home)
    before = (data_home / PROFILE_FILENAME).read_bytes()
    assert run_cli(argv).code == 2
    assert (data_home / PROFILE_FILENAME).read_bytes() == before


def test_argparse_errors_are_exit_2(run_cli):
    with pytest.raises(SystemExit) as exc:
        run_cli(["forget", "--kit", "--all"])
    assert exc.value.code == 2


class _CtrlC(io.StringIO):
    """Scripted input that ends in Ctrl-C instead of end of input."""

    def readline(self, size: int | None = -1) -> str:
        line = super().readline()
        if not line:
            raise KeyboardInterrupt
        return line


@pytest.mark.parametrize(
    ("argv", "lines", "onboarded", "code"),
    [
        (["chat", "--rules"], [], False, 1),  # onboarding: nothing was set up
        (["chat", "--rules"], ONBOARD_CN[:3], False, 1),
        (["chat", "--rules"], [], True, 0),  # the conversation ends, like /exit
        (["chat", "--rules"], ["今天上班好累"], True, 0),
        (["health"], [], True, 0),
        (["safety-plan"], [], True, 0),
        (["forget"], [], True, 0),
        (["settings"], [], True, 0),
        (["profile"], [], True, 0),
        (["profile"], ["1"], True, 0),
    ],
    ids=lambda v: " ".join(v) if isinstance(v, list) else str(v),
)
def test_ctrl_c_exits_like_end_of_input(run_cli, data_home, argv, lines, onboarded, code):
    """README 退出码: Ctrl-C gives the code end of input gives at the same point."""
    if onboarded:
        save_profile(data_home)
    script = "".join(f"{line}\n" for line in lines)
    interrupted = run_cli(argv, stdin=_CtrlC(script))
    assert interrupted.code == code, interrupted.out
    assert run_cli(argv, lines).code == code
    if argv == ["chat", "--rules"]:
        assert interrupted.lines[-1] == cli.GOODBYE
    if not onboarded:
        assert not (data_home / PROFILE_FILENAME).exists()


def test_ctrl_c_in_a_crisis_says_the_crisis_goodbye(run_cli, data_home):
    """S5: Ctrl-C inside the crisis flow ends like /exit there, numbers on screen."""
    save_profile(data_home)
    interrupted = run_cli(["chat", "--rules"], stdin=_CtrlC("我不想活了\n"))
    assert interrupted.code == 0 and interrupted.results[-1].in_crisis
    assert cli.GOODBYE not in interrupted.out
    goodbye = interrupted.out[interrupted.out.rindex("Olivia：") :]
    assert "12356" in goodbye
