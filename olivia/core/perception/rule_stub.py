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
会不会, or any one-character 不 / 没 between a character and a hit that starts with the
same character: 能不能教我, 有没有什么办法) or follows another negation (不是不). This
mirrors the red-flag detector's check.

Rules, per field:

- ``risk_level`` / ``crisis_confidence``: copied from the ``CrisisAssessment`` (level,
  score). The stub never recomputes risk.
- ``fine_grained_emotion``: the emotion with the most cue hits (aliases already folded
  into canonical ids by the lexicon loader); ties go to the earlier ``emotion_cues`` key,
  which the lexicon orders by the guide's §2.2 rule 4 (closer to risk first). No hit:
  ``calm`` (guide §2.4 labels neutral messages calm). That fallback is a label, not a
  feeling the user named: replies never put it into words (F3, ``feelings.yaml``
  ``never_named``).
- ``valence``: the midpoint of the dominant emotion's TAX ``valence_range`` (TAX has no
  default valence); 0.0 when no emotion cue matched.
- ``arousal``: the dominant emotion's TAX ``default_arousal`` (``calm``'s when nothing
  matched), plus ``AROUSAL_STEP`` per ``raise`` modifier hit (at most
  ``MAX_RAISE_STEPS``) and minus one step per ``lower`` hit (at most
  ``MAX_LOWER_STEPS``), clamped to [0, 1]. The bounded swing (+0.15 / -0.10) keeps the
  value inside the guide's table A window for every emotion. An ``acute_arousal_cues``
  hit (body signs of acute overload: 心跳快炸了, 手一直在抖, 喘不上气 ...) then floors it at
  ``arousal.thresholds.cognitive_block``, whichever emotion won, so a message whose body
  is in alarm is never read as calm enough for cognitive work (red-team rt083). With
  such a hit and no emotion cue, the emotion is ``panic`` instead of ``calm``.
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
``intent_confirmed`` when a non-negated phrase of that section matched (a request for a
named practice, below, is a direct request too, and so is a whole message, marks
stripped, that is a ``direct_request_whole`` entry: "再给我一个", "换一个"; F16b:
``another_method`` when it is such a whole message or a ``direct_request`` phrase with
再给 / 再来 / 换 / 别的 / 其他 / 其它 in it: "给我一个别的", "换个练习"). If both lock
phrases match, the later one in the message wins, since a turn cannot both set and
release the lock. ``aversion`` and ``intent_confirmed`` may both be set; the state machine
reads them in different stages (S_empower, S_closing). ``kit_recall`` when a non-negated
kit-recall phrase matched. ``therapy_question`` / ``therapy_request`` (F3): the first
non-negated ``therapy_names`` hit (a name whose first or last character is a Latin letter
or digit counts only when the text next to it is not one: "eft" inside "left" is no hit).
A Grade A practice ("正念", "CBT") with a non-negated ``therapy_request_cues`` phrase
("带我做一下") is a ``therapy_request`` and a direct request; otherwise any named method
with a ``therapy_question_cues`` phrase, or a Grade B/C method with a request phrase
(those are explained, never done alone), is a ``therapy_question``.
``haven_exit`` when a non-negated ``haven_exit`` phrase matched ("我好多了", "换个话题吧";
FSM-15); the phrases are their own group, so "不想换个话题" is void through its longer
"想换个话题" entry.
``note_recall`` (F15): ``EXPLICIT`` for a non-negated ``note_recall`` hit ("我上次让你记住
什么了"), else ``QUESTION`` for a ``note_recall_questions`` hit ("……是谁来着"); both lists
are one group of their own.
``situation_codes`` and ``contraindication_cues``: the keys of every non-negated
``situation_cues`` / ``contraindication_cues`` hit (roadmap next-phase A1); the session
decides what they mean (``methods/contraindications.py``). ``SIT-06-04`` is also set by a
message with a live hit in each of the three ``prolonged_grief`` lists (a death, half a
year or more since, still not borne: "妈妈去世一年多了，我还是走不出来"; COLBO-06b, draft
G-0); each list is its own group, so containment never crosses them. ``prolonged_grief``
when that rule alone set it, no acute cue on the turn (F13: acute and prolonged grief are
told apart).

Natural-language feedback (roadmap R-7b), only on a turn that is not a slash command:

- ``feedback``: the message with punctuation and symbols removed (``strip_marks``) is
  scanned for the ``feedback`` phrases, the aversion phrases (read as unhelpful) and the
  kit-recall phrases (so "收进锦囊的那个" is a recall, not "收进锦囊"); a hit inside a
  longer hit is dropped and a negated hit is void, as above. Unhelpful wins over the
  other classes; done together with not_now is unclear; one class is that command. A
  ``leave_taking`` phrase ("我去睡了", "今天就到这里") counts as not_now only when no
  other class matched, so "做完了，我去睡了" stays done.
- ``feedback_unclear``: done and not_now together, or the whole marks-free message is a
  ``feedback.unclear`` entry ("唉", "再说吧") and no feedback phrase matched.
- ``answer``: the whole marks-free message is an ``answers.affirm`` or
  ``answers.decline`` entry.
- ``leave_taking`` (F5d): a ``leave_taking`` phrase survives the same scan (outermost,
  not negated) and its clause is not a question: no "？" right after it (trailing
  particles aside) and no "吗" ("今天就到这里？我还没说完" is no goodbye). It is set
  whatever other feedback the message has; the session reads it only with no card
  waiting. F6a: a phrase is someone else's words, and no goodbye, when its clause has a
  ``leave_taking_reported`` word before it that is not negated ("他跟我说今天就到这里吧",
  "老板说今天就到这里"; "不说了今天就到这里" still counts). A ``leave_taking_whole``
  goodbye ("拜拜", "88", "先这样吧") counts only as a clause of its own: marks stripped,
  ``leave_taking_lead_ins`` ("好的", "那我们") dropped from its start and particles from
  its end, nothing else may be left ("拜拜那段感情" is no goodbye). Both kinds also count
  as not_now for a waiting card, as above.

The stub reads every turn on its own and knows nothing of the session: whether a card
waits for feedback, or a question waits for an answer, is the session's call.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Final, TypeVar

from olivia.core.models import CrisisLevel, PerceptionContext, SafetyGrade
from olivia.core.perception.lexicon import GRIEF_KEYS, PerceptionLexicon, strip_marks
from olivia.core.perception.signals import Answer, Command, NoteRecall, TurnSignals
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
_ACUTE: Final = "acute"
ACUTE_EMOTION: Final = "panic"
_RAISE: Final = "raise"
_LOWER: Final = "lower"
_DIRECT: Final = "direct_request"
_LOCK_ON: Final = "lock_on"
_LOCK_OFF: Final = "lock_off"
_AVERSION: Final = "aversion"
_INTENT: Final = "intent_confirmed"
_RECALL: Final = "kit_recall"
_THERAPY: Final = "therapy"
_THERAPY_CUE: Final = "therapy_cue"
_THERAPY_REQUEST: Final = "therapy_request"
_SITUATION: Final = "situation"
_CONTRAINDICATION: Final = "contraindication"
_HAVEN_EXIT: Final = "haven_exit"
_NOTE_RECALL: Final = "note_recall"
# F16b: a direct_request phrase with one of these asks for another or a different method.
_ANOTHER_MARKERS: Final = ("再给", "再来", "换", "别的", "其他", "其它")
# COLBO-06b: prolonged grief is the SIT-06-04 dossier (延长哀伤障碍与未完成丧失悲恸).
PROLONGED_GRIEF_CODE: Final = "SIT-06-04"
_GRIEF_GROUPS: Final = tuple(f"grief_{key}" for key in GRIEF_KEYS)
# Labels of the feedback matcher: a command, or a kit recall (matched only to win
# containment over a feedback phrase inside it).
_FeedbackLabel = Command | str
_LEAVE: Final = "leave_taking"
# What may follow a leave-taking phrase before its clause ends, and what makes it a question.
_CLAUSE_END: Final = re.compile(r"[,，、。.!！;；:：~～…\n?？]")
_TRAILING_PARTICLES: Final = "吧啦呀哦啊了"
_QUESTION_PARTICLES: Final = frozenset({"吗", "么", "嘛"})

_Tag = tuple[str, str]  # (group, label)
_L = TypeVar("_L", bound=str)


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
        for required in (FALLBACK_EMOTION, ACUTE_EMOTION):
            if required not in profiles:
                raise ValueError(f"taxonomy has no {required!r} emotion")
        self._acute_floor = tax.threshold("arousal.thresholds.cognitive_block")
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
        add(_SIGNAL, _RECALL, lexicon.kit_recall)
        add(_INFORMATION, _INFORMATION, lexicon.information_cues)
        add(_REFERRAL, _REFERRAL, lexicon.referral_cues)
        add(_STABILIZATION, _STABILIZATION, lexicon.stabilization_cues)
        add(_ACUTE, _ACUTE, lexicon.acute_arousal_cues)
        for method_id, phrases in lexicon.therapy_names.items():
            add(_THERAPY, method_id, phrases)
        add(_THERAPY_CUE, _THERAPY_CUE, lexicon.therapy_question_cues)
        add(_THERAPY_REQUEST, _THERAPY_REQUEST, lexicon.therapy_request_cues)
        add(_HAVEN_EXIT, _HAVEN_EXIT, lexicon.haven_exit)
        add(_NOTE_RECALL, NoteRecall.EXPLICIT, lexicon.note_recall)
        add(_NOTE_RECALL, NoteRecall.QUESTION, lexicon.note_recall_questions)
        self._practices = frozenset(
            mid
            for mid in lexicon.therapy_names
            if mid not in tax.methods() or tax.methods()[mid].grade is SafetyGrade.GRADE_A
        )
        for code, phrases in lexicon.situation_cues.items():
            add(_SITUATION, code, phrases)
        for enum_id, phrases in lexicon.contraindication_cues.items():
            add(_CONTRAINDICATION, enum_id, phrases)
        if PROLONGED_GRIEF_CODE not in tax.situation_codes():
            raise ValueError(f"taxonomy has no {PROLONGED_GRIEF_CODE!r} situation")
        for key, group in zip(GRIEF_KEYS, _GRIEF_GROUPS, strict=True):
            add(group, key, lexicon.prolonged_grief[key])
        self._tags = {phrase: tuple(t) for phrase, t in tags.items()}
        self._matcher = PhraseMatcher({phrase: phrase for phrase in self._tags})

        feedback: dict[str, _FeedbackLabel] = {}
        for label, phrases in (
            (Command.DONE, lexicon.feedback_done),
            (Command.NOT_NOW, lexicon.feedback_not_now),
            (Command.UNHELPFUL, lexicon.feedback_unhelpful),
            (Command.UNHELPFUL, lexicon.aversion),
            (_RECALL, lexicon.kit_recall),
            (_LEAVE, lexicon.leave_taking),
        ):
            for phrase in phrases:
                feedback[strip_marks(phrase)] = label
        self._feedback_labels = feedback
        self._leave_whole = frozenset(lexicon.leave_taking_whole)
        # Longest first, so "好的" is dropped before "好".
        self._lead_ins = tuple(sorted(lexicon.leave_taking_lead_ins, key=len, reverse=True))
        self._reported = lexicon.leave_taking_reported
        self._feedback_matcher = PhraseMatcher({phrase: phrase for phrase in feedback})
        self._unclear = frozenset(lexicon.feedback_unclear)
        self._whole_requests = frozenset(lexicon.direct_request_whole)
        self._answers = {
            **dict.fromkeys(lexicon.answer_affirm, Answer.AFFIRM),
            **dict.fromkeys(lexicon.answer_decline, Answer.DECLINE),
        }

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
        feedback: Command | None = None
        unclear = False
        answer: Answer | None = None
        another = False
        leaving = False
        if command is None:
            leave_live, leaving = self._leaving(body)
            feedback, unclear = self._feedback(strip_marks(body), leave_live)
            reply = strip_marks(folded)
            unclear = unclear or (feedback is None and reply in self._unclear)
            answer = self._answers.get(reply)
            another = reply in self._whole_requests

        emotion_hits = Counter(label for label, _ in hits.get(_EMOTION, ()))
        acute = bool(hits.get(_ACUTE))
        if emotion_hits:
            emotion = min(emotion_hits, key=lambda e: (-emotion_hits[e], self._priority[e]))
            valence = self._valence[emotion]
        elif acute:
            emotion = ACUTE_EMOTION
            valence = self._valence[emotion]
        else:
            emotion, valence = FALLBACK_EMOTION, 0.0
        modifiers = Counter(label for label, _ in hits.get(_MODIFIER, ()))
        steps = min(modifiers[_RAISE], MAX_RAISE_STEPS) - min(modifiers[_LOWER], MAX_LOWER_STEPS)
        arousal = round(min(max(self._arousal[emotion] + steps * AROUSAL_STEP, 0.0), 1.0), 4)
        if acute:
            arousal = max(arousal, self._acute_floor)

        situations = {label for label, _ in hits.get(_SITUATION, ())}
        acute_grief = PROLONGED_GRIEF_CODE in situations
        prolonged = all(hits.get(group) for group in _GRIEF_GROUPS)
        if prolonged:
            situations.add(PROLONGED_GRIEF_CODE)
        signals = hits.get(_SIGNAL, [])
        recall_labels = {label for label, _ in hits.get(_NOTE_RECALL, ())}
        note_recall = next((r for r in NoteRecall if r in recall_labels), None)
        labels = {label for label, _ in signals}
        asked, requested = _therapy(body, hits, self._practices)
        direct = _DIRECT in labels or requested is not None or another
        another_method = another or any(
            label == _DIRECT and any(m in match.key for m in _ANOTHER_MARKERS)
            for label, match in signals
        )
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
            another_method=another_method,
            listening_lock_on=lock_on,
            listening_lock_off=lock_off,
            aversion=_AVERSION in labels,
            intent_confirmed=_INTENT in labels,
            command=command,
            feedback=feedback,
            feedback_unclear=unclear,
            answer=answer,
            kit_recall=_RECALL in labels,
            haven_exit=bool(hits.get(_HAVEN_EXIT)),
            leave_taking=leaving,
            therapy_question=asked,
            therapy_request=requested,
            situation_codes=frozenset(situations),
            contraindication_cues=frozenset(label for label, _ in hits.get(_CONTRAINDICATION, ())),
            note_recall=note_recall,
            prolonged_grief=prolonged and not acute_grief,
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

    def _feedback(self, text: str, leaving: bool) -> tuple[Command | None, bool]:
        """(feedback, unclear) from the marks-free message; see the module docstring.
        ``leaving``: the message takes leave (``_leaving``'s first value)."""
        found = [(self._feedback_labels[m.key], m) for m in self._feedback_matcher.find_all(text)]
        live = [label for label, m in _outermost(found) if not self._negated(text, m.start)]
        classes = {label for label in live if isinstance(label, Command)}
        if Command.UNHELPFUL in classes:
            return Command.UNHELPFUL, False
        if not classes and leaving:
            return Command.NOT_NOW, False
        if len(classes) == 1:
            return classes.pop(), False
        return None, bool(classes)

    def _leaving(self, body: str) -> tuple[bool, bool]:
        """(takes leave, says goodbye). The first: a live ``leave_taking`` hit in the
        marks-free ``body`` (as for feedback) that is not reported speech, or a whole-clause
        goodbye. The second: one of them whose sentence is not a question either:
        "今天就到这里？我还没说完" is no goodbye."""
        live = goodbye = False
        # Index in ``body`` of each character that strip_marks keeps.
        kept = [i for i, ch in enumerate(body) if strip_marks(ch)]
        text = "".join(body[i] for i in kept)
        found = [(self._feedback_labels[m.key], m) for m in self._feedback_matcher.find_all(text)]
        for label, match in _outermost(found):
            if label != _LEAVE or self._negated(text, match.start):
                continue
            if self._reported_before(body, kept[match.start]):
                continue
            live = True
            if not _asked(body[kept[match.end - 1] + 1 :]):
                goodbye = True
        start = 0
        for end in [*(m.start() for m in _CLAUSE_END.finditer(body)), len(body)]:
            if self._whole_goodbye(body[start:end]):
                live = True
                if not _asked(body[end:]):
                    goodbye = True
            start = end + 1
        return live, goodbye

    def _reported_before(self, body: str, at: int) -> bool:
        """A ``leave_taking_reported`` word, not negated, between the start of the clause
        holding ``body[at]`` and ``at``: someone else said it or is leaving."""
        ends = [m.end() for m in _CLAUSE_END.finditer(body, 0, at)]
        before = strip_marks(body[ends[-1] if ends else 0 : at])
        for word in self._reported:
            i = before.find(word)
            while i >= 0:
                if not self._negated(before, i):
                    return True
                i = before.find(word, i + 1)
        return False

    def _whole_goodbye(self, clause: str) -> bool:
        """The clause, marks stripped, is a ``leave_taking_whole`` goodbye once its
        lead-ins and trailing particles are dropped."""
        bare = strip_marks(clause).rstrip(_TRAILING_PARTICLES)
        dropped = True
        while dropped:
            dropped = False
            for lead in self._lead_ins:
                if bare.startswith(lead) and len(bare) > len(lead):
                    bare, dropped = bare[len(lead) :], True
                    break
        return bare in self._leave_whole

    def _negated(self, text: str, start: int) -> bool:
        if any(text.endswith(word, 0, start) for word in self._exceptions):
            return False
        for negation in self._negations:
            if not text.endswith(negation, 0, start):
                continue
            head = start - len(negation)
            if any(neg == negation and text.endswith(a, 0, head) for a, neg in _A_NOT_A):
                continue
            if len(negation) == 1 and head > 0 and text[head - 1] == text[start]:
                continue  # A-not-A: 能不能教我, 有没有什么办法, 要不要试试
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


def _outermost(items: list[tuple[_L, Match]]) -> list[tuple[_L, Match]]:
    """Drop every hit that lies fully inside another hit of the same group."""
    ordered = sorted(items, key=lambda item: (item[1].start, -item[1].end))
    kept: list[tuple[_L, Match]] = []
    furthest = -1
    for label, match in ordered:
        if match.end > furthest:
            kept.append((label, match))
            furthest = match.end
    return kept


def _therapy(
    body: str, hits: Mapping[str, list[tuple[str, Match]]], practices: frozenset[str]
) -> tuple[str | None, str | None]:
    """(asked, requested): the first named method, as a question or a request to do it."""
    named = [(m.start, label) for label, m in hits.get(_THERAPY, ()) if _whole_word(body, m)]
    if not named:
        return None, None
    first = min(named)[1]
    if hits.get(_THERAPY_REQUEST):
        return (None, first) if first in practices else (first, None)
    if hits.get(_THERAPY_CUE):
        return first, None
    return None, None


def _asked(rest: str) -> bool:
    """The clause that ``rest`` finishes is a question: only particles, then a question
    mark ("吧？"), or a question particle ("吗")."""
    end = _CLAUSE_END.search(rest)
    head = (rest if end is None else rest[: end.start()]).strip(_TRAILING_PARTICLES)
    if head in _QUESTION_PARTICLES:
        return True
    return not head and end is not None and end.group() in "?？"


def _whole_word(body: str, match: Match) -> bool:
    """False when a Latin-letter or digit edge of the hit runs into more of the same."""
    first, last = body[match.start], body[match.end - 1]
    before = body[match.start - 1] if match.start > 0 else ""
    after = body[match.end] if match.end < len(body) else ""
    return not (_latin(first) and _latin(before)) and not (_latin(last) and _latin(after))


def _latin(char: str) -> bool:
    return char.isascii() and char.isalnum()


def _lock(signals: list[tuple[str, Match]]) -> tuple[bool, bool]:
    """(lock_on, lock_off); when both phrases occur, the later one in the text wins."""
    last_on = max((m.end for label, m in signals if label == _LOCK_ON), default=-1)
    last_off = max((m.end for label, m in signals if label == _LOCK_OFF), default=-1)
    if last_on < 0 and last_off < 0:
        return False, False
    return last_on > last_off, last_off > last_on
