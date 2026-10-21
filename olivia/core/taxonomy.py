"""Typed, read-only access to ``taxonomy.yaml``, the single source of truth.

All thresholds and enums come from the YAML file. Looking up anything that is
absent raises :class:`TaxonomyError`; no accessor ever returns a default.
"""

from __future__ import annotations

from collections.abc import Mapping
from importlib import resources
from pathlib import Path
from typing import Any, Literal

import yaml

_ID_LIST_SECTIONS: frozenset[str] = frozenset(
    {
        "emotions",
        "cognitive_distortions",
        "schemas",
        "satir_yearnings",
        "communication_stances",
        "contraindication_enums",
    }
)

_LABEL_KINDS: dict[str, tuple[str, str]] = {
    # kind -> (canonical id section, alias section)
    "emotion": ("emotions", "emotion_aliases"),
    "distortion": ("cognitive_distortions", "distortion_aliases"),
    "schema": ("schemas", "schema_aliases"),
    "yearning": ("satir_yearnings", "yearning_aliases"),
}


class TaxonomyError(Exception):
    """Raised when taxonomy data is missing, malformed, or looked up wrongly."""


class Taxonomy:
    """Read-only view over the parsed taxonomy mapping."""

    def __init__(self, data: Mapping[str, Any]) -> None:
        self._data = data

    @property
    def raw(self) -> Mapping[str, Any]:
        """The raw parsed mapping (for extension by richer views)."""
        return self._data

    @property
    def version(self) -> str:
        value = self._data.get("version")
        if not isinstance(value, str):
            raise TaxonomyError("taxonomy 'version' is missing or not a string")
        return value

    def threshold(self, dotted_path: str) -> float:
        node: Any = self._data
        for part in dotted_path.split("."):
            if not isinstance(node, Mapping) or part not in node:
                raise TaxonomyError(f"taxonomy key not found: {dotted_path}")
            node = node[part]
        if isinstance(node, bool) or not isinstance(node, int | float):
            raise TaxonomyError(f"taxonomy value at {dotted_path} is not numeric: {node!r}")
        return float(node)

    def values(self, name: str) -> tuple[str, ...]:
        if name == "distress_categories":
            return tuple(str(item) for item in self._section_list(name))
        if name not in _ID_LIST_SECTIONS:
            raise TaxonomyError(f"unknown taxonomy value set: {name}")
        return self._ids(name)

    def canonical_label(
        self, kind: Literal["emotion", "distortion", "schema", "yearning"], label: str
    ) -> str:
        if kind not in _LABEL_KINDS:
            raise TaxonomyError(f"unknown label kind: {kind}")
        section, alias_section = _LABEL_KINDS[kind]
        if label in self._ids(section):
            return label
        aliases = self._data.get(alias_section)
        if not isinstance(aliases, Mapping):
            raise TaxonomyError(f"taxonomy section missing or not a mapping: {alias_section}")
        if label in aliases:
            return str(aliases[label])
        raise TaxonomyError(f"unknown {kind} label: {label}")

    def _section_list(self, name: str) -> list[Any]:
        section = self._data.get(name)
        if not isinstance(section, list):
            raise TaxonomyError(f"taxonomy section missing or not a list: {name}")
        return section

    def _ids(self, name: str) -> tuple[str, ...]:
        ids: list[str] = []
        for item in self._section_list(name):
            if not isinstance(item, Mapping) or "id" not in item:
                raise TaxonomyError(f"taxonomy section {name} has an entry without 'id'")
            ids.append(str(item["id"]))
        return tuple(ids)


def load_taxonomy(path: Path | None = None) -> Taxonomy:
    """Load taxonomy from ``path``, or the copy packaged at ``olivia/data``."""
    try:
        if path is None:
            text = resources.files("olivia").joinpath("data/taxonomy.yaml").read_text("utf-8")
        else:
            text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise TaxonomyError(f"cannot read taxonomy file: {exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise TaxonomyError(f"invalid taxonomy YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise TaxonomyError("taxonomy top level must be a mapping")
    return Taxonomy(data)
