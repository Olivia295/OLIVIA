"""``olivia stats``: local usage numbers from the ledger, no chat content (F12)."""

from __future__ import annotations

import re
from datetime import timedelta

from cli_support import NOW, files_under, save_profile

from olivia.core.chang.profile import ProfileStore
from olivia.core.chang.stats import load_stats_text
from olivia.core.crypto.errors import NoKeychainError
from olivia.core.memory.ledger import LEDGER_DIRNAME, Ledger, SessionSummary, SummaryEntry
from olivia.core.models import HelpStage

TEXT = load_stats_text()
MESSAGES = ("今天上班好累，老板又临时加了好多活", "晚上回家还要收拾屋子")
_SLOT = re.compile(r"\{\w+\}")


def _summaries(home) -> list[SessionSummary]:
    ledger = Ledger(home, ProfileStore(home).vault)
    return [e.summary for e in ledger.entries() if isinstance(e, SummaryEntry)]


def _bare(line: str) -> str:
    """``line`` without its numbers, times and slots."""
    line = _SLOT.sub("", line)
    line = re.sub(r"\d{2}:\d{2}", "", line)
    return re.sub(r"[+-]?\d+(\.\d+)?", "", line)


def _skeletons() -> set[str]:
    """Every line ``olivia stats`` may print, bare."""
    unknown = _bare(TEXT.lines["unknown"])
    lines = {_bare(t) for k, t in TEXT.lines.items() if k != "unknown"}
    return lines | {line + unknown for line in lines} | set(TEXT.replies.values())


def test_stats_after_two_chats(run_cli, data_home):
    save_profile(data_home)
    run_cli(["chat", "--rules"], ["4", MESSAGES[0], "/exit", "6"])  # 23:30, before the window
    late = NOW + timedelta(days=2, hours=1)  # 00:30
    run_cli(["chat", "--rules"], ["", MESSAGES[1], "/exit", ""], now=late)
    first, second = _summaries(data_home)
    assert (first.turns, first.late_night) == (1, False)
    assert (second.turns, second.late_night) == (1, True)

    before = [(p, p.read_bytes()) for p in files_under(data_home)]
    run = run_cli(["stats"], now=NOW + timedelta(days=3))
    assert run.code == 0
    words = TEXT.lines
    assert run.lines == [
        words["heading"],
        words["sessions"].format(total=2, week=2, month=2),
        words["late_night"].format(start="00:00", end="05:00", count=1, known=2, percent=50),
        # The late-night line invites someone the user trusts, so it counts (B7).
        words["support"].format(count=1, turns=2, percent=50),
        words["rating"].format(change="+2.0", count=1),
    ]
    assert [(p, p.read_bytes()) for p in files_under(data_home)] == before  # writes nothing


def test_stats_hold_no_chat_content_and_no_name(run_cli, data_home):
    save_profile(data_home)
    run_cli(["chat", "--rules"], ["5", *MESSAGES, "记住：周四要去见搬家公司的人", "/exit", "7"])
    run = run_cli(["stats"])
    assert run.code == 0
    allowed = _skeletons()
    assert len(run.lines) == 5
    for line in run.lines:
        assert _bare(line) in allowed, line
    for typed in (*MESSAGES, "搬家公司", "小林"):
        assert typed not in run.out


def test_an_old_summary_counts_as_a_session_but_not_in_the_shares(run_cli, data_home):
    save_profile(data_home)
    ledger = Ledger(data_home, ProfileStore(data_home).vault)
    start = NOW - timedelta(days=10)
    old = SessionSummary(
        started_at=start,
        ended_at=start + timedelta(minutes=3),
        stage_path=(HelpStage.S_READY, HelpStage.S_EXPLORE),
        spectra=(),
        methods=(),
    )
    ledger.append_summary(old, key="before-f12")
    run = run_cli(["stats"])
    unknown = TEXT.lines["unknown"].format(count=1)
    assert TEXT.lines["sessions"].format(total=1, week=0, month=1) in run.lines
    assert TEXT.lines["late_night_none"].format(start="00:00", end="05:00") + unknown in run.lines
    assert TEXT.lines["support_none"] + unknown in run.lines


def test_stats_with_an_empty_ledger(run_cli, data_home):
    save_profile(data_home)
    run = run_cli(["stats"])
    assert run.code == 0 and run.out.strip() == TEXT.replies["empty"]
    assert not (data_home / LEDGER_DIRNAME).exists()


def test_stats_before_onboarding(run_cli, data_home):
    run = run_cli(["stats"])
    assert run.code == 1 and TEXT.replies["not_onboarded"] in run.out


def test_stats_refuse_minors(run_cli, data_home):
    save_profile(data_home, age_confirmed_18_plus=False, region=None, age_gate_refused_at=NOW)
    run = run_cli(["stats"])
    assert run.code == 1 and TEXT.replies["adults_only"] in run.out


def test_stats_without_a_keychain(run_cli, data_home, keychain):
    save_profile(data_home)
    keychain.broken = NoKeychainError("none")
    run = run_cli(["stats"])
    assert run.code == 1 and TEXT.replies["unavailable"] in run.out
