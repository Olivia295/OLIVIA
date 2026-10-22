"""Rule-based perception stub: fills ``PerceptionContext`` and ``TurnSignals`` from text.

It stands in for the trained perception model (P6) and follows the definitions of
docs/eval/perception-annotation-guide.md as far as phrase matching can. All phrases come
from ``olivia/data/lexicons/perception.yaml``; all thresholds come from the taxonomy,
except the arousal modifier steps below.

Matching. The message is folded with the safety ``normalize``; a leading ``[NN%]``
battery prefix is read and removed; the rest is clipped to the SDD §10.1 perception
window (head 128 + tail 256 characters) and scanned once. Within each lexicon section a
hit fully inside a longer hit of the same section is dropped, then a hit directly
preceded by a negation prefix is void, unless the prefix ends a non-negating word
(``negation.exceptions``: 特别, 告别 ...), completes an A-not-A question (是不是, 有没有,
会不会) or follows another negation (不是不). This mirrors the red-flag detector's check.

Rules, per field:

- ``risk_level`` / ``crisis_confidence``: copied from the ``CrisisAssessment`` (level,
  score). The stub never recomputes risk.
- ``fine_grained_emotion``: the emotion with the most cue hits (aliases already folded
  into canonical ids by the lexicon loader); ties go to the earlier ``emotion_cues`` key,
  which the lexicon orders by the guide's §2.2 rule 4 (closer to risk first). No hit:
  ``calm`` (guide §2.4 labels neutral messages calm).
- ``valence``: the midpoint of the dominant emotion's TAX ``valence_range`` (TAX has no
  default valence); 0.0 when no emotion cue matched.
- ``arousal``: the dominant emotion's TAX ``default_arousal`` (``calm``'s when nothing
  matched), plus ``AROUSAL_STEP`` per ``raise`` modifier hit (at most
  ``MAX_RAISE_STEPS``) and minus one step per ``lower`` hit (at most
  ``MAX_LOWER_STEPS``), clamped to [0, 1]. The bounded swing (+0.15 / -0.10) keeps the
  value inside the guide's table A window for every emotion.
- ``somatic_stabilization_eligible``: arousal >= ``arousal.thresholds.somatic_priority``.
- ``distress_vector``: spectrum cue hits per TAX spectrum "01".."11", normalized to sum
  to 1 (all eleven keys present); an empty mapping when no spectrum cue matched.
- ``empathy_intent``: the guide's §4.2 order, first match wins:
  1. risk L2/L3 -> REFERRAL;
  2. arousal >= somatic_priority -> STABILIZATION;
  3. a referral cue (seeking a professional, someone else in danger, violence,
     red-flag symptoms) -> REFERRAL;
  3a. arousal in the TAX ``elevated`` band and a body-symptom or calm-me-down cue ->
     STABILIZATION (the guide's extension, judged before step 4);
  4. an information cue or a direct request, arousal below the ``elevated`` band and
     valence > ``intent_rules.information_min_valence`` -> INFORMATION;
  5. valence <= ``intent_rules.validation_max_valence``, or shame/hopelessness/grief/loneliness
     without a question, or risk L1, or a lock-on phrase -> VALIDATION;
  6. emotion ``confusion`` -> REFLECTION (the stub cannot see mixed feelings otherwise);
  7. otherwise EXPLORATION.

Placeholders until P6 (the stub has no evidence for these heads):
``communication_stance`` is ``CONGRUENT`` (the guide's §7.2 default),
``readiness_to_change`` is 0.5 (the guide's §8 "no information" value),
``detected_distortions`` and ``detected_schemas`` are empty, and ``deep_yearning`` is the
first TAX ``satir_yearnings`` id (``SAFETY``).

Signals: ``battery`` from the prefix (``NN / 100`` clamped to [0, 1], None without one);
``command`` when the whole folded message is ``/done``, ``/not-now`` or ``/unhelpful``;
``direct_request``, ``listening_lock_on``, ``listening_lock_off``, ``aversion`` and
``intent_confirmed`` when a non-negated phrase of that section matched. If both lock
phrases match, the later one in the message wins, since a turn cannot both set and
release the lock. ``aversion`` and ``intent_confirmed`` may both be set; the state machine
reads them in different stages (S_empower, S_closing).
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from olivia.core.models import CrisisLevel, PerceptionContext
from olivia.core.perception.lexicon import PerceptionLexicon
from olivia.core.perception.signals import Command, TurnSignals
from olivia.core.safety.crisis import CrisisAssessment
from olivia.core.safety.matcher import Match, PhraseMatcher
from olivia.core.safety.normalize import clip_for_perception, normalize
from olivia.core.taxonomy import Taxonomy

AROUSAL_STEP: Final = 0.05
"""Arousal change per intensity modifier hit (guide §3 labels in 0.05 steps)."""
MAX_RAISE_STEPS: Final = 3
MAX_LOWER_STEPS: Final = 2

FALLBACK_EMOTION: Final = "calm"
DEFAULT_STANCE: Final = "CONGRUENT"
DEFAULT_READINESS: Final = 0.5

_VALIDATION_EMOTIONS: Final = frozenset({"shame", "hopelessness", "grief", "loneliness"})
_REFLECTION_EMOTION: Final = "confusion"
_ELEVATED_BAND: Final = "elevated"
# (head, negation) pairs that form an A-not-A question rather than a denial.
_A_NOT_A: Final = (("是", "不是"), ("有", "没有"), ("会", "不会"))
_BATTERY_PREFIX: Final = re.compile(r"\[([0-9]{1,3})%\]")
_COMMANDS: Final[Mapping[str, Command]] = MappingProxyType({c.value: c for c in Command})

# Section groups; containment is resolved within a group, never across groups.
_EMOTION: Final = "emotion"
_MODIFIER: Final = "modifier"
_SPECTRUM: Final = "spectrum"
_SIGNAL: Final = "signal"
_INFORMATION: Final = "information"
_REFERRAL: Final = "referral"
_STABILIZATION: Final = "stabilization"
_RAISE: Final = "raise"
_LOWER: Final = "lower"
_DIRECT: Final = "direct_request"
_LOCK_ON: Final = "lock_on"
_LOCK_OFF: Final = "lock_off"
_AVERSION: Final = "aversion"
_INTENT: Final = "intent_confirmed"

_Tag = tuple[str, str]  # (group, label)


class EmpathyIntent(StrEnum):
    """The six support strategies of the annotation guide §4.1."""

    REFERRAL = "REFERRAL"
    STABILIZATION = "STABILIZATION"
    INFORMATION = "INFORMATION"
    VALIDATION = "VALIDATION"
    REFLECTION = "REFLECTION"
    EXPLORATION = "EXPLORATION"


def dominant_spectrum(distress_vector: Mapping[str, float]) -> str | None:
    """The highest-scoring spectrum (ties: first in vector order), None when empty."""
    best: str | None = None
    for spectrum, score in distress_vector.items():
        if score > 0.0 and (best is None or score > distress_vector[best]):
            best = spectrum
    return best


class RuleStub:
    def __init__(self, tax: Taxonomy, lexicon: PerceptionLexicon) -> None:
        profiles = tax.emotion_profiles()
        self._arousal = {e: p.default_arousal for e, p in profiles.items()}
        self._valence = {
            e: (p.valence_range[0] + p.valence_range[1]) / 2 for e, p in profiles.items()
        }
        if FALLBACK_EMOTION not in profiles:
            raise ValueError(f"taxonomy has no {FALLBACK_EMOTION!r} emotion")
        if DEFAULT_STANCE not in tax.values("communication_stances"):
            raise ValueError(f"taxonomy has no {DEFAULT_STANCE!r} stance")
        self._yearning = tax.values("satir_yearnings")[0]
        self._somatic = tax.threshold("arousal.thresholds.somatic_priority")
        self._elevated_low = tax.bands("arousal")[_ELEVATED_BAND][0]
        self._information_min_valence = tax.threshold("intent_rules.information_min_valence")
        self._validation_max_valence = tax.threshold("intent_rules.validation_max_valence")
        self._priority = {emotion: rank for rank, emotion in enumerate(lexicon.emotion_cues)}
        self._spectra = tuple(lexicon.spectrum_cues)
        self._negations = lexicon.negation_prefixes
        self._exceptions = lexicon.negation_exceptions

        tags: dict[str, list[_Tag]] = {}

        def add(group: str, label: str, phrases: Iterable[str]) -> None:
            for phrase in phrases:
                tags.setdefault(phrase, []).append((group, label))

        for emotion, phrases in lexicon.emotion_cues.items():
            add(_EMOTION, emotion, phrases)
        for spectrum, phrases in lexicon.spectrum_cues.items():
            add(_SPECTRUM, spectrum, phrases)
        add(_MODIFIER, _RAISE, lexicon.raise_modifiers)
        add(_MODIFIER, _LOWER, lexicon.lower_modifiers)
        add(_SIGNAL, _DIRECT, lexicon.direct_request)
        add(_SIGNAL, _LOCK_ON, lexicon.lock_on)
        add(_SIGNAL, _LOCK_OFF, lexicon.lock_off)
        add(_SIGNAL, _AVERSION, lexicon.aversion)
        add(_SIGNAL, _INTENT, lexicon.intent_confirmed)
        add(_INFORMATION, _INFORMATION, lexicon.information_cues)
        add(_REFERRAL, _REFERRAL, lexicon.referral_cues)
        add(_STABILIZATION, _STABILIZATION, lexicon.stabilization_cues)
        self._tags = {phrase: tuple(t) for phrase, t in tags.items()}
        self._matcher = PhraseMatcher({phrase: phrase for phrase in self._tags})

    def perceive(
        self, text: str, assessment: CrisisAssessment
    ) -> tuple[PerceptionContext, TurnSignals]:
        folded = normalize(text)
        command = _COMMANDS.get(folded)
        battery: float | None = None
        prefix = _BATTERY_PREFIX.match(folded)
        if prefix is not None:
            battery = min(int(prefix.group(1)) / 100, 1.0)
            folded = folded[prefix.end() :]
        body = clip_for_perception(folded)
        hits = self._scan(body)

        emotion_hits = Counter(label for label, _ in hits.get(_EMOTION, ()))
        if emotion_hits:
            emotion = min(emotion_hits, key=lambda e: (-emotion_hits[e], self._priority[e]))
            valence = self._valence[emotion]
        else:
            emotion, valence = FALLBACK_EMOTION, 0.0
        modifiers = Counter(label for label, _ in hits.get(_MODIFIER, ()))
        steps = min(modifiers[_RAISE], MAX_RAISE_STEPS) - min(modifiers[_LOWER], MAX_LOWER_STEPS)
        arousal = round(min(max(self._arousal[emotion] + steps * AROUSAL_STEP, 0.0), 1.0), 4)

        signals = hits.get(_SIGNAL, [])
        labels = {label for label, _ in signals}
        direct = _DIRECT in labels
        lock_on, lock_off = _lock(signals)
        asking = direct or bool(hits.get(_INFORMATION))
        intent = self._intent(
            assessment.level,
            arousal,
            valence,
            emotion,
            asking=asking,
            referral=bool(hits.get(_REFERRAL)),
            body_led=bool(hits.get(_STABILIZATION)),
            lock_on=lock_on,
        )
        context = PerceptionContext(
            valence=valence,
            arousal=arousal,
            fine_grained_emotion=emotion,
            empathy_intent=intent.value,
            risk_level=assessment.level,
            crisis_confidence=assessment.score,
            communication_stance=DEFAULT_STANCE,
            readiness_to_change=DEFAULT_READINESS,
            distress_vector=self._distress(hits.get(_SPECTRUM, ())),
            detected_distortions=(),
            detected_schemas=(),
            deep_yearning=self._yearning,
            somatic_stabilization_eligible=arousal >= self._somatic,
        )
        turn = TurnSignals(
            battery=battery,
            direct_request=direct,
            listening_lock_on=lock_on,
            listening_lock_off=lock_off,
            aversion=_AVERSION in labels,
            intent_confirmed=_INTENT in labels,
            command=command,
        )
        return context, turn

    # -- matching ------------------------------------------------------------------

    def _scan(self, body: str) -> dict[str, list[tuple[str, Match]]]:
        """Surviving hits per group: outermost within the group, then not negated."""
        grouped: dict[str, list[tuple[str, Match]]] = {}
        for match in self._matcher.find_all(body):
            for group, label in self._tags[match.key]:
                grouped.setdefault(group, []).append((label, match))
        negated: dict[int, bool] = {}
        result: dict[str, list[tuple[str, Match]]] = {}
        for group, items in grouped.items():
            kept: list[tuple[str, Match]] = []
            for label, match in _outermost(items):
                start = match.start
                if start not in negated:
                    negated[start] = self._negated(body, start)
                if not negated[start]:
                    kept.append((label, match))
            if kept:
                result[group] = kept
        return result

    def _negated(self, text: str, start: int) -> bool:
        if any(text.endswith(word, 0, start) for word in self._exceptions):
            return False
        for negation in self._negations:
            if not text.endswith(negation, 0, start):
                continue
            head = start - len(negation)
            if any(neg == negation and text.endswith(a, 0, head) for a, neg in _A_NOT_A):
                continue
            if any(text.endswith(other, 0, head) for other in self._negations):
                continue
            return True
        return False

    # -- derived fields ------------------------------------------------------------

    def _distress(self, hits: Iterable[tuple[str, Match]]) -> Mapping[str, float]:
        counts = Counter(label for label, _ in hits)
        total = sum(counts.values())
        if total == 0:
            return MappingProxyType({})
        return MappingProxyType({sid: counts[sid] / total for sid in self._spectra})

    def _intent(
        self,
        level: CrisisLevel,
        arousal: float,
        valence: float,
        emotion: str,
        *,
        asking: bool,
        referral: bool,
        body_led: bool,
        lock_on: bool,
    ) -> EmpathyIntent:
        if level >= CrisisLevel.L2:
            return EmpathyIntent.REFERRAL
        if arousal >= self._somatic:
            return EmpathyIntent.STABILIZATION
        if referral:
            return EmpathyIntent.REFERRAL
        elevated = arousal >= self._elevated_low
        if elevated and body_led:
            return EmpathyIntent.STABILIZATION
        if asking and not elevated and valence > self._information_min_valence:
            return EmpathyIntent.INFORMATION
        if (
            valence <= self._validation_max_valence
            or (emotion in _VALIDATION_EMOTIONS and not asking)
            or level is CrisisLevel.L1
            or lock_on
        ):
            return EmpathyIntent.VALIDATION
        if emotion == _REFLECTION_EMOTION:
            return EmpathyIntent.REFLECTION
        return EmpathyIntent.EXPLORATION


def _outermost(items: list[tuple[str, Match]]) -> list[tuple[str, Match]]:
    """Drop every hit that lies fully inside another hit of the same group."""
    ordered = sorted(items, key=lambda item: (item[1].start, -item[1].end))
    kept: list[tuple[str, Match]] = []
    furthest = -1
    for label, match in ordered:
        if match.end > furthest:
            kept.append((label, match))
            furthest = match.end
    return kept


def _lock(signals: list[tuple[str, Match]]) -> tuple[bool, bool]:
    """(lock_on, lock_off); when both phrases occur, the later one in the text wins."""
    last_on = max((m.end for label, m in signals if label == _LOCK_ON), default=-1)
    last_off = max((m.end for label, m in signals if label == _LOCK_OFF), default=-1)
    if last_on < 0 and last_off < 0:
        return False, False
    return last_on > last_off, last_off > last_on
