"""Two-stage crisis assessment with safety-first arbitration.

Stage 1 looks for explicit plan, means or timing evidence and answers L3 without
consulting any model. Stage 2 asks a ``RiskModel`` (the rule model by default) for
a level and score, then arbitrates. Assessments carry cue ids only, never text.

An injected model can only raise the Stage 2 level above the rule model's, never lower
it, and a model that raises or answers out of contract counts as an L2 prediction
(``MODEL_FAILURE``): ``assess`` never raises because of the model.

An injected model's level is the higher of its own level and its score's band (owner
decision 2026-10-24, F8a: the band keeps the model's recall). A rule score always lies
in its own level's band (lexicon validation), so for the rules the band changes nothing.
Where the rules read every risk phrase of the message as a figure of speech (a hyperbole
cue such as ``HYP_MISS_YOU`` covers each one, and no other cue fires), that model level
counts at most as L1 (F8a). Negation masks get no such cap: the model's L2 on a double
negation is what the rules miss. ``CrisisAssessment.rule_level`` carries the rules' own
level, which the tracker reads (``tracker.py``).

The note recall cap (F16a) works the same way: where the rules rate a message L0, a note
recall phrase (``recall_cap``: perception.yaml's ``note_recall`` and
``note_recall_questions``, "我妈生日是哪天来着") occurs in it, no phrase of any risk, pair,
composition or denial section does, no ``recall_cap`` veto (a means, death, farewell or
no-waking word) does and the model did not fail, the model's level counts at most as L1.

The denial cap (F10) is narrower still: where the rules rate a message L0, a ``denial``
phrase ("我不会伤害自己", "我不想死，只是很累", "我已经好多了") covers every Stage 2 phrase, no
negator stands right before a denial, no contrast follows the first one, no veto (double
negation, retraction, hedge, time, means, farewell, preparation) and no composition is in
the message and the model did not fail, the model's level counts at most as L1. The
uncapped level rides along as ``CrisisAssessment.uncapped_level``; in a crisis the
tracker reads it, so the cap only changes a turn outside a crisis.

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
decides to ask. An ask composition marked ``raise_with_risk`` (a farewell, the last words,
affairs arranged, a resolve) next to a risk cue of the user's own in the same message (a
Stage 2 phrase outside its span, a method pair, an L1 / L2 composition) makes the rule
level L2 (2026-10-26); the tracker does the same after earlier risk in the session.

Someone else's reported words (2026-10-26, ``safety/reported.py``): when every Stage 2
phrase of a message is a third person's speech the user reports ("她跟我说她不想活了") and
no pair or composition cue fires, the rule model voids those phrases. Only the rules: an
injected model's level is not capped.

``reported_risk`` (问题单第 6 条, 2026-10-26) reads those reported words on their own: it
screens each span of someone else's words (``ReportedSpeech.contents``) as if the user had
said it, and says whether every rule cue of the message lies inside them. It never changes
``assess``; the session uses it to answer with resources to pass on instead of the crisis
flow.

The "X得 / 到想死" figure of speech (owner decision 2026-10-28, ``risk.yaml``
``hyperbole_ask``): when every Stage 2 phrase that counts lies inside a frame ("烦得想死",
"加班加到想死", "激到我想死"), no other rule cue occurs (another Stage 2, negation or
pair-anchor phrase, a pair cue, a composition) and no veto does (真的, 不是开玩笑, 那种, a run
of days, a plan, a time, a means, a farewell, another death word), the rule model gives
L1 with ``ASK_INTENT_HYPERBOLE_DIE`` (a D3 cue: ``asks_intent``) instead of L2, and an
injected model counts at most as L1 (a model failure is still L2; its L3 is no plan
evidence). Anything else keeps the frame's L2. The tracker raises it to L2 when the
session already showed risk (``tracker.py``).

``rule_clear`` (owner decision 2026-10-26) says the rules found no risk cue at all
(:func:`rules_found_nothing`): the session then asks once before a crisis level that
only the injected model gives, and the tracker may read a safety clause in a longer
message (S5). ``clear_denial`` is the stricter no to that question: the D3 no must also
pass the F10 denial conditions.
"""

from __future__ import annotations

import math
import numbers
from bisect import bisect_right
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import accumulate
from typing import Final, Literal, Protocol

from olivia.core.models import CrisisLevel
from olivia.core.safety.compose import Composer, CompositionHit
from olivia.core.safety.lexicon import (
    Composition,
    DenialRules,
    HyperboleAskRules,
    PairCue,
    RecallCapRules,
    RiskCue,
    RiskSection,
    SafetyLexicons,
)
from olivia.core.safety.matcher import Match, PhraseMatcher
from olivia.core.safety.normalize import bidi_readings, normalize
from olivia.core.safety.reported import ReportedSpeech, farewell_strength, names_death
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
    """Stage 2 predictor; ``level`` is the 4-class head, ``score`` the crisis confidence.

    For an injected model the screen takes the higher of ``level`` and the band of
    ``score`` (see the module docstring for the hyperbole cap)."""

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
    rule_level: CrisisLevel | None = None
    """The rules' own level for the turn, before any injected model (F8a): equal to
    ``level`` without a model. The tracker reads it: an L1 only a model gives does not join
    an L1 run, and a model's L2 alone does not turn an awaited explicit safety confirmation
    into a relapse. ``None`` when not set (no rule exemption applies)."""
    uncapped_level: CrisisLevel | None = None
    """The turn's level without the denial cap (F10), set only when that cap lowered it:
    outside a crisis a first-person denial or all-clear that only an injected model rates
    L2/L3 counts as L1, and in a crisis the tracker reads this level instead."""
    rule_clear: bool = False
    """The rules found no risk cue at all in the message (owner decision 2026-10-26; see
    :func:`rules_found_nothing`). ``False`` unless the screen checked: an assessment built
    by hand never counts as clear, so nothing relaxes for it."""


@dataclass(frozen=True)
class ReportedRisk:
    """Someone else's reported words in a message (``SafetyScreen.reported_risk``)."""

    level: CrisisLevel
    """The reported words' own level, screened as if the user had said them."""
    plan: bool
    """They carry plan evidence (Stage 1), or the injected model's own class is L3."""
    user_clear: bool
    """Every rule cue of the message lies inside the reported words."""
    rule_risk: bool = False
    """The rules themselves find risk in the reported words (L1 or above, or a D3 cue).
    The model's level on a short reported clause out of context is no evidence alone:
    "过一阵子就好了" (someone's comfort) is not someone else's risk (re-test 2026-10-27)."""
    anchor: bool = False
    """A death word the rules know only as a pair anchor (自杀, "end my life") lies in the
    reported words (round 3), or (round 4, 2026-10-28) a word for dying by one's own hand
    (去死, 跳楼; ``reported.names_death``) the rules may miss: with a time or a means it is
    someone else's plan."""
    farewell: int = 0
    """A farewell in the reported words (round 4; ``reported.farewell_strength``): 2 for a
    strong one ("永别了"), which opens the card alone, 1 for a weak one ("大家再见了"),
    which opens it only with a means or a place in the message."""


def rules_found_nothing(
    rule_level: CrisisLevel,
    matches: Sequence[Match],
    cues: Mapping[str, RiskCue],
    pair_anchor_keys: frozenset[str],
    compositions: Sequence[CompositionHit],
    asks_intent: bool,
) -> bool:
    """The definition of "no rule risk cue" (规则风险线索为零, owner decision 2026-10-26).

    A message is clear of rule risk cues only when all of these hold on its normalized
    text:

    * the rule model's level is L0 (so no Stage 2 phrase or pair counted, no L1 run);
    * no phrase of ``stage1``, ``stage2``, ``hyperbole`` or ``negation`` occurs at all,
      masked or not ("想死的心都有了", "我不想死" are cues here: the rules saw a death word);
    * no anchor phrase of a ``stage2_pairs`` or ``stage2_ask`` cue occurs (自杀, 轻生, 想走了,
      结束这一切, 别劝我 ...), even without its request word and even inside an exception;
    * no composition matched, at any level (L3 plan evidence, L2, L1 or ASK: euphemism,
      farewell, burden, self-injury; an ASK one marked ``raise_with_risk`` too), whether
      or not it counted for the level;
    * no ``ASK_INTENT`` cue fired (``asks_intent``).

    Someone else's reported words (``safety/reported.py``) count as cues as well: the rule
    model voids such a Stage 2 phrase to L0, but the phrase still occurs, so the rules did
    see a death phrase and a model alarm on it is not "the rules found nothing".

    Stage 1 never reaches this test (it answers L3 first). Pair request words alone (方法,
    步骤) and the denial, recall and safety-confirmation phrases are not risk cues. A
    model failure is not the screen's business here: the session treats it as an alarm.
    """
    if rule_level is not CrisisLevel.L0 or asks_intent or compositions:
        return False
    return not any(m.key in cues or m.key in pair_anchor_keys for m in matches)


def arbitrate(
    tax: Taxonomy, l_cls: CrisisLevel, score: float, has_plan_evidence: bool
) -> CrisisLevel:
    """Take the higher of the classifier level and the score band; L3 needs plan evidence.

    ``SafetyScreen`` passes the rule score here and folds an injected model's score band
    into the model's level first, so that the hyperbole cap (F8a) and the denial cap (F10)
    can apply to it."""
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
        # Every pair anchor (自杀, 想走了 ...): a rule risk cue even without its request word.
        self.pair_anchor_keys: frozenset[str] = frozenset(
            _PAIR_KEY + phrase for pair in pairs for phrase in pair.anchors
        )
        self.composer = Composer(lexicons.compositions)
        self.denial = _DenialIndex(lexicons.denial)
        self.recall = _RecallIndex(lexicons.recall_cap)
        self.reported = ReportedSpeech(lexicons.reported_speech, lexicons.compositions)
        self.figure = _FigureIndex(lexicons.hyperbole_ask)
        self.ask_ids: frozenset[str] = frozenset(
            [
                *(p.id for p in lexicons.ask_pairs),
                *(c.id for c in lexicons.compositions.entries if c.ask),
                *([self.figure.id] if self.figure.id else []),
            ]
        )

    def scan(self, text: str) -> list[Match]:
        return self.matcher.find_all(text)

    def figurative_only(self, matches: Sequence[Match]) -> bool:
        """At least one Stage 2 phrase matched and a hyperbole cue covers every one (F8a)."""
        sections = [(m, self.cues[m.key].section) for m in matches if m.key in self.cues]
        stage2 = [m for m, section in sections if section == "stage2"]
        cover = _MaskCover(m for m, section in sections if section == "hyperbole")
        return bool(stage2) and all(cover.contains(m) for m in stage2)

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


class _DenialIndex:
    """The ``denial`` phrases (F10) with their negators, contrasts and vetoes."""

    def __init__(self, rules: DenialRules) -> None:
        self._phrases = PhraseMatcher({p: p for p in rules.phrases}) if rules.phrases else None
        self._contrasts = PhraseMatcher({p: p for p in rules.contrasts})
        self._vetoes = PhraseMatcher({p: p for p in rules.vetoes})
        self._negators = tuple(rules.negators)

    def mentioned(self, normalized: str) -> bool:
        """Some denial phrase occurs in the message (negated or not)."""
        return self._phrases is not None and bool(self._phrases.find_all(normalized))

    def denies(
        self, normalized: str, matches: Sequence[Match], cues: Mapping[str, RiskCue]
    ) -> bool:
        """A denial covers every Stage 2 phrase, with no negator right before any denial,
        no contrast after the first one and no veto anywhere in the message."""
        if self._phrases is None:
            return False
        hits = self._phrases.find_all(normalized)
        if not hits or any(normalized[: h.start].endswith(self._negators) for h in hits):
            return False
        if self._vetoes.find_all(normalized):
            return False
        first_end = min(h.end for h in hits)
        if any(c.start >= first_end for c in self._contrasts.find_all(normalized)):
            return False
        cover = _MaskCover(hits)
        stage2 = [m for m in matches if m.key in cues and cues[m.key].section == "stage2"]
        return all(cover.contains(m) for m in stage2)

    def clears(
        self, normalized: str, matches: Sequence[Match], cues: Mapping[str, RiskCue]
    ) -> bool:
        """The F10 conditions on a no, with no denial phrase required (2026-10-26): no
        negator right before a denial, no veto and no contrast anywhere, and every Stage 2
        phrase inside a denial ("不是，我不想死" passes, "不是，可是今晚……" does not)."""
        hits = self._phrases.find_all(normalized) if self._phrases is not None else []
        if any(normalized[: h.start].endswith(self._negators) for h in hits):
            return False
        if self._vetoes.find_all(normalized) or self._contrasts.find_all(normalized):
            return False
        cover = _MaskCover(hits)
        stage2 = [m for m in matches if m.key in cues and cues[m.key].section == "stage2"]
        return all(cover.contains(m) for m in stage2)


class _FigureIndex:
    """The "X得 / 到想死" frames (owner decision 2026-10-28) with their vetoes."""

    def __init__(self, rules: HyperboleAskRules) -> None:
        self.id = rules.id
        self._frames = PhraseMatcher({p: p for p in rules.frames}) if rules.frames else None
        self._vetoes = PhraseMatcher({p: p for p in rules.vetoes}) if rules.vetoes else None

    def alone(
        self,
        normalized: str,
        valid: Sequence[Match],
        matches: Sequence[Match],
        cues: Mapping[str, RiskCue],
        anchors: frozenset[str],
    ) -> bool:
        """Every counted Stage 2 phrase lies inside a frame, no negation phrase or pair
        anchor occurs, and no veto lies anywhere in the message. The caller checks that
        no pair or composition cue fired."""
        if self._frames is None or not valid or not normalized:
            return False
        if any(
            m.key in anchors or (m.key in cues and cues[m.key].section == "negation")
            for m in matches
        ):
            return False
        if self._vetoes is not None and self._vetoes.find_all(normalized):
            return False
        cover = _MaskCover(self._frames.find_all(normalized))
        return all(cover.contains(m) for m in valid)


class _RecallIndex:
    """The note recall questions (F16a) with their vetoes."""

    def __init__(self, rules: RecallCapRules) -> None:
        self._questions = (
            PhraseMatcher({p: p for p in rules.questions}) if rules.questions else None
        )
        self._vetoes = PhraseMatcher({p: p for p in rules.vetoes}) if rules.vetoes else None

    def only_recall(self, normalized: str, matches: Sequence[Match], denial: _DenialIndex) -> bool:
        """A note recall question with no risk, pair or denial phrase and no veto."""
        if self._questions is None or matches or denial.mentioned(normalized):
            return False
        if not self._questions.find_all(normalized):
            return False
        return self._vetoes is None or not self._vetoes.find_all(normalized)


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
        self._score_l1 = tax.threshold("risk.lexicon_scores.L1")
        self._score_l2 = tax.threshold("risk.lexicon_scores.L2")

    def predict(self, text: str) -> RiskPrediction:
        normalized = normalize(text)
        return self.predict_matches(
            self._index.scan(normalized), self._index.compose(normalized), normalized
        )

    def predict_matches(
        self,
        matches: Sequence[Match],
        compositions: Sequence[CompositionHit] = (),
        normalized: str = "",
        *,
        void_reported: bool = True,
    ) -> RiskPrediction:
        """Score a prior scan of the normalized text (spans are only valid there).

        L3 compositions are Stage 1 evidence and play no part here. With the
        ``normalized`` text, Stage 2 phrases that are all someone else's reported words
        are void when no pair or composition cue fires (``safety/reported.py``; not with
        ``void_reported`` False), and the "X得 / 到想死" figure alone is L1 with its D3 cue
        (owner decision 2026-10-28)."""
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
        if (
            valid
            and normalized
            and void_reported
            and not pairs
            and not compositions
            and len(self._index.reported.reported(normalized, valid)) == len(valid)
        ):
            # Every risk phrase is someone else's reported words and the user adds no cue
            # of their own: the rules leave the user out of the crisis flow.
            valid = []
        figure = self._index.figure
        if (
            not pairs
            and not compositions
            and figure.alone(normalized, valid, matches, cues, self._index.pair_anchor_keys)
        ):
            # The "X得 / 到想死" figure of speech and nothing else (owner decision
            # 2026-10-28): L1 with the D3 question instead of L2.
            return RiskPrediction(CrisisLevel.L1, self._score_l1, (figure.id,))
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
            raised = [h for h in compositions if h.entry.raise_with_risk]
            if raised and self._has_own_risk(valid, pairs, composed, raised):
                # A farewell, the last words, affairs arranged or a resolve (a D3 cue marked
                # raise_with_risk) next to a risk cue of the user's own in the same message
                # is no longer a question (2026-10-26): L2.
                score = max(score, self._score_l2)
            level = self._tax.crisis_level_for_score(score)
            ids = _unique_ids(
                [*(m.key for m in valid), *(p.id for p in pairs), *(c.id for c in composed)]
            )
            return RiskPrediction(level, score, ids)
        if hyperbole_ids:
            return RiskPrediction(CrisisLevel.L0, self._score_hyperbole, _unique_ids(hyperbole_ids))
        return RiskPrediction(CrisisLevel.L0, self._score_l0, ())

    def _has_own_risk(
        self,
        valid: Sequence[Match],
        pairs: Sequence[PairCue],
        composed: Sequence[Composition],
        raised: Sequence[CompositionHit],
    ) -> bool:
        """Some rule cue other than a D3 cue: a Stage 2 phrase outside the raised cues'
        spans, a method request pair or an L1 / L2 composition. Another D3 cue (an ask
        pair or composition) is the same question, not a risk of its own."""
        spans = [Match(h.entry.id, h.start, h.end) for h in raised]
        ask_ids = self._index.ask_ids
        return (
            any(not any(m.start < s.end and s.start < m.end for s in spans) for m in valid)
            or any(p.id not in ask_ids for p in pairs)
            or any(not c.ask for c in composed)
        )


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
        _index: _CueIndex | None = None,
    ) -> None:
        self._tax = tax
        self._lexicons = lexicons
        self._index = _CueIndex(lexicons) if _index is None else _index
        # The rule model always shares this screen's scan. With no injected model it is the
        # Stage 2 model; with one, it is the floor the injected model can only raise.
        self._rule_model = RuleRiskModel(tax, lexicons, _index=self._index)
        self._model = model
        self._model_plan_evidence = model_plan_evidence
        self._model_failure = RiskPrediction(
            CrisisLevel.L2, tax.threshold("risk.lexicon_scores.L2"), (MODEL_FAILURE,)
        )

    def with_model(
        self, model: RiskModel | None, *, model_plan_evidence: bool = False
    ) -> SafetyScreen:
        """A screen with the same lexicons and ``model`` as its Stage 2 model.

        It shares this screen's phrase index instead of building its own: the index never
        changes once built, and it is the largest part of the safety data in memory, so a
        session in model mode no longer holds a second copy, nor builds one per session
        (G-3 peak RSS, SDD §0)."""
        return SafetyScreen(
            self._tax,
            self._lexicons,
            model,
            model_plan_evidence=model_plan_evidence,
            _index=self._index,
        )

    def assess(self, text: str) -> CrisisAssessment:
        """Round 5 (复测 q4 IN-4): text whose direction controls change the order it is shown
        in is read both as typed and as shown (``normalize.bidi_readings``), and the higher
        level is kept. The kept reading is assessed last, so an injected model's last
        prediction (what the session reads after the turn) is the one for it."""
        readings = bidi_readings(text)
        if len(readings) == 1:
            return self._assess(text)[0]
        results = [self._assess(reading)[0] for reading in readings]
        best = max(range(len(results)), key=lambda i: (results[i].level, -i))
        if best != len(results) - 1:
            return self._assess(readings[best])[0]
        return results[best]

    def reported_risk(self, text: str) -> ReportedRisk | None:
        """Someone else's reported words and their own level (问题单第 6 条, 2026-10-26).

        ``None`` unless the message reports a third person's words (``safety/reported.py``
        ``ReportedSpeech.contents``: a speaker and a speech verb, no self word in the words
        and no veto such as 我也 in the message). The reported words are screened as if
        the user had said them, with this screen's model too, so ``level`` is the risk they
        carry; ``plan`` says they carry plan evidence (a Stage 1 cue) or that the injected
        model's own class for them is L3. ``user_clear`` says every rule cue of the message
        (a Stage 1, Stage 2, hyperbole or negation phrase, a pair anchor, a composition)
        lies inside the reported words and no pair cue (a method or a painless way asked
        for) fired anywhere, so the rules heard nothing of the user's own.

        The screen only reports this; the session decides (the user is not put into the
        crisis flow for someone else's words, and gets resources to pass on). An injected
        model runs once per reported span, so the caller discards its last prediction."""
        normalized = normalize(text)
        cues = self._index.cues
        anchors = self._index.pair_anchor_keys
        matches = self._index.scan(normalized)
        risky = [m for m in matches if m.key in cues or m.key in anchors]
        spans = self._index.reported.contents(normalized, cues=risky, raw=text)
        if not spans:
            return None

        def inside(start: int, end: int) -> bool:
            return any(s.start <= start and end <= s.end for s in spans)

        # A fired pair (a method or a painless way asked for, SDD §8.2 R-MS and D3) is never
        # someone else's business alone: asking for a way, for oneself or for "her", keeps
        # the user's own level and question.
        user_clear = (
            not self._index.fired_pairs(matches)
            and all(inside(m.start, m.end) for m in matches if m.key in cues or m.key in anchors)
            and all(inside(h.start, h.end) for h in self._index.compose(normalized))
        )
        level = CrisisLevel.L0
        plan = False
        rule_risk = False
        anchor = False
        farewell = 0
        for span in spans:
            # The words are rated as the user's own: a pronoun inside them ("她说……，她想
            # 死") is no second report to void.
            assessment, model = self._assess(span.screen, void_reported=False)
            level = max(level, assessment.level)
            rules = assessment.rule_level or CrisisLevel.L0
            rule_risk = rule_risk or rules >= CrisisLevel.L1 or assessment.asks_intent
            anchor = (
                anchor
                or any(m.key in anchors for m in self._index.scan(span.screen))
                or names_death(span.screen)
            )
            farewell = max(farewell, farewell_strength(span.screen))
            plan = (
                plan
                or assessment.level is CrisisLevel.L3
                or (model is not None and model.level is CrisisLevel.L3)
            )
        return ReportedRisk(level, plan, user_clear, rule_risk, anchor, farewell)

    def _assess(
        self, text: str, *, void_reported: bool = True
    ) -> tuple[CrisisAssessment, RiskPrediction | None]:
        """The assessment and the injected model's in-contract prediction (None without a
        model, when Stage 1 answered first or when the model failed). Without
        ``void_reported`` the rule model keeps reported phrases (``reported_risk`` rates
        someone else's words as if the user had said them)."""
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
            stage1_assessment = CrisisAssessment(
                CrisisLevel.L3, score, "STAGE1", True, ids, rule_level=CrisisLevel.L3
            )
            return stage1_assessment, None
        rule_prediction = self._rule_model.predict_matches(
            matches, composed, normalized, void_reported=void_reported
        )
        prediction = rule_prediction
        asks_intent = not self._index.ask_ids.isdisjoint(prediction.cue_ids)
        has_plan_evidence = False
        uncapped: CrisisLevel | None = None
        observed: RiskPrediction | None = None
        if self._model is not None:
            model_prediction = self._predict_safely(self._model, text)
            if model_prediction is not self._model_failure:
                observed = model_prediction
            failed = model_prediction is self._model_failure
            # The model's level and its score's band, the higher of the two.
            model_level = max(
                model_prediction.level, self._tax.crisis_level_for_score(model_prediction.score)
            )
            figurative = (
                not failed
                and rule_prediction.level is CrisisLevel.L0
                and self._index.figurative_only(matches)
            )
            if figurative:
                # The rules read every risk phrase as a figure of speech (F8a): at most L1.
                model_level = min(model_level, CrisisLevel.L1)
            asked_figure = (
                not failed
                and bool(self._index.figure.id)
                and rule_prediction.cue_ids == (self._index.figure.id,)
            )
            if asked_figure:
                # The "X得 / 到想死" figure alone (owner decision 2026-10-28): the session
                # asks the D3 question, so the model counts at most as L1.
                model_level = min(model_level, CrisisLevel.L1)
            recall = (
                not failed
                and not figurative
                and model_level >= CrisisLevel.L2
                and rule_prediction.level is CrisisLevel.L0
                and not composed
                and self._index.recall.only_recall(normalized, matches, self._index.denial)
            )
            if recall:
                # A question about a note and not one risk word (F16a): at most L1.
                model_level = CrisisLevel.L1
            denial = (
                not failed
                and not figurative
                and model_level >= CrisisLevel.L2
                and rule_prediction.level is CrisisLevel.L0
                and not composed
                and self._index.denial.denies(normalized, matches, cues)
            )
            if denial:
                # A first-person denial or all-clear and nothing else (F10): at most L1
                # outside a crisis; the tracker reads the uncapped level in one.
                uncapped = arbitrate(
                    self._tax,
                    max(rule_prediction.level, model_level),
                    rule_prediction.score,
                    self._model_plan_evidence and model_prediction.level is CrisisLevel.L3,
                )
                model_level = CrisisLevel.L1
            # Only the injected model's own L3 counts; the failure prediction is L2, never L3,
            # and a score band is never plan evidence.
            has_plan_evidence = (
                self._model_plan_evidence
                and not failed
                and not figurative
                and not asked_figure
                and not recall
                and not denial
                and model_prediction.level is CrisisLevel.L3
            )
            prediction = _with_floor(
                prediction,
                RiskPrediction(model_level, model_prediction.score, model_prediction.cue_ids),
            )
        # The model's band is already in its level; the rule score's band is its level.
        level = arbitrate(self._tax, prediction.level, rule_prediction.score, has_plan_evidence)
        clear = rules_found_nothing(
            rule_prediction.level,
            matches,
            cues,
            self._index.pair_anchor_keys,
            composed,
            asks_intent,
        )
        assessment = CrisisAssessment(
            level,
            prediction.score,
            "STAGE2",
            has_plan_evidence,
            prediction.cue_ids,
            asks_intent,
            rule_prediction.level,
            None if uncapped is None or uncapped is level else uncapped,
            clear,
        )
        return assessment, observed

    def clear_denial(self, text: str) -> bool:
        """Whether a no to the question a model-only alarm asked passes the F10 denial
        conditions (owner decision 2026-10-26, the stricter of D3's no and F10's denial):
        no Stage 1 phrase, pair anchor or composition, no veto or contrast anywhere, no
        negated denial, and every Stage 2 phrase inside a denial phrase. The rules only;
        the D3 reading of the no itself is ``intent_check.read_intent_answer``."""
        normalized = normalize(text)
        matches = self._index.scan(normalized)
        cues = self._index.cues
        if self._index.compose(normalized):
            return False
        for match in matches:
            if match.key in self._index.pair_anchor_keys:
                return False
            if match.key in cues and cues[match.key].section == "stage1":
                return False
        return self._index.denial.clears(normalized, matches, cues)

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
