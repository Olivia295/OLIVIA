"""The battery figures in a session summary (CHANG-04: the journal's battery trend).

``metrics`` gains three values: whether a ``[NN%]`` prefix was given, the lowest prefix
reading rounded to 0.05, and whether the session was in S_haven. Numbers and booleans
only; summaries written before (F12's ``metrics`` without them, or none at all) read as
unknown and are never migrated.
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
    round_battery,
)
from olivia.core.memory.recorder import SessionRecorder
from olivia.core.memory.text import load_memory_text
from olivia.core.models import HelpStage, PersonaProfile, UserRegion
from olivia.core.session import Session
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
SHANGHAI = timezone(timedelta(hours=8))
EVENING = datetime(2026, 10, 22, 20, 0, tzinfo=SHANGHAI)
PATH = (HelpStage.S_READY, HelpStage.S_EXPLORE)
TEXT = load_memory_text()
COUNTS: dict[str, object] = {"turns": 4, "real_support_turns": 0, "late_night": False}


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


def test_battery_round_trips_as_numbers_and_booleans_only(ledger):
    summary = _summary(**COUNTS, battery_prefix=True, battery_min=0.05, haven=True)
    entry_id = ledger.append_summary(summary, key="s/0")
    (entry,) = ledger.entries()
    assert isinstance(entry, SummaryEntry) and entry.summary == summary
    assert entry.summary.has_battery
    assert _front(ledger, entry_id)["metrics"] == {
        **COUNTS,
        "battery_prefix": True,
        "battery_min": 0.05,
        "haven": True,
    }
    assert TEXT.summary.battery.format(percent=5) in ledger.body(entry).splitlines()


def test_no_prefix_stores_no_lowest_reading(ledger):
    summary = _summary(**COUNTS, battery_prefix=False, battery_min=None, haven=False)
    entry_id = ledger.append_summary(summary, key="k")
    metrics = _front(ledger, entry_id)["metrics"]
    assert isinstance(metrics, dict) and metrics["battery_min"] is None
    (entry,) = ledger.entries()
    assert entry.summary == summary  # type: ignore[union-attr]
    assert TEXT.summary.battery.split("{")[0] not in ledger.body(entry)


def test_an_f12_summary_reads_as_battery_unknown(ledger):
    """``metrics`` with only F12's three counts, exactly as F12 wrote it: still valid."""
    entry_id = ledger.append_summary(_summary(**COUNTS), key="f12")
    assert _front(ledger, entry_id)["metrics"] == COUNTS
    (entry,) = ledger.entries()
    assert isinstance(entry, SummaryEntry)
    s = entry.summary
    assert (s.battery_prefix, s.battery_min, s.haven) == (None, None, None)
    assert s.has_metrics and not s.has_battery


def test_a_summary_from_before_f12_reads_as_battery_unknown(ledger):
    ledger.append_summary(_summary(), key="old")
    (entry,) = ledger.entries()
    assert isinstance(entry, SummaryEntry) and not entry.summary.has_battery


@pytest.mark.parametrize(
    ("value", "rounded"),
    [(0.0, 0.0), (0.05, 0.05), (0.12, 0.1), (0.13, 0.15), (0.6, 0.6), (0.99, 1.0), (1.0, 1.0)],
)
def test_the_lowest_reading_is_rounded_to_a_twentieth(value, rounded):
    assert round_battery(value) == rounded


@pytest.mark.parametrize(
    "fields",
    [
        {"battery_prefix": True, "battery_min": 0.1, "haven": False},  # no F12 counts
        {**COUNTS, "battery_prefix": True},
        {**COUNTS, "haven": False},
        {**COUNTS, "battery_prefix": True, "battery_min": None, "haven": False},
        {**COUNTS, "battery_prefix": False, "battery_min": 0.2, "haven": False},
        {**COUNTS, "battery_prefix": True, "battery_min": 0.12, "haven": False},
        {**COUNTS, "battery_prefix": True, "battery_min": 1.5, "haven": False},
        {**COUNTS, "battery_prefix": True, "battery_min": -0.05, "haven": False},
    ],
)
def test_battery_values_are_all_known_and_consistent(fields):
    with pytest.raises(ValueError):
        _summary(**fields)


@pytest.mark.parametrize(
    "battery",
    [
        "battery_prefix: true",  # the other two missing
        "battery_prefix: true, battery_min: 0.1",
        "battery_prefix: 1, battery_min: 0.1, haven: false",
        "battery_prefix: true, battery_min: '0.1', haven: false",
        "battery_prefix: true, battery_min: 0.1, haven: 0",
        "battery_prefix: true, battery_min: true, haven: false",
        "battery_prefix: true, battery_min: 0.1, haven: false, words: x",
    ],
)
def test_a_malformed_battery_record_is_skipped(tmp_path, ledger, battery):
    good = ledger.append_summary(_summary(), key="k")
    document = ledger.read_markdown(good)
    head, body = document[4:].split("\n---\n", 1)
    entry_id = "c" * 24
    metrics = f"metrics: {{turns: 4, real_support_turns: 0, late_night: false, {battery}}}"
    head = head.replace(f"id: {good}", f"id: {entry_id}") + "\n" + metrics
    blob = ledger.vault.seal(
        LEDGER_STORE, f"---\n{head}\n---\n{body}".encode(), label=f"e_{entry_id}"
    )
    (tmp_path / LEDGER_DIRNAME / f"{entry_id}.olv").write_bytes(blob)
    entries = ledger.entries()
    assert [e.entry_id for e in entries] == [good] and ledger.skipped == 1


def test_the_body_line_passes_willow_and_the_output_gate():
    data = load_language_data(TAX)
    gate = OutputGate(TAX, data)
    line = TEXT.summary.battery.format(percent=15)
    assert apply_willow(line, ContentKind.NORMAL, data.willow) == line
    assert gate.reasons(line, kind=ContentKind.NORMAL, stage=HelpStage.S_EXPLORE) == ()


# -- the session and the recorder ------------------------------------------------------------


class Clock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now


def _record(ledger: Ledger, messages: tuple[str, ...], seed: int = 3):
    clock = Clock(EVENING)
    profile = PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=EVENING,
        updated_at=EVENING,
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


def test_the_panel_reports_the_prefix_reading_only():
    session = Session.open(
        TAX,
        PersonaProfile(age_confirmed_18_plus=True, created_at=EVENING, updated_at=EVENING),
        rng=random.Random(3),
        now=lambda: EVENING,
    )
    assert session.turn("最近工作压力很大").inspect["battery_prefix"] is None
    assert session.turn("[12%] 好累，今天不想动脑").inspect["battery_prefix"] == 0.12
    assert session.turn("嗯").inspect["battery_prefix"] is None  # the reading carries over


def test_the_recorder_keeps_the_lowest_prefix_and_the_haven(ledger):
    messages = (
        "最近工作压力很大，有点焦虑，晚上总睡不着",
        "[30%] 被领导催进度，心慌得要命",
        "[12%] 好累，今天不想动脑，只想躺着",
        "[60%] 好一点了，想聊聊我和室友的事情",
    )
    results, (summary,) = _record(ledger, messages)
    assert any(r.stage is HelpStage.S_HAVEN for r in results)
    assert summary.battery_prefix is True
    assert summary.battery_min == 0.1
    assert summary.haven is True


def test_a_session_without_a_prefix_records_none(ledger):
    _, (summary,) = _record(ledger, ("最近工作压力很大，有点焦虑", "被领导催进度"))
    assert (summary.battery_prefix, summary.battery_min, summary.haven) == (False, None, False)
    assert summary.has_battery
