"""``olivia chat`` when a turn fails outright (SDD §10.1): every number, never a traceback."""

from __future__ import annotations

import pytest
from cli_support import save_profile

from olivia import cli
from olivia.core.safety.crisis import SafetyScreen

BROKEN = "蓝色风筝坏掉了"


def test_failed_screen_still_shows_every_number(
    run_cli, data_home, monkeypatch: pytest.MonkeyPatch
) -> None:
    save_profile(data_home)
    original = SafetyScreen.assess

    def assess(self: SafetyScreen, text: str) -> object:
        if text == BROKEN:
            raise RuntimeError(text)
        return original(self, text)

    monkeypatch.setattr(SafetyScreen, "assess", assess)
    run = run_cli(["chat", "--rules"], [BROKEN, "今天上班好累", "/exit"])
    assert run.code == 0
    for number in ("110", "120", "12356"):
        assert number in run.out
    assert BROKEN not in run.out.replace(f"你：{BROKEN}", "")
    assert "Traceback" not in run.out
    # The chat goes on after the failed turn.
    assert len(run.results) == 1
    assert run.lines[-1] == cli.GOODBYE
