"""Session and the crisis screen's Stage 2 model (P6-6a): student by default, rules fallback."""

from __future__ import annotations

import random
import shutil
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path

import pytest

from olivia.core.models import CrisisLevel, HelpStage, PersonaProfile, UserRegion
from olivia.core.perception import student as student_module
from olivia.core.perception.student import StudentLoad, default_student, try_load_student
from olivia.core.safety.crisis import MODEL_FAILURE, RiskPrediction
from olivia.core.session import Session
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
NOW = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)
PACKAGED = Path(str(resources.files("olivia").joinpath("data/models/perception")))
CALM = "周末想去公园散散步"
STAGE1 = "我已经写好遗书了"
SCRIPT = (CALM, "今天上班好累", "给我一个方法", "/done", "[5%] 好累", "嗯")


def _profile() -> PersonaProfile:
    return PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        region=UserRegion("CN", "Asia/Shanghai"),
    )


def _open(**kwargs: object) -> Session:
    return Session.open(TAX, _profile(), rng=random.Random(5), now=lambda: NOW, **kwargs)  # type: ignore[arg-type]


def test_default_session_screens_with_the_student():
    fingerprint = default_student().model.fingerprint  # type: ignore[union-attr]
    session = _open()
    calm = session.turn(CALM).inspect
    assert calm["risk_model"] == f"student:{fingerprint}"
    assert calm["risk_model_reason"] is None
    assert calm["model_level"] in {level.name for level in CrisisLevel}
    score = calm["model_score"]
    assert isinstance(score, float) and 0.0 <= score <= 1.0
    # Stage 1 answers on its own; the model does not run on that turn.
    stage1 = session.turn(STAGE1).inspect
    assert stage1["assessed_level"] == "L3"
    assert stage1["model_level"] is None and stage1["model_score"] is None


def test_rules_only_session_has_no_model_fields():
    data = _open(rules_only=True).turn(CALM).inspect
    assert data["risk_model"] == "rules-only" and data["risk_model_reason"] is None
    assert data["model_level"] is None and data["model_score"] is None


def test_student_only_raises_the_session_level():
    model, rules = _open(), _open(rules_only=True)
    for text in SCRIPT:
        with_model, floor = model.turn(text), rules.turn(text)
        assessed = CrisisLevel[str(with_model.inspect["assessed_level"])]
        assert assessed >= CrisisLevel[str(floor.inspect["assessed_level"])], text


def test_unavailable_student_falls_back_to_rules_and_says_why(monkeypatch, tmp_path):
    broken = tmp_path / "model"
    shutil.copytree(PACKAGED, broken)
    (broken / "student.npz").write_bytes(b"tampered")
    monkeypatch.setattr(student_module, "default_student", lambda: try_load_student(broken))
    fallback, rules = _open(), _open(rules_only=True)
    for text in SCRIPT:
        got, want = fallback.turn(text), rules.turn(text)
        assert got.inspect["risk_model"] == "rules-only"
        assert got.inspect["risk_model_reason"] == "size_mismatch:student.npz"
        assert got.inspect["model_level"] is None and got.inspect["model_score"] is None
        # Same rng seed, same screen: the fallback session is the rules-only session.
        assert (got.reply, got.stage, got.crisis_level) == (
            want.reply,
            want.stage,
            want.crisis_level,
        )


def test_any_load_failure_reason_reaches_inspect(monkeypatch):
    monkeypatch.setattr(
        student_module, "default_student", lambda: StudentLoad(None, "npz_unreadable")
    )
    data = _open().turn(CALM).inspect
    assert (data["risk_model"], data["risk_model_reason"]) == ("rules-only", "npz_unreadable")


def test_injected_model_is_reported_and_its_l3_is_capped():
    class AlwaysL3:
        def predict(self, text: str) -> RiskPrediction:
            return RiskPrediction(CrisisLevel.L3, 0.95, ())

    result = _open(model=AlwaysL3()).turn(CALM)
    assert result.inspect["risk_model"] == "custom:AlwaysL3"
    assert result.inspect["model_level"] == "L3" and result.inspect["model_score"] == 0.95
    # model_plan_evidence stays off: Stage 2 never reaches L3 on a model's word.
    assert result.inspect["assessed_level"] == "L2"
    assert result.stage is HelpStage.S_CRISIS


@pytest.mark.parametrize("answer", ["raise", "out_of_contract"])
def test_broken_model_is_an_l2_model_failure(answer):
    class Broken:
        def predict(self, text: str) -> RiskPrediction:
            if answer == "raise":
                raise RuntimeError("boom")
            return RiskPrediction(CrisisLevel.L0, 2.0, ())

    data = _open(model=Broken()).turn(CALM).inspect
    assert data["model_level"] == "MODEL_FAILURE" and data["model_score"] is None
    assert MODEL_FAILURE in data["cue_ids"]  # type: ignore[operator]
    assert data["assessed_level"] == "L2"


def test_model_and_rules_only_are_exclusive():
    class Quiet:
        def predict(self, text: str) -> RiskPrediction:
            return RiskPrediction(CrisisLevel.L0, 0.0, ())

    with pytest.raises(ValueError, match="mutually exclusive"):
        _open(model=Quiet(), rules_only=True)
