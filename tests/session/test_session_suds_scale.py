"""Session gaps: Arousal = SUDS x taxonomy ``arousal.suds_mapping.scale_factor`` (SDD §4.4).

The rating a waiting card asks for used to be divided by a constant 10 in ``session.py``;
it now reads the taxonomy's ``scale_factor`` (0.10, "Normalized = SUDS / 10"). Every rating
0-10 gives exactly the arousal it gave before, and a changed factor changes both the
arousal and the line the reply leads with.

Every sentence typed is made up for these tests.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime
from importlib import resources
from typing import Any

import pytest

from olivia.core.language.data import load_language_data
from olivia.core.models import HelpStage, PersonaProfile, UserRegion
from olivia.core.session import Session
from olivia.core.taxonomy import Taxonomy, load_taxonomy
from olivia.core.yaml_load import safe_load

TAX = load_taxonomy()
NOW = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)
RENDER = load_language_data(TAX).render
REQUEST = "最近工作压力好大，能给我一个练习试试吗"
KEY = "arousal.suds_mapping.scale_factor"


def _open(tax: Taxonomy = TAX) -> Session:
    profile = PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        user_name="小林",
        region=UserRegion("CN", "Asia/Shanghai"),
    )
    return Session.open(tax, profile, rng=random.Random(5), now=lambda: NOW)


def _with_scale(factor: float) -> Taxonomy:
    text = resources.files("olivia").joinpath("data/taxonomy.yaml").read_text("utf-8")
    data: dict[str, Any] = safe_load(text)
    data["arousal"]["suds_mapping"]["scale_factor"] = factor
    return Taxonomy(data)


def test_the_packaged_scale_factor_is_one_tenth():
    assert TAX.threshold(KEY) == pytest.approx(0.10)


@pytest.mark.parametrize("rating", range(11))
def test_every_rating_gives_exactly_the_arousal_it_gave_before(rating):
    session = _open()
    session.turn(REQUEST)
    result = session.turn(str(rating))
    assert result.inspect["suds"] == rating
    assert result.inspect["arousal"] == rating / 10  # exactly SUDS / 10: 6 is 0.60, not more


def test_a_changed_scale_factor_changes_the_arousal_and_the_line():
    session = _open(_with_scale(0.05))
    session.turn(REQUEST)
    result = session.turn("9")
    assert result.inspect["arousal"] == pytest.approx(0.45)
    assert result.stage is HelpStage.S_EMPOWER  # 0.45 is no retreat
    assert result.reply.split("\n\n")[0] in RENDER.suds_heard  # below the somatic line
    default = _open()
    default.turn(REQUEST)
    assert default.turn("9").stage is HelpStage.S_EXPLORE  # 0.90 retreats
