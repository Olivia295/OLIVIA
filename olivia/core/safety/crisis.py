"""Two-stage crisis assessment with safety-first arbitration.

Stage 1 looks for explicit plan, means or timing evidence and answers L3 without
consulting any model. Stage 2 asks a ``RiskModel`` (the rule model by default) for
a level and score, then arbitrates. Assessments carry cue ids only, never text.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final, Literal, Protocol

from olivia.core.models import CrisisLevel
from olivia.core.safety.lexicon import RiskCue, RiskSection, SafetyLexicons
from olivia.core.safety.matcher import Match, PhraseMatcher
from olivia.core.safety.normalize import normalize
from olivia.core.taxonomy import Taxonomy

_MATCHED_SECTIONS: Final[tuple[RiskSection, ...]] = ("stage1", "stage2", "hyperbole", "negation")


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

        valid = [
            m
            for m in stage2
            if not any(m.start >= mask.start and m.end <= mask.end for mask in masks)
        ]
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
        # The default rule model shares this screen's scan; an injected model gets raw text.
        self._rule_model: RuleRiskModel | None = None
        self._model: RiskModel
        if model is None:
            self._rule_model = RuleRiskModel(tax, lexicons, _index=self._index)
            self._model = self._rule_model
        else:
            self._model = model

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
        if self._rule_model is not None:
            prediction = self._rule_model.predict_matches(matches)
        else:
            prediction = self._model.predict(text)
        level = arbitrate(self._tax, prediction.level, prediction.score, has_plan_evidence=False)
        return CrisisAssessment(level, prediction.score, "STAGE2", False, prediction.cue_ids)
