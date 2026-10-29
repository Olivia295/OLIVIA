"""Session perception in model mode (roadmap C1) and in the default rules mode."""

from __future__ import annotations

import json
import random
from datetime import UTC, datetime

import pytest

from olivia.core.models import PersonaProfile, UserRegion
from olivia.core.perception.rule_stub import FALLBACK_EMOTION, EmpathyIntent, dominant_spectrum
from olivia.core.perception.student import StudentModel, default_student
from olivia.core.safety.tracker import CrisisTracker
from olivia.core.session import Session
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
NOW = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)
PERCEPTION_KEYS = ("valence", "emotion", "intent", "stance", "readiness")
TEXTS = (
    "周末想去公园散散步",
    "最近工作压力很大，有点焦虑，晚上总睡不着",
    "心慌得要命，喘不上气",
    "我觉得都是我的错，是我不够好",
    "和室友吵架了，她根本不在乎我",
    "[20%] 好累",
    "我已经写好遗书了",
)


@pytest.fixture(scope="module")
def student() -> StudentModel:
    loaded = default_student()
    assert loaded.model is not None
    return loaded.model


def _profile() -> PersonaProfile:
    return PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        region=UserRegion("CN", "Asia/Shanghai"),
    )


def _open(*, student: bool) -> Session:
    return Session.open(TAX, _profile(), rng=random.Random(5), now=lambda: NOW, student=student)


def _top(probs: object) -> str:
    assert isinstance(probs, dict)
    return max(probs, key=lambda label: probs[label])


def _rule_context(text: str):  # type: ignore[no-untyped-def]
    rules = _open(student=False)
    return rules._shared.stub.perceive(text, rules._shared.screen.assess(text))[0]


@pytest.mark.parametrize("text", TEXTS)
def test_model_mode_perception_comes_from_the_student(student, text):
    data = _open(student=True).turn(text).inspect
    heads = student.predict_heads(text)
    rule = _rule_context(text)
    assert data["valence"] == heads["valence"]
    assert data["emotion"] == _top(heads["emotion"])
    assert data["intent"] == _top(heads["intent"])
    assert data["stance"] == _top(heads["stance"])
    assert data["readiness"] == heads["readiness"]
    assert data["arousal"] == max(rule.arousal, heads["arousal"])  # type: ignore[type-var]
    spectrum = _top(heads["dominant_spectrum"])
    if rule.distress_vector:
        assert data["spectrum"] == dominant_spectrum(rule.distress_vector)
    else:
        assert data["spectrum"] == (None if spectrum == "none" else spectrum)
    # Types and ranges: ids and numbers only.
    assert isinstance(data["valence"], float) and -1.0 <= data["valence"] <= 1.0
    assert isinstance(data["readiness"], float) and 0.0 <= data["readiness"] <= 1.0
    assert isinstance(data["arousal"], float) and 0.0 <= data["arousal"] <= 1.0
    assert data["emotion"] in TAX.emotion_profiles()
    assert data["intent"] in {intent.value for intent in EmpathyIntent}
    assert data["stance"] in TAX.values("communication_stances")


def test_model_mode_reads_the_student_and_differs_from_the_stub(student):
    # The stub's stance and readiness are fixed placeholders; the student's are not.
    seen = {(r["stance"], r["readiness"]) for r in _turns(_open(student=True), TEXTS)}
    assert seen != {("CONGRUENT", 0.5)}
    assert len({readiness for _, readiness in seen}) > 1


def _turns(session: Session, texts: tuple[str, ...]) -> list[dict[str, object]]:
    return [session.turn(text).inspect for text in texts]


@pytest.mark.parametrize("text", TEXTS)
def test_rules_mode_shows_the_stub_values(text):
    data = _open(student=False).turn(text).inspect
    rule = _rule_context(text)
    assert data["valence"] == rule.valence
    assert data["emotion"] == rule.fine_grained_emotion
    assert data["intent"] == rule.empathy_intent
    assert data["stance"] == "CONGRUENT"
    assert data["readiness"] == 0.5


def test_one_forward_pass_per_turn(student, monkeypatch):
    calls: list[int] = []
    real = student.raw_outputs

    def counted(text: str):  # type: ignore[no-untyped-def]
        calls.append(1)
        return real(text)

    monkeypatch.setattr(student, "raw_outputs", counted)
    session = _open(student=True)
    for text in ("今天上班好累", "我已经写好遗书了", "嗯"):  # the second is a Stage 1 turn
        before = len(calls)
        session.turn(text)
        assert len(calls) - before == 1, text


def test_rules_mode_never_runs_the_student(student, monkeypatch):
    def refuse(text: str):  # type: ignore[no-untyped-def]
        raise AssertionError("the student ran in rules mode")

    monkeypatch.setattr(student, "raw_outputs", refuse)
    _turns(_open(student=False), TEXTS)


def test_the_crisis_tracker_keeps_the_rule_valence(monkeypatch):
    seen: list[float | None] = []
    real = CrisisTracker.observe

    def spy(self, assessment, text, valence=None, **kwargs):  # type: ignore[no-untyped-def]
        seen.append(valence)
        return real(self, assessment, text, valence, **kwargs)

    monkeypatch.setattr(CrisisTracker, "observe", spy)
    session = _open(student=True)
    for text in TEXTS[:5]:
        session.turn(text)
    # Fix F2a: no emotion word (the fallback emotion at 0.0) is passed as None, no evidence.
    rule = [_rule_context(text) for text in TEXTS[:5]]
    expected = [
        None if c.fine_grained_emotion == FALLBACK_EMOTION and c.valence == 0.0 else c.valence
        for c in rule
    ]
    assert seen == expected and None in seen and any(v is not None for v in seen)


def test_model_mode_inspect_holds_no_user_text():
    secret = "蓝色风筝和外婆的院子"
    session = _open(student=True)
    results = [
        session.turn(f"我想起{secret}，心里很难受"),
        session.turn(f"给我一个方法吧，{secret}"),
        session.turn("我不想活了"),
    ]
    dumped = json.dumps([r.inspect for r in results], ensure_ascii=False)
    for fragment in ("蓝色风筝", "外婆", "院子", "难受", "不想活"):
        assert fragment not in dumped
    for result in results:
        for key in PERCEPTION_KEYS:
            value = result.inspect[key]
            # A number, or an ASCII id such as "anxiety" or "SUPER_REASONABLE".
            assert isinstance(value, float) or (
                isinstance(value, str) and value.isascii() and value.replace("_", "").isalpha()
            )
