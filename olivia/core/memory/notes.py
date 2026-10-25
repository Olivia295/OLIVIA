"""Explicit "remember this" requests (decision D1, step B2).

A message is a note request only when it *starts* with a cue from
``olivia/data/lexicons/memory.yaml`` (「记住：……」「帮我记一下……」「请记得……」); the
text after the cue, minus leading separators and surrounding whitespace, is the note,
kept verbatim. Cues are compared on the raw message (no folding), so the stored text is
exactly what the user typed. ``recall_ignore`` lists the words a recall question
("周四要见的那个人是谁来着") is stripped of before the notes are searched (F15,
``recall.py``). Whether a request is honoured (never on a crisis turn) is
the recorder's call, not this module's.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Final

import yaml

from olivia.core.safety.normalize import normalize
from olivia.core.yaml_load import safe_load

_FILE: Final = "memory.yaml"
_SECTIONS: Final = frozenset({"version", "note_request", "separators", "recall_ignore"})
_GROUPS: Final = ("needs_separator", "direct")


class NoteCuesError(Exception):
    """The memory lexicon is missing, malformed or ambiguous."""


@dataclass(frozen=True)
class NoteCues:
    needs_separator: tuple[str, ...]
    """Cues that count only when a separator follows ("记住：", not "记住了")."""
    direct: tuple[str, ...]
    """Cues the note may follow directly ("帮我记一下明天……")."""
    separators: frozenset[str]
    recall_ignore: tuple[str, ...] = ()
    """Words a recall question is stripped of before the notes are searched (F15): the
    question's own wording and particles, folded like the safety screen, longest first."""

    def find(self, message: str) -> str | None:
        """The note text if ``message`` is a request to remember something, else None."""
        head = message.lstrip()
        cues = [(cue, True) for cue in self.needs_separator] + [(c, False) for c in self.direct]
        cues.sort(key=lambda item: len(item[0]), reverse=True)
        for cue, needs_separator in cues:
            if not head.startswith(cue):
                continue
            rest = head[len(cue) :]
            if needs_separator and (not rest or rest[0] not in self.separators):
                return None
            note = rest.lstrip("".join(self.separators)).strip()
            return note or None
        return None


def _phrases(value: object, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise NoteCuesError(f"{_FILE}: {where} must be a non-empty list")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item or item != item.strip():
            raise NoteCuesError(f"{_FILE}: {where} entries must be non-empty, unpadded strings")
        out.append(item)
    return tuple(out)


def load_note_cues(directory: Path | None = None) -> NoteCues:
    """Load and validate the memory lexicon; ``None`` reads the packaged copy."""
    base: Traversable | Path = (
        resources.files("olivia").joinpath("data/lexicons") if directory is None else directory
    )
    try:
        doc = safe_load(base.joinpath(_FILE).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise NoteCuesError(f"{_FILE}: cannot read: {exc}") from exc
    if not isinstance(doc, dict) or doc.get("version") != 1:
        raise NoteCuesError(f"{_FILE}: must be a mapping with version 1")
    if set(doc) != _SECTIONS:
        raise NoteCuesError(f"{_FILE}: sections must be exactly {sorted(_SECTIONS)}")
    request = doc["note_request"]
    if not isinstance(request, dict) or set(request) != set(_GROUPS):
        raise NoteCuesError(f"{_FILE}: note_request must hold exactly {list(_GROUPS)}")
    groups = {name: _phrases(request[name], f"note_request.{name}") for name in _GROUPS}
    every = [cue for name in _GROUPS for cue in groups[name]]
    if len(every) != len(set(every)):
        raise NoteCuesError(f"{_FILE}: a cue is listed twice")
    separators = doc["separators"]
    if not isinstance(separators, str) or not separators:
        raise NoteCuesError(f"{_FILE}: separators must be a non-empty string")
    ignore = _phrases(doc["recall_ignore"], "recall_ignore")
    if len(ignore) != len(set(ignore)):
        raise NoteCuesError(f"{_FILE}: a recall_ignore word is listed twice")
    folded = sorted({normalize(word) for word in ignore}, key=lambda w: (-len(w), w))
    return NoteCues(
        groups["needs_separator"], groups["direct"], frozenset(separators), tuple(folded)
    )
