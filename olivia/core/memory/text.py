"""Wording for the memory ledger: the replies about memory and the entry body labels.

All of it lives in ``olivia/data/templates/memory.yaml`` and is validated on load.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from types import MappingProxyType
from typing import Final

import yaml

from olivia.core.methods.bandit import Feedback
from olivia.core.models import HelpStage
from olivia.core.yaml_load import safe_load

_FILE: Final = "memory.yaml"
REPLY_KEYS: Final = (
    "note_saved",
    "note_too_long",
    "note_unavailable",
    "memory_unavailable",
    "summary_not_saved",
    "note_continue",
    "recall_found",
    "recall_latest",
    "recall_no_match",
    "recall_none",
    "recall_unavailable",
)
RECALL_SLOT: Final = "{note}"
"""The one slot of ``recall_found`` and ``recall_latest`` (F15); no other reply has one."""
_RECALL_WITH_NOTE: Final = frozenset({"recall_found", "recall_latest"})
_SUMMARY_KEYS: Final = (
    "heading",
    "time",
    "path",
    "spectra",
    "methods",
    "no_methods",
    "crisis",
    "self_rating",
    "turns",
    "support",
    "late_night",
    "battery",
    "significant",
    "none",
    "joiner",
    "arrow",
    "journal_heading",
    "journal_shown",
    "journal_skipped",
    "journal_helpful",
    "journal_not_helpful",
)
NO_FEEDBACK: Final = "none"


class MemoryTextError(Exception):
    """``memory.yaml`` is missing, malformed or incomplete."""


@dataclass(frozen=True)
class SummaryText:
    heading: str
    time: str
    path: str
    spectra: str
    methods: str
    no_methods: str
    crisis: str
    self_rating: str
    turns: str
    support: str
    late_night: str
    battery: str
    significant: str
    none: str
    joiner: str
    arrow: str
    journal_heading: str
    journal_shown: str
    journal_skipped: str
    journal_helpful: str
    journal_not_helpful: str


@dataclass(frozen=True)
class MemoryText:
    replies: Mapping[str, str]
    """One line per :data:`REPLY_KEYS` entry."""
    summary: SummaryText
    stages: Mapping[str, str]
    """Every :class:`HelpStage` value -> its everyday name."""
    spectra: Mapping[str, str]
    """Spectrum id ("01".."11") -> an everyday, non-clinical label."""
    feedback: Mapping[str, str]
    """Every :class:`Feedback` value, and ``"none"``, -> its label."""


def _mapping(value: object, where: str) -> dict[str, str]:
    if not isinstance(value, dict) or not value:
        raise MemoryTextError(f"{_FILE}: {where} must be a non-empty mapping")
    out: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(item, str) or not item.strip():
            raise MemoryTextError(f"{_FILE}: {where}.{key} must be a non-empty string")
        out[str(key)] = item
    return out


def _exact(found: dict[str, str], wanted: set[str], where: str) -> Mapping[str, str]:
    if set(found) != wanted:
        missing = sorted(wanted - set(found))
        extra = sorted(set(found) - wanted)
        raise MemoryTextError(f"{_FILE}: {where} missing {missing}, unknown {extra}")
    return MappingProxyType(found)


def load_memory_text(
    directory: Path | None = None, *, spectrum_ids: tuple[str, ...] | None = None
) -> MemoryText:
    """Load and validate ``memory.yaml``; ``None`` reads the packaged copy.

    ``spectrum_ids`` (the taxonomy's) makes the spectrum labels checked against them.
    """
    base: Traversable | Path = (
        resources.files("olivia").joinpath("data/templates") if directory is None else directory
    )
    try:
        doc = safe_load(base.joinpath(_FILE).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise MemoryTextError(f"{_FILE}: cannot read: {exc}") from exc
    if not isinstance(doc, dict) or doc.get("version") != 1:
        raise MemoryTextError(f"{_FILE}: must be a mapping with version 1")
    expected = {"version", "replies", "summary", "stages", "spectra", "feedback"}
    if set(doc) != expected:
        raise MemoryTextError(f"{_FILE}: sections must be exactly {sorted(expected)}")
    replies = _exact(_mapping(doc["replies"], "replies"), set(REPLY_KEYS), "replies")
    for key, line in replies.items():
        wanted = 1 if key in _RECALL_WITH_NOTE else 0
        if (
            line.count("{") != wanted
            or line.count("}") != wanted
            or (wanted and RECALL_SLOT not in line)
        ):
            raise MemoryTextError(f"{_FILE}: replies.{key} must have {wanted} {RECALL_SLOT} slot")
    summary = _exact(_mapping(doc["summary"], "summary"), set(_SUMMARY_KEYS), "summary")
    stages = _exact(_mapping(doc["stages"], "stages"), {s.value for s in HelpStage}, "stages")
    spectra_raw = _mapping(doc["spectra"], "spectra")
    spectra = (
        MappingProxyType(spectra_raw)
        if spectrum_ids is None
        else _exact(spectra_raw, set(spectrum_ids), "spectra")
    )
    feedback = _exact(
        _mapping(doc["feedback"], "feedback"),
        {f.value for f in Feedback} | {NO_FEEDBACK},
        "feedback",
    )
    return MemoryText(
        replies=replies,
        summary=SummaryText(**summary),
        stages=stages,
        spectra=spectra,
        feedback=feedback,
    )
