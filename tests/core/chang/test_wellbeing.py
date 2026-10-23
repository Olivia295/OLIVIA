"""Anti-dependence prompts: the 45-minute break, late night and real-support share (B7).

The clock is the session's own (timezone-aware) clock; late night is read in the user's
profile timezone from the taxonomy's ``late_night`` window, end exclusive.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
import yaml

from olivia.core.chang.wellbeing import BREAK_AFTER, Reminder, Wellbeing
from olivia.core.taxonomy import Taxonomy, TaxonomyError, load_taxonomy

TAX = load_taxonomy()
# 14:00 UTC is 22:00 in Shanghai and 10:00 in New York (EDT): not late night anywhere here.
START = datetime(2026, 10, 22, 14, 0, tzinfo=UTC)


def _wb(tz: str = "Asia/Shanghai", start: datetime = START) -> Wellbeing:
    return Wellbeing(TAX, tz, start)


def _turn(wb: Wellbeing, now: datetime, *, eligible: bool = True) -> Reminder:
    """One turn: take the due reminder when the reply can carry it, then record it."""
    reminder = wb.due(now) if eligible else Reminder.NONE
    wb.record(now, reminder, support=False)
    return reminder


def test_taxonomy_late_night_window() -> None:
    assert TAX.late_night_window() == (time(0, 0), time(5, 0))


@pytest.mark.parametrize("bad", [{"start": "0:00", "end": "05:00"}, {"start": "00:00"}, "x"])
def test_taxonomy_late_night_window_rejects_bad_data(bad: Any) -> None:
    path = Path(__file__).resolve().parents[3] / "olivia" / "data" / "taxonomy.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["late_night"] = bad
    with pytest.raises(TaxonomyError):
        Taxonomy(data).late_night_window()


def test_break_threshold_is_forty_five_minutes() -> None:
    assert timedelta(minutes=45) == BREAK_AFTER


def test_no_break_at_44_59_and_a_break_at_45_00() -> None:
    wb = _wb()
    assert _turn(wb, START) is Reminder.NONE
    assert _turn(wb, START + timedelta(minutes=44, seconds=59)) is Reminder.NONE
    assert _turn(wb, START + timedelta(minutes=45)) is Reminder.BREAK


def test_break_repeats_only_after_another_45_minutes() -> None:
    wb = _wb()
    shown = START + timedelta(minutes=45)
    assert _turn(wb, shown) is Reminder.BREAK
    assert _turn(wb, shown + timedelta(minutes=1)) is Reminder.NONE
    assert _turn(wb, shown + timedelta(minutes=44, seconds=59)) is Reminder.NONE
    assert _turn(wb, shown + timedelta(minutes=45)) is Reminder.BREAK


def test_a_due_break_waits_for_the_next_eligible_reply() -> None:
    wb = _wb()
    late = START + timedelta(minutes=50)
    assert _turn(wb, late, eligible=False) is Reminder.NONE
    assert _turn(wb, late + timedelta(minutes=1), eligible=False) is Reminder.NONE
    assert _turn(wb, late + timedelta(minutes=2)) is Reminder.BREAK
    # The 45 minutes count from when it was shown.
    assert _turn(wb, late + timedelta(minutes=46)) is Reminder.NONE
    assert _turn(wb, late + timedelta(minutes=47)) is Reminder.BREAK


def _utc(hour: int, minute: int) -> datetime:
    return datetime(2026, 10, 22, hour, minute, tzinfo=UTC)


@pytest.mark.parametrize(
    ("tz", "moment", "late"),
    [
        # Asia/Shanghai is UTC+8.
        ("Asia/Shanghai", _utc(15, 59), False),  # 23:59
        ("Asia/Shanghai", _utc(16, 0), True),  # 00:00
        ("Asia/Shanghai", _utc(20, 59), True),  # 04:59
        ("Asia/Shanghai", _utc(21, 0), False),  # 05:00
        # America/New_York is UTC-4 on this date (EDT).
        ("America/New_York", _utc(3, 59), False),  # 23:59
        ("America/New_York", _utc(4, 0), True),  # 00:00
        ("America/New_York", _utc(8, 59), True),  # 04:59
        ("America/New_York", _utc(9, 0), False),  # 05:00
        # The same instants read in the other zone.
        ("America/New_York", _utc(16, 0), False),  # 12:00 in New York
        ("Asia/Shanghai", _utc(4, 0), False),  # 12:00 in Shanghai
    ],
)
def test_late_night_is_read_in_the_profile_timezone(tz: str, moment: datetime, late: bool) -> None:
    assert _wb(tz).is_late_night(moment) is late


def test_late_night_does_not_depend_on_the_clocks_own_offset() -> None:
    shanghai_midnight = _utc(16, 0)
    as_new_york = shanghai_midnight.astimezone(ZoneInfo("America/New_York"))
    assert _wb().is_late_night(as_new_york)


@pytest.mark.parametrize("tz", ["Not/AZone", "", None])
def test_unknown_timezone_falls_back_to_the_session_clock(tz: str | None) -> None:
    wb = Wellbeing(TAX, tz, START)
    assert wb.is_late_night(_utc(1, 0))
    assert not wb.is_late_night(_utc(12, 0))


def test_started_at_must_be_timezone_aware() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        Wellbeing(TAX, "Asia/Shanghai", datetime(2026, 10, 22, 14, 0))


def test_late_night_is_shown_once_per_session() -> None:
    wb = _wb(start=_utc(15, 50))
    assert _turn(wb, _utc(16, 1)) is Reminder.LATE_NIGHT
    assert _turn(wb, _utc(16, 3)) is Reminder.NONE
    assert _turn(wb, _utc(16, 5)) is Reminder.NONE


def test_late_night_wins_and_covers_a_due_break() -> None:
    wb = _wb(start=_utc(15, 10))  # 23:10 in Shanghai
    assert _turn(wb, _utc(15, 10)) is Reminder.NONE
    assert _turn(wb, _utc(16, 0)) is Reminder.LATE_NIGHT  # 50 minutes in: both due
    assert _turn(wb, _utc(16, 2)) is Reminder.NONE
    assert _turn(wb, _utc(16, 44)) is Reminder.NONE
    assert _turn(wb, _utc(16, 45)) is Reminder.BREAK


def test_never_two_reminders_in_a_row() -> None:
    wb = _wb(start=_utc(15, 20))  # 23:20 in Shanghai
    assert _turn(wb, _utc(15, 20)) is Reminder.NONE
    assert _turn(wb, _utc(16, 0)) is Reminder.LATE_NIGHT  # 40 minutes: no break yet
    assert _turn(wb, _utc(16, 5)) is Reminder.NONE  # the break is due, but not twice in a row
    assert _turn(wb, _utc(16, 6)) is Reminder.BREAK


def test_a_reminder_not_shown_is_not_recorded() -> None:
    wb = _wb(start=_utc(15, 50))
    wb.record(_utc(16, 1), Reminder.NONE, support=False)
    assert wb.due(_utc(16, 2)) is Reminder.LATE_NIGHT


def test_real_support_share_and_cadence() -> None:
    wb = _wb()
    due: list[int] = []
    for turn in range(1, 21):
        support = wb.support_due()
        if support:
            due.append(turn)
        wb.record(START, Reminder.NONE, support=support)
        if turn >= 3:
            assert wb.real_support_share >= 0.15
    assert due == [3, 7, 14]
    assert wb.real_support_share == pytest.approx(3 / 20)


def test_real_support_share_is_zero_before_any_turn() -> None:
    assert _wb().real_support_share == 0.0


def test_pick_rotates_and_skips_unusable_variants() -> None:
    wb = _wb()
    variants = ("a", "b", "c")
    assert wb.pick("g", variants, lambda v: v) == "a"
    assert wb.pick("g", variants, lambda v: None if v == "b" else v.upper()) == "C"
    assert wb.pick("g", variants, lambda v: v) == "a"
    assert wb.pick("other", variants, lambda v: v) == "a"
    assert wb.pick("g", variants, lambda v: None) is None
