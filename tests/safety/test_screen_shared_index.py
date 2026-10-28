"""A screen with an injected model shares the rule screen's phrase index (G-3 memory).

Model mode used to build a second copy of the whole safety phrase index (cue phrases,
compositions, reported speech) for every session, beside the rule screen's own: about
12 MB of peak RSS in ``scripts/bench_loop.py``. ``SafetyScreen.with_model`` shares the
index instead; the index never changes once built, so every result is the same.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime
from pathlib import Path

import pytest

from olivia.core.models import PersonaProfile, UserRegion
from olivia.core.perception.student import choose_risk_model
from olivia.core.safety import crisis
from olivia.core.safety.crisis import SafetyScreen
from olivia.core.safety.lexicon import load_safety_lexicons
from olivia.core.session import Session
from olivia.core.taxonomy import load_taxonomy
from olivia.core.yaml_load import safe_load

TAX = load_taxonomy()
NOW = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)
CASES = safe_load((Path(__file__).parent / "cases.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def student():
    model = choose_risk_model(student=True).model
    if model is None:
        pytest.skip("the packaged student is not available")
    return model


def test_a_screen_with_a_model_gives_the_same_results_as_one_built_alone(student):
    lexicons = load_safety_lexicons(TAX)
    rules = SafetyScreen(TAX, lexicons)
    shared = rules.with_model(student, model_plan_evidence=False)
    alone = SafetyScreen(TAX, lexicons, student, model_plan_evidence=False)
    texts = [case["text"] for case in CASES]
    assert len(texts) > 100
    for text in texts:
        assert shared.assess(text) == alone.assess(text), text
        assert shared.reported_risk(text) == alone.reported_risk(text), text
    # The rule screen itself is unchanged by sharing.
    plain = SafetyScreen(TAX, lexicons)
    assert all(rules.assess(t) == plain.assess(t) for t in texts[:50])


def test_model_mode_builds_the_phrase_index_once(monkeypatch, student):
    built = []
    real = crisis._CueIndex.__init__

    def counting(self, lexicons):
        built.append(1)
        real(self, lexicons)

    profile = PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        region=UserRegion("CN", "Asia/Shanghai"),
    )
    Session.open(TAX, profile, rng=random.Random(1), now=lambda: NOW, student=True)
    monkeypatch.setattr(crisis._CueIndex, "__init__", counting)
    for seed in range(3):
        session = Session.open(TAX, profile, rng=random.Random(seed), now=lambda: NOW, student=True)
        assert session.turn("嗯").inspect["risk_model"].startswith("student:")
    assert built == []
