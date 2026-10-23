"""Session summaries and note capture at the session boundary (decision D1, step B2).

A :class:`SessionRecorder` sits beside a :class:`~olivia.core.session.Session`: the caller
hands it every message and the ``TurnResult`` the session returned for it. It never sees
or keeps anything but the result's ids, levels and stages, plus the one thing the user
explicitly asks to have remembered:

* **Notes.** A message that starts with a note cue (``notes.py``) has the text after the
  cue stored verbatim, and a short confirmation is appended to the reply. Crisis handling
  wins: no note on a turn in the crisis flow, a turn the screen rated L1 or above (the
  same caution as for everyday phrases, roadmap R-7b), or the direct question about
  intent (D3); the reply then stays exactly as the session wrote it.
* **Summaries.** Per session: the stage path, the dominant spectra, each exercise card
  shown with its feedback, the crisis flag and level, and first/last turn times. The
  summary is written when the session closes, either through the state machine
  (S_closing -> S_ready; the conversation may go on, and what follows is a new summary)
  or by :meth:`SessionRecorder.close` (``/exit``, end of input, Ctrl-C). Writing is
  keyed by session and segment, and a segment with no turns writes nothing, so closing
  twice, or closing right after S_ready, adds no entry.

Without a usable keychain nothing is recorded; a note request gets a line saying memory
is not available on this device.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Final
from uuid import UUID

from olivia.core.memory.ledger import (
    NOTE_MAX_CHARS,
    Ledger,
    LedgerUnavailableError,
    MethodRecord,
    SessionSummary,
)
from olivia.core.memory.notes import NoteCues, load_note_cues
from olivia.core.memory.text import MemoryText
from olivia.core.methods.bandit import Feedback
from olivia.core.models import CrisisLevel, HelpStage
from olivia.core.session import ReplyKind, TurnResult

MAX_SPECTRA: Final = 3
MAX_STAGE_PATH: Final = 64
_NO_NOTE_KINDS: Final = frozenset({ReplyKind.CRISIS, ReplyKind.SAFETY_CHECK})


@dataclass
class _Segment:
    """What one session (or one segment after S_ready) has shown so far."""

    started_at: datetime | None = None
    ended_at: datetime | None = None
    stage_path: list[HelpStage] = field(default_factory=list)
    spectra: Counter[str] = field(default_factory=Counter)
    methods: list[MethodRecord] = field(default_factory=list)
    crisis_level: CrisisLevel | None = None

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

    def observe(self, message: str, result: TurnResult) -> TurnResult:
        """Record one turn; returns ``result``, with a note confirmation if one was asked."""
        now = self._now()
        if self.enabled:
            self._track(result, now)
        note = self._cues.find(message)
        reply = None
        if note is not None and self._may_note(result):
            reply = self._take_note(note, now)
        if self.enabled and self._closed_by_state_machine(result):
            self._flush()
        if reply is None:
            return result
        return replace(result, reply=f"{result.reply}\n\n{reply}")

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
        segment.ended_at = now
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
    def _may_note(result: TurnResult) -> bool:
        if result.in_crisis or result.reply_kind in _NO_NOTE_KINDS:
            return False
        if result.crisis_level >= CrisisLevel.L1:
            return False
        return _level(result.inspect.get("assessed_level")) < CrisisLevel.L1

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

    def _flush(self) -> None:
        summary = self._segment.summary()
        if summary is None:
            return
        try:
            self._ledger.append_summary(summary, key=f"{self._session_id}/{self._index}")
        except LedgerUnavailableError:
            self._lost = True
        self._segment = _Segment()
        self._index += 1
