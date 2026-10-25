"""Active contraindications and situations for the solver (roadmap next-phase A1, D2).

Each of the taxonomy's 13 ``contraindication_enums`` is derived from its
``detection_source``:

==============================  ===========================================================
``CRISIS_ACTIVE_RISK``          the crisis tracker: in a crisis, or the turn's level >= L2.
``RED_FLAG_*``                  the session's active red flags (profile ``clinical_history``
                                codes included), through the red-flag codes the taxonomy
                                names in each source ("RED_FLAG_DETECTOR (SIT-02-04)").
``RED_FLAG_PSYCHOSIS``          its source names no red-flag code: only the profile's
                                ``contraindications`` (third checklist item, onboarding or
                                ``olivia health``). No conversation cue sets it (G-0/G-2).
``ACUTE_AROUSAL_OVERLOAD``      arousal, added by the solver itself
                                (:func:`olivia.core.methods.solver.active_contraindications`).
``TOXIC_SHAME_SPIRAL``          a ``contraindication_cues`` hit (intense self-attack), or the
                                introspector's (C2) schema reading:
                                :func:`olivia.core.perception.introspector.shame_spiral`
                                (``DEFECTIVENESS`` with strong self-blame on the same turn).
``ACUTE_BEREAVEMENT_SHOCK``     the situation code its source names (SIT-06-04 丧亲初期),
                                read from the acute ``situation_cues`` only: a turn whose
                                SIT-06-04 comes from the ``prolonged_grief`` rule alone
                                (``TurnSignals.prolonged_grief``) does not set it (F13,
                                draft pending G-0). Both phases still go to m0.
``CARDIORESPIRATORY_INSTABILITY``,
``INTERPERSONAL_SAFETY_HAZARD``  the profile's ``contraindications`` (onboarding checklist or
                                ``olivia health``), or a ``contraindication_cues`` hit in
                                this session.
==============================  ===========================================================

Situation codes (``situation_cues``: SIT-06-04 bereavement, acute or prolonged (the
stub's ``prolonged_grief`` rule, COLBO-06b), SIT-11-01 extreme meaninglessness) go to the
solver as they are; its m0 rule handles them.

Everything read from the conversation holds for the rest of the session and is never
written to the profile. A profile-type disclosure heard only in the conversation (the
last two rows; psychosis has no cue) is reported once by
:meth:`SessionContraindications.unsaved_disclosures`, so the session can say once that
it can be saved with ``olivia health``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from olivia.core.models import PROFILE_CONTRAINDICATIONS, CrisisLevel, PerceptionContext
from olivia.core.perception.introspector import shame_spiral
from olivia.core.perception.signals import TurnSignals
from olivia.core.safety.tracker import CrisisStatus
from olivia.core.taxonomy import Taxonomy, TaxonomyError

CRISIS_CONTRAINDICATION: Final = "CRISIS_ACTIVE_RISK"
BEREAVEMENT_CONTRAINDICATION: Final = "ACUTE_BEREAVEMENT_SHOCK"
_GRIEF_CODE: Final = "SIT-06-04"
SHAME_CONTRAINDICATION: Final = "TOXIC_SHAME_SPIRAL"
_CODE_RE: Final = re.compile(r"SIT-\d{2}-\d{2}")


@dataclass(frozen=True)
class ActiveContext:
    """What the solver gets for one turn, besides arousal, stage and red flags."""

    contraindications: frozenset[str] = frozenset()
    """Derived enum ids; ``ACUTE_AROUSAL_OVERLOAD`` is left to the solver."""
    situations: frozenset[str] = frozenset()


@dataclass(frozen=True)
class SourceLinks:
    """The taxonomy's links from detector codes to contraindication enums."""

    red_flags: Mapping[str, frozenset[str]]
    """Red-flag code -> enum ids whose source names it."""
    situations: Mapping[str, frozenset[str]]
    """Other situation code -> enum ids whose source names it (SIT-06-04 -> bereavement)."""


def source_links(tax: Taxonomy) -> SourceLinks:
    """Parse the codes named in every ``detection_source``; an unknown code raises."""
    flags = frozenset(tax.red_flags())
    known = frozenset(tax.situation_codes())
    by_flag: dict[str, set[str]] = {}
    by_situation: dict[str, set[str]] = {}
    for enum_id, source in tax.contraindication_sources().items():
        for code in _CODE_RE.findall(source):
            if code in flags:
                by_flag.setdefault(code, set()).add(enum_id)
            elif code in known:
                by_situation.setdefault(code, set()).add(enum_id)
            else:
                raise TaxonomyError(f"contraindication {enum_id}: unknown code {code!r}")
    return SourceLinks(
        red_flags=MappingProxyType({k: frozenset(v) for k, v in by_flag.items()}),
        situations=MappingProxyType({k: frozenset(v) for k, v in by_situation.items()}),
    )


class SessionContraindications:
    """Collects one session's contraindications and situations, turn by turn."""

    def __init__(self, tax: Taxonomy, profile_contraindications: tuple[str, ...]) -> None:
        self._links = source_links(tax)
        self._profile = frozenset(profile_contraindications)
        self._heard: set[str] = set()
        self._situations: set[str] = set()
        # Situation codes whose linked enums apply: prolonged grief alone is left out (F13).
        self._linked: set[str] = set()
        self._hinted: set[str] = set()

    def observe(
        self,
        signals: TurnSignals,
        perception: PerceptionContext,
        status: CrisisStatus,
        red_flags: frozenset[str],
    ) -> ActiveContext:
        """Add this turn's cues and return everything active now."""
        self._situations |= signals.situation_codes
        linked = signals.situation_codes
        if signals.prolonged_grief:
            linked = linked - {_GRIEF_CODE}
        self._linked |= linked
        self._heard |= signals.contraindication_cues
        if shame_spiral(perception):
            self._heard.add(SHAME_CONTRAINDICATION)
        active = set(self._profile | self._heard)
        if status.in_crisis or status.level >= CrisisLevel.L2:
            active.add(CRISIS_CONTRAINDICATION)
        for code in red_flags:
            active |= self._links.red_flags.get(code, frozenset())
        for code in self._linked:
            active |= self._links.situations.get(code, frozenset())
        return ActiveContext(frozenset(active), frozenset(self._situations))

    def unsaved_disclosures(self) -> frozenset[str]:
        """Profile-type enums heard in this session, not in the profile, not yet hinted."""
        heard = self._heard & frozenset(PROFILE_CONTRAINDICATIONS)
        return frozenset(heard - self._profile - self._hinted)

    def mark_hinted(self, enum_ids: frozenset[str]) -> None:
        self._hinted |= enum_ids
