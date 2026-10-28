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
While a confirmation is awaited, an explicit confirmation that only an injected model
raises to L2 or L3 (the turn's ``rule_level`` is below L2, and the model did not fail) is
tracked at the rules' level, so the model's L2 alone does not make it a relapse (F8a).
Outside a crisis, an L1 turn that only an injected model gives (the rules' level is L0)
is reported as L1 but counts for the escalation trend as an L0 turn would (F8a), so a
run of everyday turns the student alone rates L1 never escalates into crisis.
The screen's denial cap (F10: a first-person denial or all-clear that only an injected
model rates L2/L3 counts as L1) is for a turn outside a crisis: in a crisis the tracker
reads the turn's uncapped level (``CrisisAssessment.uncapped_level``), so in a crisis
such a turn is tracked exactly as without the cap.
A farewell, last words, affairs arranged or a resolve (a D3 cue marked ``raise_with_risk``
in risk.yaml) outside a crisis escalates to L2 at once, instead of asking, when the session
already showed risk: an earlier L1 turn of the current run or an earlier crisis
(2026-10-26).
The "X得 / 到想死" figure of speech that the screen reads as a D3 question (owner decision
2026-10-28, ``ASK_INTENT_HYPERBOLE_DIE``) escalates to L2 at once, outside a crisis, when
the session showed any other risk before: an earlier turn whose rule level was L1 or
above or that carried a D3 cue (the figure itself does not count, so a second one after a
clear no asks again), or an earlier crisis.
S5 (2026-10-26): besides the ``safety_confirm`` phrases and the whole-message short yes, one
clause of a longer message that says the user is safe ("我现在在家，是安全的", "是的，我现在
安全，已经给我姐打了电话") confirms, but only when the screen found no rule risk cue in the
message (``CrisisAssessment.rule_clear``) and no F10 denial veto or contrast and no
confirm veto occurs in it; the exit rule after a confirmation is unchanged.
Round 3 (2026-10-27, re-test r2 第 5 节): a promise not to harm oneself ("我答应你今晚不会
做什么傻事", "我保证不会做傻事") confirms like a safe clause, under the same guards, and
"I am safe now" is a short yes; the exit rule after a confirmation is unchanged.
The tracker keeps numbers and flags only; it never stores user text.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from typing import Final

from olivia.core.models import CrisisLevel
from olivia.core.safety.crisis import MODEL_FAILURE, CrisisAssessment
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
# A short yes to the question every crisis reply asks until safety is confirmed
# ("你现在是安全的吗？"), as the whole
# message: an optional 嗯, an optional 是(的)/对(的), then an optional "(我)(是|很|挺)安全
# (的|了|啦)". It must contain 是, 对 or 安全, so a bare "嗯" (an acknowledgement, not an
# answer) never counts. Anything with a negation, a hedge or a new cue does not match.
_DIRECT_ANSWER: Final = re.compile(
    r"(?:嗯+|恩+)?(?:(?:是|对)的?)?(?:我?(?:是|很|挺)?安全(?:的|了|啦)?)?(?:哦|呀|啊)?"
)
_DIRECT_ANSWER_WORDS: Final[tuple[str, ...]] = ("是", "对", "安全")
# S5 (2026-10-26): one clause of a longer message that says the user is safe ("我现在在家，
# 是安全的", "是的，我现在安全，已经给我姐打了电话"), read after the fillers are dropped. It
# is the short answer's grammar, optionally after "在家", and must say 安全; the message
# must carry no rule risk cue, no F10 denial veto or contrast and no confirm veto.
_CLAUSE_SPLIT: Final = re.compile(r"[,.!?;:、。！？，；：~…\s]+")
_SAFE_CLAUSE: Final = re.compile(
    r"(?:嗯+|恩+)?(?:(?:是|对)的?)?我?(?:在家里?)?(?:是|很|挺)?安全(?:的|了|啦)?(?:哦|呀|啊|呢)?"
)
_DIRECT_ANSWER_ENGLISH: Final[frozenset[str]] = frozenset(
    {"yes", "yeah", "yep", "i'msafe", "iamsafe", "imsafe", "yesi'msafe", "yesiamsafe"}
)
# Round 3 (2026-10-27): "I am safe now", "yes, I'm safe right now" (folded, no spaces, no
# punctuation), as the whole message.
_ENGLISH_SAFE: Final = re.compile(
    r"(?:yes|yeah|yep|ok|okay)?(?:i'm|im|iam)(?:totally|really|completely|perfectly)?"
    r"safe(?:now|rightnow)?(?:thanks|thankyou|don'tworry|dontworry|promise)?"
)
# Round 3 (2026-10-27, re-test r2 第 5 节): a promise not to harm oneself, as the whole
# message or one clause of it ("我答应你今晚不会做什么傻事", "我答应你，今晚不会做什么",
# "我保证不会做傻事"). Either a promise verb or an object that names the harm (傻事, 伤害
# 自己); never a plain "不会" alone. Read like the safe clause: no rule risk cue, no F10
# veto or contrast and no confirm veto in the message.
_PROMISE: Final = re.compile(
    r"(?:嗯+|好+的?|放心吧?)?我?(?:答应你|向你保证|跟你保证|保证|发誓)我?"
    r"(?:今晚|今天|今天晚上|晚上|这几天)?(?:绝对|肯定|一定)?不会(?:做|干|去做)?"
    r"(?:什么|啥|任何)?(?:傻事|蠢事|事|伤害自己的事)?(?:的|了|啦)?"
    r"|我?(?:今晚|今天|这几天)?(?:绝对|肯定|一定)?不会(?:做|干|去做)(?:傻事|蠢事|伤害自己的事)"
    r"(?:的|了|啦)?"
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
    if bare in _DIRECT_ANSWER_ENGLISH or _ENGLISH_SAFE.fullmatch(bare) is not None:
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
        self._raise_ids = frozenset(
            entry.id for entry in lexicons.compositions.entries if entry.raise_with_risk
        )
        self._figure_id = lexicons.hyperbole_ask.id
        # The F10 denial conditions guard the clause reading (S5): any veto or contrast of
        # the ``denial`` section anywhere in the message voids it.
        guards = (*lexicons.denial.vetoes, *lexicons.denial.contrasts)
        self._clause_guard = PhraseMatcher({p: p for p in guards}) if guards else None

        self._run = 0
        self._last_l1_valence: float | None = None
        self._l0_streak = 0

        self._in_crisis = False
        self._entry_level: CrisisLevel | None = None
        self._confirmed = False
        self._safe_turns = 0
        self._had_crisis = False
        # Some turn of this session carried a rule risk cue other than the figure of speech
        # (owner decision 2026-10-28).
        self._risk_seen = False

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
        if self._in_crisis and assessment.uncapped_level is not None:
            # The denial cap (F10) applies outside a crisis only.
            assessment = replace(assessment, level=assessment.uncapped_level)
        rules_level = self._model_only_relapse(assessment, text)
        assessed = assessment.level if rules_level is None else rules_level
        usable = valence if valence is not None and math.isfinite(valence) else None
        trend = assessed
        if (
            not self._in_crisis
            and assessed is CrisisLevel.L1
            and assessment.rule_level is CrisisLevel.L0
        ):
            trend = CrisisLevel.L0  # a model-only L1 is not part of an L1 run (F8a)
        self._update_trend(trend, usable)

        level = assessed
        escalated = trend is CrisisLevel.L1 and (
            self._run >= self._streak
            or self._asks_again(assessment)
            or self._figure_after_risk(assessment)
        )
        self._note_risk(assessment)
        if escalated:
            level = CrisisLevel.L2

        just_entered = False
        just_exited = False
        if level >= CrisisLevel.L2:
            self._had_crisis = True
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
            just_exited = self._observe_safe_candidate(level, text, assessment)

        return self._status(level, escalated, just_entered, just_exited)

    def _model_only_relapse(self, assessment: CrisisAssessment, text: str) -> CrisisLevel | None:
        """The rules' level of an awaited explicit confirmation that only an injected model
        puts at L2 or above (F8a), else None."""
        rule = assessment.rule_level
        if (
            self._in_crisis
            and not self._confirmed
            and rule is not None
            and rule < CrisisLevel.L2 <= assessment.level
            and MODEL_FAILURE not in assessment.cue_ids
            and self._is_explicit_confirmation(normalize(text), assessment)
        ):
            return rule
        return None

    def _asks_again(self, assessment: CrisisAssessment) -> bool:
        """A farewell, last words, affairs arranged or a resolve (a D3 cue marked
        ``raise_with_risk``) outside a crisis in a session that already showed risk: an
        earlier L1 turn of the current run (this turn is already counted, so the run is at
        least 2) or an earlier crisis. It escalates to L2 like a full L1 run instead of
        asking (2026-10-26)."""
        return (
            not self._in_crisis
            and assessment.asks_intent
            and not self._raise_ids.isdisjoint(assessment.cue_ids)
            and (self._run >= 2 or self._had_crisis)
        )

    def _is_figure(self, assessment: CrisisAssessment) -> bool:
        return bool(self._figure_id) and self._figure_id in assessment.cue_ids

    def _figure_after_risk(self, assessment: CrisisAssessment) -> bool:
        """The "X得 / 到想死" figure (a D3 cue) outside a crisis in a session that already
        showed other risk or a crisis: L2 at once instead of the question (owner decision
        2026-10-28)."""
        return (
            not self._in_crisis
            and assessment.asks_intent
            and self._is_figure(assessment)
            and (self._risk_seen or self._had_crisis)
        )

    def _note_risk(self, assessment: CrisisAssessment) -> None:
        """Remember a turn whose rules saw risk (rule level L1 or above, or a D3 cue), the
        figure of speech alone excepted."""
        if self._is_figure(assessment):
            return
        rule = assessment.rule_level or CrisisLevel.L0
        if rule >= CrisisLevel.L1 or assessment.asks_intent:
            self._risk_seen = True

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

    def _observe_safe_candidate(
        self, level: CrisisLevel, text: str, assessment: CrisisAssessment
    ) -> bool:
        """Handle a turn at effective level <= L1 while in crisis; True when it exits."""
        entry = self._entry_level
        if entry is None:  # unreachable: in_crisis always has an entry level
            return False
        if not self._confirmed:
            if self._is_explicit_confirmation(normalize(text), assessment):
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

    def _is_explicit_confirmation(self, normalized: str, assessment: CrisisAssessment) -> bool:
        """A safety_confirm phrase, a short yes to the crisis reply's safety question, or a
        clause that says so in a longer message (S5, :meth:`_safe_clause`).

        Every crisis reply asks whether the user is safe now until a confirmation counts
        (after it, the opening no longer asks, F5b), so while a confirmation is awaited the
        previous reply always asked it: a whole-message yes ("是的", "安全的",
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
        if _is_direct_answer(compact):
            return True
        return self._safe_clause(normalized, compact, assessment)

    def _safe_clause(self, normalized: str, compact: str, assessment: CrisisAssessment) -> bool:
        """One clause says the user is safe ("我现在在家，是安全的"; S5, 2026-10-26).

        Only when the screen found no rule risk cue in the message
        (``CrisisAssessment.rule_clear``) and no F10 denial veto or contrast occurs in it,
        so "我是安全的，可是药还在" or "我现在安全，就是今晚不想睡" never counts."""
        if not assessment.rule_clear:
            return False
        # Round 3: a message that is nothing but a promise ("我答应你，今晚不会做什么"): its
        # time word is the promise's own scope, so the F10 time vetoes do not apply to it.
        if _PROMISE.fullmatch(compact.translate(_ANSWER_PUNCTUATION)) is not None:
            return True
        if self._clause_guard is not None and self._clause_guard.find_all(normalized):
            return False
        clauses = [c.translate(_ANSWER_PUNCTUATION) for c in _CLAUSE_SPLIT.split(compact)]
        return any(
            c and (_SAFE_CLAUSE.fullmatch(c) is not None or _PROMISE.fullmatch(c) is not None)
            for c in clauses
        )

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
