"""Fixtures for the ``olivia`` command-line tests.

Every test gets its own data directory under ``tmp_path`` (``OLIVIA_HOME``), and the
platform's real user data directory is made unreachable, so no test can touch it.
"""

from __future__ import annotations

import io
import random
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import platformdirs
import pytest
from cli_support import NOW, Run

from olivia import cli
from olivia.core.session import Session, TurnResult


@pytest.fixture(autouse=True)
def data_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "olivia-home"
    monkeypatch.setenv("OLIVIA_HOME", str(home))

    def forbidden(*_args: object, **_kwargs: object) -> Path:
        raise AssertionError("tests must never resolve the real user data directory")

    monkeypatch.setattr(platformdirs, "user_data_path", forbidden)
    return home


class Recorder:
    """Every ``Session.turn`` the CLI makes: the text in and the result out."""

    def __init__(self) -> None:
        self.results: list[TurnResult] = []
        self.texts: list[str] = []
        self.sessions: list[Session] = []


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    record = Recorder()
    original = Session.turn

    def spy(self: Session, text: str) -> TurnResult:
        if all(self is not s for s in record.sessions):
            record.sessions.append(self)
        record.texts.append(text)
        result = original(self, text)
        record.results.append(result)
        return result

    monkeypatch.setattr(Session, "turn", spy)
    return record


@pytest.fixture
def run_cli(recorder: Recorder) -> Callable[..., Run]:
    """Run ``olivia.cli.main`` on scripted input with a fixed clock and seed."""

    def run(
        argv: list[str],
        lines: list[str] | None = None,
        *,
        now: datetime = NOW,
        seed: int = 7,
        stdin: Any = None,
    ) -> Run:
        start = len(recorder.results)
        sessions_before = len(recorder.sessions)
        source = stdin if stdin is not None else io.StringIO("".join(f"{x}\n" for x in lines or []))
        out = io.StringIO()
        code = cli.main(argv, stdin=source, stdout=out, clock=lambda: now, rng=random.Random(seed))
        return Run(
            code,
            out.getvalue(),
            recorder.results[start:],
            recorder.texts[start:],
            recorder.sessions[sessions_before:],
        )

    return run
