"""In-chat anti-dependence prompts (PRD NG-4, RSK-07, §11.1; next-phase B7, decision D5).

Decision D5 keeps these prompts always on inside the conversation; system notifications
are a separate opt-in (B9). The copy is the ``wellbeing`` section of the persona template
file (G-0 draft). Three prompts:

* Break (§11.1): once the session has run :data:`BREAK_AFTER` of wall-clock time on the
  session clock, the next ordinary reply ends with one ``break_reminder`` paragraph; after
  that at most once per :data:`BREAK_AFTER`, counted from when it was shown.
* Late night (taxonomy ``late_night``, 00:00-05:00, end exclusive, read in the profile's
  IANA timezone; no or an unknown zone falls back to the session clock's own offset): once per
  session, a ``late_night`` paragraph that names the hour, invites rest and someone the
  user trusts. When a break is due on the same reply the late-night line covers it.
* Real-world support (§11.1 share >= 15%): from turn :data:`SUPPORT_FIRST_TURN`, whenever
  the share of replies carrying real-support guidance would drop below
  :data:`SUPPORT_PERCENT`, the next eligible S_explore / S_clarify reply (not while the
  listening lock is on) gets a ``real_support`` question in place of its invite paragraph.
  A late-night line counts too. :attr:`Wellbeing.real_support_share` is that share over
  every turn of the session, crisis turns included.

Where they go: only on an ordinary composed reply (the session decides that: never a
crisis turn or an L1-L3 screen, the D3 safety question, a card, an information card, a
referral-only reply or a short follow-up line). In S_haven the reminders use the softer
``*_haven`` lines, which replace the haven line itself (no question, haven window); the
real-support question never appears there. One prompt per reply at most, and never a
reminder on two turns in a row. Variants rotate in file order, so no prompt draws from
the session's random generator.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time, timedelta, tzinfo
from enum import StrEnum
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from olivia.core.language.data import Templates
from olivia.core.models import HelpStage
from olivia.core.taxonomy import Taxonomy

BREAK_AFTER: Final = timedelta(minutes=45)
SUPPORT_PERCENT: Final = 15
SUPPORT_FIRST_TURN: Final = 3
_SUPPORT_STAGES: Final = frozenset({HelpStage.S_EXPLORE, HelpStage.S_CLARIFY})
_PARAGRAPH: Final = "\n\n"
# S_explore and S_clarify replies are reflect / image-or-need / invite.
_COMPOSED_PARAGRAPHS: Final = 3


class Reminder(StrEnum):
    """``inspect["reminder"]``: which reminder this reply carries."""

    NONE = "none"
    BREAK = "break"
    LATE_NIGHT = "late_night"


@dataclass(frozen=True)
class Prompted:
    reply: str
    reminder: Reminder
    support: bool
    """The reply now carries real-support guidance."""


# Fills one variant's name slots and runs it through WILLOW, the output gate and the
# taboo filter; None when the variant cannot be used.
Render = Callable[[str], str | None]


class Wellbeing:
    """Per-session state for the prompts; call :meth:`prompt` exactly once per turn."""

    def __init__(self, tax: Taxonomy, timezone: str | None, started_at: datetime) -> None:
        if started_at.tzinfo is None or started_at.utcoffset() is None:
            raise ValueError("started_at must be timezone-aware")
        self._night_start, self._night_end = tax.late_night_window()
        self._zone = _zone(timezone)
        self._started = started_at
        self._last_break: datetime | None = None
        self._late_night_shown = False
        self._reminded_last_turn = False
        self._turns = 0
        self._support = 0
        self._rotation: Counter[str] = Counter()

    @property
    def real_support_share(self) -> float:
        return self._support / self._turns if self._turns else 0.0

    def is_late_night(self, now: datetime) -> bool:
        local = now.astimezone(self._zone) if self._zone is not None else now
        clock = time(local.hour, local.minute, local.second, local.microsecond)
        start, end = self._night_start, self._night_end
        if start <= end:
            return start <= clock < end
        return clock >= start or clock < end

    def due(self, now: datetime) -> Reminder:
        """The reminder an eligible reply at ``now`` would carry (no side effects)."""
        if self._reminded_last_turn:
            return Reminder.NONE
        if not self._late_night_shown and self.is_late_night(now):
            return Reminder.LATE_NIGHT
        if self._break_due(now):
            return Reminder.BREAK
        return Reminder.NONE

    def support_due(self) -> bool:
        """Whether the turn about to be recorded should carry real-support guidance."""
        turn = self._turns + 1
        return turn >= SUPPORT_FIRST_TURN and self._support * 100 < SUPPORT_PERCENT * turn

    def record(self, now: datetime, reminder: Reminder, *, support: bool) -> None:
        """Count one turn and what its reply actually carried."""
        self._turns += 1
        if support:
            self._support += 1
        self._reminded_last_turn = reminder is not Reminder.NONE
        if reminder is Reminder.LATE_NIGHT:
            self._late_night_shown = True
            if self._break_due(now):
                self._last_break = now
        elif reminder is Reminder.BREAK:
            self._last_break = now

    def pick(self, group: str, variants: tuple[str, ...], render: Render) -> str | None:
        """The next usable variant of ``group`` in rotation, or None."""
        start = self._rotation[group]
        for offset in range(len(variants)):
            text = render(variants[(start + offset) % len(variants)])
            if text is not None:
                self._rotation[group] = start + offset + 1
                return text
        return None

    def prompt(
        self,
        reply: str,
        *,
        now: datetime,
        stage: HelpStage,
        eligible: bool,
        locked: bool,
        templates: Templates,
        render: Render,
    ) -> Prompted:
        """Add this turn's prompt to ``reply`` (if any) and record the turn.

        ``eligible``: the reply is an ordinary composed reply on a calm turn (see the
        module docstring); a prompt that is due on any other turn waits.
        """
        reminder = self.due(now) if eligible else Reminder.NONE
        support = False
        haven = stage is HelpStage.S_HAVEN
        if reminder is not Reminder.NONE:
            late = reminder is Reminder.LATE_NIGHT
            if haven:
                group = "late_night_haven" if late else "break_reminder_haven"
            else:
                group = "late_night" if late else "break_reminder"
            line = self.pick(group, getattr(templates, group), render)
            if line is None:
                reminder = Reminder.NONE
            elif haven:
                reply = line
            else:
                reply = f"{reply}{_PARAGRAPH}{line}"
                support = late
        elif eligible and stage in _SUPPORT_STAGES and not locked and self.support_due():
            paragraphs = reply.split(_PARAGRAPH)
            if len(paragraphs) == _COMPOSED_PARAGRAPHS:
                line = self.pick("real_support", templates.real_support, render)
                if line is not None:
                    reply = _PARAGRAPH.join([*paragraphs[:-1], line])
                    support = True
        self.record(now, reminder, support=support)
        return Prompted(reply, reminder, support)

    def _break_due(self, now: datetime) -> bool:
        since = self._last_break if self._last_break is not None else self._started
        return now - since >= BREAK_AFTER


def _zone(name: str | None) -> tzinfo | None:
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None
