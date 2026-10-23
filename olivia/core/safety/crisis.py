"""Two-stage crisis assessment with safety-first arbitration.

Stage 1 looks for explicit plan, means or timing evidence and answers L3 without
consulting any model. Stage 2 asks a ``RiskModel`` (the rule model by default) for
a level and score, then arbitrates. Assessments carry cue ids only, never text.

An injected model can only raise the Stage 2 level above the rule model's, never lower
it, and a model that raises or answers out of contract counts as an L2 prediction
(``MODEL_FAILURE``): ``assess`` never raises because of the model.

With ``model_plan_evidence=True`` (off by default, enabled only after the injected model
passes an independent evaluation), an injected model's own in-contract L3 prediction
counts as plan evidence, so Stage 2 can answer L3. The rule model's prediction and a
model failure never count as plan evidence.

Compositional cues (fix F1, ``safety/compose.py``) join two phrase lists across a short
gap. An L3 composition is Stage 1 plan evidence like a Stage 1 phrase; L1 and L2 ones are
rule-model cues that the negation and hyperbole masks can void, like Stage 2 phrases; ASK
ones are D3 cues, never masked, like the ask pairs.

``asks_intent`` (decision D3) is set when a rule ``ASK_INTENT`` cue fires: an L1 pair or
composition cue for a euphemistic request for a way to end a life, current self-injury,
a farewell, or a sense of being a burden. The screen only reports it; the session
decides to ask.
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
from olivia.core.safety.compose import Composer, CompositionHit
from olivia.core.safety.lexicon import PairCue, RiskCue, RiskSection, SafetyLexicons
from olivia.core.safety.matcher import Match, PhraseMatcher
from olivia.core.safety.normalize import normalize
from olivia.core.taxonomy import Taxonomy

_MATCHED_SECTIONS: Final[tuple[RiskSection, ...]] = ("stage1", "stage2", "hyperbole", "negation")
# Matcher keys of pair-cue phrases start with this; lexicon cue ids are printable text.
_PAIR_KEY: Final = "\x00"
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
    asks_intent: bool = False
    """An ``ASK_INTENT`` rule cue fired (decision D3): a euphemistic request for a way to
    end a life. Only the rules set it, never an injected model. The cue itself is L1; the
    session asks one direct question when the turn's level stays below L2."""


def arbitrate(
    tax: Taxonomy, l_cls: CrisisLevel, score: float, has_plan_evidence: bool
) -> CrisisLevel:
    """Take the higher of the classifier level and the score band; L3 needs plan evidence."""
    level = max(l_cls, tax.crisis_level_for_score(score))
    if level is CrisisLevel.L3 and not has_plan_evidence:
        return CrisisLevel.L2
    return level


class _CueIndex:
    """One matcher over every stage1/stage2/hyperbole/negation phrase, keyed by cue id,
    and every pair-cue phrase, keyed by the phrase behind ``_PAIR_KEY``."""

    def __init__(self, lexicons: SafetyLexicons) -> None:
        phrases: dict[str, str] = {}
        cues: dict[str, RiskCue] = {}
        for section in _MATCHED_SECTIONS:
            for cue in lexicons.cues(section):
                cues[cue.id] = cue
                for phrase in cue.patterns:
                    phrases[phrase] = cue.id
        # Lexicon validation keeps pair phrases disjoint from the risk phrases above. The
        # ask cues (decision D3) are pairs too; they fire at L1.
        pairs = (*lexicons.pairs, *lexicons.ask_pairs)
        for pair in pairs:
            for phrase in (*pair.anchors, *pair.requests, *pair.exceptions):
                phrases[phrase] = _PAIR_KEY + phrase
        self.matcher = PhraseMatcher(phrases)
        self.cues: dict[str, RiskCue] = cues
        self.pairs: tuple[PairCue, ...] = pairs
        self.composer = Composer(lexicons.compositions)
        self.ask_ids: frozenset[str] = frozenset(
            [
                *(p.id for p in lexicons.ask_pairs),
                *(c.id for c in lexicons.compositions.entries if c.ask),
            ]
        )

    def scan(self, text: str) -> list[Match]:
        return self.matcher.find_all(text)

    def compose(self, text: str) -> list[CompositionHit]:
        return self.composer.find(text)

    def fired_pairs(self, matches: Sequence[Match]) -> list[PairCue]:
        """Pair cues with a request and an anchor that none of their exceptions contains."""
        found: dict[str, list[Match]] = {}
        for match in matches:
            if match.key.startswith(_PAIR_KEY):
                found.setdefault(match.key[len(_PAIR_KEY) :], []).append(match)
        if not found:
            return []
        fired: list[PairCue] = []
        for pair in self.pairs:
            if not any(phrase in found for phrase in pair.requests):
                continue
            cover = _MaskCover(m for phrase in pair.exceptions for m in found.get(phrase, ()))
            anchors = (m for phrase in pair.anchors for m in found.get(phrase, ()))
            if any(not cover.contains(m) for m in anchors):
                fired.append(pair)
        return fired


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
        normalized = normalize(text)
        return self.predict_matches(self._index.scan(normalized), self._index.compose(normalized))

    def predict_matches(
        self, matches: Sequence[Match], compositions: Sequence[CompositionHit] = ()
    ) -> RiskPrediction:
        """Score a prior scan of the normalized text (spans are only valid there).

        L3 compositions are Stage 1 evidence and play no part here."""
        cues = self._index.cues
        masks: list[Match] = []
        stage2: list[Match] = []
        hyperbole_ids: list[str] = []
        for match in matches:
            cue = cues.get(match.key)
            section = None if cue is None else cue.section  # None: a pair phrase
            if section == "stage2":
                stage2.append(match)
            elif section == "hyperbole":
                masks.append(match)
                hyperbole_ids.append(match.key)
            elif section == "negation":
                masks.append(match)

        covered = _MaskCover(masks)
        valid = [m for m in stage2 if not covered.contains(m)]
        # Pair cues ignore the negation and hyperbole masks (only their own exceptions apply),
        # and so do ask compositions; L1 and L2 compositions are masked like stage2 phrases.
        pairs = self._index.fired_pairs(matches)
        phrase_level = max(
            [cues[m.key].level or CrisisLevel.L0 for m in valid] + [p.level for p in pairs],
            default=CrisisLevel.L0,
        )
        # A composition adds what the phrases miss: an L1 or L2 one counts only above the
        # phrase cues' level, so the cue ids of a turn the phrases already rate stay as they
        # were. An ask composition always counts: it sets the D3 flag.
        composed = [
            hit.entry
            for hit in compositions
            if hit.entry.ask
            or (
                hit.entry.level is not CrisisLevel.L3
                and hit.entry.level > phrase_level
                and not covered.contains(Match(hit.entry.id, hit.start, hit.end))
            )
        ]
        if valid or pairs or composed:
            score = max(
                [_cue_score(cues[m.key]) for m in valid]
                + [p.score for p in pairs]
                + [c.score for c in composed]
            )
            level = self._tax.crisis_level_for_score(score)
            ids = _unique_ids(
                [*(m.key for m in valid), *(p.id for p in pairs), *(c.id for c in composed)]
            )
            return RiskPrediction(level, score, ids)
        if hyperbole_ids:
            return RiskPrediction(CrisisLevel.L0, self._score_hyperbole, _unique_ids(hyperbole_ids))
        return RiskPrediction(CrisisLevel.L0, self._score_l0, ())


class SafetyScreen:
    """Stage 1 plan-evidence check followed by Stage 2 model prediction and arbitration.

    ``model_plan_evidence`` lets an injected model's own L3 prediction supply the plan
    evidence Stage 2 arbitration needs for L3; it has no effect without an injected model.
    """

    def __init__(
        self,
        tax: Taxonomy,
        lexicons: SafetyLexicons,
        model: RiskModel | None = None,
        *,
        model_plan_evidence: bool = False,
    ) -> None:
        self._tax = tax
        self._index = _CueIndex(lexicons)
        # The rule model always shares this screen's scan. With no injected model it is the
        # Stage 2 model; with one, it is the floor the injected model can only raise.
        self._rule_model = RuleRiskModel(tax, lexicons, _index=self._index)
        self._model = model
        self._model_plan_evidence = model_plan_evidence
        self._model_failure = RiskPrediction(
            CrisisLevel.L2, tax.threshold("risk.lexicon_scores.L2"), (MODEL_FAILURE,)
        )

    def assess(self, text: str) -> CrisisAssessment:
        normalized = normalize(text)
        matches = self._index.scan(normalized)
        cues = self._index.cues
        stage1 = [m for m in matches if m.key in cues and cues[m.key].section == "stage1"]
        composed = self._index.compose(normalized)
        # Like the Stage 2 compositions, an L3 one is reported only when no Stage 1 phrase
        # already gives the plan evidence.
        plans = [] if stage1 else [h.entry for h in composed if h.entry.level is CrisisLevel.L3]
        if stage1 or plans:
            score = max([_cue_score(cues[m.key]) for m in stage1] + [c.score for c in plans])
            ids = _unique_ids([*(m.key for m in stage1), *(c.id for c in plans)])
            return CrisisAssessment(CrisisLevel.L3, score, "STAGE1", True, ids)
        prediction = self._rule_model.predict_matches(matches, composed)
        asks_intent = not self._index.ask_ids.isdisjoint(prediction.cue_ids)
        has_plan_evidence = False
        if self._model is not None:
            model_prediction = self._predict_safely(self._model, text)
            # Only the injected model's own L3 counts; the failure prediction is L2, never L3.
            has_plan_evidence = (
                self._model_plan_evidence
                and model_prediction is not self._model_failure
                and model_prediction.level is CrisisLevel.L3
            )
            prediction = _with_floor(prediction, model_prediction)
        level = arbitrate(self._tax, prediction.level, prediction.score, has_plan_evidence)
        return CrisisAssessment(
            level, prediction.score, "STAGE2", has_plan_evidence, prediction.cue_ids, asks_intent
        )

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
