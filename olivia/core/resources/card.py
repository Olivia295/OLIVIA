"""The resolved crisis-resource card (SDD section 2.5)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from olivia.core.models import CrisisLevel
from olivia.core.resources.store import EmergencyNumber, HotlineEntry, LineKind


class CardMode(StrEnum):
    CRISIS = "crisis"
    """L2/L3 crisis card: only the entries for that level, in priority (file) order."""
    BROWSING = "browsing"
    """``olivia resources``: every entry for the region, lines grouped by kind."""


@dataclass(frozen=True)
class ResourceCard:
    region_used: str
    """Region whose entries are shown: a supported country code, or ``ZZ``."""
    level: CrisisLevel
    mode: CardMode
    emergency: tuple[EmergencyNumber, ...]
    """Emergency numbers; they render before ``lines`` unless ``emergency_leads`` is False."""
    lines: tuple[HotlineEntry, ...]
    stale_entries: tuple[str, ...]
    """Ids of shown entries verified more than 180 days ago ("可能已过期")."""
    compiled_on: date
    directory_version: int
    emergency_leads: bool = True
    """Whether ``emergency`` renders before ``lines``. False on an L2 crisis card with a line
    to call, whose one local emergency number follows the hotlines (owner decisions
    2026-10-28 and 2026-11-25: CN 120, HK 999, ...); True for every other card."""
    here: ResourceCard | None = None
    """Owner decision 2026-11-25 B: the card of the region where the user said in this
    session they are now, when it is not ``region_used``; it renders before this card's
    entries, which follow it. Never a mainland card unless the user named mainland China."""
    here_note: str = ""
    """Owner decision 2026-11-25 B: for a country the user said they are in that has no
    verified lines here, its official emergency numbers as ``crisis.local_emergency`` gives
    them ("日本：报警 110，消防与急救 119"); it renders first."""
    here_numbers: tuple[str, ...] = ()
    """The numbers in ``here_note``, which the output gate allows with the card's."""

    @property
    def stale(self) -> bool:
        return bool(self.stale_entries)

    def numbers(self) -> tuple[str, ...]:
        """Every number the card shows, where the user said they are first: the note's,
        then the ``here`` card's, then this card's emergency numbers and lines."""
        here = () if self.here is None else self.here.numbers()
        own = (*(e.number for e in self.emergency), *(ln.number for ln in self.lines))
        return (*self.here_numbers, *here, *own)

    def lines_by_kind(self) -> tuple[tuple[LineKind, tuple[HotlineEntry, ...]], ...]:
        """Lines grouped by kind in :class:`LineKind` order, empty groups omitted."""
        groups = ((kind, tuple(ln for ln in self.lines if ln.kind is kind)) for kind in LineKind)
        return tuple((kind, group) for kind, group in groups if group)
