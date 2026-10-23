"""``LanguageEngine.render_safety_check``: the direct question about intent (decision D3).

The reply is one ``followups.safety_check`` variant plus the region's L2 crisis-card
resource lines. It must pass the output gate as NORMAL content in every stage it can be
asked in, with exactly the card's numbers allowed, for every region.
"""

from __future__ import annotations

import random
from dataclasses import replace
from datetime import date

import pytest

from olivia.core.language import LanguageEngine, Slots
from olivia.core.language.data import LanguageData
from olivia.core.language.gate import phone_like_runs
from olivia.core.models import CrisisLevel, HelpStage, UserRegion
from olivia.core.resources.card import CardMode, ResourceCard
from olivia.core.resources.resolver import resolve
from olivia.core.resources.store import ResourceStore, load_store
from olivia.core.taxonomy import Taxonomy

TODAY = date(2026, 10, 22)
STAGES = [
    HelpStage.S_EXPLORE,
    HelpStage.S_CLARIFY,
    HelpStage.S_EMPOWER,
    HelpStage.S_HAVEN,
    HelpStage.S_CLOSING,
]


@pytest.fixture(scope="module")
def store() -> ResourceStore:
    return load_store()


def _card(store: ResourceStore, code: str) -> ResourceCard:
    region = UserRegion(code, "UTC") if code != "ZZ" else None
    return resolve(store, region, CrisisLevel.L2, mode=CardMode.CRISIS, today=TODAY)


def _numbers(card: ResourceCard) -> list[str]:
    return [e.number for e in card.emergency] + [ln.number for ln in card.lines]


def test_every_region_and_variant_passes_the_gate(
    tax: Taxonomy, lang: LanguageData, store: ResourceStore
) -> None:
    slots = Slots(user_name="小雨", agent_name="阿柳")
    for code in store.regions:
        card = _card(store, code)
        for stage in STAGES:
            for seed in range(12):
                engine = LanguageEngine(tax, rng=random.Random(seed), data=lang)
                text = engine.render_safety_check(card, slots, stage)
                assert engine.last_gate is not None and engine.last_gate.ok, (code, stage)
                question = text.split("\n\n", 1)[0]
                assert question.replace("小雨", "{user_name}") in lang.templates.safety_check
                for number in _numbers(card):
                    assert number in text, (code, number)
                allowed = {"".join(ch for ch in n if ch.isdigit()) for n in _numbers(card)}
                assert set(phone_like_runs(text)) <= allowed, (code, text)


def test_non_cn_regions_never_show_mainland_numbers(
    engine: LanguageEngine, store: ResourceStore
) -> None:
    mainland = set(_numbers(_card(store, "CN")))
    slots = Slots(user_name="小雨", agent_name="阿柳")
    for code in store.regions:
        if code == "CN":
            continue
        text = engine.render_safety_check(_card(store, code), slots, HelpStage.S_EXPLORE)
        own = set(_numbers(_card(store, code)))
        assert not any(n in text for n in mainland - own), code


def test_slot_free_variant_without_a_name(engine: LanguageEngine, store: ResourceStore) -> None:
    for _ in range(20):
        text = engine.render_safety_check(_card(store, "CN"), Slots("", ""), HelpStage.S_EXPLORE)
        assert "{" not in text and "12356" in text


def test_refuses_a_browsing_card(engine: LanguageEngine, store: ResourceStore) -> None:
    card = resolve(store, None, CrisisLevel.L0, mode=CardMode.BROWSING, today=TODAY)
    with pytest.raises(ValueError, match="render_safety_check"):
        engine.render_safety_check(card, Slots("", ""), HelpStage.S_EXPLORE)


def test_gate_block_keeps_every_number(engine: LanguageEngine, store: ResourceStore) -> None:
    card = _card(store, "CN")
    tampered = replace(card, lines=(replace(card.lines[0], name_zh="热线 99999"),))
    text = engine.render_safety_check(tampered, Slots("", ""), HelpStage.S_EXPLORE)
    assert engine.last_gate is not None and not engine.last_gate.ok
    assert engine.last_gate.reasons == ("number:99999",)
    for number in _numbers(tampered):
        assert number in text
    assert "99999" not in text
