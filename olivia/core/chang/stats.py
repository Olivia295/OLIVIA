"""Local usage numbers: ``olivia stats`` (step F12; PRD §11.1, NG-4, RSK-07).

Numbers only, computed on demand from the ledger's session summaries and never stored
anywhere else; no conversation text, no names, no spectra or exercise titles:

* **sessions**: summary entries in all, in the last 7 and in the last 30 days (by start
  time; the same "session" as the weekly journal's count);
* **late night**: sessions with a turn in the B7 late-night window (taxonomy
  ``late_night``, 00:00-05:00 in the profile's timezone), over the sessions that recorded
  it;
* **real-world support**: replies that carried real-world support guidance (B7), over all
  recorded turns (PRD §11.1 asks for >= 15%);
* **self-rating change**: the mean of after - before over the sessions with both 0-10
  self-ratings (B6; higher is better).

Summaries written before F12 carry no turn, support or late-night counts: they count as
sessions and for the self-ratings, are left out of the two shares, and the line says how
many were left out. Nothing is migrated.

All wording is in ``olivia/data/templates/stats.yaml`` (G-0 draft).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from functools import cache
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Final

import yaml

from olivia.core.memory.ledger import Ledger, LedgerUnavailableError, SessionSummary, SummaryEntry
from olivia.core.yaml_load import safe_load

WEEK: Final = timedelta(days=7)
MONTH: Final = timedelta(days=30)

_FILE: Final = "stats.yaml"
LINE_KEYS: Final = (
    "heading",
    "sessions",
    "late_night",
    "late_night_none",
    "support",
    "support_none",
    "rating",
    "rating_none",
    "unknown",
)
REPLY_KEYS: Final = ("empty", "unavailable", "not_onboarded", "adults_only")

Say = Callable[[str], None]


class StatsTextError(Exception):
    """``stats.yaml`` is missing, malformed or incomplete."""


@dataclass(frozen=True)
class StatsText:
    lines: Mapping[str, str]
    replies: Mapping[str, str]


def load_stats_text(directory: Path | None = None) -> StatsText:
    """Load and validate ``stats.yaml``; ``None`` reads the packaged copy (cached)."""
    if directory is None:
        return _packaged_text()
    return _load_text(directory)


@cache
def _packaged_text() -> StatsText:
    return _load_text(resources.files("olivia").joinpath("data/templates"))


def _strings(value: object, keys: tuple[str, ...], where: str) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != set(keys):
        raise StatsTextError(f"{_FILE}: {where} must have exactly {list(keys)}")
    out: dict[str, str] = {}
    for key in keys:
        item = value[key]
        if not isinstance(item, str) or not item.strip():
            raise StatsTextError(f"{_FILE}: {where}.{key} must be a non-empty string")
        out[key] = item
    return out


def _load_text(base: Traversable | Path) -> StatsText:
    try:
        doc = safe_load(base.joinpath(_FILE).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise StatsTextError(f"{_FILE}: cannot read: {exc}") from exc
    expected = {"version", "lines", "replies"}
    if not isinstance(doc, dict) or doc.get("version") != 1 or set(doc) != expected:
        raise StatsTextError(f"{_FILE}: must be version 1 with sections {sorted(expected)}")
    return StatsText(
        lines=_strings(doc["lines"], LINE_KEYS, "lines"),
        replies=_strings(doc["replies"], REPLY_KEYS, "replies"),
    )


# -- the numbers -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Stats:
    sessions: int
    last_week: int
    last_month: int
    late_night: int
    """Sessions with a turn in the late-night window, among :attr:`counted`."""
    counted: int
    """Sessions that recorded turns, support and late night (written from F12 on)."""
    support_turns: int
    turns: int
    rated: int
    """Sessions with both self-ratings."""
    rating_change: float | None
    """Mean of after - before over :attr:`rated`; None when there are none."""

    @property
    def uncounted(self) -> int:
        """Sessions from before F12, left out of the late-night and support shares."""
        return self.sessions - self.counted


def compute(summaries: Iterable[SessionSummary], now: datetime) -> Stats:
    """The numbers for ``summaries`` as of ``now`` (timezone-aware)."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    items = tuple(summaries)
    with_counts = [s for s in items if s.has_metrics]
    changes = [
        s.self_rating_after - s.self_rating_before
        for s in items
        if s.self_rating_before is not None and s.self_rating_after is not None
    ]
    return Stats(
        sessions=len(items),
        last_week=sum(1 for s in items if s.started_at >= now - WEEK),
        last_month=sum(1 for s in items if s.started_at >= now - MONTH),
        late_night=sum(1 for s in with_counts if s.late_night),
        counted=len(with_counts),
        support_turns=sum(s.real_support_turns or 0 for s in with_counts),
        turns=sum(s.turns or 0 for s in with_counts),
        rated=len(changes),
        rating_change=sum(changes) / len(changes) if changes else None,
    )


def _percent(part: int, whole: int) -> int:
    return round(100 * part / whole)


def _signed(value: float) -> str:
    shown = f"{value:+.1f}"
    return "0.0" if shown in ("+0.0", "-0.0") else shown


def render(stats: Stats, text: StatsText, window: tuple[time, time]) -> str:
    """The ``olivia stats`` lines for ``stats`` (which must hold at least one session)."""
    if not stats.sessions:
        raise ValueError("the numbers need at least one session")
    words = text.lines
    start, end = (t.strftime("%H:%M") for t in window)
    unknown = words["unknown"].format(count=stats.uncounted) if stats.uncounted else ""
    lines = [
        words["heading"],
        words["sessions"].format(
            total=stats.sessions, week=stats.last_week, month=stats.last_month
        ),
    ]
    if stats.counted:
        late = words["late_night"].format(
            start=start,
            end=end,
            count=stats.late_night,
            known=stats.counted,
            percent=_percent(stats.late_night, stats.counted),
        )
    else:
        late = words["late_night_none"].format(start=start, end=end)
    lines.append(late + unknown)
    if stats.turns:
        support = words["support"].format(
            count=stats.support_turns,
            turns=stats.turns,
            percent=_percent(stats.support_turns, stats.turns),
        )
    else:
        support = words["support_none"]
    lines.append(support + unknown)
    if stats.rating_change is not None:
        lines.append(words["rating"].format(change=_signed(stats.rating_change), count=stats.rated))
    else:
        lines.append(words["rating_none"])
    return "\n".join(lines)


def run_command(
    say: Say,
    ledger: Ledger,
    now: datetime,
    window: tuple[time, time],
    *,
    text: StatsText | None = None,
) -> int:
    """``olivia stats``: print the numbers; the exit status (1: the ledger is unavailable)."""
    words = load_stats_text() if text is None else text
    try:
        if not ledger.available():
            raise LedgerUnavailableError("the keychain is unavailable", permanent=False)
        entries = ledger.entries()
    except LedgerUnavailableError:
        say(words.replies["unavailable"])
        return 1
    summaries = [e.summary for e in entries if isinstance(e, SummaryEntry)]
    if not summaries:
        say(words.replies["empty"])
        return 0
    say(render(compute(summaries, now), words, window))
    return 0
