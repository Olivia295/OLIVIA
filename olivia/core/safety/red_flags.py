"""Red-flag condition detection from self-report and feature cues.

Detected codes later restrict which self-help actions may be offered, so a miss
is costlier than a false hit. Self-report hits are voided only by an immediately
preceding negation ("我没有双相"); feature hits are never negated. Once a code is
active in a session it is never withdrawn. This module never writes back to the
profile: persisting a detected flag needs explicit user consent (a later phase).
"""

from __future__ import annotations

from collections.abc import Iterable

from olivia.core.safety.lexicon import SafetyLexicons
from olivia.core.safety.matcher import PhraseMatcher
from olivia.core.safety.normalize import normalize
from olivia.core.taxonomy import Taxonomy


class UnknownRedFlagError(ValueError):
    """Raised when a clinical-history code is not a known red-flag code."""


class RedFlagDetector:
    def __init__(self, tax: Taxonomy, lexicons: SafetyLexicons) -> None:
        self._known = frozenset(tax.red_flags())
        self._cues = lexicons.red_flags
        self._negations = lexicons.self_report_negations
        self._window = max((len(n) for n in self._negations), default=0)
        phrases = {phrase: cue.id for cue in lexicons.red_flags.values() for phrase in cue.patterns}
        self._matcher = PhraseMatcher(phrases)

    def detect(self, text: str) -> frozenset[str]:
        folded = normalize(text)
        found: set[str] = set()
        for match in self._matcher.find_all(folded):
            cue = self._cues[match.key]
            if cue.tier == "SELF_REPORT" and self._negated(folded, match.start):
                continue
            found.add(cue.code)
        return frozenset(found)

    def profile_flags(self, clinical_history: Iterable[str]) -> frozenset[str]:
        codes = frozenset(clinical_history)
        for code in sorted(codes - self._known):
            raise UnknownRedFlagError(f"unknown red flag code: {code}")
        return codes

    def _negated(self, folded: str, start: int) -> bool:
        """True when a negation directly precedes the hit and is not neutralised.

        A negation is neutralised (the hit survives) when it follows "是" (the
        A-not-A question form 是不是) or follows another negation (double negation
        such as 不是没有). A miss is the costly direction, so both fail toward flagging.
        """
        before = folded[max(0, start - self._window) : start]
        for negation in self._negations:
            if not before.endswith(negation):
                continue
            head = folded[: start - len(negation)]
            if head.endswith("是") or any(head.endswith(other) for other in self._negations):
                continue
            return True
        return False


class SessionRedFlags:
    """Accumulates red flags over a session; profile codes are always active."""

    def __init__(self, detector: RedFlagDetector, clinical_history: Iterable[str] = ()) -> None:
        self._detector = detector
        self._active: frozenset[str] = detector.profile_flags(clinical_history)

    @property
    def active(self) -> frozenset[str]:
        return self._active

    def observe(self, text: str) -> frozenset[str]:
        self._active |= self._detector.detect(text)
        return self._active
