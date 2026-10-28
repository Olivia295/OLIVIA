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
    """Whether ``emergency`` renders before ``lines``. True for every card but the mainland
    L2 crisis card, whose 120 follows 12356 (owner decision 2026-10-28)."""

    @property
    def stale(self) -> bool:
        return bool(self.stale_entries)

    def lines_by_kind(self) -> tuple[tuple[LineKind, tuple[HotlineEntry, ...]], ...]:
        """Lines grouped by kind in :class:`LineKind` order, empty groups omitted."""
        groups = ((kind, tuple(ln for ln in self.lines if ln.kind is kind)) for kind in LineKind)
        return tuple((kind, group) for kind, group in groups if group)
