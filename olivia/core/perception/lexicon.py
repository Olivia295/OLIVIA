"""Phrase lexicon for the rule-based perception stub, with strict load-time validation.

The stub builds one phrase matcher over every section, so anything ambiguous is
rejected here: unknown sections, emotion or spectrum ids that the taxonomy does not
define, empty lists, and a phrase listed twice within one section group (two emotions,
two spectra, or two of the direct-request / lock-on / lock-off / aversion /
intent-confirmed / kit-recall signals). The same phrase
may appear in different groups, for example as an emotion cue and a spectrum cue.

Feedback and answer phrases (roadmap R-7b) are folded once more with
:func:`strip_marks`, since the stub matches them on the message without punctuation
("试过了，没用" reads as "试过了没用"). Within the feedback group (done, not now,
unhelpful, plus the aversion and kit-recall phrases, which the stub matches there too) and
within the whole-message group (unclear, affirm, decline) a phrase may appear once.

Emotion keys may be TAX emotion aliases; they are folded into the canonical id, and the
key order is kept as the tie-break priority between emotions (first key wins).

``therapy_names`` maps every Grade B and Grade C taxonomy method id, and nothing else, to
the names a user may ask about it by; a name belongs to one method only.
``therapy_question_cues`` are the words that make a named therapy a question.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

import yaml

from olivia.core.models import SafetyGrade
from olivia.core.safety.normalize import normalize
from olivia.core.taxonomy import Taxonomy, TaxonomyError

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
_FEEDBACK_KEYS: Final = ("done", "not_now", "unhelpful", "unclear")
_ANSWER_KEYS: Final = ("affirm", "decline")
_INFO_GRADES: Final = frozenset({SafetyGrade.GRADE_B, SafetyGrade.GRADE_C})


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
    answer_affirm: tuple[str, ...]
    """Whole-message yes ("好的"), marks stripped."""
    answer_decline: tuple[str, ...]
    """Whole-message no ("不用了"), marks stripped."""
    kit_recall: tuple[str, ...]
    """The user asks to see a shelved method again ("锦囊里那个再给我看看")."""
    therapy_names: Mapping[str, tuple[str, ...]]
    """Grade B/C method id -> folded names, every such method present, in taxonomy order."""
    therapy_question_cues: tuple[str, ...]
    """Words that make a named therapy a question ("是什么", "有用吗")."""


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
    prefixes, exceptions = _negation(doc.get("negation"))
    feedback = _marked_section(doc.get("feedback"), "feedback", _FEEDBACK_KEYS)
    answers = _marked_section(doc.get("answers"), "answers", _ANSWER_KEYS)
    aversion = tuple(strip_marks(p) for p in phrases["aversion"])
    _check_distinct(
        {
            "feedback.done": feedback["done"],
            "feedback.not_now": feedback["not_now"],
            "feedback.unhelpful": feedback["unhelpful"],
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
        },
        "whole-message replies",
    )
    return PerceptionLexicon(
        emotion_cues=MappingProxyType(emotions),
        raise_modifiers=raise_mods,
        lower_modifiers=lower_mods,
        spectrum_cues=MappingProxyType(spectra),
        direct_request=phrases["direct_request"],
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
        answer_affirm=answers["affirm"],
        answer_decline=answers["decline"],
        kit_recall=phrases["kit_recall"],
        therapy_names=MappingProxyType(_therapy_names(tax, doc.get("therapy_names"))),
        therapy_question_cues=phrases["therapy_question_cues"],
    )


def _read_yaml(base: Traversable | Path) -> Mapping[str, Any]:
    try:
        text = base.joinpath(_FILE).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise PerceptionLexiconError(f"{_FILE}: cannot read lexicon file: {exc}") from exc
    try:
        doc = yaml.safe_load(text)
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


def _marked_section(node: Any, where: str, keys: tuple[str, ...]) -> dict[str, tuple[str, ...]]:
    """A mapping of ``keys`` to phrase lists, folded and then stripped of marks."""
    section = _mapping(node, where)
    extra = sorted(str(key) for key in section if key not in keys)
    if extra:
        raise PerceptionLexiconError(f"{_FILE}: {where}: unknown keys {extra}")
    out: dict[str, tuple[str, ...]] = {}
    for key in keys:
        name = f"{where}.{key}"
        stripped: list[str] = []
        for phrase in _phrases(section.get(key), name):
            bare = strip_marks(phrase)
            if not bare:
                raise PerceptionLexiconError(f"{_FILE}: {name}: {phrase!r} is only marks")
            if bare in stripped:
                raise PerceptionLexiconError(f"{_FILE}: {name}: phrase {bare!r} is repeated")
            stripped.append(bare)
        out[key] = tuple(stripped)
    return out


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
    section = _mapping(node, "therapy_names")
    names: dict[str, tuple[str, ...]] = {}
    for key, raw in section.items():
        method = methods.get(key) if isinstance(key, str) else None
        if method is None or method.grade not in _INFO_GRADES:
            raise PerceptionLexiconError(
                f"{_FILE}: therapy_names key {key!r} is not a Grade B or C method id (quote it)"
            )
        names[key] = _phrases(raw, f"therapy_names.{key}")
    missing = [mid for mid, m in methods.items() if m.grade in _INFO_GRADES and mid not in names]
    if missing:
        raise PerceptionLexiconError(f"{_FILE}: therapy_names has no entry for {missing}")
    _check_distinct(names, "therapy_names")
    return {mid: names[mid] for mid in methods if mid in names}


def _negation(node: Any) -> tuple[tuple[str, ...], tuple[str, ...]]:
    section = _mapping(node, "negation")
    extra = sorted(str(key) for key in section if key not in ("prefixes", "exceptions"))
    if extra:
        raise PerceptionLexiconError(f"{_FILE}: negation: unknown keys {extra}")
    prefixes = _phrases(section.get("prefixes"), "negation.prefixes")
    exceptions = _phrases(section.get("exceptions"), "negation.exceptions")
    _check_distinct({"prefixes": prefixes, "exceptions": exceptions}, "negation")
    return prefixes, exceptions
