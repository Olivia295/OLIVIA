"""Model-mode perception (roadmap C1): the student's heads over the rule stub's context."""

from __future__ import annotations

import math
from dataclasses import replace
from types import MappingProxyType

import pytest

from olivia.core.models import CrisisLevel, PerceptionContext
from olivia.core.perception.model_heads import ModelHeads
from olivia.core.perception.student import (
    HeadValue,
    StudentModel,
    StudentRiskModel,
    default_student,
)
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
SOMATIC = TAX.threshold("arousal.thresholds.somatic_priority")
SPECTRA = TAX.spectrum_ids()


@pytest.fixture(scope="module")
def student() -> StudentModel:
    loaded = default_student()
    assert loaded.model is not None
    return loaded.model


def _rule(**overrides: object) -> PerceptionContext:
    base = PerceptionContext(
        valence=-0.3,
        arousal=0.40,
        fine_grained_emotion="calm",
        empathy_intent="EXPLORATION",
        risk_level=CrisisLevel.L1,
        crisis_confidence=0.35,
        communication_stance="CONGRUENT",
        readiness_to_change=0.5,
        distress_vector=MappingProxyType({}),
        detected_distortions=(),
        detected_schemas=(),
        deep_yearning="SAFETY",
        somatic_stabilization_eligible=False,
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


def _one_hot(labels: tuple[str, ...], winner: str) -> dict[str, float]:
    return {label: (0.9 if label == winner else 0.1 / (len(labels) - 1)) for label in labels}


def _heads(student: StudentModel, **overrides: object) -> dict[str, HeadValue]:
    labels = {name: head.labels for name, head in student.heads.items() if head.labels}
    heads: dict[str, HeadValue] = {
        "valence": -0.6,
        "emotion": _one_hot(labels["emotion"], "anxiety"),  # type: ignore[arg-type]
        "arousal": 0.70,
        "intent": _one_hot(labels["intent"], "VALIDATION"),  # type: ignore[arg-type]
        "risk": _one_hot(labels["risk"], "L1"),  # type: ignore[arg-type]
        "crisis_confidence": 0.2,
        "stance": _one_hot(labels["stance"], "PLACATING"),  # type: ignore[arg-type]
        "readiness": 0.25,
        "dominant_spectrum": _one_hot(labels["dominant_spectrum"], "04"),  # type: ignore[arg-type]
    }
    heads.update(overrides)  # type: ignore[arg-type]
    return heads


def _merger(
    student: StudentModel, monkeypatch: pytest.MonkeyPatch, heads: dict[str, HeadValue]
) -> ModelHeads:
    monkeypatch.setattr(student, "predict_heads", lambda text: heads)
    return ModelHeads(TAX, StudentRiskModel(student))


def test_model_fields_replace_the_rule_guesses(student, monkeypatch):
    merged = _merger(student, monkeypatch, _heads(student)).refine("x", _rule())
    assert merged.valence == -0.6
    assert merged.fine_grained_emotion == "anxiety"
    assert merged.empathy_intent == "VALIDATION"
    assert merged.communication_stance == "PLACATING"
    assert merged.readiness_to_change == 0.25
    # The screen's risk, the yearning and the empty introspection fields stay the rules'.
    assert (merged.risk_level, merged.crisis_confidence) == (CrisisLevel.L1, 0.35)
    assert merged.deep_yearning == "SAFETY"
    assert merged.detected_distortions == () and merged.detected_schemas == ()


@pytest.mark.parametrize(("rule", "model"), [(0.40, 0.70), (0.85, 0.30), (0.5, 0.5)])
def test_arousal_is_the_higher_of_rule_and_model(student, monkeypatch, rule, model):
    merger = _merger(student, monkeypatch, _heads(student, arousal=model))
    merged = merger.refine("x", _rule(arousal=rule))
    assert merged.arousal == max(rule, model)
    assert merged.somatic_stabilization_eligible is (max(rule, model) >= SOMATIC)


def test_model_spectrum_when_the_rules_found_no_cue(student, monkeypatch):
    merged = _merger(student, monkeypatch, _heads(student)).refine("x", _rule())
    vector = merged.distress_vector
    assert tuple(vector) == SPECTRA
    assert math.isclose(sum(vector.values()), 1.0)
    assert max(vector, key=lambda s: vector[s]) == "04"


def test_a_rule_spectrum_cue_wins(student, monkeypatch):
    rule_vector = MappingProxyType({s: (1.0 if s == "07" else 0.0) for s in SPECTRA})
    merged = _merger(student, monkeypatch, _heads(student)).refine(
        "x", _rule(distress_vector=rule_vector)
    )
    assert merged.distress_vector is rule_vector


def test_none_spectrum_leaves_no_vector(student, monkeypatch):
    labels = student.heads["dominant_spectrum"].labels
    assert labels is not None
    heads = _heads(student, dominant_spectrum=_one_hot(labels, "none"))
    merged = _merger(student, monkeypatch, heads).refine("x", _rule())
    assert dict(merged.distress_vector) == {}


@pytest.mark.parametrize(
    "broken",
    [
        {"valence": float("nan")},
        {"arousal": 1.5},
        {"readiness": -0.1},
        {"emotion": {}},
        {"intent": "VALIDATION"},
    ],
)
def test_out_of_contract_heads_leave_the_rule_context(student, monkeypatch, broken):
    rule = _rule()
    merged = _merger(student, monkeypatch, _heads(student, **broken)).refine("x", rule)
    assert merged is rule


def test_a_raising_forward_leaves_the_rule_context(student, monkeypatch):
    def boom(text: str) -> dict[str, HeadValue]:
        raise RuntimeError("boom")

    monkeypatch.setattr(student, "predict_heads", boom)
    rule = _rule()
    assert ModelHeads(TAX, StudentRiskModel(student)).refine("x", rule) is rule


def test_heads_from_the_risk_call_are_reused_once(student, monkeypatch):
    calls: list[str] = []
    real = student.predict_heads

    def counted(text: str) -> dict[str, HeadValue]:
        calls.append(text)
        return real(text)

    monkeypatch.setattr(student, "predict_heads", counted)
    risk = StudentRiskModel(student)
    merger = ModelHeads(TAX, risk)
    risk.predict("今天上班好累")
    merger.refine("今天上班好累", _rule())
    assert len(calls) == 1
    # Nothing is left over for the next turn: without a risk call it runs the student.
    merger.refine("我已经写好遗书了", _rule())
    assert len(calls) == 2


def test_labels_must_match_the_taxonomy(student, monkeypatch):
    head = student.heads["stance"]
    assert head.labels is not None
    broken = replace(head, labels=(*head.labels[:-1], "SILENT"))
    monkeypatch.setitem(student.heads, "stance", broken)
    with pytest.raises(ValueError, match="stance"):
        ModelHeads(TAX, StudentRiskModel(student))
