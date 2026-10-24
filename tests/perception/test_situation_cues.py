"""Situation cues for the 60 distress dossiers (plan D-2, PRD §8.2).

Every dossier the lexicon wires has hand-written positives and hard negatives in
``situation_cases.yaml``; the cues never borrow crisis or red-flag wording, never key a
red-flag code (the red-flag detector owns those seven dossiers) and never shadow the
two m0 situations of A1.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from olivia.core.models import CrisisLevel
from olivia.core.perception.lexicon import PerceptionLexiconError, load_perception_lexicon
from olivia.core.perception.rule_stub import RuleStub
from olivia.core.safety.crisis import CrisisAssessment
from olivia.core.safety.normalize import normalize
from olivia.core.taxonomy import Taxonomy, load_taxonomy

HERE = Path(__file__).resolve().parent
LEXICONS = HERE.parents[1] / "olivia/data/lexicons"
CASES: dict[str, dict[str, list[str]]] = yaml.safe_load(
    (HERE / "situation_cases.yaml").read_text(encoding="utf-8")
)["cases"]
M0_CODES = ("SIT-06-04", "SIT-11-01")
TAX = load_taxonomy()
LEX = load_perception_lexicon(TAX)
STUB = RuleStub(TAX, LEX)
CALM = CrisisAssessment(CrisisLevel.L0, 0.0, "STAGE1", False, ())


def _situations(text: str) -> frozenset[str]:
    return STUB.perceive(text, CALM)[1].situation_codes


# risk.yaml sections that are dialogue words, not crisis wording: the D3 answer words and
# the safety-confirmation vetoes ("不知道", "但是"). A pair's ``requests`` ("最简单",
# "步骤") only count next to one of its ``anchors``, so only the anchors are crisis wording.
_DIALOGUE_SECTIONS = frozenset({"version", "intent_answers", "confirm_veto"})


def _crisis_phrases() -> set[str]:
    """Every crisis cue of risk.yaml and every red_flags.yaml pattern, folded."""
    risk = yaml.safe_load((LEXICONS / "risk.yaml").read_text(encoding="utf-8"))
    flags = yaml.safe_load((LEXICONS / "red_flags.yaml").read_text(encoding="utf-8"))
    phrases: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("patterns", "anchors") and isinstance(value, list):
                    phrases.update(normalize(p) for p in value if isinstance(p, str))
                elif key != "requests":
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk({k: v for k, v in risk.items() if k not in _DIALOGUE_SECTIONS})
    walk(flags["entries"])
    return phrases


CASE_PARAMS = [
    pytest.param(code, text, id=f"{code}-{i}")
    for code, group in CASES.items()
    for i, text in enumerate(group["positive"])
]
NEGATIVE_PARAMS = [
    pytest.param(code, text, id=f"{code}-not-{i}")
    for code, group in CASES.items()
    for i, text in enumerate(group["negative"])
]


def test_every_wired_dossier_has_cases_and_every_case_a_wired_dossier() -> None:
    wired = set(LEX.situation_cues) - set(M0_CODES)
    assert set(CASES) == wired
    for code, group in CASES.items():
        assert len(group["positive"]) >= 2, code
        assert len(group["negative"]) >= 2, code


@pytest.mark.parametrize(("code", "text"), CASE_PARAMS)
def test_positive_sets_the_situation(code: str, text: str) -> None:
    assert code in _situations(text)


@pytest.mark.parametrize(("code", "text"), NEGATIVE_PARAMS)
def test_hard_negative_does_not_set_it(code: str, text: str) -> None:
    assert code not in _situations(text)


def test_cue_coverage_is_at_least_80_percent_of_the_dossiers() -> None:
    codes = TAX.situation_codes()
    assert len(codes) == 60
    assert len(LEX.situation_cues) >= 48


def test_no_red_flag_dossier_has_situation_cues() -> None:
    # The seven red-flag dossiers are read by the red-flag detector (red_flags.yaml).
    assert not set(LEX.situation_cues) & set(TAX.red_flags())


def test_no_cue_overlaps_crisis_or_red_flag_wording() -> None:
    """No cue equals, contains or sits inside a risk.yaml or red_flags.yaml pattern."""
    crisis = _crisis_phrases()
    assert len(crisis) > 100
    clashes = [
        (code, cue, phrase)
        for code, cues in LEX.situation_cues.items()
        for cue in cues
        for phrase in crisis
        if cue in phrase or phrase in cue
    ]
    assert not clashes


def test_no_cue_shadows_an_m0_cue() -> None:
    """Within the group the longer hit wins, so no other cue may contain an m0 cue."""
    m0 = [cue for code in M0_CODES for cue in LEX.situation_cues[code]]
    others = [
        cue for code, cues in LEX.situation_cues.items() if code not in M0_CODES for cue in cues
    ]
    assert not [(a, b) for a in others for b in m0 if a in b or b in a]


# -- prolonged grief (COLBO-06b, PRD 特性一-4; draft, G-0) -------------------------------

PROLONGED_GRIEF = [
    "妈妈去世一年多了，我还是走不出来",
    "我爸过世两年了，我到现在都没法接受",
    "奶奶走了半年，我还是每天想她",
    "外公离开我们好几年了，我一直放不下",
    "一年前我妈去世了，到现在还是接受不了",
    "[60%] 爸爸不在了快三年，我还是缓不过来",
]
NOT_PROLONGED_GRIEF = [
    "外婆去世好几年了，现在想起来更多是温暖",
    "宠物走了一年了，我已经慢慢好了",
    "妈妈去世一年多了",  # no unresolved grief named
    "这一年我还是走不出来",  # no death named
    "奶奶去世了，我还是放不下",  # no long time since
    "妈妈去世一年多了，我并不是走不出来",  # the unresolved part is negated
    "工作了一年多，还是放不下手机",
]


@pytest.mark.parametrize("text", PROLONGED_GRIEF)
def test_prolonged_grief_sets_the_bereavement_situation(text: str) -> None:
    assert "SIT-06-04" in _situations(text)


@pytest.mark.parametrize("text", NOT_PROLONGED_GRIEF)
def test_a_settled_or_partial_loss_is_no_prolonged_grief(text: str) -> None:
    assert "SIT-06-04" not in _situations(text)


def test_prolonged_grief_lists_are_loaded_and_distinct() -> None:
    lists = LEX.prolonged_grief
    assert set(lists) == {"loss", "duration", "unresolved"}
    assert all(lists.values())
    words = [w for ws in lists.values() for w in ws]
    assert len(words) == len(set(words))


def test_situation_cue_keys_must_not_be_red_flag_codes(tax: Taxonomy, tmp_path: Path) -> None:
    text = (LEXICONS / "perception.yaml").read_text(encoding="utf-8")
    bipolar = 'situation_cues:\n  "SIT-02-04":\n    - 心情忽高忽低\n'
    text = text.replace("situation_cues:\n", bipolar, 1)
    (tmp_path / "perception.yaml").write_text(text, encoding="utf-8")
    with pytest.raises(PerceptionLexiconError, match="red-flag code"):
        load_perception_lexicon(tax, tmp_path)


@pytest.fixture(scope="module")
def tax() -> Taxonomy:
    return TAX
