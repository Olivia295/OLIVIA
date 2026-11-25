"""The student's input (HAZ-07, 2026-11-25): the training preprocessing plus a Traditional ->
Simplified fold and the removal of invisible and combining characters.

The training notebooks read text through ``preprocess`` (unescape, NBSP to space, collapse
whitespace, strip); ``model_input`` adds :func:`~olivia.core.perception.student.fold_input`
between the NBSP and the whitespace. Text with no Traditional, invisible or combining
character reads exactly as in training, so the golden fixture (``student_golden.json``)
and the notebook reference parity in test_student.py hold unchanged.
"""

from __future__ import annotations

import random
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from olivia.core.models import CrisisLevel, PersonaProfile, UserRegion
from olivia.core.perception.student import (
    StudentModel,
    StudentRiskModel,
    default_student,
    fold_input,
    model_input,
    preprocess,
)
from olivia.core.safety._trad2simp import AMBIGUOUS, TRAD_TO_SIMP, strict_pairs
from olivia.core.safety.crisis import SafetyScreen
from olivia.core.safety.lexicon import load_safety_lexicons
from olivia.core.safety.normalize import _DROPPED_RANGES
from olivia.core.session import ReplyKind, Session
from olivia.core.taxonomy import load_taxonomy
from tests.safety.metamorphic import BY_NAME, load_seeds

HERE = Path(__file__).parent
GOLDEN = yaml.safe_load((HERE / "student_golden.json").read_text(encoding="utf-8"))
SEEDS = load_seeds()
TAX = load_taxonomy()
VS16 = "️"
# Every code point model_input drops: the safety fold's, less whitespace and U+FE0F.
DROPPED = [
    chr(cp)
    for first, last in _DROPPED_RANGES
    for cp in range(first, last + 1)
    if not chr(cp).isspace() and cp != 0xFE0F
]
WHITESPACE = [chr(cp) for cp in range(sys.maxunicode + 1) if chr(cp).isspace()]


@pytest.fixture(scope="module")
def student() -> StudentModel:
    loaded = default_student()
    assert loaded.reason is None and loaded.model is not None
    return loaded.model


def _strict_traditional(text: str) -> str:
    """``text`` with each character written in its first strict Traditional form."""
    views: dict[str, str] = {}
    for trad, simp in strict_pairs().items():
        views.setdefault(simp, trad)
    return "".join(views.get(ch, ch) for ch in text)


def _plain(text: str) -> bool:
    """No character model_input folds or drops."""
    strict = strict_pairs()
    return not any(ch in strict or ch in DROPPED or ch == VS16 for ch in text)


# -- what stays as in training ----------------------------------------------------------------


def test_golden_texts_read_as_in_training() -> None:
    # The golden fixture has no Traditional or invisible text: no case changes.
    for case in GOLDEN["cases"]:
        assert model_input(case["text"]) == preprocess(case["text"]), case["text"]


def test_simplified_seed_sentences_read_as_in_training() -> None:
    plain = [seed.text for seed in SEEDS if _plain(seed.text)]
    assert len(plain) > 1000
    for text in plain:
        assert model_input(text) == preprocess(text), text


def test_no_nfkc_casefold_punctuation_or_space_removal() -> None:
    for text in ("ＰＴＳＤ，好累！", "I Can't", "想 死", "［５％］", "鱼&熊掌 好"):
        assert model_input(text) == text
    assert model_input("  鱼&amp;熊掌   好\t\n") == "鱼&熊掌 好"


@pytest.mark.parametrize("char", sorted("乾著後於覆藉沈后") + sorted(AMBIGUOUS))
def test_valid_simplified_and_ambiguous_characters_stay(char: str) -> None:
    # 著名, 乾坤, 覆盖 and 慰藉 are Simplified text; 讎 (仇 / 雠) depends on the word.
    assert model_input(f"想{char}死") == f"想{char}死"


# -- the Traditional fold ------------------------------------------------------------------------


def test_every_strict_pair_folds() -> None:
    wrong = [trad for trad, simp in strict_pairs().items() if model_input(trad) != simp]
    assert not wrong, "".join(wrong)


def test_strict_pairs_are_the_table_less_the_simplified_sources() -> None:
    assert len(strict_pairs()) == len(TRAD_TO_SIMP) - 11


@pytest.mark.parametrize(
    "trad,simp",
    [
        ("我想自殺", "我想自杀"),
        ("遺書寫好了", "遗书写好了"),
        ("說實話，我覺得沒意思", "说实话，我觉得没意思"),
        ("心裡很亂", "心里很乱"),
        ("爲甚麼説不出口", "为甚么说不出口"),
    ],
)
def test_traditional_reads_as_simplified(student: StudentModel, trad: str, simp: str) -> None:
    assert model_input(trad) == simp
    assert student.encode(trad) == student.encode(simp)


def test_traditional_view_of_every_seed_reads_back(student: StudentModel) -> None:
    for seed in SEEDS:
        assert model_input(_strict_traditional(seed.text)) == model_input(seed.text), seed.id


def test_a_traditional_crisis_sentence_scores_as_the_simplified_one(
    student: StudentModel,
) -> None:
    risk = StudentRiskModel(student)
    crisis = [
        seed
        for seed in SEEDS
        if seed.expect >= CrisisLevel.L2 and _strict_traditional(seed.text) != seed.text
    ]
    assert len(crisis) > 100
    for seed in crisis[:40]:
        assert risk.predict(_strict_traditional(seed.text)) == risk.predict(seed.text), seed.id


# -- invisible, format and combining characters --------------------------------------------------


def test_every_dropped_code_point_goes() -> None:
    kept = [f"U+{ord(ch):04X}" for ch in DROPPED if model_input(f"想{ch}死") != "想死"]
    assert not kept


def test_whitespace_is_collapsed_as_in_training() -> None:
    for ch in WHITESPACE:
        assert model_input(f"想{ch}死") == "想 死", f"U+{ord(ch):04X}"
    assert model_input("想 ​ 死") == "想 死"  # a dropped character between two spaces
    assert model_input("​ 想死 ﻿") == "想死"


def test_an_escaped_invisible_character_goes() -> None:
    assert model_input("想&#8203;死") == "想死"


def test_the_emoji_variation_selector_stays_after_a_symbol_only() -> None:
    assert model_input("今天好开心❤️☀️") == "今天好开心❤️☀️"
    assert model_input("想️死") == "想死"
    assert model_input("考了5️⃣0️⃣分") == "考了50分"  # keycaps
    assert model_input("❤​️") == "❤️"
    assert model_input("❤️️") == "❤️"
    assert fold_input("️") == ""


@pytest.mark.parametrize(
    "name",
    [
        "zwsp_between",
        "zwnj_between",
        "bom_between",
        "invisible_mix",
        "invisible_fillers",
        "underline",
        "emoji_zwj",
    ],
)
def test_invisible_rewrites_of_every_seed_read_as_the_seed(name: str) -> None:
    # tests/safety/metamorphic.py's rewrites; spaces_between is left as it is (training
    # reads spaces), and emoji_zwj only loses its joiner.
    transform = BY_NAME[name]
    for seed in SEEDS:
        expected = model_input(seed.text)
        if name == "emoji_zwj":
            expected = model_input(seed.text + "😮💨")
        assert model_input(transform(seed.text)) == expected, seed.id


# -- the session: the same crisis flow or question in either script --------------------------

NOW = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)
PROFILE = PersonaProfile(
    age_confirmed_18_plus=True,
    created_at=NOW,
    updated_at=NOW,
    region=UserRegion("CN", "Asia/Shanghai"),
)


def _turn(text: str) -> tuple[CrisisLevel, bool, ReplyKind]:
    session = Session.open(TAX, PROFILE, rng=random.Random(7), now=lambda: NOW, student=True)
    result = session.turn(text)
    assert str(result.inspect["risk_model"]).startswith("student:")
    return result.crisis_level, result.in_crisis, result.reply_kind


def test_a_model_only_alarm_takes_the_same_turn_in_either_script() -> None:
    # The seeds the rules alone keep below L2, so the student's level and its 0.6 band
    # decide between the crisis flow and one direct question (owner decision 2026-10-26).
    screen = SafetyScreen(TAX, load_safety_lexicons(TAX))
    model_only = [
        seed
        for seed in SEEDS
        if seed.expect >= CrisisLevel.L2
        and _strict_traditional(seed.text) != seed.text
        and screen.assess(seed.text).level < CrisisLevel.L2
    ]
    assert len(model_only) >= 10
    for seed in model_only[:12]:
        simplified = _turn(seed.text)
        assert _turn(_strict_traditional(seed.text)) == simplified, seed.id
        assert _turn(BY_NAME["invisible_mix"](seed.text)) == simplified, seed.id
