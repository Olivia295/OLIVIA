"""NG-8: nothing OLIVIA can say draws on astrology, tarot or other divination (PRD §2.2).

Every user-facing string comes from the YAML under ``olivia/data`` (cards, language,
templates, resources) or from the CLI's own sentences, so scanning both covers every
reply. ``taxonomy.yaml`` is not scanned: its "算命式预言" names the CBT distortion
(fortune telling), an internal label.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

from olivia import cli

ROOT = Path(__file__).resolve().parents[2]
SOURCES = ("cards", "language", "templates", "resources")
TERMS = (
    "星盘", "塔罗", "星座", "占卜", "算命", "风水", "运势", "水逆", "八字",
    "生辰", "紫微", "灵摆", "水晶", "能量石", "命理", "前世", "因果报应",
)  # fmt: skip


def _strings(node: object) -> Iterator[str]:
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for key, value in node.items():
            yield from _strings(key)
            yield from _strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _strings(value)


def _data_files() -> list[Path]:
    return sorted(
        path
        for source in SOURCES
        for path in (ROOT / "olivia/data" / source).rglob("*")
        if path.suffix in {".yaml", ".yml", ".json"}
    )


def test_the_scan_reaches_the_data():
    names = {path.name for path in _data_files()}
    assert {"grade_a.yaml", "utterances.yaml", "journal.yaml"} <= names


@pytest.mark.parametrize("path", _data_files(), ids=lambda p: p.name)
def test_no_divination_words_in_data(path: Path):
    text = path.read_text(encoding="utf-8")
    doc = yaml.safe_load(text)
    found = {term for s in _strings(doc) for term in TERMS if term in s}
    assert not found, f"{path.relative_to(ROOT)}: {sorted(found)}"


def test_no_divination_words_in_cli_sentences():
    found = {term for s in cli.USER_TEXTS for term in TERMS if term in s}
    assert not found
