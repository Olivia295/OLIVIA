"""Bringing back a note in the conversation (PRD MIYI-04, SDD §3.3; step F15).

When the user asks about something they had OLIVIA remember ("我上次让你记住什么了",
"周四要见的那个人是谁来着"), :func:`recall_note` picks the note to mention. Only notes are
candidates, never session summaries: the user asks about what they asked to keep, and a
summary is OLIVIA's own templated record (stage path, spectra, cards, the crisis line).
Among notes the SDD §3.3 weighted sum (``retrieval.MemoryIndex``) ranks as usual; every
note is significant and permanently protected, so the recency and salience terms are the
same for all of them and the order is similarity first, then newest first.

The question is first stripped of its own wording and particles (``memory.yaml``
``recall_ignore``: "让你记住", "来着", "是谁", "的"...), the removed words leaving a gap so
no n-gram spans them, and folded like the safety screen (NFKC, case, Traditional to
Simplified); the notes are folded the same way for the index only. Then:

* nothing left (a general question, "我上次让你记住什么了"): the newest note, ``LATEST``;
* something left that a note shares an n-gram with: the best such note, ``FOUND``;
* something left that no note shares: ``NO_MATCH``, no note at all.

No notes: ``NONE``. One note at most is ever returned, so an unrelated one is never read
back alongside it. Nothing here reads the ledger, writes or logs: the caller passes the
notes and shows the note in the turn's reply only.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from olivia.core.memory.ledger import NoteEntry
from olivia.core.memory.retrieval import MemoryIndex, char_ngrams
from olivia.core.safety.normalize import normalize


class RecallOutcome(StrEnum):
    """What a recall found (``inspect["note_recall_result"]``; no text)."""

    FOUND = "found"
    LATEST = "latest"
    NO_MATCH = "no_match"
    NONE = "none"
    UNAVAILABLE = "unavailable"
    """The ledger cannot be read on this device now (no keychain, or it is locked)."""


@dataclass(frozen=True)
class Recall:
    outcome: RecallOutcome
    note: NoteEntry | None = None
    """The note to mention: set exactly for ``FOUND`` and ``LATEST``."""


def query_terms(question: str, ignore: Sequence[str]) -> str:
    """``question`` folded, with every ``ignore`` word (longest first) cut out as a gap."""
    folded = normalize(question)
    for word in ignore:
        folded = folded.replace(word, " ")
    return folded


def recall_note(
    question: str, notes: Sequence[NoteEntry], now: datetime, ignore: Sequence[str]
) -> Recall:
    """The note ``question`` asks about, if any; see the module docstring."""
    if not notes:
        return Recall(RecallOutcome.NONE)
    by_id = {note.entry_id: note for note in notes}
    index = MemoryIndex(replace(note, text=normalize(note.text)) for note in notes)
    terms = query_terms(question, ignore)
    general = not char_ngrams(terms)
    ((best, _score),) = index.rank("" if general else terms, now, k=1)
    if general:
        return Recall(RecallOutcome.LATEST, by_id[best.entry_id])
    position = next(i for i, e in enumerate(index.entries) if e.entry_id == best.entry_id)
    if index.similarities(terms)[position] <= 0.0:
        return Recall(RecallOutcome.NO_MATCH)
    return Recall(RecallOutcome.FOUND, by_id[best.entry_id])


__all__ = ["Recall", "RecallOutcome", "query_terms", "recall_note"]
