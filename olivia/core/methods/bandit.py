"""Beta-Bernoulli Thompson sampling over methods, one posterior per spectrum (SDD 6.3).

Each (spectrum id, canonical action id) pair holds ``Beta(alpha, beta)``. An arm with
no feedback yet sits at the prior of its method's evidence level; a registry sub-action
uses its parent method's level. Every number (priors, decay rate, the exploit-only
arousal threshold) comes from the taxonomy.

``UNHELPFUL`` sets ``beta`` to its decayed value plus 1 and records the time; at read
time the excess over the prior decays: ``beta_eff = beta0 + (beta - beta0) *
exp(-lambda_decay * days)`` with ``days`` counted from the last ``UNHELPFUL``. Folding
the decay in at each update makes every penalty decay from its own date.
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from olivia.core.taxonomy import Taxonomy, TaxonomyError

_PRIORS_KEY: Final = "thompson_sampling_index.evidence_level_priors"
_DECAY_KEY: Final = "thompson_sampling_index.lambda_decay_per_day"
_EXPLOIT_ABOVE_KEY: Final = "arousal.thresholds.exploration_allow"
_SECONDS_PER_DAY: Final = 86_400.0


class Feedback(StrEnum):
    HELPFUL = "HELPFUL"
    UNHELPFUL = "UNHELPFUL"
    NOT_NOW = "NOT_NOW"


@dataclass
class _Arm:
    alpha: float
    beta: float
    last_unhelpful_at: datetime | None


def _require_aware(moment: datetime, what: str) -> None:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError(f"{what} must be timezone-aware, got {moment!r}")


def _positive_float(value: object, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{where} must be a number, got {value!r}")
    number = float(value)
    if not math.isfinite(number) or number <= 0.0:
        raise ValueError(f"{where} must be a positive finite number, got {value!r}")
    return number


class ThompsonSampler:
    """Thompson sampling with an arousal-gated exploit-only fallback.

    The caller passes the dominant spectrum id; only that spectrum's posteriors are read
    or updated. Randomness and time are injected so results are reproducible.
    """

    def __init__(self, tax: Taxonomy, state: Mapping[str, object] | None = None) -> None:
        self._tax = tax
        self._spectra: frozenset[str] = frozenset(tax.spectrum_ids())
        self._decay_per_day = tax.threshold(_DECAY_KEY)
        if self._decay_per_day < 0.0:
            raise TaxonomyError(f"{_DECAY_KEY} must be non-negative")
        self._exploit_above = tax.threshold(_EXPLOIT_ABOVE_KEY)
        self._arms: dict[str, dict[str, _Arm]] = {}
        if state is not None:
            self._load(state)

    # -- public API ----------------------------------------------------------------

    def choose(
        self,
        candidates: Sequence[str],
        spectrum: str,
        arousal: float,
        rng: random.Random,
        now: datetime,
    ) -> str:
        """Return the canonical id of the chosen candidate.

        Above the exploit-only arousal threshold the highest posterior mean wins
        (sampling variance forced to zero); otherwise one Beta draw per candidate
        decides. Ties go to the earlier candidate.
        """
        if not candidates:
            raise ValueError("choose needs at least one candidate")
        self._check_spectrum(spectrum)
        if not math.isfinite(arousal):
            raise ValueError(f"arousal must be a finite number, got {arousal!r}")
        _require_aware(now, "now")
        ids = [self._tax.canonical_action_id(raw) for raw in candidates]
        params = [self._effective(spectrum, aid, now) for aid in ids]
        if arousal > self._exploit_above:
            scores = [a / (a + b) for a, b in params]
        else:
            scores = [rng.betavariate(a, b) for a, b in params]
        best = max(range(len(ids)), key=lambda i: (scores[i], -i))
        return ids[best]

    def update(self, action_id: str, spectrum: str, feedback: Feedback, now: datetime) -> None:
        """Apply one feedback signal to the dominant spectrum's posterior for the action."""
        self._check_spectrum(spectrum)
        _require_aware(now, "now")
        aid = self._tax.canonical_action_id(action_id)
        prior_alpha, prior_beta = self._prior(aid)
        feedback = Feedback(feedback)
        if feedback is Feedback.NOT_NOW:
            return
        arm = self._arms.setdefault(spectrum, {}).setdefault(
            aid, _Arm(prior_alpha, prior_beta, None)
        )
        if feedback is Feedback.HELPFUL:
            arm.alpha += 1.0
        else:
            # Fold the decay so far into beta before adding the new penalty, so each
            # UNHELPFUL decays from its own date and old penalties never come back.
            arm.beta = self._effective(spectrum, aid, now)[1] + 1.0
            arm.last_unhelpful_at = now

    def posterior(self, action_id: str, spectrum: str, now: datetime) -> tuple[float, float]:
        """Return ``(alpha, beta_eff)`` for the action in the spectrum at ``now``."""
        self._check_spectrum(spectrum)
        _require_aware(now, "now")
        return self._effective(spectrum, self._tax.canonical_action_id(action_id), now)

    def to_dict(self) -> dict[str, object]:
        """JSON-safe state; ``ThompsonSampler(tax, sampler.to_dict())`` restores it."""
        spectra: dict[str, object] = {}
        for spectrum in sorted(self._arms):
            arms: dict[str, object] = {}
            for aid in sorted(self._arms[spectrum]):
                arm = self._arms[spectrum][aid]
                arms[aid] = {
                    "alpha": arm.alpha,
                    "beta": arm.beta,
                    "last_unhelpful_at": (
                        None if arm.last_unhelpful_at is None else arm.last_unhelpful_at.isoformat()
                    ),
                }
            spectra[spectrum] = arms
        return {"spectra": spectra}

    # -- internals -----------------------------------------------------------------

    def _check_spectrum(self, spectrum: str) -> None:
        if spectrum not in self._spectra:
            raise ValueError(f"unknown spectrum id: {spectrum!r}")

    def _prior(self, aid: str) -> tuple[float, float]:
        """Beta prior from the evidence level of the method (or the sub-action's parent)."""
        methods = self._tax.methods()
        method_id = aid
        if aid not in methods:
            parent = self._tax.action_registry()[aid].parent_method_id
            if parent is None:
                raise ValueError(f"action {aid} has no parent method, so no evidence-level prior")
            method_id = parent
        level = methods[method_id].evidence_level
        if level is None:
            raise ValueError(f"method {method_id} has no evidence level, so no Thompson prior")
        return (
            self._tax.threshold(f"{_PRIORS_KEY}.{level}.alpha"),
            self._tax.threshold(f"{_PRIORS_KEY}.{level}.beta"),
        )

    def _effective(self, spectrum: str, aid: str, now: datetime) -> tuple[float, float]:
        prior_alpha, prior_beta = self._prior(aid)
        arm = self._arms.get(spectrum, {}).get(aid)
        if arm is None:
            return prior_alpha, prior_beta
        if arm.last_unhelpful_at is None:
            return arm.alpha, arm.beta
        # A clock that runs backwards must not amplify the penalty, so Δt never goes negative.
        days = max(0.0, (now - arm.last_unhelpful_at).total_seconds() / _SECONDS_PER_DAY)
        beta_eff = prior_beta + (arm.beta - prior_beta) * math.exp(-self._decay_per_day * days)
        return arm.alpha, beta_eff

    def _load(self, state: Mapping[str, object]) -> None:
        if set(state) != {"spectra"}:
            raise ValueError(
                f"bandit state must have exactly the key 'spectra', got {sorted(state)}"
            )
        spectra = state["spectra"]
        if not isinstance(spectra, Mapping):
            raise ValueError("bandit state 'spectra' must be a mapping")
        for spectrum, raw_arms in spectra.items():
            if not isinstance(spectrum, str):
                raise ValueError(f"spectrum id must be a string, got {spectrum!r}")
            self._check_spectrum(spectrum)
            if not isinstance(raw_arms, Mapping):
                raise ValueError(f"bandit state for spectrum {spectrum} must be a mapping")
            arms: dict[str, _Arm] = {}
            for raw_id, raw_arm in raw_arms.items():
                where = f"bandit state {spectrum}/{raw_id}"
                if not isinstance(raw_id, str):
                    raise ValueError(f"{where}: action id must be a string")
                aid = self._tax.canonical_action_id(raw_id)
                self._prior(aid)  # an arm the sampler could never score is corrupt state
                if aid in arms:
                    raise ValueError(f"{where}: duplicates action {aid} after alias resolution")
                arms[aid] = self._parse_arm(raw_arm, where)
            self._arms[spectrum] = arms

    @staticmethod
    def _parse_arm(raw: object, where: str) -> _Arm:
        if not isinstance(raw, Mapping) or set(raw) != {"alpha", "beta", "last_unhelpful_at"}:
            raise ValueError(f"{where} must have exactly alpha, beta and last_unhelpful_at")
        stamp = raw["last_unhelpful_at"]
        moment: datetime | None = None
        if stamp is not None:
            if not isinstance(stamp, str):
                raise ValueError(f"{where}: last_unhelpful_at must be an ISO string or null")
            moment = datetime.fromisoformat(stamp)
            _require_aware(moment, f"{where} last_unhelpful_at")
        return _Arm(
            alpha=_positive_float(raw["alpha"], f"{where} alpha"),
            beta=_positive_float(raw["beta"], f"{where} beta"),
            last_unhelpful_at=moment,
        )
