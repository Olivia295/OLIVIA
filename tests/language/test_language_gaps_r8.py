"""Round 8 language gaps (2026-11-25; drafts pending G-0), read by the language layer.

* Someone else stopping a psychiatric medicine is its own kind (``others_psychiatric``,
  owner's decision of 2026-11-25); someone else's other medicine stays ``general`` and the
  user's own stop keeps the class it names. The psychiatric classes are data
  (``substance.yaml`` ``stopping.others_classes``) and must be known classes.

Every example message is written here; none comes from an evaluation set or a re-test
report.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from olivia.core.language.data import LanguageDataError, _parse_substance, load_language_data
from olivia.core.language.guard import read_substance
from olivia.core.taxonomy import load_taxonomy

DATA = load_language_data(load_taxonomy())
CUES = DATA.substance
SUBSTANCE = Path(__file__).resolve().parents[2] / "olivia" / "data" / "lexicons" / "substance.yaml"


def _doc() -> dict[str, Any]:
    doc: dict[str, Any] = yaml.safe_load(SUBSTANCE.read_text(encoding="utf-8"))
    return doc


# -- 1: someone else's psychiatric medicine ---------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "我妈自己把抗抑郁药停了",
        "我爸最近偷偷把安眠药断了",
        "我哥把医生开的抗焦虑药全停了",
        "我女朋友说她不想吃精神科的药了，已经停了",
        "她自己把喹硫平停掉了",
    ],
)
def test_someone_elses_psychiatric_medicine_is_its_own_kind(text: str) -> None:
    reading = read_substance(CUES, text, context=False)
    assert reading.stopping and reading.withdrawal, text
    assert reading.kind == "others_psychiatric", text


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("我妈自己把降压药停了", "general"),
        ("我爸把止痛药停了", "general"),
        ("我自己把抗抑郁药停了", "antidepressant"),
        ("安眠药我昨天起自己停了", "sleep"),
        ("我把药停了", ""),
    ],
)
def test_other_kinds_are_unchanged(text: str, kind: str) -> None:
    assert read_substance(CUES, text, context=False).kind == kind


def test_the_psychiatric_classes_are_known_classes() -> None:
    assert CUES.stop_others_classes
    assert CUES.stop_others_classes <= CUES.classes.keys()
    assert "other_medicine" not in CUES.stop_others_classes
    assert "painkiller" not in CUES.stop_others_classes
    assert "others_psychiatric" in DATA.utterances.withdrawal_classes


def test_an_unknown_psychiatric_class_is_refused() -> None:
    doc = _doc()
    doc["stopping"]["others_classes"] = ["antidepressant", "no_such_class"]
    with pytest.raises(LanguageDataError, match="no_such_class"):
        _parse_substance(doc)


def test_the_psychiatric_classes_are_optional() -> None:
    doc = _doc()
    del doc["stopping"]["others_classes"]
    cues = _parse_substance(doc)
    assert cues.stop_others_classes == frozenset()
    assert read_substance(cues, "我妈自己把抗抑郁药停了", context=False).kind == "general"
