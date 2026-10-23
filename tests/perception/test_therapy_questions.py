"""Questions about a Grade B/C therapy by name (roadmap next-phase A4, PRD §8.1).

The stub sets ``TurnSignals.therapy_question`` to the asked method's taxonomy id when a
``therapy_names`` phrase and a ``therapy_question_cues`` phrase both survive in the
message. Grade A therapies have no information card and are never listed, so asking
about them is not a therapy question.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from olivia.core.models import CrisisLevel, SafetyGrade
from olivia.core.perception.lexicon import PerceptionLexiconError, load_perception_lexicon
from olivia.core.perception.rule_stub import RuleStub
from olivia.core.safety.crisis import CrisisAssessment
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
LEXICON = load_perception_lexicon(TAX)
STUB = RuleStub(TAX, LEXICON)
PACKAGED = Path(__file__).resolve().parents[2] / "olivia" / "data" / "lexicons" / "perception.yaml"
INFO_GRADES = (SafetyGrade.GRADE_B, SafetyGrade.GRADE_C)


def _asked(text: str) -> str | None:
    assessment = CrisisAssessment(CrisisLevel.L0, 0.0, "STAGE2", False, ())
    return STUB.perceive(text, assessment)[1].therapy_question


@pytest.mark.parametrize(
    ("text", "method_id"),
    [
        ("EMDR 有用吗", "21"),
        ("emdr?", "21"),
        ("眼动脱敏是什么", "21"),
        ("眼動脫敏是什麼", "21"),  # Traditional folds to Simplified
        ("你知道认知加工疗法吗", "22"),
        ("暴露疗法有效吗", "05"),
        ("延长暴露疗法是什么", "23"),  # the longer name wins over 暴露疗法
        ("叙事暴露疗法和叙事疗法有什么区别？", "26"),  # the first named therapy
        ("想了解一下精神分析", "31"),
        ("能介绍一下IFS吗", "47"),
        ("图式疗法是什么？", "19"),
        ("萨提亚冰山模型是什么意思", "48"),
        ("情绪聚焦疗法靠谱吗", "40"),
        ("最近很难受，EMDR 能帮到我吗", "21"),
    ],
)
def test_question_about_a_grade_b_or_c_therapy(text: str, method_id: str) -> None:
    assert _asked(text) == method_id


@pytest.mark.parametrize(
    "text",
    [
        "认知行为疗法是什么",  # Grade A: no information card
        "正念是什么",  # Grade A family (14, 15, 18), not 68 哈科米正念躯体心理治疗
        "DBT有用吗",
        "我在做EMDR",  # names it, asks nothing
        "我的咨询师用的是叙事疗法",
        "我不想了解精神分析",  # the cue is negated
        "left是什么意思",  # EFT only as a whole Latin word
        "这个script有用吗",  # IPT likewise
        "ERP系统有用吗",  # enterprise software, not a therapy alias
        "家庭治疗是什么",  # five family therapies: too vague to pick one
        "给我一个方法",
        "这是什么",
    ],
)
def test_hard_negatives_are_not_therapy_questions(text: str) -> None:
    assert _asked(text) is None


def test_every_grade_b_and_c_method_is_listed_under_its_own_names() -> None:
    names = LEXICON.therapy_names
    expected = {mid for mid, m in TAX.methods().items() if m.grade in INFO_GRADES}
    assert set(names) == expected
    for mid, phrases in names.items():
        for part in TAX.methods()[mid].name_zh.split(" / "):
            assert any(part.replace(" ", "") == p for p in phrases), (mid, part)
    assert LEXICON.therapy_question_cues


def _doc() -> dict[str, Any]:
    loaded = yaml.safe_load(PACKAGED.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _load_mutated(tmp_path: Path, mutate: Callable[[dict[str, Any]], None]) -> None:
    doc = _doc()
    mutate(doc)
    (tmp_path / "perception.yaml").write_text(
        yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    load_perception_lexicon(TAX, tmp_path)


def _grade_a_entry(doc: dict[str, Any]) -> None:
    doc["therapy_names"]["01"] = ["认知行为疗法"]


def _unknown_entry(doc: dict[str, Any]) -> None:
    doc["therapy_names"]["99"] = ["不存在疗法"]


def _missing_entry(doc: dict[str, Any]) -> None:
    del doc["therapy_names"]["21"]


def _shared_phrase(doc: dict[str, Any]) -> None:
    doc["therapy_names"]["22"].append("emdr")


def _no_cues(doc: dict[str, Any]) -> None:
    doc["therapy_question_cues"] = []


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (_grade_a_entry, "Grade B or C"),
        (_unknown_entry, "Grade B or C"),
        (_missing_entry, "no entry"),
        (_shared_phrase, "appears in both"),
        (_no_cues, "therapy_question_cues"),
    ],
)
def test_lexicon_rejects_bad_therapy_names(
    tmp_path: Path, mutate: Callable[[dict[str, Any]], None], message: str
) -> None:
    with pytest.raises(PerceptionLexiconError, match=message):
        _load_mutated(tmp_path, mutate)
