"""The session counts behind ``olivia stats`` (F12): turns, real-support replies, late night.

Entries written before F12 have no ``metrics`` and read as unknown; nothing is migrated.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest
import yaml

from olivia.core.crypto.vault import Vault
from olivia.core.language.data import ContentKind, load_language_data
from olivia.core.language.filters import apply_willow
from olivia.core.language.gate import OutputGate
from olivia.core.memory.ledger import (
    LEDGER_DIRNAME,
    LEDGER_STORE,
    Ledger,
    SessionSummary,
    SummaryEntry,
)
from olivia.core.memory.recorder import SessionRecorder
from olivia.core.memory.text import load_memory_text
from olivia.core.models import HelpStage, PersonaProfile, UserRegion
from olivia.core.session import Session
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
SHANGHAI = timezone(timedelta(hours=8))
EVENING = datetime(2026, 10, 22, 20, 0, tzinfo=SHANGHAI)
NIGHT = datetime(2026, 10, 23, 0, 30, tzinfo=SHANGHAI)
PATH = (HelpStage.S_READY, HelpStage.S_EXPLORE)
TEXT = load_memory_text()
# The opening of the rules-mode golden script: with seed 3 its sixth reply carries the
# real-support question (``tests/session/rules_mode_golden.json``).
MESSAGES = (
    "最近工作压力很大，有点焦虑，晚上总睡不着",
    "被领导催进度，心慌得要命",
    "给我一个方法",
    "/done",
    "[5%] 好累，今天不想动脑，只想躺着",
    "[60%] 好一点了，想聊聊我和室友的事情，我觉得她根本不在乎我",
)


def _summary(**overrides: object) -> SessionSummary:
    fields: dict[str, object] = {
        "started_at": EVENING,
        "ended_at": EVENING + timedelta(minutes=10),
        "stage_path": PATH,
        "spectra": (),
        "methods": (),
    }
    fields.update(overrides)
    return SessionSummary(**fields)  # type: ignore[arg-type]


@pytest.fixture
def ledger(tmp_path, keychain):
    return Ledger(tmp_path, Vault(tmp_path, keychain))


def _front(ledger: Ledger, entry_id: str) -> dict[str, object]:
    head = ledger.read_markdown(entry_id)[4:].split("\n---\n", 1)[0]
    front = yaml.safe_load(head)
    assert isinstance(front, dict)
    return front


# -- the ledger ------------------------------------------------------------------------------


def test_counts_round_trip_and_show_in_the_body(ledger):
    summary = _summary(turns=12, real_support_turns=2, late_night=True)
    entry_id = ledger.append_summary(summary, key="s/0")
    (entry,) = ledger.entries()
    assert isinstance(entry, SummaryEntry) and entry.summary == summary
    assert entry.summary.has_metrics
    assert _front(ledger, entry_id)["metrics"] == {
        "turns": 12,
        "real_support_turns": 2,
        "late_night": True,
    }
    body = ledger.body(entry).splitlines()
    assert TEXT.summary.turns.format(turns=12) in body
    assert TEXT.summary.support.format(count=2) in body
    assert TEXT.summary.late_night in body


def test_zero_support_and_daytime_add_only_the_turn_line(ledger):
    ledger.append_summary(_summary(turns=3, real_support_turns=0, late_night=False), key="k")
    (entry,) = ledger.entries()
    body = ledger.body(entry).splitlines()
    assert TEXT.summary.turns.format(turns=3) in body
    assert not any(line.startswith(TEXT.summary.support.split("{")[0]) for line in body)
    assert TEXT.summary.late_night not in body


def test_an_entry_from_before_f12_reads_as_unknown(ledger):
    """No ``metrics`` key, exactly the front-matter B2-B6 wrote: still valid, unknown."""
    entry_id = ledger.append_summary(_summary(), key="old")
    assert "metrics" not in _front(ledger, entry_id)
    (entry,) = ledger.entries()
    assert isinstance(entry, SummaryEntry)
    s = entry.summary
    assert (s.turns, s.real_support_turns, s.late_night) == (None, None, None)
    assert not s.has_metrics
    assert TEXT.summary.turns.split("{")[0] not in ledger.body(entry)


@pytest.mark.parametrize(
    "fields",
    [
        {"turns": 3},
        {"turns": 3, "real_support_turns": 1},
        {"late_night": False},
        {"turns": 2, "real_support_turns": 3, "late_night": False},
        {"turns": -1, "real_support_turns": 0, "late_night": False},
        {"turns": 2, "real_support_turns": -1, "late_night": False},
    ],
)
def test_counts_are_all_known_and_consistent(fields):
    with pytest.raises(ValueError):
        _summary(**fields)


@pytest.mark.parametrize(
    "metrics",
    [
        "metrics: {turns: 3, real_support_turns: 1}\n",
        "metrics: {turns: 3, real_support_turns: 1, late_night: 1}\n",
        "metrics: {turns: '3', real_support_turns: 1, late_night: false}\n",
        "metrics: {turns: 3, real_support_turns: 1, late_night: false, text: x}\n",
        "metrics: [3, 1, false]\n",
    ],
)
def test_a_malformed_metrics_record_is_skipped(tmp_path, ledger, metrics):
    good = ledger.append_summary(_summary(), key="k")
    document = ledger.read_markdown(good)
    head, body = document[4:].split("\n---\n", 1)
    entry_id = "b" * 24
    head = head.replace(f"id: {good}", f"id: {entry_id}") + "\n" + metrics.rstrip("\n")
    blob = ledger.vault.seal(
        LEDGER_STORE, f"---\n{head}\n---\n{body}".encode(), label=f"e_{entry_id}"
    )
    (tmp_path / LEDGER_DIRNAME / f"{entry_id}.olv").write_bytes(blob)
    entries = ledger.entries()
    assert [e.entry_id for e in entries] == [good] and ledger.skipped == 1


def test_the_new_lines_pass_willow_and_the_output_gate():
    data = load_language_data(TAX)
    gate = OutputGate(TAX, data)
    st = TEXT.summary
    for line in (st.turns.format(turns=12), st.support.format(count=2), st.late_night):
        assert apply_willow(line, ContentKind.NORMAL, data.willow) == line, line
        assert gate.reasons(line, kind=ContentKind.NORMAL, stage=HelpStage.S_EXPLORE) == (), line


# -- the recorder ----------------------------------------------------------------------------


class Clock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now


def _record(ledger: Ledger, start: datetime, messages: tuple[str, ...], seed: int = 3):
    clock = Clock(start)
    profile = PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=start,
        updated_at=start,
        region=UserRegion("CN", "Asia/Shanghai"),
    )
    session = Session.open(TAX, profile, rng=random.Random(seed), now=clock)
    recorder = SessionRecorder(ledger, session.state.session_id, clock)
    results = []
    for message in messages:
        clock.now += timedelta(minutes=1)
        results.append(recorder.observe(message, session.turn(message)))
    assert recorder.close()
    summaries = [e.summary for e in ledger.entries() if isinstance(e, SummaryEntry)]
    return results, summaries


def test_the_recorder_counts_turns_and_real_support_replies(ledger):
    results, summaries = _record(ledger, EVENING, MESSAGES)
    assert all(isinstance(r.inspect["real_support"], bool) for r in results)
    assert all(r.inspect["late_night"] is False for r in results)
    assert len(summaries) == 1
    (summary,) = summaries
    assert summary.turns == len(MESSAGES)
    assert summary.real_support_turns == sum(1 for r in results if r.inspect["real_support"])
    assert summary.real_support_turns >= 1
    assert summary.late_night is False


def test_a_session_after_midnight_is_late_night(ledger):
    results, (summary,) = _record(ledger, NIGHT, MESSAGES[:2])
    assert all(r.inspect["late_night"] is True for r in results)
    assert summary.late_night is True and summary.turns == 2


def test_a_session_that_runs_into_the_night_is_late_night(ledger):
    start = datetime(2026, 10, 22, 23, 58, tzinfo=SHANGHAI)
    results, (summary,) = _record(ledger, start, MESSAGES[:3])
    assert [r.inspect["late_night"] for r in results] == [False, True, True]
    assert summary.late_night is True
