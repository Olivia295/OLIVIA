"""Resolve a user's region and crisis level to a :class:`ResourceCard` (GEO-01..07, R8).

Region: a supported ``UserRegion.country_code`` selects that region; ``None``, ``ZZ``
or any unsupported code (``UK`` included; the code is ``GB``) falls back to ``ZZ``.
Only the selected region's entries are ever shown, so a non-CN user never sees a
mainland entry (R8 / GEO-03). Mainland 12356 routes by caller location, so no
province or city lookup is needed.

A CRISIS card at L3 always leads with the region's emergency numbers; at L2 only when the
region has no L2 line that can be called (ZZ has only directory links), so no crisis card
is ever without a number to call.

Every L2 card with a line to call also lists one local emergency number after its hotlines,
from the same signed data: ``ResourceCard.emergency_leads`` is False, so the region's first
hotline stays the first number and the emergency number follows under the L2 card's gentler
emergency heading. The mainland card lists its ambulance number (owner decision 2026-10-28,
beyond PRD GEO-02's 12356: 120, never the police number 110); Hong Kong, Macau, the US,
Canada, Great Britain and Australia list the number for police, fire and ambulance, Taiwan
its fire and ambulance number (owner decision 2026-11-25: HK 999, MO 999 without the 110
and 112 that reach it, TW 119 without 110, US 911, CA 911, GB 999, AU 000). ZZ's L2 card
already leads with 112 and is unchanged.
"""

from __future__ import annotations

from datetime import date
from typing import Final

from olivia.core.models import UNKNOWN_COUNTRY, CrisisLevel, UserRegion
from olivia.core.resources.card import CardMode, ResourceCard
from olivia.core.resources.store import (
    EmergencyNumber,
    EmergencyPurpose,
    HotlineEntry,
    LineKind,
    RegionResources,
    ResourceStore,
)

STALE_AFTER_DAYS: Final = 180
# Owner decisions 2026-10-28 (CN) and 2026-11-25 (the rest): the emergency purpose an L2 crisis
# card lists after its lines, by region. Only the purpose is named here; the number is the
# region's first emergency entry with that purpose in the signed data, so Macau's 999 is
# listed and the 110 and 112 that reach it (the same purpose, later in the file) are not.
L2_EMERGENCY_AFTER_LINES: Final[dict[str, EmergencyPurpose]] = {
    "CN": EmergencyPurpose.AMBULANCE,
    "HK": EmergencyPurpose.POLICE_FIRE_AMBULANCE,
    "MO": EmergencyPurpose.POLICE_FIRE_AMBULANCE,
    "TW": EmergencyPurpose.FIRE_AMBULANCE,
    "US": EmergencyPurpose.POLICE_FIRE_AMBULANCE,
    "CA": EmergencyPurpose.POLICE_FIRE_AMBULANCE,
    "GB": EmergencyPurpose.POLICE_FIRE_AMBULANCE,
    "AU": EmergencyPurpose.POLICE_FIRE_AMBULANCE,
}


def resolve_region_code(store: ResourceStore, region: UserRegion | None) -> str:
    if region is not None and store.has_region(region.country_code):
        return region.country_code
    return UNKNOWN_COUNTRY


def resolve(
    store: ResourceStore,
    region: UserRegion | None,
    level: CrisisLevel,
    *,
    mode: CardMode,
    today: date,
    is_minor: bool = False,
) -> ResourceCard:
    """Build the card for ``region`` at ``level``.

    Minors-only lines (CN 12355) are shown only when ``is_minor`` is true.
    CRISIS mode requires L2 or L3; L0/L1 raise :class:`ValueError`.
    """
    code = resolve_region_code(store, region)
    data = store.region(code)
    lines = tuple(ln for ln in data.lines if is_minor or not ln.minors_only)

    emergency: tuple[EmergencyNumber, ...]
    leads = True
    if mode is CardMode.BROWSING:
        emergency = data.emergency
        lines = tuple(ln for kind in LineKind for ln in lines if ln.kind is kind)
    elif level < CrisisLevel.L2:
        raise ValueError(f"crisis card requires L2 or L3, got {level.name}")
    else:
        emergency, lines = _crisis_entries(data, lines, level)
        added = L2_EMERGENCY_AFTER_LINES.get(code)
        if level is CrisisLevel.L2 and not emergency and added is not None:
            emergency = tuple(e for e in data.emergency if e.purpose is added)[:1]
            leads = False

    shown: tuple[EmergencyNumber | HotlineEntry, ...] = (*emergency, *lines)
    stale = tuple(e.id for e in shown if (today - e.verified_on).days > STALE_AFTER_DAYS)
    return ResourceCard(
        region_used=code,
        level=level,
        mode=mode,
        emergency=emergency,
        lines=lines,
        stale_entries=stale,
        compiled_on=store.compiled_on,
        directory_version=store.version,
        emergency_leads=leads,
    )


def _crisis_entries(
    data: RegionResources, lines: tuple[HotlineEntry, ...], level: CrisisLevel
) -> tuple[tuple[EmergencyNumber, ...], tuple[HotlineEntry, ...]]:
    at_level = tuple(ln for ln in lines if level in ln.levels)
    # L3 always carries emergency numbers; L2 only when the region has no L2 line to call
    # (none at all, or only directory links: ZZ). The crisis wording says "请先拨打下面的电话",
    # and a directory is not a number (QA 2026-10-26 #8).
    if level is CrisisLevel.L3 or all(ln.kind is LineKind.DIRECTORY_URL for ln in at_level):
        return data.emergency, at_level
    return (), at_level
