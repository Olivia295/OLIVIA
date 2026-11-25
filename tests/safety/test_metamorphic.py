"""Metamorphic testing of the rules-mode crisis screen (tests/safety/metamorphic.py).

Every seed the screen gets right is rewritten by every meaning-preserving transform and
screened again through ``SafetyScreen.assess``, the entry of test_case_suite.py. Each
(seed, transform) pair must keep the invariance rule (``metamorphic.holds``: expected L3
stays L3, L2 stays at L2 or above, L0 stays below L2), except the pairs listed in
known_metamorphic_gaps.yaml, which are held strictly, as tests/redteam/known_gaps.yaml is:

* ``test_seed_keeps_its_level``, one per seed: every pair of the seed that is not a known
  gap keeps the rule. A new failure fails here and names its (seed id, transform).
* ``test_known_gap``, one per gap, ``xfail(strict=True)``: a gap that starts passing fails
  the suite until it is removed (``python scripts/metamorphic_report.py --write-gaps``).
* ``test_gap_file_is_generated``: the gap file is exactly what that script writes for its
  entries, reasons and header counts included, so no entry is hand-picked.

L1 seeds are only reported (scripts/metamorphic_report.py). Cost: about 26,000 screenings,
a second or two without coverage (most rewrites fold to a text already scanned), so every
pair runs and nothing is sampled.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

import pytest

from olivia.core.models import CrisisLevel
from olivia.core.safety.crisis import SafetyScreen
from olivia.core.safety.lexicon import load_safety_lexicons
from olivia.core.safety.normalize import normalize
from olivia.core.taxonomy import load_taxonomy
from tests.safety.metamorphic import (
    BY_NAME,
    FAMILIES,
    GAPS_FILE,
    TRANSFORMS,
    Outcome,
    by_seed,
    gap_key,
    holds,
    load_gaps,
    load_seeds,
    render_gaps,
    skipped,
)

TAX = load_taxonomy()
SCREEN = SafetyScreen(TAX, load_safety_lexicons(TAX))
SEEDS = load_seeds()
BY_ID = {seed.id: seed for seed in SEEDS}
GAPS = load_gaps()
GAPS_BY_SEED = by_seed(GAPS)


def level(text: str) -> CrisisLevel:
    return SCREEN.assess(text).level


ORIGINAL = {seed.id: level(seed.text) for seed in SEEDS}
ASSERTED = [
    seed
    for seed in SEEDS
    if seed.expect is not CrisisLevel.L1 and not skipped(seed, ORIGINAL[seed.id])
]


@pytest.mark.parametrize("seed", ASSERTED, ids=[seed.id for seed in ASSERTED])
def test_seed_keeps_its_level(seed):
    known = GAPS_BY_SEED.get(seed.id, set())
    broken = []
    for transform in TRANSFORMS:
        if transform.name in known:
            continue
        got = level(transform(seed.text))
        if not holds(seed.expect, got):
            broken.append(f"{gap_key(seed.id, transform.name)}: {seed.expect.name} -> {got.name}")
    assert not broken, broken


def _gap_params() -> list[Any]:
    return [
        pytest.param(
            key, id=key, marks=pytest.mark.xfail(strict=True, raises=AssertionError, reason=why)
        )
        for key, why in GAPS.items()
    ]


@pytest.mark.parametrize("key", _gap_params())
def test_known_gap(key):
    seed_id, name = key.rsplit("/", 1)
    seed = BY_ID[seed_id]
    assert holds(seed.expect, level(BY_NAME[name](seed.text)))


def test_gaps_name_asserted_seeds_and_known_transforms():
    asserted = {seed.id for seed in ASSERTED}
    for key in GAPS:
        seed_id, name = key.rsplit("/", 1)
        assert seed_id in asserted, key
        assert name in BY_NAME, key


def test_gap_file_is_generated():
    outcomes = []
    for key in GAPS:
        seed_id, name = key.rsplit("/", 1)
        seed, transform = BY_ID[seed_id], BY_NAME[name]
        outcomes.append(Outcome(seed, transform, ORIGINAL[seed_id], level(transform(seed.text))))
    seed_order = {seed.id: i for i, seed in enumerate(SEEDS)}
    transform_order = {transform.name: i for i, transform in enumerate(TRANSFORMS)}
    outcomes.sort(key=lambda o: (seed_order[o.seed.id], transform_order[o.transform.name]))
    assert GAPS_FILE.read_text(encoding="utf-8") == render_gaps(outcomes), (
        "known_metamorphic_gaps.yaml is not what `python scripts/metamorphic_report.py "
        "--write-gaps` writes; rerun it"
    )


def test_skipped_seeds_are_the_known_limitations():
    # cases.yaml, composition_cases.yaml and tuned_probe.yaml hold their exact levels in
    # their own suites, so only known_false_positives.yaml (ideal != current) is skipped.
    skips = [seed for seed in SEEDS if skipped(seed, ORIGINAL[seed.id])]
    assert {seed.source for seed in skips} == {"known_limits"}
    assert Counter(seed.source for seed in SEEDS)["known_limits"] - len(skips) == sum(
        seed.expect is CrisisLevel.L1 for seed in SEEDS if seed.source == "known_limits"
    )


def test_seed_files_and_transform_families():
    assert {seed.source for seed in SEEDS} == {
        "cases",
        "compositions",
        "tuned_probe",
        "known_limits",
    }
    assert len(ASSERTED) >= 800
    assert {transform.family for transform in TRANSFORMS} == set(FAMILIES)
    assert len(BY_NAME) == len(TRANSFORMS)


@pytest.mark.parametrize(
    ("expect", "got", "kept"),
    [
        (CrisisLevel.L3, CrisisLevel.L3, True),
        (CrisisLevel.L3, CrisisLevel.L2, False),
        (CrisisLevel.L2, CrisisLevel.L3, True),
        (CrisisLevel.L2, CrisisLevel.L1, False),
        (CrisisLevel.L0, CrisisLevel.L1, True),
        (CrisisLevel.L0, CrisisLevel.L2, False),
        (CrisisLevel.L1, CrisisLevel.L3, None),
    ],
)
def test_invariance_rule(expect, got, kept):
    assert holds(expect, got) is kept


@pytest.mark.parametrize(
    ("name", "text", "expected"),
    [
        ("prefix_shuoshihua", "今天好累", "说实话，今天好累"),
        ("prefix_qishi", "今天好累", "其实今天好累"),
        ("suffix_period", "今天好累！", "今天好累。"),
        ("suffix_ellipsis", "今天好累", "今天好累……"),
        ("suffix_a", "今天好累。", "今天好累啊"),
        ("suffix_a", "怎么办？", "怎么办啊？"),
        ("suffix_period", "真的吗？？", "真的吗？？"),
        ("suffix_ellipsis", "真的吗。?", "真的吗……?"),
        ("punct_strip", "今天好累，真的。", "今天好累真的"),
        ("punct_strip", "i don't know.", "i don't know"),
        ("punct_to_space", "好累，真的。", "好累 真的 "),
        ("width_swap", "ok，好\u3000累", "ｏｋ,好 累"),
        ("width_swap", "好。", "好｡"),
        ("punct_ascii", "好累，真的。", "好累,真的."),
        ("bang_repeat", "好累！", "好累！！！"),
        ("bang_repeat", "好累。", "好累！！！"),
        ("ellipsis_repeat", "好累…", "好累………"),
        ("ellipsis_repeat", "好累", "好累…………"),
        ("emoji_sob", "好累", "好累😭"),
        ("emote_code_cry", "好累", "好累[哭]"),
        ("traditional", "说实话这个时候", "說實話這個時候"),
        ("spaces_between", "好累", "好 累"),
        ("zwsp_between", "好累了", "好\u200b累\u200b了"),
        ("invisible_fillers", "好累了", "好\u034f累\u3164了"),
        ("underline", "好累", "好\u0332累\u0332"),
        ("lead_overtime", "好累", "今天加班到九点。好累"),
        ("lead_overtime_space", "好累", "今天加班到九点 好累"),
        ("repeat_twice", "好累", "好累 好累"),
    ],
)
def test_transform(name, text, expected):
    assert BY_NAME[name](text) == expected


# Rewrites that touch only what normalize folds away: their text must fold to the seed's.
FOLDED_AWAY = (
    "width_swap",
    "traditional",
    "spaces_between",
    "zwsp_between",
    "zwnj_between",
    "bom_between",
    "invisible_mix",
    "invisible_fillers",
    "underline",
)


@pytest.mark.parametrize("name", FOLDED_AWAY)
def test_surface_rewrites_fold_to_the_seed_text(name):
    transform = BY_NAME[name]
    differ = [seed.id for seed in SEEDS if normalize(transform(seed.text)) != normalize(seed.text)]
    assert not differ
