"""``olivia chat`` and the memory ledger: summaries at every exit, notes, no keychain (B2)."""

from __future__ import annotations

import io
from datetime import datetime, timedelta

import pytest
from cli_support import L3_SENTENCE, NOW, SHANGHAI, files_under, save_profile

from olivia import cli
from olivia.core.chang.profile import ProfileStore
from olivia.core.crypto.errors import NoKeychainError
from olivia.core.memory import recorder as recorder_module
from olivia.core.memory.forget import load_forget_text
from olivia.core.memory.ledger import LEDGER_DIRNAME, Ledger, NoteEntry, SummaryEntry
from olivia.core.memory.text import load_memory_text
from olivia.core.models import CrisisLevel, HelpStage

TEXT = load_memory_text()


def _ledger(home) -> Ledger:
    return Ledger(home, ProfileStore(home).vault)


def test_two_sessions_each_leave_one_summary_and_the_note_survives(run_cli, data_home):
    save_profile(data_home)
    first = run_cli(["chat", "--rules"], ["记住：下周三面试，我有点紧张", "今天上班好累", "/exit"])
    assert first.code == 0
    assert TEXT.replies["note_saved"] in first.out
    assert first.lines[-1] == cli.GOODBYE
    later = NOW + timedelta(days=1)
    # ends at EOF
    second = run_cli(["chat", "--rules"], ["给我一个方法", "/done", L3_SENTENCE], now=later)
    assert second.code == 0

    ledger = _ledger(data_home)
    entries = ledger.entries()
    notes = [e for e in entries if isinstance(e, NoteEntry)]
    summaries = [e for e in entries if isinstance(e, SummaryEntry)]
    assert [n.text for n in notes] == ["下周三面试，我有点紧张"]
    assert len(summaries) == 2
    calm, crisis = (s.summary for s in summaries)
    assert not calm.entered_crisis and calm.methods == ()
    assert crisis.crisis_level is CrisisLevel.L3 and HelpStage.S_CRISIS in crisis.stage_path
    shown = second.results[0].action_id
    assert [(m.method_id, m.feedback.value if m.feedback else None) for m in crisis.methods] == [
        (shown, "HELPFUL")
    ]
    assert calm.started_at.utcoffset() == NOW.utcoffset()  # the profile's local time
    # Nothing on disk is readable without the key.
    for path in files_under(data_home / LEDGER_DIRNAME):
        for needle in ("面试", "紧张", "上班", "遗书", "S_crisis", "summary"):
            assert needle.encode() not in path.read_bytes()


def test_ctrl_c_still_writes_the_summary(run_cli, data_home):
    save_profile(data_home)

    class Interrupting(io.StringIO):
        def __init__(self) -> None:
            super().__init__("今天上班好累\n")

        def readline(self, size: int | None = -1) -> str:
            line = super().readline()
            if not line:
                raise KeyboardInterrupt
            return line

    run = run_cli(["chat", "--rules"], stdin=Interrupting())
    assert run.code == 0 and run.lines[-1] == cli.GOODBYE
    (entry,) = _ledger(data_home).entries()
    assert isinstance(entry, SummaryEntry)


def test_exit_right_away_writes_nothing(run_cli, data_home):
    save_profile(data_home)
    run = run_cli(["chat", "--rules"], ["/exit"])
    assert run.code == 0
    assert not (data_home / LEDGER_DIRNAME).exists()


def test_no_keychain_is_told_once_and_nothing_is_remembered(run_cli, data_home, keychain):
    save_profile(data_home)
    keychain.broken = NoKeychainError("none")
    notice = TEXT.replies["memory_unavailable"]
    first = run_cli(["chat", "--rules"], ["记住：下周三面试", "今天上班好累"])
    assert first.code == 0
    assert first.out.count(notice) == 1
    assert first.out.index(notice) < first.out.index(cli.CHAT_HINT)
    assert TEXT.replies["note_unavailable"] in first.out
    assert TEXT.replies["note_saved"] not in first.out
    again = run_cli(["chat", "--rules"], ["今天上班好累"])
    assert notice not in again.out
    ledger_files = files_under(data_home / LEDGER_DIRNAME)
    assert [p.read_bytes() for p in ledger_files] == [b""]  # only the "told" marker
    assert not (data_home / "keys").exists()


def test_a_summary_lost_to_a_locked_keychain_is_mentioned(run_cli, data_home, monkeypatch):
    save_profile(data_home)

    def lost(self: object) -> bool:
        return False

    monkeypatch.setattr(recorder_module.SessionRecorder, "close", lost)
    run = run_cli(["chat", "--rules"], ["今天上班好累"])
    assert TEXT.replies["summary_not_saved"] in run.out
    assert run.lines[-1] == cli.GOODBYE


@pytest.mark.parametrize("message", ["我记住了他说的话", "今天好累，记住：别再加班"])
def test_ordinary_messages_are_never_stored(run_cli, data_home, message):
    save_profile(data_home)
    run_cli(["chat", "--rules"], [message])
    assert _ledger(data_home).notes() == ()


def test_memory_shows_times_in_the_current_timezone_after_a_move(run_cli, data_home):
    """PRD Q-8 (F11): stored as recorded, shown in the profile's timezone of today."""
    save_profile(data_home)
    morning = datetime(2026, 10, 23, 9, 0, tzinfo=SHANGHAI)  # 18:00 the day before in LA
    run_cli(["chat", "--rules"], ["记住：周五去看展", "今天上班好累", "/exit"], now=morning)
    before = run_cli(["memory"])
    assert "1. 2026-10-23 的一次聊天" in before.lines  # the summary first, then the note
    assert "   - 时间：09:00 – 09:00" in before.lines
    moved = run_cli(["region", "US", "--timezone", "America/Los_Angeles"], now=morning)
    assert moved.code == 0
    after = run_cli(["memory"])
    assert "1. 2026-10-22 的一次聊天" in after.lines
    assert "   - 时间：18:00 – 18:00" in after.lines
    note = load_forget_text().memory["note"].replace("{date}", "2026-10-22")
    assert f"2. {note}" in after.lines
    # Nothing stored was rewritten: the summary keeps the Shanghai offset it was made with.
    (summary,) = [e for e in _ledger(data_home).entries() if isinstance(e, SummaryEntry)]
    assert summary.summary.started_at.utcoffset() == morning.utcoffset()
