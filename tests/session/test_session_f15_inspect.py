"""F15: ``--inspect`` shows the level before the F10 denial cap (display only)."""

from __future__ import annotations

import random
from datetime import UTC, datetime

from olivia.cli import inspect_panel
from olivia.core.models import CrisisLevel, PersonaProfile, UserRegion
from olivia.core.safety.crisis import RiskPrediction
from olivia.core.session import Session
from olivia.core.taxonomy import load_taxonomy

TAX = load_taxonomy()
NOW = datetime(2026, 10, 25, 13, 0, tzinfo=UTC)
DENIAL = "我不会伤害自己"


class _DenialModel:
    """Scores L2 on the denial only, L0 on everything else."""

    def predict(self, text: str) -> RiskPrediction:
        if text == DENIAL:
            return RiskPrediction(CrisisLevel.L2, 0.6, ())
        return RiskPrediction(CrisisLevel.L0, 0.05, ())


def _open() -> Session:
    profile = PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        region=UserRegion("CN", "Asia/Shanghai"),
    )
    return Session.open(TAX, profile, rng=random.Random(5), now=lambda: NOW, model=_DenialModel())


def test_in_a_crisis_both_levels_are_shown():
    # After a confirmation the tracker reads the uncapped L2 (a relapse, F10 unchanged):
    # the panel used to say "风险 L2（本轮筛查 L1）" with no hint why.
    session = _open()
    session.turn("我写了一封遗书")
    session.turn("我现在安全了")
    result = session.turn(DENIAL)
    data = result.inspect
    assert result.in_crisis
    assert (data["level"], data["assessed_level"], data["uncapped_level"]) == ("L2", "L1", "L2")
    assert inspect_panel(result)[1].startswith("│ 风险 L2（本轮筛查 L1，否认封顶前 L2）")


def test_outside_a_crisis_both_levels_are_shown_and_nothing_else_changes():
    result = _open().turn(DENIAL)
    data = result.inspect
    assert not result.in_crisis and result.crisis_level is CrisisLevel.L1  # the cap held
    assert (data["assessed_level"], data["uncapped_level"]) == ("L1", "L2")
    assert inspect_panel(result)[1].startswith("│ 风险 L1（本轮筛查 L1，否认封顶前 L2）")


def test_an_uncapped_turn_has_no_extra_key():
    result = _open().turn("今天上班好累")
    assert "uncapped_level" not in result.inspect
    assert inspect_panel(result)[1].startswith("│ 风险 L0（本轮筛查 L0） · 危机中 否")
