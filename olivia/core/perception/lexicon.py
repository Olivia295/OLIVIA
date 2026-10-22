"""Phrase lexicon for the rule-based perception stub, with strict load-time validation.

The stub builds one phrase matcher over every section, so anything ambiguous is
rejected here: unknown sections, emotion or spectrum ids that the taxonomy does not
define, empty lists, and a phrase listed twice within one section group (two emotions,
two spectra, or two of the direct-request / lock-on / lock-off / aversion /
intent-confirmed signals). The same phrase
may appear in different groups, for example as an emotion cue and a spectrum cue.

Emotion keys may be TAX emotion aliases; they are folded into the canonical id, and the
key order is kept as the tie-break priority between emotions (first key wins).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

import yaml

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
)
_SECTIONS: Final = frozenset(
    {
        "version",
        "emotion_cues",
        "intensity_modifiers",
        "spectrum_cues",
        "negation",
        *_PHRASE_SECTIONS,
    }
)
# Sections whose phrases must be distinct from each other: one phrase cannot both set
# and release the listening lock, both ask for a method and set the lock, or both reject
# a practice and commit to it.
_SIGNAL_GROUP: Final = ("direct_request", "lock_on", "lock_off", "aversion", "intent_confirmed")


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


def _negation(node: Any) -> tuple[tuple[str, ...], tuple[str, ...]]:
    section = _mapping(node, "negation")
    extra = sorted(str(key) for key in section if key not in ("prefixes", "exceptions"))
    if extra:
        raise PerceptionLexiconError(f"{_FILE}: negation: unknown keys {extra}")
    prefixes = _phrases(section.get("prefixes"), "negation.prefixes")
    exceptions = _phrases(section.get("exceptions"), "negation.exceptions")
    _check_distinct({"prefixes": prefixes, "exceptions": exceptions}, "negation")
    return prefixes, exceptions
