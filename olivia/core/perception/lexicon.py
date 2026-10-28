"""Phrase lexicon for the rule-based perception stub, with strict load-time validation.

The stub builds one phrase matcher over every section, so anything ambiguous is
rejected here: unknown sections, emotion or spectrum ids that the taxonomy does not
define, empty lists, and a phrase listed twice within one section group (two emotions,
two spectra, or two of the direct-request / lock-on / lock-off / aversion /
intent-confirmed / kit-recall signals). The same phrase
may appear in different groups, for example as an emotion cue and a spectrum cue.

Feedback and answer phrases (roadmap R-7b), the leave-taking phrases and the
whole-message requests are folded once more with :func:`strip_marks`, since the stub
matches them on the message without punctuation ("试过了，没用" reads as "试过了没用").
Within the feedback group (done, not now, unhelpful, leave-taking, plus the aversion and
kit-recall phrases, which the stub matches there too) and within the whole-message group
(unclear, affirm, decline, whole-message requests) a phrase may appear once.

Emotion keys may be TAX emotion aliases; they are folded into the canonical id, and the
key order is kept as the tie-break priority between emotions (first key wins).

``therapy_names`` maps every Grade B and Grade C taxonomy method id to the names a user
may ask about it by; a name belongs to one method only. It may also map Grade A practices
(a Grade A method id or a card-type registry action id such as ``30:grounding``) that a
user can ask about or ask to do by a common name (F3: 正念, CBT, 呼吸练习 ...).
``therapy_question_cues`` are the words that make a named therapy a question;
``therapy_request_cues`` the words that ask to do it ("带我做一下").

``situation_cues`` maps taxonomy situation codes, and ``contraindication_cues`` taxonomy
contraindication enum ids, to the phrases that reveal them in conversation (roadmap
next-phase A1); a phrase belongs to one key of its section only. ``prolonged_grief``
holds three phrase lists (``loss``, ``duration``, ``unresolved``) that reveal SIT-06-04
only together, in one message (COLBO-06b; draft, G-0); a phrase belongs to one list.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

import yaml

from olivia.core.models import ActionType, SafetyGrade
from olivia.core.safety.normalize import normalize
from olivia.core.taxonomy import Taxonomy, TaxonomyError
from olivia.core.yaml_load import safe_load

_FILE: Final = "perception.yaml"
_PHRASE_SECTIONS: Final = (
    "direct_request",
    "lock_on",
    "lock_off",
    "aversion",
    "intent_confirmed",
    "information_cues",
    "referral_cues",
    "stabilization_cues",
    "acute_arousal_cues",
    "kit_recall",
    "therapy_question_cues",
    "therapy_request_cues",
    "haven_exit",
    "note_recall",
    "note_recall_questions",
    "why_not",
    "cardiac_symptom_cues",
    "privacy_questions",
    "privacy_subjects",
    "hotline_pushback",
    "hotline_anonymous",
    "hotline_abroad",
    "strain_cues",
    "imminent_times",
    "imminent_means",
    "keep_secret_cues",
    "imminent_context",
    "third_party_unreachable",
    "third_party_questions",
    "help_seeking_cues",
    "hotline_fee",
    "hotline_hours",
    "hotline_language",
    "hotline_real",
    "hotline_more",
    "hotline_words",
    "help_seeking_school",
    "third_party_how_to_ask",
    "hotline_unreachable",
    "hotline_emergency",
)
_SECTIONS: Final = frozenset(
    {
        "version",
        "emotion_cues",
        "intensity_modifiers",
        "spectrum_cues",
        "negation",
        "feedback",
        "answers",
        "therapy_names",
        # Read and validated by perception/introspector.py (step C2).
        "introspection",
        "situation_cues",
        "prolonged_grief",
        "contraindication_cues",
        "leave_taking",
        "leave_taking_whole",
        "leave_taking_lead_ins",
        "leave_taking_reported",
        "direct_request_whole",
        "direct_request_patterns",
        "advice_patterns",
        "hotline_request_patterns",
        "minor_disclosure_patterns",
        "contraindicated_practices",
        "hotline_places",
        "local_emergency_places",
        "third_party_says_fine_patterns",
        "suds_patterns",
        "hotline_number_patterns",
        "hotline_place_hint_patterns",
        "hotline_place_patterns",
        *_PHRASE_SECTIONS,
    }
)
# Sections whose phrases must be distinct from each other: one phrase cannot both set
# and release the listening lock, both ask for a method and set the lock, or both reject
# a practice and commit to it.
_SIGNAL_GROUP: Final = (
    "direct_request",
    "lock_on",
    "lock_off",
    "aversion",
    "intent_confirmed",
    "kit_recall",
)
# The placeholders of ``direct_request_patterns``: the start of a clause, one character
# of the same clause, and the end of a clause (dogfood I1).
_CLAUSE_MARKS: Final = "，。！？,.!?；;~～…\n"
_PATTERN_SLOTS: Final = {
    "{S}": f"(?:^|(?<=[{_CLAUSE_MARKS}]))",
    "{C}": f"[^{_CLAUSE_MARKS}]",
    "{E}": f"(?=[{_CLAUSE_MARKS}]|$)",
}
_FEEDBACK_KEYS: Final = ("done", "not_now", "unhelpful", "unclear")
_ANSWER_KEYS: Final = ("affirm", "decline")
GRIEF_KEYS: Final = ("loss", "duration", "unresolved")
_INFO_GRADES: Final = frozenset({SafetyGrade.GRADE_B, SafetyGrade.GRADE_C})
_CARD_ACTION_TYPES: Final = frozenset({ActionType.STABILIZATION, ActionType.MICRO_EXERCISE})


class PerceptionLexiconError(Exception):
    """Raised when the perception lexicon is missing, malformed, or inconsistent."""


@dataclass(frozen=True)
class PerceptionLexicon:
    emotion_cues: Mapping[str, tuple[str, ...]]
    """Canonical TAX emotion id -> folded phrases; iteration order is tie-break priority."""
    raise_modifiers: tuple[str, ...]
    lower_modifiers: tuple[str, ...]
    spectrum_cues: Mapping[str, tuple[str, ...]]
    """TAX distress spectrum id ("01".."11") -> folded phrases, every spectrum present."""
    direct_request: tuple[str, ...]
    direct_request_whole: tuple[str, ...]
    """Whole messages, marks stripped, that ask for another method ("再给我一个", "换一个")."""
    lock_on: tuple[str, ...]
    lock_off: tuple[str, ...]
    aversion: tuple[str, ...]
    """The user rejects the suggested practice (SDD §4.2 S_empower "表达反感")."""
    intent_confirmed: tuple[str, ...]
    """The user commits to when or how to try it (SDD §4.2 S_closing "实施意向确认完成")."""
    information_cues: tuple[str, ...]
    referral_cues: tuple[str, ...]
    stabilization_cues: tuple[str, ...]
    acute_arousal_cues: tuple[str, ...]
    """Body signs of acute overload; a hit floors arousal at the cognitive-block line."""
    negation_prefixes: tuple[str, ...]
    negation_exceptions: tuple[str, ...]
    feedback_done: tuple[str, ...]
    """Natural-language feedback, matched anywhere in the message (marks stripped)."""
    feedback_not_now: tuple[str, ...]
    feedback_unhelpful: tuple[str, ...]
    feedback_unclear: tuple[str, ...]
    """Whole messages that may be about the card without saying which way ("唉")."""
    leave_taking: tuple[str, ...]
    """The user is leaving for now ("我去睡了", "今天就到这里"), marks stripped: on a card
    that waits, the stub reads it as not now unless another feedback phrase says more."""
    leave_taking_whole: tuple[str, ...]
    """Goodbyes that count only as a whole clause ("拜拜", "88", "先这样"), marks stripped."""
    leave_taking_lead_ins: tuple[str, ...]
    """Words that may open a whole-clause goodbye ("好的", "那我们"), marks stripped."""
    leave_taking_reported: tuple[str, ...]
    """Reported speech or another person before a goodbye in its clause ("说", "他", "老板"):
    the goodbye is someone else's (F6a)."""
    answer_affirm: tuple[str, ...]
    """Whole-message yes ("好的"), marks stripped."""
    answer_decline: tuple[str, ...]
    """Whole-message no ("不用了"), marks stripped."""
    kit_recall: tuple[str, ...]
    """The user asks to see a shelved method again ("锦囊里那个再给我看看")."""
    therapy_names: Mapping[str, tuple[str, ...]]
    """Method or card id -> folded names: every Grade B/C method, in taxonomy order, then
    the Grade A practices that have common names (F3)."""
    therapy_question_cues: tuple[str, ...]
    """Words that make a named therapy a question ("是什么", "有用吗")."""
    therapy_request_cues: tuple[str, ...]
    """Words that ask to do a named practice ("带我做一下", "教我练"; F3)."""
    haven_exit: tuple[str, ...]
    """The user feels better or wants another topic ("我好多了", "换个话题吧"; FSM-15): in
    S_haven the state machine goes back to S_explore."""
    note_recall: tuple[str, ...]
    """The user asks what they had OLIVIA remember ("我上次让你记住什么了"; MIYI-04, F15)."""
    note_recall_questions: tuple[str, ...]
    """A question about a fact the user cannot recall ("……是谁来着"; F15): a note is
    looked up, and the turn is ordinary conversation when none matches."""
    situation_cues: Mapping[str, tuple[str, ...]]
    """Taxonomy situation code -> folded phrases (A1: SIT-06-04, SIT-11-01)."""
    prolonged_grief: Mapping[str, tuple[str, ...]]
    """``GRIEF_KEYS`` -> folded phrases: a death, a long time since, still not borne; a
    message with a live hit of all three reveals SIT-06-04 (COLBO-06b; draft, G-0)."""
    contraindication_cues: Mapping[str, tuple[str, ...]]
    """Taxonomy contraindication enum id -> folded phrases (A1)."""
    direct_request_patterns: tuple[re.Pattern[str], ...] = ()
    """Requests whose words are apart ("有什么五分钟能做的放松方法吗"; dogfood I1),
    compiled with the ``{S}`` / ``{C}`` / ``{E}`` placeholders expanded."""
    contraindicated_practices: Mapping[str, tuple[str, ...]] = field(
        default_factory=lambda: MappingProxyType({})
    )
    """Contraindication enum id -> names of the practices it masks ("憋气", "冷水敷脸";
    dogfood I2)."""
    why_not: tuple[str, ...] = ()
    """"Why not?" ("为什么不行"), read right after a masked practice was explained."""
    cardiac_symptom_cues: tuple[str, ...] = ()
    """Heart or breathing symptoms ("胸口发紧", "心跳很快"; dogfood I2)."""
    privacy_questions: tuple[str, ...] = ()
    """Questions about what is kept ("会不会上传"; dogfood I8)."""
    privacy_subjects: tuple[str, ...] = ()
    """What a privacy question must also name ("你", "聊天", "我说的")."""
    advice_patterns: tuple[re.Pattern[str], ...] = ()
    """Asking how to say or do something ("怎么开口"; dogfood I1): advice, not a practice."""
    hotline_pushback: tuple[str, ...] = ()
    """"Stop sending me hotlines" ("别老给我发热线"; dogfood I1)."""
    hotline_request_patterns: tuple[re.Pattern[str], ...] = ()
    """Asking for a hotline or help number ("能给我一个心理援助热线的号码吗"; 问题单第 7 条)."""
    hotline_anonymous: tuple[str, ...] = ()
    """Whether a hotline needs one's real name ("实名", "匿名")."""
    hotline_abroad: tuple[str, ...] = ()
    """Calling from abroad ("国外", "打国内")."""
    minor_disclosure_patterns: tuple[re.Pattern[str], ...] = ()
    """The user's own age under 18 ("我才初二", "其实我14岁"; 问题单第 5 条)."""
    strain_cues: tuple[str, ...] = ()
    """Strain that is no crisis cue ("撑不了多久了"), read only after a crisis (第 11 条)."""
    imminent_times: tuple[str, ...] = ()
    """Time words that, with ``imminent_means``, make reported risk urgent (第 6 条)."""
    imminent_means: tuple[str, ...] = ()
    """Means and place words that, with ``imminent_times``, make reported risk urgent."""
    keep_secret_cues: tuple[str, ...] = ()
    imminent_context: tuple[str, ...] = ()
    """Places and everyday means ("江边", "pills") that make someone else's reported risk
    urgent only together with risk the rules find in the reported words (round 3)."""
    third_party_unreachable: tuple[str, ...] = ()
    """The user cannot reach the other person ("我联系不上他"; round 3)."""
    third_party_questions: tuple[str, ...] = ()
    """The user asks what to do for the other person ("我该怎么办"; round 3)."""
    help_seeking_cues: tuple[str, ...] = ()
    """The user means to see a doctor or counsellor ("想去学校的心理中心看看"; round 3)."""
    hotline_fee: tuple[str, ...] = ()
    """A follow-up about a hotline: does it cost money ("要收费吗"; round 3)."""
    hotline_hours: tuple[str, ...] = ()
    """When it answers ("晚上有人接吗")."""
    hotline_language: tuple[str, ...] = ()
    """Which languages ("能讲普通话吗")."""
    hotline_real: tuple[str, ...] = ()
    """Whether the number is real ("你确定这个号码是真的吗")."""
    hotline_more: tuple[str, ...] = ()
    """More numbers ("除了12356还有别的吗")."""
    hotline_words: tuple[str, ...] = ()
    """A phone line or a call named ("这个号码", "打过去")."""
    hotline_places: Mapping[str, tuple[str, ...]] = field(
        default_factory=lambda: MappingProxyType({})
    )
    """Region code -> place names where the user says they are (round 3); ``ZZ`` is a
    place without verified numbers here."""
    help_seeking_school: tuple[str, ...] = ()
    """With ``help_seeking``, the place is at school or university (round 4, 2026-10-28)."""
    third_party_how_to_ask: tuple[str, ...] = ()
    """After the card for someone else's risk: how to start the talk or what to say to the
    other person ("我该怎么开口问他"; round 4)."""
    third_party_says_fine_patterns: tuple[re.Pattern[str], ...] = ()
    """After that card: the other person says they are fine ("他说他没事"; round 4)."""
    local_emergency_places: Mapping[str, tuple[str, ...]] = field(
        default_factory=lambda: MappingProxyType({})
    )
    """ISO country code -> place names of a country without verified hotlines here whose
    official emergency numbers render.yaml lists (round 4)."""
    suds_patterns: tuple[re.Pattern[str], ...] = ()
    """A whole-message 0-10 distress rating (SUDS, PRD COLBO-07; round 4); group 1 is the
    number."""
    # Round 5 (2026-10-29, re-test q2 第 5 节; draft, G-0).
    hotline_number_patterns: tuple[re.Pattern[str], ...] = ()
    """What a number is ("12356是干嘛的"); group 1 is the number."""
    hotline_unreachable: tuple[str, ...] = ()
    """A call that does not get through ("打不通", "一直占线")."""
    hotline_emergency: tuple[str, ...] = ()
    """The police or ambulance number asked for ("报警", "救护车")."""
    hotline_place_hint_patterns: tuple[re.Pattern[str], ...] = ()
    """An English place hotline_places does not name ("in Brazil"), on the raw text."""
    hotline_place_patterns: Mapping[str, tuple[re.Pattern[str], ...]] = field(
        default_factory=lambda: MappingProxyType({})
    )
    """Region code -> patterns on the raw text for places that need word edges ("the US")."""
    """The other person asked the user to keep it secret ("她不让我告诉别人"; 第 6 条)."""


def strip_marks(text: str) -> str:
    """Drop punctuation and symbols (Unicode categories P* and S*) from folded text."""
    return "".join(ch for ch in text if not unicodedata.category(ch).startswith(("P", "S")))


def load_perception_lexicon(tax: Taxonomy, directory: Path | None = None) -> PerceptionLexicon:
    """Load and validate ``perception.yaml``; ``None`` reads the packaged copy."""
    base: Traversable | Path = (
        resources.files("olivia").joinpath("data/lexicons") if directory is None else directory
    )
    doc = _read_yaml(base)
    extra = sorted(str(key) for key in doc if key not in _SECTIONS)
    if extra:
        raise PerceptionLexiconError(f"{_FILE}: unknown sections {extra}")

    emotions = _emotion_cues(tax, doc.get("emotion_cues"))
    raise_mods, lower_mods = _modifiers(doc.get("intensity_modifiers"))
    spectra = _spectrum_cues(tax, doc.get("spectrum_cues"))
    phrases = {name: _phrases(doc.get(name), name) for name in _PHRASE_SECTIONS}
    _check_distinct({name: phrases[name] for name in _SIGNAL_GROUP}, "signal sections")
    _check_distinct(
        {name: phrases[name] for name in ("note_recall", "note_recall_questions")},
        "note recall sections",
    )
    prefixes, exceptions = _negation(doc.get("negation"))
    feedback = _marked_section(doc.get("feedback"), "feedback", _FEEDBACK_KEYS)
    answers = _marked_section(doc.get("answers"), "answers", _ANSWER_KEYS)
    leave = _marked_list(doc.get("leave_taking"), "leave_taking")
    leave_whole = _marked_list(doc.get("leave_taking_whole"), "leave_taking_whole")
    lead_ins = _marked_list(doc.get("leave_taking_lead_ins"), "leave_taking_lead_ins")
    reported = _marked_list(doc.get("leave_taking_reported"), "leave_taking_reported")
    _check_distinct(
        {"leave_taking_whole": leave_whole, "leave_taking_lead_ins": lead_ins},
        "whole-clause goodbyes",
    )
    whole_requests = _marked_list(doc.get("direct_request_whole"), "direct_request_whole")
    aversion = tuple(strip_marks(p) for p in phrases["aversion"])
    _check_distinct(
        {
            "feedback.done": feedback["done"],
            "feedback.not_now": feedback["not_now"],
            "feedback.unhelpful": feedback["unhelpful"],
            "leave_taking": leave,
            "aversion": aversion,
            "kit_recall": tuple(strip_marks(p) for p in phrases["kit_recall"]),
        },
        "feedback phrases",
    )
    _check_distinct(
        {
            "feedback.unclear": feedback["unclear"],
            "answers.affirm": answers["affirm"],
            "answers.decline": answers["decline"],
            "direct_request_whole": whole_requests,
        },
        "whole-message replies",
    )
    return PerceptionLexicon(
        emotion_cues=MappingProxyType(emotions),
        raise_modifiers=raise_mods,
        lower_modifiers=lower_mods,
        spectrum_cues=MappingProxyType(spectra),
        direct_request=phrases["direct_request"],
        direct_request_whole=whole_requests,
        lock_on=phrases["lock_on"],
        lock_off=phrases["lock_off"],
        aversion=phrases["aversion"],
        intent_confirmed=phrases["intent_confirmed"],
        information_cues=phrases["information_cues"],
        referral_cues=phrases["referral_cues"],
        stabilization_cues=phrases["stabilization_cues"],
        acute_arousal_cues=phrases["acute_arousal_cues"],
        negation_prefixes=prefixes,
        negation_exceptions=exceptions,
        feedback_done=feedback["done"],
        feedback_not_now=feedback["not_now"],
        feedback_unhelpful=feedback["unhelpful"],
        feedback_unclear=feedback["unclear"],
        leave_taking=leave,
        leave_taking_whole=leave_whole,
        leave_taking_lead_ins=lead_ins,
        leave_taking_reported=reported,
        answer_affirm=answers["affirm"],
        answer_decline=answers["decline"],
        kit_recall=phrases["kit_recall"],
        therapy_names=MappingProxyType(_therapy_names(tax, doc.get("therapy_names"))),
        therapy_question_cues=phrases["therapy_question_cues"],
        therapy_request_cues=phrases["therapy_request_cues"],
        haven_exit=phrases["haven_exit"],
        note_recall=phrases["note_recall"],
        note_recall_questions=phrases["note_recall_questions"],
        situation_cues=MappingProxyType(_situation_cues(tax, doc.get("situation_cues"))),
        prolonged_grief=MappingProxyType(_prolonged_grief(doc.get("prolonged_grief"))),
        contraindication_cues=MappingProxyType(
            _keyed_cues(
                doc.get("contraindication_cues"),
                "contraindication_cues",
                tax.values("contraindication_enums"),
            )
        ),
        direct_request_patterns=_patterns(
            doc.get("direct_request_patterns"), "direct_request_patterns"
        ),
        contraindicated_practices=MappingProxyType(
            _keyed_cues(
                doc.get("contraindicated_practices"),
                "contraindicated_practices",
                tax.values("contraindication_enums"),
            )
        ),
        why_not=phrases["why_not"],
        cardiac_symptom_cues=phrases["cardiac_symptom_cues"],
        privacy_questions=phrases["privacy_questions"],
        privacy_subjects=phrases["privacy_subjects"],
        advice_patterns=_patterns(doc.get("advice_patterns"), "advice_patterns"),
        hotline_pushback=phrases["hotline_pushback"],
        hotline_request_patterns=_patterns(
            doc.get("hotline_request_patterns"), "hotline_request_patterns"
        ),
        hotline_anonymous=phrases["hotline_anonymous"],
        hotline_abroad=phrases["hotline_abroad"],
        minor_disclosure_patterns=_patterns(
            doc.get("minor_disclosure_patterns"), "minor_disclosure_patterns"
        ),
        strain_cues=phrases["strain_cues"],
        imminent_times=phrases["imminent_times"],
        imminent_means=phrases["imminent_means"],
        keep_secret_cues=phrases["keep_secret_cues"],
        imminent_context=phrases["imminent_context"],
        third_party_unreachable=phrases["third_party_unreachable"],
        third_party_questions=phrases["third_party_questions"],
        help_seeking_cues=phrases["help_seeking_cues"],
        hotline_fee=phrases["hotline_fee"],
        hotline_hours=phrases["hotline_hours"],
        hotline_language=phrases["hotline_language"],
        hotline_real=phrases["hotline_real"],
        hotline_more=phrases["hotline_more"],
        hotline_words=phrases["hotline_words"],
        hotline_places=MappingProxyType(_places(doc.get("hotline_places"))),
        help_seeking_school=phrases["help_seeking_school"],
        third_party_how_to_ask=phrases["third_party_how_to_ask"],
        third_party_says_fine_patterns=_patterns(
            doc.get("third_party_says_fine_patterns"), "third_party_says_fine_patterns"
        ),
        local_emergency_places=MappingProxyType(
            _places(doc.get("local_emergency_places"), "local_emergency_places")
        ),
        suds_patterns=_patterns(doc.get("suds_patterns"), "suds_patterns"),
        hotline_number_patterns=_patterns(
            doc.get("hotline_number_patterns"), "hotline_number_patterns"
        ),
        hotline_unreachable=phrases["hotline_unreachable"],
        hotline_emergency=phrases["hotline_emergency"],
        hotline_place_hint_patterns=_patterns(
            doc.get("hotline_place_hint_patterns"), "hotline_place_hint_patterns"
        ),
        hotline_place_patterns=MappingProxyType(_place_patterns(doc.get("hotline_place_patterns"))),
    )


def _read_yaml(base: Traversable | Path) -> Mapping[str, Any]:
    try:
        text = base.joinpath(_FILE).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise PerceptionLexiconError(f"{_FILE}: cannot read lexicon file: {exc}") from exc
    try:
        doc = safe_load(text)
    except yaml.YAMLError as exc:
        raise PerceptionLexiconError(f"{_FILE}: invalid YAML: {exc}") from exc
    if not isinstance(doc, dict):
        raise PerceptionLexiconError(f"{_FILE}: top level must be a mapping")
    version = doc.get("version")
    if type(version) is not int or version != 1:
        raise PerceptionLexiconError(f"{_FILE}: top-level 'version' must be 1, got {version!r}")
    return doc


def _mapping(node: Any, where: str) -> Mapping[Any, Any]:
    if not isinstance(node, dict) or not node:
        raise PerceptionLexiconError(f"{_FILE}: '{where}' must be a non-empty mapping")
    return node


def _phrases(node: Any, where: str) -> tuple[str, ...]:
    """A non-empty list of strings, folded for matching, with no repeats."""
    if not isinstance(node, list) or not node:
        raise PerceptionLexiconError(f"{_FILE}: '{where}' must be a non-empty list")
    out: list[str] = []
    for raw in node:
        if not isinstance(raw, str):
            raise PerceptionLexiconError(f"{_FILE}: {where}: {raw!r} is not a string")
        folded = normalize(raw)
        if not folded:
            raise PerceptionLexiconError(f"{_FILE}: {where}: {raw!r} is empty after folding")
        if folded in out:
            raise PerceptionLexiconError(f"{_FILE}: {where}: phrase {folded!r} is repeated")
        out.append(folded)
    return tuple(out)


def _patterns(node: Any, where: str) -> tuple[re.Pattern[str], ...]:
    """A non-empty list of regular expressions with the clause placeholders expanded;
    each must compile and must not match the empty string."""
    if not isinstance(node, list) or not node:
        raise PerceptionLexiconError(f"{_FILE}: '{where}' must be a non-empty list")
    out: list[re.Pattern[str]] = []
    for raw in node:
        if not isinstance(raw, str) or not raw.strip():
            raise PerceptionLexiconError(f"{_FILE}: {where}: {raw!r} is not a pattern")
        source = raw
        for slot, expansion in _PATTERN_SLOTS.items():
            source = source.replace(slot, expansion)
        try:
            pattern = re.compile(source)
        except re.error as exc:
            raise PerceptionLexiconError(f"{_FILE}: {where}: {raw!r}: {exc}") from exc
        if pattern.fullmatch(""):
            raise PerceptionLexiconError(f"{_FILE}: {where}: {raw!r} matches empty text")
        out.append(pattern)
    return tuple(out)


def _marked_section(node: Any, where: str, keys: tuple[str, ...]) -> dict[str, tuple[str, ...]]:
    """A mapping of ``keys`` to phrase lists, folded and then stripped of marks."""
    section = _mapping(node, where)
    extra = sorted(str(key) for key in section if key not in keys)
    if extra:
        raise PerceptionLexiconError(f"{_FILE}: {where}: unknown keys {extra}")
    return {key: _marked_list(section.get(key), f"{where}.{key}") for key in keys}


def _marked_list(node: Any, where: str) -> tuple[str, ...]:
    """A phrase list, folded and then stripped of marks, with no repeats."""
    stripped: list[str] = []
    for phrase in _phrases(node, where):
        bare = strip_marks(phrase)
        if not bare:
            raise PerceptionLexiconError(f"{_FILE}: {where}: {phrase!r} is only marks")
        if bare in stripped:
            raise PerceptionLexiconError(f"{_FILE}: {where}: phrase {bare!r} is repeated")
        stripped.append(bare)
    return tuple(stripped)


def _check_distinct(sections: Mapping[str, tuple[str, ...]], group: str) -> None:
    """Reject a phrase that two members of one section group both list."""
    owners: dict[str, str] = {}
    for name, phrases in sections.items():
        for phrase in phrases:
            owner = owners.setdefault(phrase, name)
            if owner != name:
                raise PerceptionLexiconError(
                    f"{_FILE}: phrase {phrase!r} appears in both {owner} and {name} ({group})"
                )


def _emotion_cues(tax: Taxonomy, node: Any) -> dict[str, tuple[str, ...]]:
    merged: dict[str, tuple[str, ...]] = {}
    for key, raw in _mapping(node, "emotion_cues").items():
        if not isinstance(key, str):
            raise PerceptionLexiconError(f"{_FILE}: emotion key {key!r} is not a string")
        try:
            emotion = tax.canonical_label("emotion", key)
        except TaxonomyError as exc:
            raise PerceptionLexiconError(f"{_FILE}: unknown emotion {key!r}") from exc
        phrases = _phrases(raw, f"emotion_cues.{key}")
        existing = merged.get(emotion, ())
        for phrase in phrases:
            if phrase in existing:
                raise PerceptionLexiconError(
                    f"{_FILE}: phrase {phrase!r} is repeated under {emotion} (key {key})"
                )
        merged[emotion] = existing + phrases
    _check_distinct(merged, "emotion_cues")
    return merged


def _modifiers(node: Any) -> tuple[tuple[str, ...], tuple[str, ...]]:
    section = _mapping(node, "intensity_modifiers")
    extra = sorted(str(key) for key in section if key not in ("raise", "lower"))
    if extra:
        raise PerceptionLexiconError(f"{_FILE}: intensity_modifiers: unknown keys {extra}")
    raise_mods = _phrases(section.get("raise"), "intensity_modifiers.raise")
    lower_mods = _phrases(section.get("lower"), "intensity_modifiers.lower")
    _check_distinct({"raise": raise_mods, "lower": lower_mods}, "intensity_modifiers")
    return raise_mods, lower_mods


def _spectrum_cues(tax: Taxonomy, node: Any) -> dict[str, tuple[str, ...]]:
    known = tax.spectrum_ids()
    section = _mapping(node, "spectrum_cues")
    spectra: dict[str, tuple[str, ...]] = {}
    for key, raw in section.items():
        if not isinstance(key, str) or key not in known:
            raise PerceptionLexiconError(
                f"{_FILE}: spectrum {key!r} is not a TAX distress spectrum id (quote it)"
            )
        spectra[key] = _phrases(raw, f"spectrum_cues.{key}")
    missing = [sid for sid in known if sid not in spectra]
    if missing:
        raise PerceptionLexiconError(f"{_FILE}: spectrum_cues has no entry for {missing}")
    _check_distinct(spectra, "spectrum_cues")
    # Taxonomy order, whatever the file order, so the distress vector is stable.
    return {sid: spectra[sid] for sid in known}


def _therapy_names(tax: Taxonomy, node: Any) -> dict[str, tuple[str, ...]]:
    methods = tax.methods()
    practices = [
        aid for aid, a in tax.action_registry().items() if a.action_type in _CARD_ACTION_TYPES
    ]
    section = _mapping(node, "therapy_names")
    names: dict[str, tuple[str, ...]] = {}
    for key, raw in section.items():
        method = methods.get(key) if isinstance(key, str) else None
        if method is None and key not in practices:
            raise PerceptionLexiconError(
                f"{_FILE}: therapy_names key {key!r} is not a method or practice id (quote it)"
            )
        names[key] = _phrases(raw, f"therapy_names.{key}")
    missing = [mid for mid, m in methods.items() if m.grade in _INFO_GRADES and mid not in names]
    if missing:
        raise PerceptionLexiconError(f"{_FILE}: therapy_names has no entry for {missing}")
    _check_distinct(names, "therapy_names")
    ordered = {mid: names[mid] for mid in methods if mid in names}
    ordered.update({aid: names[aid] for aid in practices if aid in names and aid not in ordered})
    return ordered


def _places(node: Any, where: str = "hotline_places") -> dict[str, tuple[str, ...]]:
    """``hotline_places`` (or ``local_emergency_places``): a two-letter region code (upper
    case) -> place names."""
    section = _mapping(node, where)
    places: dict[str, tuple[str, ...]] = {}
    for key, raw in section.items():
        if not (isinstance(key, str) and len(key) == 2 and key.isascii() and key.isupper()):
            raise PerceptionLexiconError(f"{_FILE}: {where}: {key!r} is not a region code")
        places[key] = _phrases(raw, f"{where}.{key}")
    _check_distinct(places, where)
    return places


def _place_patterns(node: Any) -> dict[str, tuple[re.Pattern[str], ...]]:
    """``hotline_place_patterns`` (round 5): a region code -> patterns on the raw text."""
    where = "hotline_place_patterns"
    section = _mapping(node, where)
    places: dict[str, tuple[re.Pattern[str], ...]] = {}
    for key, raw in section.items():
        if not (isinstance(key, str) and len(key) == 2 and key.isascii() and key.isupper()):
            raise PerceptionLexiconError(f"{_FILE}: {where}: {key!r} is not a region code")
        places[key] = _patterns(raw, f"{where}.{key}")
    return places


def _keyed_cues(node: Any, where: str, known: tuple[str, ...]) -> dict[str, tuple[str, ...]]:
    """``key -> phrases`` where every key is one of ``known`` (taxonomy ids or codes)."""
    section = _mapping(node, where)
    cues: dict[str, tuple[str, ...]] = {}
    for key, raw in section.items():
        if not isinstance(key, str) or key not in known:
            raise PerceptionLexiconError(f"{_FILE}: {where}: {key!r} is not a taxonomy id")
        cues[key] = _phrases(raw, f"{where}.{key}")
    _check_distinct(cues, where)
    return cues


def _situation_cues(tax: Taxonomy, node: Any) -> dict[str, tuple[str, ...]]:
    """``situation_cues``: situation code -> phrases; a red-flag code is not allowed.

    The seven red-flag dossiers are read by the red-flag detector (``red_flags.yaml``)
    and lead to a referral; a situation cue for one would bypass that path.
    """
    cues = _keyed_cues(node, "situation_cues", tax.situation_codes())
    flagged = sorted(code for code in cues if code in tax.red_flags())
    if flagged:
        raise PerceptionLexiconError(
            f"{_FILE}: situation_cues: {flagged} is a red-flag code (red_flags.yaml reads it)"
        )
    return cues


def _prolonged_grief(node: Any) -> dict[str, tuple[str, ...]]:
    section = _mapping(node, "prolonged_grief")
    extra = sorted(str(key) for key in section if key not in GRIEF_KEYS)
    if extra:
        raise PerceptionLexiconError(f"{_FILE}: prolonged_grief: unknown keys {extra}")
    lists = {key: _phrases(section.get(key), f"prolonged_grief.{key}") for key in GRIEF_KEYS}
    _check_distinct(lists, "prolonged_grief")
    return lists


def _negation(node: Any) -> tuple[tuple[str, ...], tuple[str, ...]]:
    section = _mapping(node, "negation")
    extra = sorted(str(key) for key in section if key not in ("prefixes", "exceptions"))
    if extra:
        raise PerceptionLexiconError(f"{_FILE}: negation: unknown keys {extra}")
    prefixes = _phrases(section.get("prefixes"), "negation.prefixes")
    exceptions = _phrases(section.get("exceptions"), "negation.exceptions")
    _check_distinct({"prefixes": prefixes, "exceptions": exceptions}, "negation")
    return prefixes, exceptions
