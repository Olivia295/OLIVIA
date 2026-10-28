"""S5 wording (2026-10-26, draft pending G-0): the reach-out line, the crisis farewell and
the safety-plan reminder pass WILLOW unchanged and the output gate, and the farewell keeps
every number of every region's crisis card, emergency numbers first."""

from __future__ import annotations

import random
from datetime import date

import pytest

from olivia.core.chang.safety_plan import Contact, SafetyPlan, crisis_reminder, farewell_people
from olivia.core.language import LanguageEngine
from olivia.core.language.data import ContentKind, load_language_data
from olivia.core.language.filters import apply_willow
from olivia.core.models import CrisisLevel, HelpStage, UserRegion
from olivia.core.resources.card import CardMode
from olivia.core.resources.resolver import resolve
from olivia.core.resources.store import load_store
from olivia.core.taxonomy import Taxonomy

TODAY = date(2026, 10, 26)
PLAN = SafetyPlan(people=(Contact("表姐", "138-0000-0000"), Contact("小周")))


def test_the_new_lines_pass_willow_unchanged_and_the_gate(tax: Taxonomy) -> None:
    data = load_language_data(tax)
    engine = LanguageEngine(tax, rng=random.Random(0), data=data)
    lines = (*data.render.crisis_reach_out, *data.render.crisis_farewell, crisis_reminder(PLAN))
    assert data.render.crisis_reach_out and data.render.crisis_farewell
    for line in lines:
        for kind in (ContentKind.NORMAL, ContentKind.CRISIS):
            assert apply_willow(line, kind, data.willow) == line, line
        assert engine.gate.check(line, kind=ContentKind.CRISIS, stage=HelpStage.S_CRISIS).ok
        assert "？" not in line and "?" not in line
        assert not any(ch.isdigit() for ch in line), line


@pytest.mark.parametrize("level", [CrisisLevel.L2, CrisisLevel.L3])
def test_the_farewell_keeps_every_number_of_every_region(tax: Taxonomy, level: CrisisLevel) -> None:
    store = load_store()
    engine = LanguageEngine(tax, rng=random.Random(0), data=load_language_data(tax))
    people = farewell_people(PLAN)
    for code in store.regions:
        region = UserRegion(code, "UTC") if code != "ZZ" else None
        card = resolve(store, region, level, mode=CardMode.CRISIS, today=TODAY, is_minor=False)
        text = engine.render_crisis_farewell(card, people=people)
        assert engine.last_gate is not None and engine.last_gate.ok, code
        numbers = [e.number for e in card.emergency] + [ln.number for ln in card.lines]
        for number in numbers:
            assert number in text, (code, number)
        if card.emergency and card.emergency_leads:
            first = min(text.index(e.number) for e in card.emergency)
            assert first <= min(text.index(n) for n in numbers)
        elif card.emergency:
            # The mainland L2 card's 120 follows 12356 (owner decision 2026-10-28).
            assert min(text.index(e.number) for e in card.emergency) > max(
                text.index(ln.number) for ln in card.lines
            )
        assert text.index(numbers[-1]) < text.index("表姐：138-0000-0000")
