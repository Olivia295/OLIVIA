"""Two-stage crisis assessment with safety-first arbitration.

Stage 1 looks for explicit plan, means or timing evidence and answers L3 without
consulting any model. Stage 2 asks a ``RiskModel`` (the rule model by default) for
a level and score, then arbitrates. Assessments carry cue ids only, never text.

An injected model can only raise the Stage 2 level above the rule model's, never lower
it, and a model that raises or answers out of contract counts as an L2 prediction
(``MODEL_FAILURE``): ``assess`` never raises because of the model.
"""

from __future__ import annotations

import math
import numbers
from bisect import bisect_right
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from itertools import accumulate
from typing import Final, Literal, Protocol

from olivia.core.models import CrisisLevel
from olivia.core.safety.lexicon import RiskCue, RiskSection, SafetyLexicons
from olivia.core.safety.matcher import Match, PhraseMatcher
from olivia.core.safety.normalize import normalize
from olivia.core.taxonomy import Taxonomy

_MATCHED_SECTIONS: Final[tuple[RiskSection, ...]] = ("stage1", "stage2", "hyperbole", "negation")
MODEL_FAILURE: Final = "MODEL_FAILURE"


@dataclass(frozen=True)
class RiskPrediction:
    level: CrisisLevel
    score: float
    cue_ids: tuple[str, ...]


class RiskModel(Protocol):
    """Stage 2 predictor; ``level`` is the 4-class head, ``score`` the crisis confidence."""

    def predict(self, text: str) -> RiskPrediction: ...


@dataclass(frozen=True)
class CrisisAssessment:
    level: CrisisLevel
    score: float
    stage: Literal["STAGE1", "STAGE2"]
    has_plan_evidence: bool
    cue_ids: tuple[str, ...]


def arbitrate(
    tax: Taxonomy, l_cls: CrisisLevel, score: float, has_plan_evidence: bool
) -> CrisisLevel:
    """Take the higher of the classifier level and the score band; L3 needs plan evidence."""
    level = max(l_cls, tax.crisis_level_for_score(score))
    if level is CrisisLevel.L3 and not has_plan_evidence:
        return CrisisLevel.L2
    return level


class _CueIndex:
    """One matcher over every stage1/stage2/hyperbole/negation phrase, keyed by cue id."""

    def __init__(self, lexicons: SafetyLexicons) -> None:
        phrases: dict[str, str] = {}
        cues: dict[str, RiskCue] = {}
        for section in _MATCHED_SECTIONS:
            for cue in lexicons.cues(section):
                cues[cue.id] = cue
                for phrase in cue.patterns:
                    phrases[phrase] = cue.id
        self.matcher = PhraseMatcher(phrases)
        self.cues: dict[str, RiskCue] = cues

    def scan(self, text: str) -> list[Match]:
        return self.matcher.find_all(text)


def _unique_ids(ids: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(ids))


def _cue_score(cue: RiskCue) -> float:
    # Lexicon validation guarantees a score on stage1, stage2 and hyperbole cues.
    if cue.score is None:
        raise ValueError(f"cue {cue.id} has no score")
    return cue.score


class _MaskCover:
    """Answers "does some mask fully contain this span?" in O(log n) per query."""

    def __init__(self, masks: Iterable[Match]) -> None:
        ordered = sorted(masks, key=lambda m: m.start)
        self._starts = [m.start for m in ordered]
        # _max_ends[i]: the furthest end among the masks starting no later than _starts[i].
        self._max_ends = list(accumulate((m.end for m in ordered), max))

    def contains(self, span: Match) -> bool:
        i = bisect_right(self._starts, span.start) - 1
        return i >= 0 and self._max_ends[i] >= span.end


class RuleRiskModel:
    """Lexicon-based Stage 2 model with hyperbole and negation masking."""

    def __init__(
        self, tax: Taxonomy, lexicons: SafetyLexicons, *, _index: _CueIndex | None = None
    ) -> None:
        self._tax = tax
        self._index = _index if _index is not None else _CueIndex(lexicons)
        self._score_hyperbole = tax.threshold("risk.lexicon_scores.HYPERBOLE")
        self._score_l0 = tax.threshold("risk.lexicon_scores.L0")

    def predict(self, text: str) -> RiskPrediction:
        return self.predict_matches(self._index.scan(normalize(text)))

    def predict_matches(self, matches: Sequence[Match]) -> RiskPrediction:
        """Score a prior scan of the normalized text (spans are only valid there)."""
        cues = self._index.cues
        masks: list[Match] = []
        stage2: list[Match] = []
        hyperbole_ids: list[str] = []
        for match in matches:
            section = cues[match.key].section
            if section == "stage2":
                stage2.append(match)
            elif section == "hyperbole":
                masks.append(match)
                hyperbole_ids.append(match.key)
            elif section == "negation":
                masks.append(match)

        covered = _MaskCover(masks)
        valid = [m for m in stage2 if not covered.contains(m)]
        if valid:
            score = max(_cue_score(cues[m.key]) for m in valid)
            level = self._tax.crisis_level_for_score(score)
            return RiskPrediction(level, score, _unique_ids(m.key for m in valid))
        if hyperbole_ids:
            return RiskPrediction(CrisisLevel.L0, self._score_hyperbole, _unique_ids(hyperbole_ids))
        return RiskPrediction(CrisisLevel.L0, self._score_l0, ())


class SafetyScreen:
    """Stage 1 plan-evidence check followed by Stage 2 model prediction and arbitration."""

    def __init__(
        self, tax: Taxonomy, lexicons: SafetyLexicons, model: RiskModel | None = None
    ) -> None:
        self._tax = tax
        self._index = _CueIndex(lexicons)
        # The rule model always shares this screen's scan. With no injected model it is the
        # Stage 2 model; with one, it is the floor the injected model can only raise.
        self._rule_model = RuleRiskModel(tax, lexicons, _index=self._index)
        self._model = model
        self._model_failure = RiskPrediction(
            CrisisLevel.L2, tax.threshold("risk.lexicon_scores.L2"), (MODEL_FAILURE,)
        )

    def assess(self, text: str) -> CrisisAssessment:
        normalized = normalize(text)
        matches = self._index.scan(normalized)
        cues = self._index.cues
        stage1 = [m for m in matches if cues[m.key].section == "stage1"]
        if stage1:
            score = max(_cue_score(cues[m.key]) for m in stage1)
            return CrisisAssessment(
                CrisisLevel.L3, score, "STAGE1", True, _unique_ids(m.key for m in stage1)
            )
        prediction = self._rule_model.predict_matches(matches)
        if self._model is not None:
            prediction = _with_floor(prediction, self._predict_safely(self._model, text))
        level = arbitrate(self._tax, prediction.level, prediction.score, has_plan_evidence=False)
        return CrisisAssessment(level, prediction.score, "STAGE2", False, prediction.cue_ids)

    def _predict_safely(self, model: RiskModel, text: str) -> RiskPrediction:
        """The injected model's prediction, or the L2 failure prediction when it breaks."""
        try:
            prediction = model.predict(text)
        except Exception:  # any model fault must fail toward safety, never crash the screen
            return self._model_failure
        checked = _checked_prediction(prediction)
        return self._model_failure if checked is None else checked


def _checked_prediction(prediction: object) -> RiskPrediction | None:
    """The prediction in canonical form (float score, tuple of str ids), or None if it is
    out of contract. Any ``numbers.Real`` score is accepted, so numpy floats work."""
    if not isinstance(prediction, RiskPrediction) or not isinstance(prediction.level, CrisisLevel):
        return None
    score: object = prediction.score
    if not isinstance(score, numbers.Real) or isinstance(score, bool):
        return None
    value = float(score)
    if not (math.isfinite(value) and 0.0 <= value <= 1.0):
        return None
    cue_ids: object = prediction.cue_ids
    if not isinstance(cue_ids, tuple | list) or not all(isinstance(c, str) for c in cue_ids):
        return None
    return RiskPrediction(prediction.level, value, tuple(cue_ids))


def _with_floor(rule: RiskPrediction, model: RiskPrediction) -> RiskPrediction:
    """Combine the rule floor with an injected model: the higher level and score win."""
    return RiskPrediction(
        max(rule.level, model.level),
        max(rule.score, model.score),
        _unique_ids((*rule.cue_ids, *model.cue_ids)),
    )
