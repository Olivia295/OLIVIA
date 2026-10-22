"""Static checks for the W.I.L.L.O.W. language data (willow.yaml, metaphors.yaml).

The engine that consumes these tables does not exist yet, so ``_apply`` below is the
reference substitution semantics the data is written for: scan left to right, take the
longest pattern at each position, never rescan replaced text.
"""

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
LANG = ROOT / "olivia/data/language"
DRAFT_HEADER = (
    "# 草稿：待 G-0 两名注册心理师审核"
    "（docs/superpowers/plans/2026-10-22-remaining-roadmap.md R1-4）"
)
EXEMPT_KINDS = {"CRISIS", "REFERRAL", "GRADE_C_INFO"}
FILTERS = {
    "didactic_rewrites",
    "depathologize",
    "diagnosis_terms",
    "word_window",
    "metaphor_weaving",
}
MAX_PHRASE = 16
# Death, drowning and falling imagery (and their near relatives) never appear in a metaphor.
FORBIDDEN_IMAGERY = (
    "死",
    "亡",
    "溺",
    "淹",
    "沉",
    "坠",
    "跌",
    "落",
    "坟",
    "墓",
    "葬",
    "枯",
    "凋",
    "崖",
    "渊",
    "灭",
    "熄",
    "断",
    "碎",
    "跳",
)


def _load(name: str) -> dict[str, Any]:
    data = yaml.safe_load((LANG / name).read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


@pytest.fixture(scope="module")
def willow() -> dict[str, Any]:
    return _load("willow.yaml")


@pytest.fixture(scope="module")
def metaphors() -> dict[str, Any]:
    return _load("metaphors.yaml")


@pytest.fixture(scope="module")
def tax() -> dict[str, Any]:
    data = yaml.safe_load((ROOT / "olivia/data/taxonomy.yaml").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _apply(text: str, table: dict[str, str]) -> str:
    keys = sorted(table, key=len, reverse=True)
    out: list[str] = []
    i = 0
    while i < len(text):
        for key in keys:
            if text.startswith(key, i):
                out.append(table[key])
                i += len(key)
                break
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def _touches(term: str, protected: str) -> bool:
    """True if replacing ``term`` could alter ``protected`` in some realistic context.

    Containment either way, or an overlap of two or more characters at the join
    (``term`` running into the start of ``protected`` or out of its end).
    """
    if term in protected or protected in term:
        return True
    for k in range(2, min(len(term), len(protected))):
        if term.endswith(protected[:k]) or term.startswith(protected[-k:]):
            return True
    return False


def _rewrites(willow: dict[str, Any]) -> dict[str, str]:
    return {e["pattern"]: e["rewrite"] for e in willow["didactic_rewrites"]}


def _depath(willow: dict[str, Any]) -> dict[str, str]:
    return {e["term"]: e["replacement"] for e in willow["depathologize"]}


def _all_metaphors(metaphors: dict[str, Any]) -> list[str]:
    phrases = [
        p for cell in metaphors["by_spectrum_yearning"].values() for v in cell.values() for p in v
    ]
    return phrases + list(metaphors["fallback"])


def _method_names(tax: dict[str, Any]) -> list[str]:
    tiers = tax["method_safety_tiers"]
    return [m["name_zh"] for g in ("grade_A", "grade_B", "grade_C") for m in tiers[g]["methods"]]


def _no_dupes(items: Iterable[str]) -> None:
    seen: set[str] = set()
    dupes = [x for x in items if x in seen or seen.add(x)]
    assert not dupes, dupes


@pytest.mark.parametrize("name", ["willow.yaml", "metaphors.yaml"])
def test_draft_header(name: str) -> None:
    first = (LANG / name).read_text(encoding="utf-8").splitlines()[0]
    assert first == DRAFT_HEADER


def test_section_sizes(willow: dict[str, Any], metaphors: dict[str, Any]) -> None:
    assert len(willow["didactic_rewrites"]) >= 40
    assert len(willow["diagnosis_terms"]) >= 60
    assert len(willow["depathologize"]) >= 30
    assert len(metaphors["fallback"]) == 6


def test_every_spectrum_yearning_cell_has_three_phrases(
    metaphors: dict[str, Any], tax: dict[str, Any]
) -> None:
    spectra = {s["id"] for s in tax["distress_spectra"]}
    yearnings = {y["id"] for y in tax["satir_yearnings"]}
    assert len(spectra) == 11 and len(yearnings) == 5
    grid = metaphors["by_spectrum_yearning"]
    assert set(grid) == spectra
    for sid, cell in grid.items():
        assert set(cell) == yearnings, sid
        for yid, phrases in cell.items():
            assert len(phrases) == 3, (sid, yid)
            assert all(isinstance(p, str) and p for p in phrases), (sid, yid)


def test_metaphor_phrases_are_short_and_gentle(metaphors: dict[str, Any]) -> None:
    for phrase in _all_metaphors(metaphors):
        assert len(phrase) <= MAX_PHRASE, phrase
        assert not [c for c in FORBIDDEN_IMAGERY if c in phrase], phrase


def test_no_duplicates(willow: dict[str, Any], metaphors: dict[str, Any]) -> None:
    _no_dupes(_all_metaphors(metaphors))
    _no_dupes(e["pattern"] for e in willow["didactic_rewrites"])
    _no_dupes(t.casefold() for t in willow["diagnosis_terms"])
    _no_dupes(e["term"] for e in willow["depathologize"])
    _no_dupes(willow["protected_terms"])


def test_diagnosis_terms_never_in_generated_text(
    willow: dict[str, Any], metaphors: dict[str, Any]
) -> None:
    terms = [t.casefold() for t in willow["diagnosis_terms"]]
    generated = (
        _all_metaphors(metaphors)
        + list(_rewrites(willow).values())
        + list(_depath(willow).values())
    )
    for text in generated:
        hits = [t for t in terms if t in text.casefold()]
        assert not hits, (text, hits)


def test_diagnosis_terms_do_not_block_protected_terms(willow: dict[str, Any]) -> None:
    for term in willow["diagnosis_terms"]:
        for protected in willow["protected_terms"]:
            assert term.casefold() not in protected.casefold(), (term, protected)


def test_protected_terms_cover_every_method_name(
    willow: dict[str, Any], tax: dict[str, Any]
) -> None:
    names = _method_names(tax)
    assert len(names) == 75
    assert set(names) <= set(willow["protected_terms"])
    assert "疗法" in willow["protected_terms"]


def test_depathologize_leaves_protected_terms_unchanged(willow: dict[str, Any]) -> None:
    table = _depath(willow)
    for protected in willow["protected_terms"]:
        assert _apply(protected, table) == protected, protected
        for term in table:
            assert not _touches(term, protected), (term, protected)


def test_didactic_patterns_stay_out_of_protected_terms(willow: dict[str, Any]) -> None:
    table = _rewrites(willow)
    for protected in willow["protected_terms"]:
        assert _apply(protected, table) == protected, protected
        for pattern in table:
            assert not _touches(pattern, protected), (pattern, protected)


def test_outputs_are_fixed_points(willow: dict[str, Any], metaphors: dict[str, Any]) -> None:
    """A rewrite or replacement never contains anything another filter would change."""
    rewrites, depath = _rewrites(willow), _depath(willow)
    for text in list(rewrites.values()) + list(depath.values()) + _all_metaphors(metaphors):
        assert _apply(text, rewrites) == text, text
        assert _apply(text, depath) == text, text


def test_diagnosis_and_depathologize_tables_are_disjoint(willow: dict[str, Any]) -> None:
    for term in _depath(willow):
        for diag in willow["diagnosis_terms"]:
            assert term not in diag and diag not in term, (term, diag)


def test_exemptions(willow: dict[str, Any]) -> None:
    exemptions = willow["exemptions"]
    assert set(exemptions) == FILTERS
    for kinds in exemptions.values():
        assert set(kinds) <= EXEMPT_KINDS
    assert exemptions["diagnosis_terms"] == []
    assert {"CRISIS", "REFERRAL"} <= set(exemptions["didactic_rewrites"])
    assert "REFERRAL" in exemptions["depathologize"]


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("你应该早点睡。", "或许可以试试早点睡。"),
        ("你应该很累吧。", "你可能很累吧。"),
        ("你必须面对它。", "如果愿意，你可以面对它。"),
        ("说出来不是必须的。", "说出来并不强求。"),
        ("我们必须先停下来。", "我们可以先停下来。"),
        ("首先，深呼吸三次。", "如果愿意，可以先深呼吸三次。"),
        ("你要知道，你并不孤单。", "想和你说，你并不孤单。"),
        ("千万不要熬夜。", "可以试着不熬夜。"),
        ("别想太多了，早点休息。", "想得多也没关系，早点休息。"),
        ("总而言之，你已经做得很好。", "回头看看，你已经做得很好。"),
    ],
)
def test_didactic_examples(willow: dict[str, Any], before: str, after: str) -> None:
    assert _apply(before, _rewrites(willow)) == after


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("你的症状让你很辛苦。", "你的这些感受让你很辛苦。"),
        ("焦虑发作的时候。", "焦虑涌上来的时候。"),
        ("这种病态的想法。", "这种卡住的想法。"),
        ("可以了解一下聚焦取向心理治疗。", "可以了解一下聚焦取向心理治疗。"),
    ],
)
def test_depathologize_examples(willow: dict[str, Any], before: str, after: str) -> None:
    assert _apply(before, _depath(willow)) == after
