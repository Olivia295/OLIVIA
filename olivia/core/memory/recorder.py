"""Session summaries and note capture at the session boundary (decision D1, step B2).

A :class:`SessionRecorder` sits beside a :class:`~olivia.core.session.Session`: the caller
hands it every message and the ``TurnResult`` the session returned for it. It never sees
or keeps anything but the result's ids, levels and stages, plus the one thing the user
explicitly asks to have remembered:

* **Notes.** A message that starts with a note cue (``notes.py``) has the text after the
  cue stored verbatim. An ordinary reply (NORMAL or HAVEN) is replaced by the short
  confirmation and ``note_continue``, a gentle line that keeps the conversation open, so
  the note is never reflected back as a feeling (F3); a reply that carries a card keeps
  it, with the confirmation appended. Crisis handling
  wins: no note on a turn in the crisis flow, a turn the screen rated L1 or above (the
  same caution as for everyday phrases, roadmap R-7b), or the direct question about
  intent (D3); the reply then stays exactly as the session wrote it.
* **Recall** (F15, PRD MIYI-04). On a turn the session passed a note question on
  (``inspect["note_recall"]``, a calm turn only) and that is no note request, the notes
  are looked up (``recall.py``: notes only, never summaries; one note at most) under the
  same crisis rule as notes, except that an L1 counts as calm (F16a: the session passes a
  question on only when the rules rate the turn L0, so that L1 is a model's alone). An
  ``explicit`` question ("我上次让你记住什么了") is always answered: the note, the latest
  one, no match, no notes yet, or memory not available here. A ``question``
  ("……是谁来着") is answered only with a matching note; without a usable keychain it
  gets the not-available line after the session's reply, and otherwise the reply stays
  as the session wrote it. An answer replaces an ordinary (NORMAL or HAVEN) reply,
  followed by ``note_continue``, and follows any other reply.
  The note is in that reply only: ``inspect["note_recall_result"]`` is the outcome id
  (``found``, ``latest``, ``no_match``, ``none``, ``unavailable``), never text.
* **Summaries.** Per session: the stage path, the dominant spectra, each exercise card
  shown with its feedback, the crisis flag and level, first/last turn times and (step
  F12) the turn count, how many replies carried real-world support guidance
  (``inspect["real_support"]``) and whether any turn fell in the late-night window
  (``inspect["late_night"]``); a turn without those keys counts as neither. The
  battery figures for the journal (CHANG-04): whether a turn gave a ``[NN%]`` prefix
  (``inspect["battery_prefix"]``), the lowest such reading rounded to 0.05, and whether
  a turn was in S_haven. The
  summary is written when the session closes, either through the state machine
  (S_closing -> S_ready; the conversation may go on, and what follows is a new summary)
  or by :meth:`SessionRecorder.close` (``/exit``, end of input, Ctrl-C). Writing is
  keyed by session and segment, and a segment with no turns writes nothing, so closing
  twice, or closing right after S_ready, adds no entry.

* **Self-ratings** (step B6). :meth:`SessionRecorder.rate_before` puts the opening 0-10
  rating on the session's first segment; :meth:`SessionRecorder.rate_after` puts the
  closing one on the segment still open (``/exit``), or rewrites the summary the state
  machine has just written (S_closing -> S_ready), under the same key. When and whether
  to ask is the caller's business (``chang/journal.py``).

Without a usable keychain nothing is recorded; a note request gets a line saying memory
is not available on this device.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Final
from uuid import UUID

from olivia.core.memory.ledger import (
    NOTE_MAX_CHARS,
    SELF_RATING_RANGE,
    Ledger,
    LedgerUnavailableError,
    MethodRecord,
    SessionSummary,
    round_battery,
)
from olivia.core.memory.notes import NoteCues, load_note_cues
from olivia.core.memory.recall import Recall, RecallOutcome, recall_note
from olivia.core.memory.text import RECALL_SLOT, MemoryText
from olivia.core.methods.bandit import Feedback
from olivia.core.models import CrisisLevel, HelpStage
from olivia.core.perception.signals import NoteRecall
from olivia.core.session import ReplyKind, TurnResult

MAX_SPECTRA: Final = 3
MAX_STAGE_PATH: Final = 64
# A resource reply (2026-10-26) keeps no note either: after a user says they are under 18
# nothing they say is kept ("记住：我才14岁"), and a hotline request is no note.
_NO_NOTE_KINDS: Final = frozenset({ReplyKind.CRISIS, ReplyKind.SAFETY_CHECK, ReplyKind.RESOURCES})
# Replies a note turn replaces with its confirmation (F3); any other kind keeps its card.
_NOTE_ONLY_KINDS: Final = frozenset({ReplyKind.NORMAL, ReplyKind.HAVEN})


@dataclass
class _Segment:
    """What one session (or one segment after S_ready) has shown so far."""

    started_at: datetime | None = None
    ended_at: datetime | None = None
    stage_path: list[HelpStage] = field(default_factory=list)
    spectra: Counter[str] = field(default_factory=Counter)
    methods: list[MethodRecord] = field(default_factory=list)
    crisis_level: CrisisLevel | None = None
    rating_before: int | None = None
    rating_after: int | None = None
    turns: int = 0
    support_turns: int = 0
    late_night: bool = False
    battery_min: float | None = None
    """The lowest ``[NN%]`` reading of the segment; None while no prefix was given."""
    haven: bool = False

    def add_stage(self, stage: HelpStage) -> None:
        if (not self.stage_path or self.stage_path[-1] is not stage) and len(
            self.stage_path
        ) < MAX_STAGE_PATH:
            self.stage_path.append(stage)

    def summary(self) -> SessionSummary | None:
        if self.started_at is None or self.ended_at is None or not self.stage_path:
            return None
        order = list(self.spectra)  # first appearance breaks ties
        ranked = sorted(order, key=lambda sid: (-self.spectra[sid], order.index(sid)))
        return SessionSummary(
            started_at=self.started_at,
            ended_at=self.ended_at,
            stage_path=tuple(self.stage_path),
            spectra=tuple(ranked[:MAX_SPECTRA]),
            methods=tuple(self.methods),
            crisis_level=self.crisis_level,
            self_rating_before=self.rating_before,
            self_rating_after=self.rating_after,
            turns=self.turns,
            real_support_turns=self.support_turns,
            late_night=self.late_night,
            battery_prefix=self.battery_min is not None,
            battery_min=None if self.battery_min is None else round_battery(self.battery_min),
            haven=self.haven,
        )


def _stage(value: object) -> HelpStage | None:
    try:
        return HelpStage(str(value)) if value is not None else None
    except ValueError:
        return None


def _level(value: object) -> CrisisLevel:
    """The screen's level for this turn; an unknown value counts as L3 (fail closed)."""
    try:
        return CrisisLevel[str(value)]
    except KeyError:
        return CrisisLevel.L3


class SessionRecorder:
    """Records one session into ``ledger``; ``now`` is the session's clock."""

    def __init__(
        self,
        ledger: Ledger,
        session_id: UUID,
        now: Callable[[], datetime],
        *,
        cues: NoteCues | None = None,
        text: MemoryText | None = None,
    ) -> None:
        self._ledger = ledger
        self._session_id = session_id
        self._now = now
        self._cues = load_note_cues() if cues is None else cues
        self._text = ledger.text if text is None else text
        self.enabled: bool = ledger.available()
        """False without a usable keychain: nothing is recorded."""
        self._segment = _Segment()
        self._index = 0
        self._lost = False
        self._written: tuple[str, SessionSummary] | None = None
        self.closed_segment: bool = False
        """The last :meth:`observe` wrote a segment's summary (S_closing -> S_ready)."""

    def observe(self, message: str, result: TurnResult) -> TurnResult:
        """Record one turn; returns ``result``, with a note confirmation if one was asked."""
        now = self._now()
        self.closed_segment = False
        if self.enabled:
            self._track(result, now)
        note = self._cues.find(message)
        reply = None
        after = False  # the line follows the session's reply instead of replacing it
        if note is not None and self._may_note(result):
            reply = self._take_note(note, now)
        elif note is None and self._may_recall(result):
            reply, after, result = self._recall(message, result, now)
        if self.enabled and self._closed_by_state_machine(result):
            self.closed_segment = self._flush()
        if reply is None:
            return result
        if result.reply_kind in _NOTE_ONLY_KINDS and not after:
            return replace(result, reply=f"{reply}{self._text.replies['note_continue']}")
        return replace(result, reply=f"{result.reply}\n\n{reply}")

    @property
    def segment_open(self) -> bool:
        """The current segment has turns, so closing now writes a summary."""
        return self._segment.started_at is not None

    def rate_before(self, rating: int) -> None:
        """The opening self-rating (0-10), kept on the session's first segment."""
        _check_rating(rating)
        if self._index == 0:
            self._segment.rating_before = rating

    def rate_after(self, rating: int) -> bool:
        """The closing self-rating (0-10): on the open segment when it has turns, else on
        the summary written last. False if there is nothing to rate or it was not saved."""
        _check_rating(rating)
        if not self.enabled:
            return False
        if self.segment_open:
            self._segment.rating_after = rating
            return True
        if self._written is None:
            return False
        key, summary = self._written
        rated = replace(summary, self_rating_after=rating)
        try:
            self._ledger.append_summary(rated, key=key)
        except LedgerUnavailableError:
            return False
        self._written = (key, rated)
        return True

    def close(self) -> bool:
        """Write the current session's summary, once. False if it could not be saved."""
        if self.enabled:
            self._flush()
        return not self._lost

    # -- internals -------------------------------------------------------------------------

    def _track(self, result: TurnResult, now: datetime) -> None:
        segment = self._segment
        inspect = result.inspect
        if segment.started_at is None:
            segment.started_at = now
            previous = _stage(inspect.get("previous_stage"))
            if previous is not None:
                segment.add_stage(previous)
        # A clock stepped back (NTP, a DST fall-back) never ends a segment before it began
        # or before an earlier turn (robustness D5, D6); times compare in UTC.
        segment.ended_at = _latest(segment.ended_at, segment.started_at, now)
        segment.turns += 1
        if inspect.get("real_support") is True:
            segment.support_turns += 1
        if inspect.get("late_night") is True:
            segment.late_night = True
        reading = inspect.get("battery_prefix")
        if isinstance(reading, int | float) and not isinstance(reading, bool):
            low = segment.battery_min
            segment.battery_min = float(reading) if low is None else min(low, float(reading))
        if result.stage is HelpStage.S_HAVEN:
            segment.haven = True
        if not self._closed_by_state_machine(result):
            segment.add_stage(result.stage)
        spectrum = inspect.get("spectrum")
        if isinstance(spectrum, str):
            segment.spectra[spectrum] += 1
        feedback = inspect.get("feedback")
        if isinstance(feedback, str) and segment.methods:
            # Feedback only ever lands on the card still waiting, the last one shown.
            last = segment.methods[-1]
            if last.feedback is None:
                segment.methods[-1] = replace(last, feedback=Feedback(feedback))
        if result.reply_kind is ReplyKind.CARD and result.action_id is not None:
            segment.methods.append(MethodRecord(result.action_id))
        if result.in_crisis:
            level = max(result.crisis_level, CrisisLevel.L2)
            current = segment.crisis_level
            segment.crisis_level = level if current is None else max(current, level)

    @staticmethod
    def _closed_by_state_machine(result: TurnResult) -> bool:
        previous = _stage(result.inspect.get("previous_stage"))
        return previous is HelpStage.S_CLOSING and result.stage is HelpStage.S_READY

    @staticmethod
    def _may_note(result: TurnResult, below: CrisisLevel = CrisisLevel.L1) -> bool:
        if result.in_crisis or result.reply_kind in _NO_NOTE_KINDS:
            return False
        if result.crisis_level >= below:
            return False
        return _level(result.inspect.get("assessed_level")) < below

    @classmethod
    def _may_recall(cls, result: TurnResult) -> bool:
        """A recall turn may be L1 (F16a): the session passes a note question on only when
        the rules rate the turn L0, so its L1 is one only an injected model gives."""
        return cls._may_note(result, CrisisLevel.L2)

    def _take_note(self, note: str, now: datetime) -> str:
        replies = self._text.replies
        if not self.enabled:
            return replies["note_unavailable"]
        if len(note) > NOTE_MAX_CHARS:
            return replies["note_too_long"]
        try:
            self._ledger.add_note(note, now=now)
        except LedgerUnavailableError:
            return replies["note_unavailable"]
        return replies["note_saved"]

    def _recall(
        self, message: str, result: TurnResult, now: datetime
    ) -> tuple[str | None, bool, TurnResult]:
        """(line, after the reply, result with the outcome id) for a note question."""
        try:
            kind = NoteRecall(str(result.inspect.get("note_recall")))
        except ValueError:
            return None, False, result
        found = self._look_up(message, now)
        explicit = kind is NoteRecall.EXPLICIT
        replies = self._text.replies
        line: str | None = None
        after = False
        if found.note is not None:
            key = "recall_found" if found.outcome is RecallOutcome.FOUND else "recall_latest"
            if explicit or found.outcome is RecallOutcome.FOUND:
                line = replies[key].replace(RECALL_SLOT, found.note.text)
        elif found.outcome is RecallOutcome.UNAVAILABLE:
            line = replies["recall_unavailable"]
            after = not explicit
        elif explicit:
            line = replies[f"recall_{found.outcome.value}"]
        if line is None:
            return None, False, result
        inspect = {**result.inspect, "note_recall_result": found.outcome.value}
        return line, after, replace(result, inspect=inspect)

    def _look_up(self, message: str, now: datetime) -> Recall:
        if not self.enabled:
            return Recall(RecallOutcome.UNAVAILABLE)
        try:
            notes = self._ledger.notes()
        except LedgerUnavailableError:
            return Recall(RecallOutcome.UNAVAILABLE)
        return recall_note(message, notes, now, self._cues.recall_ignore)

    def _flush(self) -> bool:
        """Write the open segment's summary; True when one was written.

        Nothing raised while building or writing it escapes: the session is ending, and
        the CLI says "the summary was not saved" instead of a traceback.
        """
        key = f"{self._session_id}/{self._index}"
        written = False
        try:
            summary = self._segment.summary()
            if summary is None:
                return False
            self._ledger.append_summary(summary, key=key)
            self._written = (key, summary)
            written = True
        except Exception:  # noqa: BLE001 - LedgerUnavailableError and anything unforeseen
            self._lost = True
        self._segment = _Segment()
        self._index += 1
        return written


def _latest(*moments: datetime | None) -> datetime:
    """The latest of ``moments`` (some may be None) in real time, as given."""
    known = [m for m in moments if m is not None]
    return max(known, key=lambda m: m.astimezone(UTC))


def _check_rating(rating: int) -> None:
    if isinstance(rating, bool) or rating not in SELF_RATING_RANGE:
        raise ValueError("self-ratings are 0-10")
