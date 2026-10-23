"""Action solver: the four-way candidate mask and the only-companionship baseline m0.

The available set follows the taxonomy's ``resolution_priority`` formula (SDD §4.3.7)::

    A_available = (C_candidates ∩ A_allowed) \\ B_banned \\ X_contraindicated

minus the actions the user shelved this session. Every identifier is canonicalized
through the action registry before any set operation, so aliases never produce a
false empty set.

* ``C_candidates`` is the stage's entry pool. ``S_empower`` below the somatic-priority
  arousal threshold and at or above ``battery.thresholds.empower_min`` gets the 32
  Grade A methods (COLBO-07, the right wing). ``S_explore``, ``S_clarify`` and
  ``S_empower`` at or above that arousal threshold, and ``S_empower`` below that
  battery threshold, get only the stabilization whitelist (COLBO-02, the left wing);
  the battery case is reported as ``AllowedSet.battery_gated``. ``S_explore`` and
  ``S_clarify`` below the arousal threshold, and every other stage, get nothing. A pool
  entry that is a method also admits that method's registered sub-actions; each
  sub-action is then filtered on its own.
* ``A_allowed`` is the closed upper bound of the active red flags: the intersection
  of their ``allowed_actions``, or everything when no red flag is active.
* ``B_banned`` is every active red flag's ``banned_methods`` with banned tags expanded
  to method ids. Banning a parent method also bans its sub-actions, unless an active
  red flag's ``allowed_actions`` names the sub-action explicitly (TAX
  ``inheritance_rules.parent_ban_penetration``).
* ``X_contraindicated`` holds every action whose *own* contraindications meet the
  active set. A parent's contraindications never flow down to its sub-actions (TAX
  ``inheritance_rules.contraindication_isolation``). The active set is the caller's
  set plus ``ACUTE_AROUSAL_OVERLOAD``, which this module derives from arousal (see
  :func:`active_contraindications`); the caller derives every other enum.

m0 (``EMOTIONAL_HOLDING_PRESENCE``) never enters the candidate set and is never
sampled. It is chosen by fixed rule: in ``S_haven``, when a prolonged-grief or
extreme-meaninglessness situation is active, or when the mask leaves nothing. Any
active red flag is a mandatory-referral condition (SDD §8.4), so its code is always
reported in ``referral_flags``.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Final

from olivia.core.models import ActionSkeleton, ActionType, HelpStage, SafetyGrade
from olivia.core.taxonomy import Taxonomy, TaxonomyError

M0_ACTION_ID: Final = "EMOTIONAL_HOLDING_PRESENCE"
# COLBO-06 / SDD §4.3.3: prolonged grief and extreme meaninglessness go straight to m0.
M0_SITUATIONS: Final[frozenset[str]] = frozenset({"SIT-06-04", "SIT-11-01"})
OVERLOAD_CONTRAINDICATION: Final = "ACUTE_AROUSAL_OVERLOAD"

_SOMATIC_PRIORITY_KEY: Final = "arousal.thresholds.somatic_priority"
# COLBO-07: the right wing needs Battery >= 0.40 (the key that also gates S_clarify -> S_empower).
_RIGHT_WING_BATTERY_KEY: Final = "battery.thresholds.empower_min"
# The overload enum is defined as "Arousal >= 0.85"; cognitive_block is the TAX key at 0.85.
_OVERLOAD_KEY: Final = "arousal.thresholds.cognitive_block"
_STABILIZATION_STAGES: Final = frozenset(
    {HelpStage.S_EXPLORE, HelpStage.S_CLARIFY, HelpStage.S_EMPOWER}
)


@dataclass(frozen=True)
class SolverInput:
    stage: HelpStage
    arousal: float
    active_red_flags: frozenset[str]  # red-flag codes, e.g. "SIT-09-01"
    active_contraindications: frozenset[str]  # contraindication enum ids derived by the caller
    situation_codes: frozenset[str]  # detected SIT codes, may be empty
    shelved_actions: frozenset[str]  # actions the user shelved this session
    battery: float  # the session's social battery after this turn's update

    def __post_init__(self) -> None:
        if math.isnan(self.arousal) or not 0.0 <= self.arousal <= 1.0:
            raise ValueError(f"arousal must be within [0.0, 1.0], got {self.arousal}")
        if math.isnan(self.battery) or not 0.0 <= self.battery <= 1.0:
            raise ValueError(f"battery must be within [0.0, 1.0], got {self.battery}")


@dataclass(frozen=True)
class AllowedSet:
    candidates: tuple[str, ...]  # canonical ids eligible for sampling, stable order
    use_m0: bool  # True when the fixed m0 rule applies (candidates then empty)
    referral_flags: tuple[str, ...]  # red-flag codes that require a referral card
    # S_empower below the right-wing battery: the pool was cut to the stabilization whitelist.
    battery_gated: bool = False

    def __post_init__(self) -> None:
        if self.use_m0 == bool(self.candidates):
            raise ValueError("use_m0 must be set exactly when there are no candidates")


@dataclass(frozen=True)
class ActionPlan:
    primary: ActionSkeleton
    referral_flags: tuple[str, ...]  # non-empty => render a referral card too


def active_contraindications(tax: Taxonomy, inp: SolverInput) -> frozenset[str]:
    """The caller's contraindications plus ``ACUTE_AROUSAL_OVERLOAD`` at high arousal."""
    derived = {OVERLOAD_CONTRAINDICATION} if inp.arousal >= tax.threshold(_OVERLOAD_KEY) else set()
    return inp.active_contraindications | derived


def allowed_actions(tax: Taxonomy, inp: SolverInput) -> AllowedSet:
    """Solve the available set; raises ``ValueError`` on an unknown flag or enum id."""
    _validate(tax, inp)
    flags = inp.active_red_flags
    referral = tuple(code for code in tax.red_flags() if code in flags)
    if inp.stage is HelpStage.S_HAVEN or inp.situation_codes & M0_SITUATIONS:
        return AllowedSet((), True, referral)

    gated = inp.stage is HelpStage.S_EMPOWER and inp.battery < tax.threshold(
        _RIGHT_WING_BATTERY_KEY
    )
    pool = _stage_pool(tax, inp.stage, inp.arousal, left_wing_only=gated)
    if flags:
        pool &= _red_flag_allowed(tax, flags)
    pool -= banned_actions(tax, flags)
    active = active_contraindications(tax, inp)
    pool = {aid for aid in pool if active.isdisjoint(_own_contraindications(tax, aid))}
    pool -= {tax.canonical_action_id(aid) for aid in inp.shelved_actions}

    candidates = tuple(aid for aid in _ordered_ids(tax) if aid in pool)
    return AllowedSet(candidates, not candidates, referral, battery_gated=gated)


def build_plan(tax: Taxonomy, chosen_id: str | None, allowed: AllowedSet) -> ActionPlan:
    """Assemble the plan for ``chosen_id``, or m0 when the fixed rule or no choice applies.

    Raises ``KeyError`` when ``chosen_id`` is not one of ``allowed.candidates``.
    """
    if allowed.use_m0 or chosen_id is None:
        return ActionPlan(_m0_skeleton(tax), allowed.referral_flags)
    canonical = tax.canonical_action_id(chosen_id)
    if canonical not in allowed.candidates:
        raise KeyError(f"action {chosen_id!r} is not an eligible candidate")
    return ActionPlan(_skeleton(tax, canonical), allowed.referral_flags)


# -- the four masks ----------------------------------------------------------------------


def _validate(tax: Taxonomy, inp: SolverInput) -> None:
    unknown_flags = inp.active_red_flags - frozenset(tax.red_flags())
    if unknown_flags:
        raise ValueError(f"unknown red flag codes: {sorted(unknown_flags)}")
    unknown_enums = inp.active_contraindications - frozenset(tax.values("contraindication_enums"))
    if unknown_enums:
        raise ValueError(f"unknown contraindication ids: {sorted(unknown_enums)}")


def _stage_pool(
    tax: Taxonomy, stage: HelpStage, arousal: float, *, left_wing_only: bool
) -> set[str]:
    """``C_candidates``: the stage's entry pool, with each method's sub-actions."""
    somatic = arousal >= tax.threshold(_SOMATIC_PRIORITY_KEY)
    if stage in _STABILIZATION_STAGES and (somatic or left_wing_only):
        base: Iterable[str] = tax.stabilization_whitelist()
    elif stage is HelpStage.S_EMPOWER:
        base = tax.grade_a_ids()
    else:
        return set()
    children = _children(tax)
    pool: set[str] = set()
    for entry in base:
        aid = tax.canonical_action_id(entry)
        pool.add(aid)
        pool.update(children.get(aid, ()))
    return pool


def _red_flag_allowed(tax: Taxonomy, flags: frozenset[str]) -> set[str]:
    """``A_allowed``: each active flag's allowed actions bound the set, so intersect them."""
    sets = [_canonical(tax, tax.red_flags()[code].allowed_actions) for code in flags]
    return set.intersection(*sets)


def banned_actions(tax: Taxonomy, flags: frozenset[str]) -> frozenset[str]:
    """``B_banned``: expanded bans plus sub-actions of banned parents not explicitly allowed.

    Under the closure axiom this mask is defense in depth: any sub-action that survives
    ``A_allowed`` is listed by every active flag and is therefore exempt from penetration.
    """
    direct: set[str] = set()
    exempt: set[str] = set()
    for code in flags:
        flag = tax.red_flags()[code]
        exempt |= _canonical(tax, flag.allowed_actions)
        for entry in flag.banned_methods:
            if tax.is_banned_tag(entry):
                direct |= _canonical(tax, tax.banned_tag_methods(entry))
            else:
                direct.add(tax.canonical_action_id(entry))
    children = _children(tax)
    penetrated = {sub for mid in direct for sub in children.get(mid, ()) if sub not in exempt}
    return frozenset(direct | penetrated)


def _own_contraindications(tax: Taxonomy, aid: str) -> tuple[str, ...]:
    methods = tax.methods()
    if aid in methods:
        return methods[aid].contraindications
    return tax.action_registry()[aid].contraindications


# -- skeleton assembly --------------------------------------------------------------------


def _m0_skeleton(tax: Taxonomy) -> ActionSkeleton:
    skeleton = _skeleton(tax, M0_ACTION_ID)
    if skeleton.action_type is not ActionType.COMPANIONSHIP:
        raise TaxonomyError(f"{M0_ACTION_ID} must be a COMPANIONSHIP action")
    return skeleton


def _skeleton(tax: Taxonomy, aid: str) -> ActionSkeleton:
    methods = tax.methods()
    if aid in methods:
        method = methods[aid]
        if (
            method.grade is not SafetyGrade.GRADE_A
            or method.clinical_rationale is None
            or method.duration_minutes is None
            or method.stealth_workplace_compatible is None
        ):
            raise ValueError(f"method {aid} is not a Grade A self-help exercise")
        return ActionSkeleton(
            method_id=aid,
            action_type=ActionType.MICRO_EXERCISE,
            safety_grade=method.grade,
            clinical_rationale=method.clinical_rationale,
            core_action_steps=method.core_action_steps,
            duration_minutes=method.duration_minutes,
            stealth_workplace_compatible=method.stealth_workplace_compatible,
            contraindications=method.contraindications,
        )
    action = tax.action_registry()[aid]
    parent = action.parent_method_id
    return ActionSkeleton(
        method_id=aid,
        action_type=action.action_type,
        # A sub-action carries its parent's grade; a standalone action has none.
        safety_grade=methods[parent].grade if parent is not None else None,
        clinical_rationale=action.clinical_rationale,
        core_action_steps=action.core_action_steps,
        duration_minutes=action.duration_minutes,
        stealth_workplace_compatible=action.stealth_workplace_compatible,
        contraindications=action.contraindications,
    )


# -- helpers --------------------------------------------------------------------------------


def _canonical(tax: Taxonomy, entries: Iterable[str]) -> set[str]:
    return {tax.canonical_action_id(entry) for entry in entries}


def _children(tax: Taxonomy) -> Mapping[str, tuple[str, ...]]:
    """Registered sub-actions keyed by parent method id, in registry order."""
    children: dict[str, list[str]] = {}
    for action in tax.action_registry().values():
        if action.parent_method_id is not None:
            children.setdefault(action.parent_method_id, []).append(action.id)
    return {parent: tuple(subs) for parent, subs in children.items()}


def _ordered_ids(tax: Taxonomy) -> Iterator[str]:
    """Every action id in taxonomy order, each method followed by its sub-actions."""
    children = _children(tax)
    for mid in tax.methods():
        yield mid
        yield from children.get(mid, ())
    for action in tax.action_registry().values():
        if action.parent_method_id is None:
            yield action.id
