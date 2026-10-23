"""Anti-dependence prompts in the session (next-phase B7, PRD NG-4 / RSK-07 / §11.1, D5).

The clock is injected: 45 minutes of session time bring one break paragraph on the next
ordinary reply, late night (00:00-05:00 in the profile timezone) brings one care line per
session, and real-support questions keep their share of replies at or above 15%. None of
them appears on a crisis turn or in place of a card.
"""

from __future__ import annotations

import random
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from olivia.core.language.data import load_language_data
from olivia.core.models import HelpStage, PersonaProfile, UserRegion
from olivia.core.session import ReplyKind, Session, TurnResult
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
TEMPLATES = load_language_data(TAX).templates
# 14:00 UTC: 22:00 in Shanghai, 10:00 in New York. Not late night.
DAY = datetime(2026, 10, 22, 14, 0, tzinfo=UTC)
# 16:00 UTC: 00:00 in Shanghai, 12:00 in New York.
SHANGHAI_MIDNIGHT = datetime(2026, 10, 22, 16, 0, tzinfo=UTC)
NAME = "小林"
CALM = (
    "今天上班好累",
    "最近和室友有点小矛盾",
    "工作上的事情让我有点烦",
    "回家以后也提不起劲",
    "周末也不太想出门",
    "感觉自己一直在硬撑",
    "说不上来哪里不对劲",
    "就是心里有点堵",
)


class Clock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now


def _open(clock: Clock, tz: str = "Asia/Shanghai", seed: int = 7, **overrides: object) -> Session:
    profile = replace(
        PersonaProfile(
            age_confirmed_18_plus=True,
            created_at=DAY,
            updated_at=DAY,
            user_name=NAME,
            region=UserRegion("CN", tz),
        ),
        **overrides,
    )
    return Session.open(TAX, profile, rng=random.Random(seed), now=clock, student=False)


def _filled(variants: tuple[str, ...]) -> set[str]:
    return {v.replace("{user_name}", NAME) for v in variants}


BREAK = _filled(TEMPLATES.break_reminder)
BREAK_HAVEN = _filled(TEMPLATES.break_reminder_haven)
LATE = _filled(TEMPLATES.late_night)
LATE_HAVEN = _filled(TEMPLATES.late_night_haven)
SUPPORT = _filled(TEMPLATES.real_support)
EVERY_LINE = BREAK | BREAK_HAVEN | LATE | LATE_HAVEN | SUPPORT


def _last(result: TurnResult) -> str:
    return result.reply.split("\n\n")[-1]


def _no_reminder(result: TurnResult) -> None:
    assert result.inspect["reminder"] == "none"
    assert not any(line in result.reply for line in BREAK | BREAK_HAVEN | LATE | LATE_HAVEN)


# -- 45-minute break ------------------------------------------------------------------------


def test_break_reminder_at_45_minutes_not_before() -> None:
    clock = Clock(DAY)
    session = _open(clock)
    _no_reminder(session.turn(CALM[0]))
    clock.now = DAY + timedelta(minutes=44, seconds=59)
    _no_reminder(session.turn(CALM[1]))
    clock.now = DAY + timedelta(minutes=45)
    result = session.turn(CALM[2])
    assert result.inspect["reminder"] == "break"
    assert result.reply_kind is ReplyKind.NORMAL
    assert _last(result) in BREAK
    assert sum(line in result.reply for line in EVERY_LINE) == 1


def test_break_repeats_after_another_45_minutes_and_never_twice_in_a_row() -> None:
    clock = Clock(DAY)
    # 10:00 in New York, so the whole run stays clear of late night.
    session = _open(clock, tz="America/New_York")
    session.turn(CALM[0])
    clock.now = DAY + timedelta(minutes=45)
    assert session.turn(CALM[1]).inspect["reminder"] == "break"
    clock.now = DAY + timedelta(minutes=46)
    _no_reminder(session.turn(CALM[2]))
    clock.now = DAY + timedelta(minutes=89, seconds=59)
    _no_reminder(session.turn(CALM[3]))
    clock.now = DAY + timedelta(minutes=90)
    result = session.turn(CALM[4])
    assert result.inspect["reminder"] == "break"
    assert _last(result) in BREAK
    clock.now = DAY + timedelta(minutes=200)
    # Overdue again, but the reply right after a reminder never carries another one.
    _no_reminder(session.turn(CALM[5]))
    assert session.turn(CALM[6]).inspect["reminder"] == "break"


def test_break_never_lands_on_a_crisis_turn_and_waits() -> None:
    clock = Clock(DAY)
    session = _open(clock)
    session.turn(CALM[0])
    clock.now = DAY + timedelta(minutes=45)
    result = session.turn("我不想活了")
    assert result.reply_kind is ReplyKind.CRISIS
    _no_reminder(result)


def test_break_never_lands_on_an_l1_screen() -> None:
    clock = Clock(DAY)
    session = _open(clock)
    session.turn(CALM[0])
    clock.now = DAY + timedelta(minutes=45)
    result = session.turn("我想消失")
    assert result.inspect["assessed_level"] == "L1"
    _no_reminder(result)


def test_break_never_replaces_a_card_and_comes_with_the_next_ordinary_reply() -> None:
    clock = Clock(DAY)
    session = _open(clock)
    session.turn("最近工作压力很大，有点焦虑，晚上总睡不着")
    clock.now = DAY + timedelta(minutes=45)
    card = session.turn("给我一个方法")
    assert card.reply_kind is ReplyKind.CARD
    assert card.action_id is not None
    _no_reminder(card)
    clock.now = DAY + timedelta(minutes=46)
    after = session.turn("/done")
    assert after.stage is HelpStage.S_CLOSING
    assert after.inspect["reminder"] == "break"
    assert _last(after) in BREAK


def test_break_in_haven_is_the_softer_line_alone() -> None:
    clock = Clock(DAY)
    session = _open(clock)
    session.turn(CALM[0])
    clock.now = DAY + timedelta(minutes=45)
    result = session.turn("[5%] 好累，今天不想动脑，只想躺着")
    assert result.stage is HelpStage.S_HAVEN
    assert result.reply_kind is ReplyKind.HAVEN
    assert result.inspect["reminder"] == "break"
    assert result.reply in BREAK_HAVEN


# -- late night -----------------------------------------------------------------------------


def test_late_night_line_once_per_session_in_shanghai() -> None:
    clock = Clock(SHANGHAI_MIDNIGHT)
    session = _open(clock)
    first = session.turn(CALM[0])
    assert first.inspect["reminder"] == "late_night"
    assert _last(first) in LATE
    for text in CALM[1:5]:
        clock.now += timedelta(minutes=5)
        _no_reminder(session.turn(text))


def test_the_same_instant_is_midday_in_new_york() -> None:
    _no_reminder(_open(Clock(SHANGHAI_MIDNIGHT), tz="America/New_York").turn(CALM[0]))


def test_late_night_edges_in_the_profile_timezone() -> None:
    def reminder(moment: datetime, tz: str) -> object:
        return _open(Clock(moment), tz=tz).turn(CALM[0]).inspect["reminder"]

    utc = SHANGHAI_MIDNIGHT
    assert reminder(utc - timedelta(minutes=1), "Asia/Shanghai") == "none"  # 23:59
    assert reminder(utc, "Asia/Shanghai") == "late_night"  # 00:00
    assert reminder(utc + timedelta(hours=4, minutes=59), "Asia/Shanghai") == "late_night"
    assert reminder(utc + timedelta(hours=5), "Asia/Shanghai") == "none"  # 05:00
    ny_midnight = datetime(2026, 10, 22, 4, 0, tzinfo=UTC)  # EDT, UTC-4
    assert reminder(ny_midnight - timedelta(minutes=1), "America/New_York") == "none"
    assert reminder(ny_midnight, "America/New_York") == "late_night"
    assert reminder(ny_midnight + timedelta(hours=4, minutes=59), "America/New_York") == (
        "late_night"
    )
    assert reminder(ny_midnight + timedelta(hours=5), "America/New_York") == "none"


def test_late_night_never_on_a_crisis_turn() -> None:
    clock = Clock(SHANGHAI_MIDNIGHT)
    result = _open(clock).turn("我不想活了")
    assert result.reply_kind is ReplyKind.CRISIS
    _no_reminder(result)
    assert not any(line in result.reply for line in SUPPORT)


def test_late_night_in_haven_is_the_softer_line_alone() -> None:
    result = _open(Clock(SHANGHAI_MIDNIGHT)).turn("[5%] 好累，今天不想动脑，只想躺着")
    assert result.stage is HelpStage.S_HAVEN
    assert result.reply_kind is ReplyKind.HAVEN
    assert result.inspect["reminder"] == "late_night"
    assert result.reply in LATE_HAVEN
    # The haven line is rest only: it does not count as real-support guidance.
    assert result.inspect["real_support_share"] == 0.0


def test_late_night_line_counts_as_real_support() -> None:
    result = _open(Clock(SHANGHAI_MIDNIGHT)).turn(CALM[0])
    assert result.inspect["reminder"] == "late_night"
    assert result.inspect["real_support_share"] == 1.0


# -- real-world support share ---------------------------------------------------------------


def _calm_session(seed: int = 7, **overrides: object) -> list[TurnResult]:
    clock = Clock(DAY)
    session = _open(clock, seed=seed, **overrides)
    return [session.turn(text) for text in CALM]


def test_real_support_question_replaces_the_invite_and_keeps_its_share() -> None:
    for seed in (3, 7, 11):
        results = _calm_session(seed)
        shown = [i for i, r in enumerate(results, 1) if _last(r) in SUPPORT]
        assert shown, seed
        assert shown[0] == 3, seed
        for turn, result in enumerate(results, 1):
            assert result.inspect["reminder"] == "none"
            share = result.inspect["real_support_share"]
            assert isinstance(share, float)
            if turn >= 3:
                assert share >= 0.15, (seed, turn)
            if _last(result) in SUPPORT:
                assert result.stage in (HelpStage.S_EXPLORE, HelpStage.S_CLARIFY)
                assert result.reply_kind is ReplyKind.NORMAL
                assert len(result.reply.split("\n\n")) == 3
                assert result.reply.count("？") == 1


def test_real_support_avoids_taboo_topics() -> None:
    results = _calm_session(taboo_topics=("家人",))
    lines = [_last(r) for r in results if _last(r) in SUPPORT]
    assert lines
    assert all("家人" not in line for line in lines)


def test_no_real_support_question_while_the_listening_lock_is_on() -> None:
    clock = Clock(DAY)
    session = _open(clock)
    session.turn(CALM[0])
    locked = session.turn("你听我说就好，不用给建议")
    assert locked.inspect["lock"] is True
    for text in CALM[1:6]:
        result = session.turn(text)
        if result.inspect["lock"]:
            assert _last(result) not in SUPPORT


def test_inspect_holds_no_prompt_text() -> None:
    result = _open(Clock(SHANGHAI_MIDNIGHT)).turn(CALM[0])
    assert set(result.inspect) >= {"reminder", "real_support_share"}
    assert result.inspect["reminder"] in ("none", "break", "late_night")
    for value in result.inspect.values():
        if isinstance(value, str):
            assert value not in EVERY_LINE
