"""The transparent ledger: format, encryption at rest, idempotence, shredding (B2, D1)."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
import yaml

from olivia.core.crypto.errors import KeychainUnavailableError, NoKeychainError
from olivia.core.crypto.vault import Vault
from olivia.core.language.data import ContentKind, load_language_data
from olivia.core.language.filters import apply_willow
from olivia.core.language.gate import OutputGate
from olivia.core.memory.ledger import (
    LEDGER_DIRNAME,
    LEDGER_STORE,
    NOTE_MAX_CHARS,
    JournalEntry,
    Ledger,
    LedgerUnavailableError,
    MethodRecord,
    NoteEntry,
    SessionSummary,
    SummaryEntry,
)
from olivia.core.memory.text import load_memory_text
from olivia.core.methods.bandit import Feedback
from olivia.core.models import CrisisLevel, HelpStage
from olivia.core.taxonomy import load_taxonomy

SHANGHAI = timezone(timedelta(hours=8))
START = datetime(2026, 10, 22, 23, 30, tzinfo=SHANGHAI)
END = START + timedelta(minutes=22)
PATH = (HelpStage.S_READY, HelpStage.S_EXPLORE, HelpStage.S_EMPOWER, HelpStage.S_CLOSING)


def _summary(**overrides: object) -> SessionSummary:
    fields: dict[str, object] = {
        "started_at": START,
        "ended_at": END,
        "stage_path": PATH,
        "spectra": ("02", "05"),
        "methods": (MethodRecord("12:tipp_breathing", Feedback.HELPFUL), MethodRecord("30")),
    }
    fields.update(overrides)
    return SessionSummary(**fields)  # type: ignore[arg-type]


@pytest.fixture
def ledger(tmp_path, keychain):
    return Ledger(tmp_path, Vault(tmp_path, keychain))


def _decrypted(ledger: Ledger) -> list[str]:
    """Every entry file, opened with the ledger's own key."""
    return [ledger.read_markdown(path.stem) for path in ledger.entry_paths()]


# -- format ----------------------------------------------------------------------------------


def test_summary_round_trips_with_yaml_front_matter_and_a_chinese_body(ledger):
    entry_id = ledger.append_summary(_summary(), key="s1/0")
    (entry,) = ledger.entries()
    assert isinstance(entry, SummaryEntry) and entry.entry_id == entry_id
    assert entry.summary == _summary()
    assert entry.time == START and not entry.significant

    raw = ledger.read_markdown(entry_id)
    assert raw.startswith("---\n")
    head, body = raw[4:].split("\n---\n", 1)
    front = yaml.safe_load(head)
    assert front == {
        "olivia_ledger": 1,
        "id": entry_id,
        "kind": "summary",
        "started_at": START.isoformat(),
        "ended_at": END.isoformat(),
        "stage_path": ["S_ready", "S_explore", "S_empower", "S_closing"],
        "spectra": ["02", "05"],
        "methods": [
            {"id": "12:tipp_breathing", "feedback": "HELPFUL"},
            {"id": "30", "feedback": None},
        ],
        "crisis": {"entered": False, "level": None},
        "self_rating": {"before": None, "after": None},
        "significant": False,
        "marked_by_user": False,
    }
    text = load_memory_text()
    assert body.startswith("## 2026-10-22 的一次聊天")
    assert "开始 → 倾听 → 小练习 → 收尾" in body
    assert "低落和没劲、累和耗尽" in body
    assert "有帮助" in body and "还没有反馈" in body
    assert text.summary.crisis not in body and text.summary.significant not in body


def test_body_uses_card_titles_when_given(tmp_path, keychain):
    ledger = Ledger(tmp_path, Vault(tmp_path, keychain), method_titles={"30": "五感着陆"})
    entry_id = ledger.append_summary(_summary(), key="k")
    body = ledger.read_markdown(entry_id).split("\n---\n", 1)[1]
    assert "五感着陆（还没有反馈）" in body
    assert "12:tipp_breathing（有帮助）" in body  # unknown titles fall back to the id


def test_crisis_summary_keeps_flag_and_level_and_is_significant(ledger):
    summary = _summary(
        stage_path=(HelpStage.S_READY, HelpStage.S_EXPLORE, HelpStage.S_CRISIS),
        methods=(),
        crisis_level=CrisisLevel.L3,
    )
    assert summary.entered_crisis and summary.significant
    entry_id = ledger.append_summary(summary, key="k")
    raw = ledger.read_markdown(entry_id)
    front = yaml.safe_load(raw[4:].split("\n---\n", 1)[0])
    assert front["crisis"] == {"entered": True, "level": "L3"}
    assert front["significant"] is True
    text = load_memory_text()
    assert text.summary.crisis in raw and text.summary.significant in raw
    assert text.summary.no_methods in raw
    (entry,) = ledger.entries()
    assert entry.significant and entry.summary.crisis_level is CrisisLevel.L3


def test_user_marked_summary_is_significant(ledger):
    assert _summary(marked_by_user=True).significant
    assert not _summary(crisis_level=CrisisLevel.L1).significant  # ruling 29: >= L2 only
    assert _summary(crisis_level=CrisisLevel.L2).significant


def test_self_ratings_round_trip(ledger):
    ledger.append_summary(_summary(self_rating_before=3, self_rating_after=6), key="k")
    (entry,) = ledger.entries()
    assert (entry.summary.self_rating_before, entry.summary.self_rating_after) == (3, 6)
    assert "开始时 3，结束时 6" in ledger.read_markdown(entry.entry_id)


def test_summary_validation():
    with pytest.raises(ValueError):
        _summary(started_at=datetime(2026, 10, 22))  # naive
    with pytest.raises(ValueError):
        _summary(ended_at=START - timedelta(minutes=1))
    with pytest.raises(ValueError):
        _summary(self_rating_before=11)
    with pytest.raises(ValueError):
        _summary(stage_path=())
    with pytest.raises(ValueError):
        _summary(crisis_level=CrisisLevel.L0)


def test_note_round_trips_verbatim(ledger):
    note = "下周三有面试 ---\n---\n别忘了：带简历"
    entry_id = ledger.add_note(note, now=START)
    (entry,) = ledger.notes()
    assert entry == NoteEntry(entry_id, note, START)
    assert entry.significant  # the user asked for it: ruling 29 "user marked"
    raw = ledger.read_markdown(entry_id)
    front = yaml.safe_load(raw[4:].split("\n---\n", 1)[0])
    assert front == {
        "olivia_ledger": 1,
        "id": entry_id,
        "kind": "note",
        "created_at": START.isoformat(),
        "significant": True,
    }


@pytest.mark.parametrize("text", ["", "   ", "x" * (NOTE_MAX_CHARS + 1)])
def test_note_must_be_non_empty_and_short(ledger, text):
    with pytest.raises(ValueError):
        ledger.add_note(text, now=START)
    assert ledger.entries() == ()


def test_entries_are_sorted_and_filtered_by_time(ledger):
    later = START + timedelta(days=2)
    ledger.add_note("第二条", now=later)
    ledger.append_summary(_summary(), key="a")
    ledger.add_note("第一条", now=START + timedelta(hours=1))
    times = [e.time for e in ledger.entries()]
    assert times == sorted(times) and len(times) == 3
    assert [e.time for e in ledger.entries(since=later)] == [later]
    assert [n.text for n in ledger.notes()] == ["第一条", "第二条"]


def test_append_summary_is_idempotent_per_key(ledger):
    first = ledger.append_summary(_summary(), key="session/0")
    again = ledger.append_summary(_summary(ended_at=END + timedelta(minutes=1)), key="session/0")
    other = ledger.append_summary(_summary(), key="session/1")
    assert first == again != other
    assert len(ledger.entries()) == 2
    entry = next(e for e in ledger.entries() if e.entry_id == first)
    assert entry.summary.ended_at == END + timedelta(minutes=1)


# -- journal records (B6) --------------------------------------------------------------------


def test_journal_record_round_trips_and_is_updated_in_place(ledger):
    entry_id = ledger.record_journal(START, shown=True)
    assert ledger.record_journal(START, shown=True, helpful=False, entry_id=entry_id) == entry_id
    (entry,) = ledger.entries()
    assert entry == JournalEntry(entry_id, START, shown=True, helpful=False)
    assert entry.time == START and not entry.significant
    raw = ledger.read_markdown(entry_id)
    front = yaml.safe_load(raw[4:].split("\n---\n", 1)[0])
    assert front == {
        "olivia_ledger": 1,
        "id": entry_id,
        "kind": "journal",
        "offered_at": START.isoformat(),
        "shown": True,
        "helpful": False,
    }
    assert raw.endswith("## 2026-10-22 的一周小结\n- 看了这一周的小结。\n- 觉得帮助不大。\n")


def test_journal_record_validation(ledger):
    with pytest.raises(ValueError):
        ledger.record_journal(START, shown=False, helpful=True)
    with pytest.raises(ValueError):
        ledger.record_journal(datetime(2026, 10, 22), shown=True)  # naive
    with pytest.raises(ValueError):
        ledger.record_journal(START, shown=True, entry_id="../x")
    assert ledger.entries() == ()


@pytest.mark.parametrize(
    "front",
    [
        "kind: journal\noffered_at: '2026-10-22T23:30:00+08:00'\nshown: 1\nhelpful: null\n",
        "kind: journal\noffered_at: '2026-10-22T23:30:00+08:00'\nshown: true\nhelpful: 2\n",
        "kind: journal\noffered_at: '2026-10-22T23:30:00+08:00'\nshown: false\nhelpful: true\n",
        "kind: journal\noffered_at: '2026-10-22T23:30:00'\nshown: true\nhelpful: null\n",
        "kind: journal\nshown: true\nhelpful: null\n",
        "kind: diary\noffered_at: '2026-10-22T23:30:00+08:00'\nshown: true\nhelpful: null\n",
    ],
)
def test_a_malformed_journal_record_is_skipped(tmp_path, ledger, front):
    entry_id = "a" * 24
    document = f"---\nolivia_ledger: 1\nid: {entry_id}\n{front}---\n正文\n"
    blob = ledger.vault.seal(LEDGER_STORE, document.encode(), label=f"e_{entry_id}")
    (tmp_path / LEDGER_DIRNAME).mkdir()
    (tmp_path / LEDGER_DIRNAME / f"{entry_id}.olv").write_bytes(blob)
    assert ledger.entries() == () and ledger.skipped == 1


# -- encryption at rest ----------------------------------------------------------------------


def test_everything_is_encrypted_at_rest(tmp_path, ledger):
    ledger.append_summary(_summary(crisis_level=CrisisLevel.L3), key="k")
    ledger.add_note("外婆的院子里有一棵枣树", now=START)
    files = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert {p.parent.name for p in files} == {LEDGER_DIRNAME, "keys"}
    for path in files:
        data = path.read_bytes()  # only fragments too long to occur by chance in ciphertext
        for needle in ("外婆", "枣树", "S_crisis", "level: L3", "olivia_ledger", "summary", "2026"):
            assert needle.encode() not in data, (path, needle)
    entries = ledger.entry_paths()
    assert len(entries) == 2 and all(p.suffix == ".olv" for p in entries)
    if os.name != "nt":
        assert (tmp_path / LEDGER_DIRNAME).stat().st_mode & 0o777 == 0o700
        assert all(p.stat().st_mode & 0o777 == 0o600 for p in entries)
    assert not (tmp_path / LEDGER_DIRNAME / ".snapshots").exists()


def test_a_tampered_or_renamed_entry_is_skipped(tmp_path, ledger):
    keep = ledger.add_note("留下", now=START)
    gone = ledger.add_note("被改", now=START)
    path = tmp_path / LEDGER_DIRNAME / f"{gone}.olv"
    data = bytearray(path.read_bytes())
    data[-1] ^= 0x01
    path.write_bytes(bytes(data))
    moved = ledger.add_note("被挪", now=START)
    (tmp_path / LEDGER_DIRNAME / f"{moved}.olv").rename(
        tmp_path / LEDGER_DIRNAME / f"{'0' * 24}.olv"
    )
    assert [e.entry_id for e in ledger.entries()] == [keep]
    assert ledger.skipped == 2


def test_stray_files_are_ignored(tmp_path, ledger):
    ledger.add_note("一条", now=START)
    directory = tmp_path / LEDGER_DIRNAME
    (directory / ".abc.olv.123.tmp").write_bytes(b"half written")
    (directory / "notes.txt").write_text("not ours", encoding="utf-8")
    assert len(ledger.entries()) == 1 and ledger.skipped == 0


# -- keychain --------------------------------------------------------------------------------


def test_no_keychain_disables_the_ledger(tmp_path, keychain):
    keychain.broken = NoKeychainError("none")
    ledger = Ledger(tmp_path, Vault(tmp_path, keychain))
    assert not ledger.available()
    with pytest.raises(LedgerUnavailableError):
        ledger.append_summary(_summary(), key="k")
    with pytest.raises(LedgerUnavailableError):
        ledger.add_note("一条", now=START)
    assert not (tmp_path / LEDGER_DIRNAME).exists() or not ledger.entry_paths()
    assert not (tmp_path / "keys").exists()


def test_locked_keychain_raises_unavailable_and_changes_nothing(tmp_path, ledger, keychain):
    ledger.add_note("一条", now=START)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    keychain.broken = KeychainUnavailableError("locked")
    fresh = Ledger(tmp_path, Vault(tmp_path, keychain))
    with pytest.raises(LedgerUnavailableError):
        fresh.entries()
    with pytest.raises(LedgerUnavailableError):
        fresh.add_note("另一条", now=START)
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before


def test_unavailable_notice_is_due_once_per_device(tmp_path, keychain):
    keychain.broken = NoKeychainError("none")
    ledger = Ledger(tmp_path, Vault(tmp_path, keychain))
    assert ledger.take_unavailable_notice() is True
    assert Ledger(tmp_path, Vault(tmp_path, keychain)).take_unavailable_notice() is False


# -- shredding -------------------------------------------------------------------------------


def test_shred_makes_the_ledger_unreadable_and_removes_its_files(tmp_path, ledger, keychain):
    ledger.append_summary(_summary(), key="k")
    ledger.add_note("一条", now=START)
    copies = {p.name: p.read_bytes() for p in ledger.entry_paths()}
    ledger.shred()
    assert ledger.entries() == () and ledger.entry_paths() == []
    assert not Vault(tmp_path, keychain).has_data_key(LEDGER_STORE)
    # A lingering copy of an old entry can never be opened again.
    directory = tmp_path / LEDGER_DIRNAME
    for name, data in copies.items():
        (directory / name).write_bytes(data)
    fresh = Ledger(tmp_path, Vault(tmp_path, keychain))
    assert fresh.entries() == () and fresh.skipped == len(copies)
    # The ledger keeps working afterwards with a new key.
    fresh.add_note("新的一条", now=START)
    assert [n.text for n in fresh.notes()] == ["新的一条"]


def test_shred_on_an_empty_ledger_is_harmless(ledger):
    ledger.shred()
    assert ledger.entries() == ()


# -- copy ------------------------------------------------------------------------------------


def test_memory_copy_passes_willow_and_the_output_gate():
    tax = load_taxonomy()
    data = load_language_data(tax)
    gate = OutputGate(tax, data)
    text = load_memory_text()
    lines = [
        *text.replies.values(),
        *text.stages.values(),
        *text.spectra.values(),
        *text.feedback.values(),
        text.summary.crisis,
        text.summary.significant,
        text.summary.no_methods,
        text.summary.journal_shown,
        text.summary.journal_skipped,
        text.summary.journal_helpful,
        text.summary.journal_not_helpful,
    ]
    for line in lines:
        assert apply_willow(line, ContentKind.NORMAL, data.willow) == line, line
        assert gate.reasons(line, kind=ContentKind.NORMAL, stage=HelpStage.S_EXPLORE) == (), line
        assert "！" not in line and "!" not in line
    assert set(text.spectra) == set(tax.spectrum_ids())
    assert set(text.stages) == {stage.value for stage in HelpStage}


def test_summary_times_are_kept_in_their_own_zone(ledger):
    utc_start = START.astimezone(UTC)
    ledger.append_summary(_summary(started_at=utc_start, ended_at=END.astimezone(UTC)), key="k")
    (entry,) = ledger.entries()
    assert entry.summary.started_at == START and entry.summary.started_at.utcoffset() == timedelta()


def test_bodies_show_times_in_the_display_zone_and_store_them_as_recorded(tmp_path, keychain):
    """PRD Q-8: stored as recorded, shown in the profile's current timezone."""
    new_york = ZoneInfo("America/New_York")
    ledger = Ledger(tmp_path, Vault(tmp_path, keychain), zone=new_york)
    ledger.append_summary(_summary(), key="k")
    ledger.record_journal(START + timedelta(minutes=1), shown=False)
    summary, journal = ledger.entries()
    body = ledger.body(summary)
    assert body.startswith("## 2026-10-22 的一次聊天")  # 11:30 in New York, same day
    assert "- 时间：11:30 – 11:52" in body
    assert ledger.body(journal).startswith("## 2026-10-22 的一周小结")
    morning = datetime(2026, 10, 23, 8, 0, tzinfo=SHANGHAI)  # still 10-22 in New York
    ledger.append_summary(_summary(started_at=morning, ended_at=morning), key="morning")
    assert ledger.body(ledger.entries()[-1]).startswith("## 2026-10-22 的一次聊天")
    assert ledger.local(START) == START and ledger.local(START).tzinfo is new_york
    # What is stored keeps the recorded offset.
    head = ledger.read_markdown(summary.entry_id).split("\n---\n", 1)[0]
    assert yaml.safe_load(head[4:])["started_at"] == START.isoformat()
    plain = Ledger(tmp_path, Vault(tmp_path, keychain))
    assert "- 时间：23:30 – 23:52" in plain.body(summary)
