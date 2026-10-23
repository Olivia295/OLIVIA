"""Cross-turn crisis tracking: L1 escalation, crisis entry and confirmed exit.

Escalation (PRD 9.1, owner decision 2026-10-24): ``risk.ewma_streak`` (3) L1 turns in a
row *without improvement* raise the third one to L2, which enters crisis. An L1 turn
improves when its valence is known and higher than the last L1 turn's known valence; the
count then starts again at 0. An L0 turn improves when it is calm (a known valence at or
above 0, that is a calm or positive feeling) or its known valence is higher than the last
L1 turn's; it then resets the count. Valence ``None`` (no emotion evidence) is never an
improvement. Any other L0 turn pauses the count (neither counts nor resets it), and
``risk.l1_clear_streak`` L0 turns in a row reset it whatever their valence. Every turn at
L2 or above, crisis entry included, and crisis exit reset it too.

Exit from crisis needs an explicit safety confirmation followed by N safe (L0) turns, so
a single calm message never switches emergency resources off. After confirmation an L1
turn pauses the count: it neither counts as safe nor resets the turns already counted.
The tracker keeps numbers and flags only; it never stores user text.
"""

from __future__ import annotations

import math
import re
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
# Gap tolerance: these adverbs are dropped from both the message and the safety_confirm
# phrases before matching, so "我已经联系上朋友了" matches "我联系上朋友了" and
# "我现在是安全的" matches "我是安全的". Vetoes are still read on the whole message.
_CONFIRM_FILLERS: Final[tuple[str, ...]] = ("已经", "现在", "都")
# Punctuation dropped before reading a short direct answer ("是的，安全的。").
_ANSWER_PUNCTUATION: Final = str.maketrans("", "", ",.!~…、。！ ")
# A short yes to the question every crisis reply asks ("你现在是安全的吗？"), as the whole
# message: an optional 嗯, an optional 是(的)/对(的), then an optional "(我)(是|很|挺)安全
# (的|了|啦)". It must contain 是, 对 or 安全, so a bare "嗯" (an acknowledgement, not an
# answer) never counts. Anything with a negation, a hedge or a new cue does not match.
_DIRECT_ANSWER: Final = re.compile(
    r"(?:嗯+|恩+)?(?:(?:是|对)的?)?(?:我?(?:是|很|挺)?安全(?:的|了|啦)?)?(?:哦|呀|啊)?"
)
_DIRECT_ANSWER_WORDS: Final[tuple[str, ...]] = ("是", "对", "安全")
_DIRECT_ANSWER_ENGLISH: Final[frozenset[str]] = frozenset(
    {"yes", "yeah", "yep", "i'msafe", "iamsafe", "imsafe", "yesi'msafe", "yesiamsafe"}
)
# An L0 turn with a known valence at or above this is calm: it resets the escalation count.
_CALM_VALENCE: Final = 0.0
# Valence must rise by more than this to count as an improvement (float noise guard).
_VALENCE_EPSILON: Final = 1e-9


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
    consecutive_l1_count: int = 0
    """L1 turns without improvement in the current run (see ``CrisisTracker``)."""


def _whole_threshold(tax: Taxonomy, path: str) -> int:
    value = tax.threshold(path)
    if not value.is_integer() or value < 1:
        raise ValueError(f"taxonomy threshold {path} must be a positive whole number, got {value}")
    return int(value)


def _compact(text: str) -> str:
    for filler in _CONFIRM_FILLERS:
        text = text.replace(filler, "")
    return text


def _is_direct_answer(compact: str) -> bool:
    bare = compact.translate(_ANSWER_PUNCTUATION)
    if bare in _DIRECT_ANSWER_ENGLISH:
        return True
    return _DIRECT_ANSWER.fullmatch(bare) is not None and any(
        word in bare for word in _DIRECT_ANSWER_WORDS
    )


class CrisisTracker:
    """Stateful per-session tracker; call ``observe`` exactly once per user turn."""

    def __init__(self, tax: Taxonomy, lexicons: SafetyLexicons) -> None:
        self._tax = tax
        self._streak = _whole_threshold(tax, "risk.ewma_streak")
        self._clear_streak = _whole_threshold(tax, "risk.l1_clear_streak")
        phrases: dict[str, str] = {}
        for cue in lexicons.cues("safety_confirm"):
            for phrase in cue.patterns:
                compact = _compact(phrase)
                if compact:
                    phrases.setdefault(compact, cue.id)
        self._confirm_matcher = PhraseMatcher(phrases)
        self._veto_matcher = PhraseMatcher(
            {phrase: cue.id for cue in lexicons.cues("confirm_veto") for phrase in cue.patterns}
        )

        self._run = 0
        self._last_l1_valence: float | None = None
        self._l0_streak = 0

        self._in_crisis = False
        self._entry_level: CrisisLevel | None = None
        self._confirmed = False
        self._safe_turns = 0

    @property
    def consecutive_l1_count(self) -> int:
        """L1 turns without improvement in the current run: the session's one count of record.

        An improving turn (see the module docstring), ``risk.l1_clear_streak`` L0 turns in a
        row, any L2/L3 turn and crisis exit reset it to 0; any other L0 turn leaves it as it
        is. ``SessionState.consecutive_l1_count`` mirrors this value each turn and is never
        counted separately.
        """
        return self._run

    def observe(
        self, assessment: CrisisAssessment, text: str, valence: float | None = None
    ) -> CrisisStatus:
        """Track one user turn. ``valence`` is ``None`` when there is no emotion evidence."""
        assessed = assessment.level
        usable = valence if valence is not None and math.isfinite(valence) else None
        self._update_trend(assessed, usable)

        level = assessed
        escalated = assessed is CrisisLevel.L1 and self._run >= self._streak
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
            # The L1 escalation count starts afresh after any crisis-level turn, so earlier
            # L1 turns never lift later ones into a spurious escalation.
            self._reset_trend()
        elif self._in_crisis:
            just_exited = self._observe_safe_candidate(level, text)

        return self._status(level, escalated, just_entered, just_exited)

    def _update_trend(self, assessed: CrisisLevel, valence: float | None) -> None:
        if assessed is CrisisLevel.L1:
            self._l0_streak = 0
            self._run = 0 if self._rose(valence) else self._run + 1
            if valence is not None:
                self._last_l1_valence = valence
        elif assessed is CrisisLevel.L0:
            self._l0_streak += 1
            calm = valence is not None and valence >= _CALM_VALENCE
            if calm or self._rose(valence) or self._l0_streak >= self._clear_streak:
                self._reset_trend()
        else:
            self._l0_streak = 0

    def _rose(self, valence: float | None) -> bool:
        last = self._last_l1_valence
        return valence is not None and last is not None and valence - last > _VALENCE_EPSILON

    def _reset_trend(self) -> None:
        self._run = 0
        self._last_l1_valence = None

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
        """A safety_confirm phrase, or a short yes to the crisis reply's safety question.

        Every crisis reply asks whether the user is safe now, so while a confirmation is
        awaited the previous reply always asked it: a whole-message yes ("是的", "安全的",
        "嗯 安全") then answers it. That closed grammar leaves no room for a negation, a
        hedge or a crisis cue, so it is read whatever level a risk model gave the turn;
        vetoes, a question and a negation in front of a phrase still win over both paths.
        """
        if self._veto_matcher.find_all(normalized):
            return False
        if normalized.rstrip(_TRAILING_PUNCTUATION).endswith(_QUESTION_ENDINGS):
            return False
        compact = _compact(normalized)
        hits = self._confirm_matcher.find_all(compact)
        if any(not compact[: hit.start].endswith(_NEGATING_PREFIXES) for hit in hits):
            return True
        return _is_direct_answer(compact)

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
            consecutive_l1_count=self._run,
        )
