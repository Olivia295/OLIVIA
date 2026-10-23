"""Questions about a Grade B/C therapy by name (roadmap next-phase A4, PRD §8.1).

The stub sets ``TurnSignals.therapy_question`` to the asked method's taxonomy id when a
``therapy_names`` phrase and a ``therapy_question_cues`` phrase both survive in the
message. Since F3 a few Grade A practices are listed under their common names too (正念,
CBT, 呼吸练习 ...): asking what one is gets its short explainer, and asking to do it
(``therapy_request_cues``) sets ``therapy_request`` and ``direct_request``.
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
from olivia.core.perception.signals import TurnSignals
from olivia.core.safety.crisis import CrisisAssessment
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
LEXICON = load_perception_lexicon(TAX)
STUB = RuleStub(TAX, LEXICON)
PACKAGED = Path(__file__).resolve().parents[2] / "olivia" / "data" / "lexicons" / "perception.yaml"
INFO_GRADES = (SafetyGrade.GRADE_B, SafetyGrade.GRADE_C)


def _signals(text: str) -> TurnSignals:
    assessment = CrisisAssessment(CrisisLevel.L0, 0.0, "STAGE2", False, ())
    return STUB.perceive(text, assessment)[1]


def _asked(text: str) -> str | None:
    return _signals(text).therapy_question


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


@pytest.mark.parametrize(
    ("text", "method_id"),
    [
        ("认知行为疗法是什么", "01"),
        ("CBT是什么", "01"),
        ("正念是什么", "15"),
        ("冥想有用吗", "15"),
        ("DBT有用吗", "12"),
        ("呼吸练习有用吗", "28"),
        ("接地练习是什么", "30:grounding"),
        ("哈科米正念躯体心理治疗是什么", "68"),  # the longer B name wins over 正念
        ("创伤聚焦认知行为疗法是什么", "27"),  # likewise over 认知行为疗法
    ],
)
def test_question_about_a_grade_a_practice(text: str, method_id: str) -> None:
    signals = _signals(text)
    assert signals.therapy_question == method_id
    assert signals.therapy_request is None


@pytest.mark.parametrize(
    ("text", "method_id"),
    [
        ("能带我做一下正念吗", "15"),
        ("CBT是什么？能教我做一下吗", "01"),
        ("教我练一下呼吸练习", "28"),
        ("我想试试冥想", "15"),
        ("陪我做一下肌肉放松吧", "29"),
    ],
)
def test_request_for_a_grade_a_practice(text: str, method_id: str) -> None:
    signals = _signals(text)
    assert signals.therapy_request == method_id
    assert signals.direct_request
    assert signals.therapy_question is None


@pytest.mark.parametrize(
    "text",
    [
        "我不想试试正念",  # negated request
        "我在做正念练习",  # names it, asks for nothing
        "冥想的时候我总走神",
        "这话很接地气",  # not 接地练习
        "飞机着陆了",  # not 着陆技术
        "带我做一下吧",  # no practice named
    ],
)
def test_no_request_without_a_named_practice_asked_for(text: str) -> None:
    signals = _signals(text)
    assert signals.therapy_request is None
    assert signals.therapy_question is None


def test_a_request_for_a_grade_b_or_c_therapy_gets_its_information() -> None:
    signals = _signals("能带我做一下EMDR吗")
    assert signals.therapy_question == "21"
    assert signals.therapy_request is None


def test_every_grade_b_and_c_method_is_listed_under_its_own_names() -> None:
    names = LEXICON.therapy_names
    expected = {mid for mid, m in TAX.methods().items() if m.grade in INFO_GRADES}
    assert set(names) >= expected
    practices = set(names) - expected
    assert practices == {"01", "03", "11", "12", "15", "18", "28", "29", "30:grounding"}
    for mid, phrases in names.items():
        if mid in practices:
            continue
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
        (_unknown_entry, "method or practice id"),
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
