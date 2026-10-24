"""Model-mode perception (roadmap C1, P6-6b): the student's heads over the rule stub.

Only with the student on (``Session.open(student=True)``, ``olivia chat`` by default);
rules mode never builds this. :meth:`ModelHeads.refine` takes the rule stub's
``PerceptionContext`` for the turn and replaces the fields the student has a head for:

- ``valence``: the ``valence`` head (tanh, in [-1, 1]).
- ``fine_grained_emotion``, ``empathy_intent``, ``communication_stance``: the most likely
  label of the ``emotion``, ``intent`` and ``stance`` class heads (softmax with the
  calibrated temperatures of ``student_config.json``; ties go to the earlier label).
- ``readiness_to_change``: the ``readiness`` head (sigmoid).
- ``arousal``: the higher of the rule value and the ``arousal`` head. Higher arousal only
  steers towards stabilization, so the model can raise it and never lower it;
  ``somatic_stabilization_eligible`` is recomputed from the result.
- ``distress_vector``: the rule stub's when it found a spectrum cue (the user's own words
  win); otherwise the ``dominant_spectrum`` head's probabilities over the eleven spectra,
  normalized to sum to 1, or empty when ``none`` is the most likely label. The session's
  dominant spectrum is read from this vector, so it is the head's top spectrum.

Everything else stays from the rules: the crisis screen's level and confidence, the
introspection fields (distortions, schemas, yearning) and every ``TurnSignals`` field.
The crisis tracker reads the rule valence before ``refine`` runs (``session.py``), so
crisis screening and arbitration are the same in both modes.

The student runs once per turn: the screen's ``StudentRiskModel`` keeps the heads of its
forward pass and ``refine`` takes them; it runs the student itself only on a turn where
the screen did not (Stage 1 answered first). A forward pass that raises, or a head
outside its range (not finite, or a class head that is not a label distribution), leaves
the turn with the rule context unchanged.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import replace
from types import MappingProxyType
from typing import Final

from olivia.core.models import PerceptionContext
from olivia.core.perception.rule_stub import EmpathyIntent
from olivia.core.perception.student import HeadValue, StudentRiskModel
from olivia.core.taxonomy import Taxonomy

NO_SPECTRUM: Final = "none"
_SOMATIC_KEY: Final = "arousal.thresholds.somatic_priority"


class ModelHeads:
    """The student's perception heads for one session; see the module docstring.

    Raises ``ValueError`` when the student's labels do not match the taxonomy.
    """

    def __init__(self, tax: Taxonomy, risk_model: StudentRiskModel) -> None:
        self._risk_model = risk_model
        self._somatic = tax.threshold(_SOMATIC_KEY)
        self._spectra = tax.spectrum_ids()
        self._labels: dict[str, frozenset[str]] = {
            "emotion": frozenset(tax.emotion_profiles()),
            "intent": frozenset(intent.value for intent in EmpathyIntent),
            "stance": frozenset(tax.values("communication_stances")),
            "dominant_spectrum": frozenset((*self._spectra, NO_SPECTRUM)),
        }
        heads = risk_model.student.heads
        for name, labels in self._labels.items():
            head = heads.get(name)
            if head is None or head.labels is None or not set(head.labels) <= labels:
                raise ValueError(f"student head {name!r} does not match the taxonomy")
        if set(heads["dominant_spectrum"].labels or ()) != self._labels["dominant_spectrum"]:
            raise ValueError("student head 'dominant_spectrum' does not cover every spectrum")
        for name in ("valence", "arousal", "readiness"):
            head = heads.get(name)
            if head is None or head.labels is not None:
                raise ValueError(f"student head {name!r} is missing or not a scalar")

    def refine(self, text: str, rule: PerceptionContext) -> PerceptionContext:
        """The turn's context with the student's heads; ``rule`` when they are unusable."""
        heads = self._risk_model.take_heads()
        if heads is None:
            try:
                heads = self._risk_model.student.predict_heads(text)
            except Exception:  # a broken forward pass never breaks the turn
                return rule
        valence = _scalar(heads, "valence", -1.0)
        arousal = _scalar(heads, "arousal", 0.0)
        readiness = _scalar(heads, "readiness", 0.0)
        emotion, intent, stance, spectra = (
            self._distribution(heads, name)
            for name in ("emotion", "intent", "stance", "dominant_spectrum")
        )
        if (
            valence is None
            or arousal is None
            or readiness is None
            or emotion is None
            or intent is None
            or stance is None
            or spectra is None
            or set(spectra) != self._labels["dominant_spectrum"]
        ):
            return rule
        merged_arousal = max(rule.arousal, arousal)
        return replace(
            rule,
            valence=valence,
            arousal=merged_arousal,
            fine_grained_emotion=_top(emotion),
            empathy_intent=_top(intent),
            communication_stance=_top(stance),
            readiness_to_change=readiness,
            distress_vector=rule.distress_vector or self._distress(spectra),
            somatic_stabilization_eligible=merged_arousal >= self._somatic,
        )

    def _distribution(
        self, heads: Mapping[str, HeadValue], name: str
    ) -> Mapping[str, float] | None:
        """A class head's label probabilities, or None unless it is a distribution over
        known labels."""
        probs = heads.get(name)
        if not isinstance(probs, Mapping) or not probs or not set(probs) <= self._labels[name]:
            return None
        for value in probs.values():
            if isinstance(value, bool) or not isinstance(value, int | float):
                return None
            if not (math.isfinite(value) and 0.0 <= value <= 1.0):
                return None
        if not math.isclose(sum(probs.values()), 1.0, abs_tol=1e-6):
            return None
        return probs

    def _distress(self, probs: Mapping[str, float]) -> Mapping[str, float]:
        if _top(probs) == NO_SPECTRUM:
            return MappingProxyType({})
        total = sum(probs[spectrum] for spectrum in self._spectra)
        return MappingProxyType({s: probs[s] / total for s in self._spectra})


def _scalar(heads: Mapping[str, HeadValue], name: str, low: float) -> float | None:
    value = heads.get(name)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    value = float(value)
    return value if math.isfinite(value) and low <= value <= 1.0 else None


def _top(probs: Mapping[str, float]) -> str:
    """The most likely label; ties go to the earlier label."""
    return max(probs, key=lambda label: probs[label])
