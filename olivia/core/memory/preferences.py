"""Method preferences, one method at a time (PRD RSK-06 "支持透明管理"; SDD §6.3).

The kit store (``memory/state.py``) keeps the Thompson posteriors: per spectrum, per
action, two numbers and the time of the last "not for me". ``olivia memory`` shows them
here as one plain sentence per method, never the numbers, and ``olivia forget --method``
resets one method by removing its posterior in every spectrum (:func:`without_method`),
so it is recommended as it was at first again.

A method is listed when its posterior moved away from its prior in some spectrum
(:class:`PreferenceStatus`), in this order of precedence:

* ``UNHELPFUL_RECENTLY``: a "not for me" whose decayed penalty still adds at least
  :data:`RECENT_PENALTY` to ``beta`` (with the taxonomy's 0.1 per day: about a week), so
  it is offered less for a while;
* ``HELPFUL``: some "helpful" raised ``alpha`` above the prior;
* ``RECOVERED``: a "not for me" that has decayed below the threshold.

Methods are sorted by title (then id), so ``olivia memory`` and ``olivia forget`` number
them alike. The titles are the exercise-card titles the user saw (the ledger's
``method_titles``), else the taxonomy's Chinese name. Nothing here reads or writes files.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from olivia.core.memory.state import restore_sampler
from olivia.core.taxonomy import Taxonomy, TaxonomyError

RECENT_PENALTY: Final = 0.5
"""How much of a "not for me" (one unit of ``beta``) must remain for it to count as
recent. Draft pending G-0, like the wording that shows it."""


class PreferenceStatus(StrEnum):
    UNHELPFUL_RECENTLY = "unhelpful_recently"
    HELPFUL = "helpful"
    RECOVERED = "recovered"


@dataclass(frozen=True)
class MethodPreference:
    action_id: str
    """The canonical action id, as the posteriors store it."""
    title: str
    status: PreferenceStatus


def _title(tax: Taxonomy, action_id: str, titles: Mapping[str, str]) -> str:
    if action_id in titles:
        return titles[action_id]
    methods = tax.methods()
    if action_id in methods:
        return methods[action_id].name_zh
    return tax.action_registry()[action_id].name_zh


def method_preferences(
    tax: Taxonomy,
    bandit: Mapping[str, object],
    now: datetime,
    titles: Mapping[str, str] | None = None,
) -> tuple[MethodPreference, ...]:
    """The methods with a preference recorded in ``bandit`` (``ThompsonSampler.to_dict()``),
    sorted by title; arms the taxonomy no longer knows are left out."""
    sampler = restore_sampler(tax, bandit)
    spectra = sampler.to_dict()["spectra"]
    found: dict[str, set[PreferenceStatus]] = {}
    for spectrum, arms in _items(spectra):
        for action_id, arm in _items(arms):
            prior_alpha, prior_beta = sampler.prior(action_id)
            alpha, beta_eff = sampler.posterior(action_id, spectrum, now)
            marks = found.setdefault(action_id, set())
            if isinstance(arm, Mapping) and arm.get("last_unhelpful_at") is not None:
                recent = beta_eff - prior_beta >= RECENT_PENALTY
                marks.add(
                    PreferenceStatus.UNHELPFUL_RECENTLY if recent else PreferenceStatus.RECOVERED
                )
            if alpha > prior_alpha:
                marks.add(PreferenceStatus.HELPFUL)
    preferences = []
    for action_id, marks in found.items():
        for status in PreferenceStatus:  # in order of precedence
            if status in marks:
                title = _title(tax, action_id, {} if titles is None else titles)
                preferences.append(MethodPreference(action_id, title, status))
                break
    return tuple(sorted(preferences, key=lambda p: (p.title, p.action_id)))


def without_method(
    tax: Taxonomy, bandit: Mapping[str, object], action_id: str
) -> dict[str, object]:
    """``bandit`` without any posterior of ``action_id`` (an alias of it included) in any
    spectrum; a spectrum left with no arms is dropped."""
    target = tax.canonical_action_id(action_id)
    spectra = bandit.get("spectra")
    kept: dict[str, object] = {}
    if isinstance(spectra, Mapping):
        for spectrum, arms in spectra.items():
            if not isinstance(arms, Mapping):
                continue
            rest = {aid: arm for aid, arm in arms.items() if _canonical(tax, aid) != target}
            if rest:
                kept[spectrum] = rest
    return {"spectra": kept}


def _items(value: object) -> list[tuple[str, object]]:
    """A mapping's string-keyed items (``ThompsonSampler.to_dict()`` is typed loosely)."""
    if not isinstance(value, Mapping):
        return []
    return [(key, item) for key, item in value.items() if isinstance(key, str)]


def _canonical(tax: Taxonomy, action_id: object) -> object:
    if not isinstance(action_id, str):
        return action_id
    try:
        return tax.canonical_action_id(action_id)
    except (KeyError, TaxonomyError):  # UnknownActionError is a KeyError
        return action_id
