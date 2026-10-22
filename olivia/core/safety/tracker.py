"""Cross-turn crisis tracking: EWMA escalation, crisis entry and confirmed exit.

Exit from crisis needs an explicit safety confirmation followed by N safe (L0) turns, so
a single calm message never switches emergency resources off. After confirmation an L1
turn pauses the count: it neither counts as safe nor resets the turns already counted. The L1
escalation trend (EWMA and L1 run) is reset on every turn at L2 or above, crisis entry
included, and on crisis exit. The tracker keeps numbers and flags only; it never stores
user text.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Final

from olivia.core.models import CrisisLevel
from olivia.core.safety.crisis import CrisisAssessment
from olivia.core.safety.lexicon import SafetyLexicons
from olivia.core.safety.matcher import PhraseMatcher
from olivia.core.safety.normalize import normalize
from olivia.core.taxonomy import Taxonomy

# The spec requires the user to *explicitly confirm* safety ("明确确认安全"). A safety_confirm
# phrase therefore counts only when it is not negated, questioned or sarcastic. Anything
# ambiguous fails toward staying in crisis, which keeps emergency resources visible.
# Directly preceding the hit: "我不觉得…", "我哪里…", "我没有…" negate or deflect the phrase.
_NEGATING_PREFIXES: Final[tuple[str, ...]] = ("不", "没", "没有", "不是", "并非", "哪里")
# Trailing punctuation ignored before the question check (NFKC already folds "？" to "?").
_TRAILING_PUNCTUATION: Final = "。.!！~…"
# A message ending in a question particle asks about safety rather than confirming it.
_QUESTION_ENDINGS: Final[tuple[str, ...]] = ("吗", "么", "?")


@dataclass(frozen=True)
class CrisisStatus:
    level: CrisisLevel
    in_crisis: bool
    entry_level: CrisisLevel | None
    escalated: bool
    awaiting_confirmation: bool
    safe_turns_remaining: int
    just_entered: bool
    just_exited: bool


def _whole_threshold(tax: Taxonomy, path: str) -> int:
    value = tax.threshold(path)
    if not value.is_integer() or value < 1:
        raise ValueError(f"taxonomy threshold {path} must be a positive whole number, got {value}")
    return int(value)


def _strictly_decreasing(values: list[float]) -> bool:
    return all(earlier > later for earlier, later in zip(values, values[1:], strict=False))


class CrisisTracker:
    """Stateful per-session tracker; call ``observe`` exactly once per user turn."""

    def __init__(self, tax: Taxonomy, lexicons: SafetyLexicons) -> None:
        self._tax = tax
        self._lambda = tax.threshold("risk.ewma_lambda")
        self._escalate = tax.threshold("risk.ewma_escalate")
        self._streak = _whole_threshold(tax, "risk.ewma_streak")
        self._clear_streak = _whole_threshold(tax, "risk.l1_clear_streak")
        phrases = {
            phrase: cue.id for cue in lexicons.cues("safety_confirm") for phrase in cue.patterns
        }
        self._confirm_matcher = PhraseMatcher(phrases)
        self._veto_matcher = PhraseMatcher(
            {phrase: cue.id for cue in lexicons.cues("confirm_veto") for phrase in cue.patterns}
        )

        self._ewma: float | None = None
        self._l1_run = 0
        self._recent_valence: deque[float | None] = deque(maxlen=self._streak)
        self._l0_streak = 0

        self._in_crisis = False
        self._entry_level: CrisisLevel | None = None
        self._confirmed = False
        self._safe_turns = 0

    def observe(
        self, assessment: CrisisAssessment, text: str, valence: float | None = None
    ) -> CrisisStatus:
        assessed = assessment.level
        self._update_trend(assessed, assessment.score, valence)

        level = assessed
        escalated = assessed is CrisisLevel.L1 and self._should_escalate()
        if escalated:
            level = CrisisLevel.L2

        just_entered = False
        just_exited = False
        if level >= CrisisLevel.L2:
            if not self._in_crisis:
                self._in_crisis = True
                self._entry_level = level
                just_entered = True
            elif self._entry_level is not None:
                self._entry_level = max(self._entry_level, level)
            self._confirmed = False
            self._safe_turns = 0
            # The L1 escalation trend starts afresh after any crisis-level turn, so an L2/L3
            # score never lifts later L1 turns into a spurious escalation.
            self._reset_trend()
        elif self._in_crisis:
            just_exited = self._observe_safe_candidate(level, text)

        return self._status(level, escalated, just_entered, just_exited)

    def _update_trend(self, assessed: CrisisLevel, score: float, valence: float | None) -> None:
        if assessed >= CrisisLevel.L1:
            self._l0_streak = 0
            if self._ewma is None:
                self._ewma = score
            else:
                self._ewma = self._lambda * score + (1.0 - self._lambda) * self._ewma
        if assessed is CrisisLevel.L1:
            self._l1_run += 1
            usable = valence if valence is not None and math.isfinite(valence) else None
            self._recent_valence.append(usable)
        elif assessed is CrisisLevel.L0:
            self._l0_streak += 1
            if self._l0_streak >= self._clear_streak:
                self._reset_trend()

    def _reset_trend(self) -> None:
        self._ewma = None
        self._l1_run = 0
        self._recent_valence.clear()

    def _should_escalate(self) -> bool:
        if self._l1_run < self._streak or self._ewma is None or self._ewma < self._escalate:
            return False
        recent = list(self._recent_valence)
        if len(recent) < self._streak:
            return False
        known = [v for v in recent if v is not None]
        if len(known) == len(recent):
            return _strictly_decreasing(known)
        return True

    def _observe_safe_candidate(self, level: CrisisLevel, text: str) -> bool:
        """Handle a turn at effective level <= L1 while in crisis; True when it exits."""
        entry = self._entry_level
        if entry is None:  # unreachable: in_crisis always has an entry level
            return False
        if not self._confirmed:
            if self._is_explicit_confirmation(normalize(text)):
                self._confirmed = True
            return False
        # Only L0 counts as safe; an L1 turn pauses the count without resetting it.
        if level is not CrisisLevel.L0:
            return False
        self._safe_turns += 1
        if self._safe_turns < self._tax.crisis_exit_safe_turns(entry):
            return False
        self._in_crisis = False
        self._entry_level = None
        self._confirmed = False
        self._safe_turns = 0
        self._reset_trend()
        return True

    def _is_explicit_confirmation(self, normalized: str) -> bool:
        hits = self._confirm_matcher.find_all(normalized)
        if not hits:
            return False
        if self._veto_matcher.find_all(normalized):
            return False
        if normalized.rstrip(_TRAILING_PUNCTUATION).endswith(_QUESTION_ENDINGS):
            return False
        return any(not normalized[: hit.start].endswith(_NEGATING_PREFIXES) for hit in hits)

    def _status(
        self, level: CrisisLevel, escalated: bool, just_entered: bool, just_exited: bool
    ) -> CrisisStatus:
        remaining = 0
        if self._in_crisis and self._entry_level is not None:
            needed = self._tax.crisis_exit_safe_turns(self._entry_level)
            remaining = needed - self._safe_turns if self._confirmed else needed
        return CrisisStatus(
            level=level,
            in_crisis=self._in_crisis,
            entry_level=self._entry_level,
            escalated=escalated,
            awaiting_confirmation=self._in_crisis and not self._confirmed,
            safe_turns_remaining=remaining,
            just_entered=just_entered,
            just_exited=just_exited,
        )
