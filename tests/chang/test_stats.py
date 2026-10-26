"""``olivia stats`` numbers and wording (F12; PRD §11.1)."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

import pytest
import yaml

from olivia.core.chang.stats import (
    LINE_KEYS,
    REPLY_KEYS,
    StatsTextError,
    compute,
    load_stats_text,
    render,
)
from olivia.core.language.data import ContentKind, load_language_data
from olivia.core.language.filters import apply_willow
from olivia.core.language.gate import OutputGate
from olivia.core.memory.ledger import JournalEntry, MethodRecord, SessionSummary
from olivia.core.models import HelpStage
from olivia.core.taxonomy import load_taxonomy

SHANGHAI = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 25, 20, 0, tzinfo=SHANGHAI)
WINDOW = (time(0, 0), time(5, 0))
TEXT = load_stats_text()


def _s(days_ago: float, **fields: object) -> SessionSummary:
    start = NOW - timedelta(days=days_ago)
    base: dict[str, object] = {
        "started_at": start,
        "ended_at": start + timedelta(minutes=5),
        "stage_path": (HelpStage.S_READY, HelpStage.S_EXPLORE),
        "spectra": ("02",),
        "methods": (MethodRecord("30"),),
    }
    base.update(fields)
    return SessionSummary(**base)  # type: ignore[arg-type]


def _counted(days_ago: float, turns: int, support: int, late: bool, **fields: object):
    return _s(days_ago, turns=turns, real_support_turns=support, late_night=late, **fields)


def test_counts_windows_shares_and_mean_change():
    summaries = [
        _s(40, self_rating_before=3, self_rating_after=6),  # before F12: no counts
        _counted(20, 10, 1, True, self_rating_before=5, self_rating_after=4),
        _counted(6, 8, 2, False, self_rating_before=4),
        _counted(1, 2, 0, True, self_rating_before=2, self_rating_after=4),
    ]
    stats = compute(summaries, NOW)
    assert (stats.sessions, stats.last_week, stats.last_month) == (4, 2, 3)
    assert (stats.late_night, stats.counted, stats.uncounted) == (2, 3, 1)
    assert (stats.support_turns, stats.turns) == (3, 20)
    assert stats.rated == 3
    assert stats.rating_change == pytest.approx((3 - 1 + 2) / 3)


def test_the_window_edges_are_inclusive():
    stats = compute([_s(7), _s(30), _s(30.001)], NOW)
    assert (stats.last_week, stats.last_month) == (1, 2)


def test_render_prints_numbers_only():
    summaries = [
        _s(40),
        _counted(3, 10, 2, True, self_rating_before=4, self_rating_after=7),
        _counted(1, 10, 1, False, self_rating_before=6, self_rating_after=5),
    ]
    lines = render(compute(summaries, NOW), TEXT, WINDOW).splitlines()
    unknown = TEXT.lines["unknown"].format(count=1)
    assert lines == [
        TEXT.lines["heading"],
        TEXT.lines["sessions"].format(total=3, week=2, month=2),
        TEXT.lines["late_night"].format(start="00:00", end="05:00", count=1, known=2, percent=50)
        + unknown,
        TEXT.lines["support"].format(count=3, turns=20, percent=15) + unknown,
        TEXT.lines["rating"].format(change="+1.0", count=2),
        TEXT.lines["rose"].format(count=1, rated=2, percent=50),
        TEXT.lines["journal_helpful_none"],
    ]
    # No spectra, exercise titles or stage names: the template text and numbers only.
    out = "\n".join(lines)
    assert "倾听" not in out and "低落" not in out and "S_" not in out


def test_render_with_only_old_entries_and_no_ratings():
    lines = render(compute([_s(2), _s(1)], NOW), TEXT, WINDOW).splitlines()
    unknown = TEXT.lines["unknown"].format(count=2)
    assert lines[2] == TEXT.lines["late_night_none"].format(start="00:00", end="05:00") + unknown
    assert lines[3] == TEXT.lines["support_none"] + unknown
    assert lines[4] == TEXT.lines["rating_none"]
    assert lines[5] == TEXT.lines["rose_none"]
    assert lines[6] == TEXT.lines["journal_helpful_none"]


@pytest.mark.parametrize(("before", "after", "shown"), [(5, 5, "0.0"), (6, 3, "-3.0")])
def test_the_change_is_signed(before, after, shown):
    stats = compute([_s(1, self_rating_before=before, self_rating_after=after)], NOW)
    assert TEXT.lines["rating"].format(change=shown, count=1) in render(stats, TEXT, WINDOW)


def test_render_needs_a_session():
    with pytest.raises(ValueError):
        render(compute([], NOW), TEXT, WINDOW)


def test_compute_needs_an_aware_time():
    with pytest.raises(ValueError):
        compute([], NOW.replace(tzinfo=None))


def test_the_window_comes_from_the_taxonomy():
    assert load_taxonomy().late_night_window() == WINDOW


def test_the_copy_passes_willow_and_the_output_gate():
    tax = load_taxonomy()
    data = load_language_data(tax)
    gate = OutputGate(tax, data)
    filled = {
        "start": "00:00",
        "end": "05:00",
        "total": 3,
        "week": 1,
        "month": 2,
        "count": 1,
        "known": 2,
        "percent": 50,
        "turns": 20,
        "change": "+1.0",
        "rated": 3,
        "answered": 4,
    }
    for line in (*TEXT.lines.values(), *TEXT.replies.values()):
        shown = line.format(**filled)
        assert apply_willow(shown, ContentKind.NORMAL, data.willow) == shown, shown
        assert gate.reasons(shown, kind=ContentKind.NORMAL, stage=HelpStage.S_EXPLORE) == ()
        assert "！" not in shown and "!" not in shown


def test_a_bad_text_file_is_refused(tmp_path):
    doc = {
        "version": 1,
        "lines": dict.fromkeys(LINE_KEYS, "x"),
        "replies": dict.fromkeys(REPLY_KEYS, "x"),
    }
    (tmp_path / "stats.yaml").write_text(yaml.safe_dump(doc), "utf-8")
    assert load_stats_text(tmp_path).lines["heading"] == "x"
    del doc["lines"]["unknown"]
    (tmp_path / "stats.yaml").write_text(yaml.safe_dump(doc), "utf-8")
    with pytest.raises(StatsTextError):
        load_stats_text(tmp_path)


# -- the share that rose and the journal answers (PRD §11.1) ----------------------------------


def _journal(days_ago: float, *, shown: bool = True, helpful: bool | None = None) -> JournalEntry:
    return JournalEntry("a" * 24, NOW - timedelta(days=days_ago), shown, helpful)


def test_the_share_of_sessions_whose_rating_rose():
    summaries = [
        _s(5, self_rating_before=3, self_rating_after=6),  # rose
        _s(4, self_rating_before=5, self_rating_after=5),  # same: not "after > before"
        _s(3, self_rating_before=6, self_rating_after=2),
        _s(2, self_rating_before=1, self_rating_after=2),  # rose
        _s(1, self_rating_before=4),  # one rating only: left out
        _s(0.5),
    ]
    stats = compute(summaries, NOW)
    assert (stats.rose, stats.rated) == (2, 4)
    line = TEXT.lines["rose"].format(count=2, rated=4, percent=50)
    assert line in render(stats, TEXT, WINDOW).splitlines()


def test_no_session_with_both_ratings_has_no_share():
    stats = compute([_s(1, self_rating_after=7), _s(2)], NOW)
    assert (stats.rose, stats.rated) == (0, 0)
    assert TEXT.lines["rose_none"] in render(stats, TEXT, WINDOW).splitlines()


def test_the_journal_answers_are_counted():
    journals = [
        _journal(20, helpful=True),
        _journal(9, helpful=False),
        _journal(8, helpful=True),
        _journal(3, shown=True, helpful=None),  # skipped the question
        _journal(1, shown=False),  # declined the journal
    ]
    stats = compute([_s(1)], NOW, journals)
    assert (stats.journal_answered, stats.journal_helpful) == (3, 2)
    line = TEXT.lines["journal_helpful"].format(answered=3, count=2, percent=67)
    assert line in render(stats, TEXT, WINDOW).splitlines()


def test_journals_without_an_answer_have_no_share():
    stats = compute([_s(1)], NOW, [_journal(1, shown=False), _journal(2, helpful=None)])
    assert (stats.journal_answered, stats.journal_helpful) == (0, 0)
    assert TEXT.lines["journal_helpful_none"] in render(stats, TEXT, WINDOW).splitlines()
    assert compute([_s(1)], NOW).journal_answered == 0
