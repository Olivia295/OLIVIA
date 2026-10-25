"""LanguageEngine: template composition, cards, info, referral and crisis rendering."""

from __future__ import annotations

import random
from dataclasses import replace
from datetime import date, timedelta

import pytest

from olivia.core.language import LanguageEngine, Slots
from olivia.core.language.data import LanguageData
from olivia.core.language.engine import count_all, count_cjk, paragraphs
from olivia.core.language.gate import phone_like_runs
from olivia.core.methods.solver import (
    M0_ACTION_ID,
    ActionPlan,
    SolverInput,
    allowed_actions,
    build_plan,
)
from olivia.core.models import (
    ActionSkeleton,
    ActionType,
    CrisisLevel,
    HelpStage,
    PersonaSpectrum,
    SafetyGrade,
    UserRegion,
)
from olivia.core.resources.card import CardMode, ResourceCard
from olivia.core.resources.resolver import resolve
from olivia.core.resources.store import ResourceStore, load_store
from olivia.core.taxonomy import Taxonomy

SEEDS = range(40)
TODAY = date(2026, 10, 22)
COMPOSED = [HelpStage.S_EXPLORE, HelpStage.S_CLARIFY, HelpStage.S_EMPOWER]
COLD_WATER = "12:tipp_cold_water"


def _engine(tax: Taxonomy, lang: LanguageData, seed: int) -> LanguageEngine:
    return LanguageEngine(tax, rng=random.Random(seed), data=lang)


def _slots(engine: LanguageEngine, seed: int) -> Slots:
    rng = random.Random(seed)
    tax_emotions = ["anxiety", "sadness", "loneliness", "shame", "overwhelm", "numbness"]
    return engine.build_slots(
        user_name=rng.choice(["小雨", "阿哲", "Lin"]),
        agent_name="阿柳",
        user_text=rng.choice(
            [
                "我觉得你根本不在乎我",
                "我在家里做了很多，却没有人看见",
                "领导当着大家的面批评我",
                "我最近总是睡不着，一闭眼就想到工作上的事情",
            ]
        ),
        emotion_id=rng.choice(tax_emotions),
        yearning_id=rng.choice(["SAFETY", "ACCEPTANCE", "AUTONOMY", "COMPETENCE", "CONNECTION"]),
        spectrum_id=f"{rng.randint(1, 11):02d}",
        card_title="五感着陆练习",
    )


def _skeleton(tax: Taxonomy, action_id: str) -> ActionSkeleton:
    if action_id in tax.methods():
        m = tax.methods()[action_id]
        return ActionSkeleton(
            action_id,
            ActionType.MICRO_EXERCISE,
            m.grade,
            m.clinical_rationale or "",
            m.core_action_steps,
            m.duration_minutes or 0,
            bool(m.stealth_workplace_compatible),
            m.contraindications,
        )
    a = tax.action_registry()[action_id]
    return ActionSkeleton(
        action_id,
        a.action_type,
        None,
        a.clinical_rationale,
        a.core_action_steps,
        a.duration_minutes,
        a.stealth_workplace_compatible,
        a.contraindications,
    )


# -- compose ------------------------------------------------------------------------------


@pytest.mark.parametrize("stage", COMPOSED + [HelpStage.S_CLOSING])
@pytest.mark.parametrize("seed", SEEDS)
def test_compose_holds_the_normal_window(
    tax: Taxonomy, lang: LanguageData, stage: HelpStage, seed: int
) -> None:
    engine = _engine(tax, lang, seed)
    slots = _slots(engine, seed)
    card = engine.render_card(_skeleton(tax, "30:grounding"))
    text = engine.compose(stage, slots, card=card)
    assert engine.last_gate is not None and engine.last_gate.ok, engine.last_gate
    counted = text.replace(f"{card}\n\n", "") if stage is HelpStage.S_EMPOWER else text
    if stage is HelpStage.S_EMPOWER:
        assert card in text
        assert len(paragraphs(counted)) == 3
    low, high = lang.templates.normal_window
    assert low <= count_cjk(counted) and count_all(counted) <= high, counted
    for para in paragraphs(counted):
        assert count_all(para) <= lang.templates.paragraph_max, para
    assert "{" not in text


@pytest.mark.parametrize("seed", SEEDS)
def test_haven_and_ready_windows(tax: Taxonomy, lang: LanguageData, seed: int) -> None:
    engine = _engine(tax, lang, seed)
    slots = _slots(engine, seed)
    haven = engine.compose(HelpStage.S_HAVEN, slots)
    low, high = lang.templates.haven_window
    assert "\n" not in haven and "？" not in haven
    assert low <= count_cjk(haven) and count_all(haven) <= high
    for returning in (False, True):
        ready = engine.compose(HelpStage.S_READY, slots, returning_after_crisis=returning)
        assert "\n" not in ready and count_all(ready) <= lang.templates.paragraph_max
        assert ("安全" in ready) or not returning


def test_compose_is_reproducible_per_seed(tax: Taxonomy, lang: LanguageData) -> None:
    def run(seed: int) -> list[str]:
        engine = _engine(tax, lang, seed)
        slots = _slots(engine, 1)
        return [engine.compose(s, slots) for s in (HelpStage.S_EXPLORE, HelpStage.S_CLARIFY)]

    assert run(3) == run(3)
    assert len({tuple(run(seed)) for seed in range(6)}) > 1


def test_compose_falls_back_to_the_least_penalized_combo(tax: Taxonomy, lang: LanguageData) -> None:
    engine = _engine(tax, lang, 0)
    slots = replace(_slots(engine, 0), mirror="你" + "很" * 60)
    text = engine.compose(HelpStage.S_EXPLORE, slots)
    assert engine.window_penalty(HelpStage.S_EXPLORE, text) > 0
    assert engine.last_gate is not None and engine.last_gate.ok


def test_compose_refuses_crisis_and_cardless_empower(engine: LanguageEngine) -> None:
    slots = _slots(engine, 0)
    with pytest.raises(ValueError, match="render_crisis"):
        engine.compose(HelpStage.S_CRISIS, slots)
    with pytest.raises(ValueError, match="card"):
        engine.compose(HelpStage.S_EMPOWER, slots)


@pytest.mark.parametrize("seed", SEEDS)
def test_light_empower_swaps_the_bridge_and_holds_the_window(
    tax: Taxonomy, lang: LanguageData, seed: int
) -> None:
    engine = _engine(tax, lang, seed)
    slots = _slots(engine, seed)
    card = engine.render_card(_skeleton(tax, "30:grounding"))
    text = engine.compose(HelpStage.S_EMPOWER, slots, card=card, light=True)
    assert engine.last_gate is not None and engine.last_gate.ok, engine.last_gate
    first = paragraphs(text)[0]
    assert "先从轻一点的开始" in first
    assert (
        "先从轻一点的开始"
        not in paragraphs(engine.compose(HelpStage.S_EMPOWER, slots, card=card))[0]
    )
    counted = text.replace(f"{card}\n\n", "")
    low, high = lang.templates.normal_window
    assert low <= count_cjk(counted) and count_all(counted) <= high, counted
    for para in paragraphs(counted):
        assert count_all(para) <= lang.templates.paragraph_max, para


def test_light_is_only_for_empower(engine: LanguageEngine) -> None:
    with pytest.raises(ValueError, match="light"):
        engine.compose(HelpStage.S_EXPLORE, _slots(engine, 0), light=True)


def test_compose_refuses_missing_slots(engine: LanguageEngine) -> None:
    with pytest.raises(ValueError, match="slots"):
        engine.compose(HelpStage.S_EXPLORE, Slots(user_name="小雨", agent_name="阿柳"))


def test_gate_block_in_compose_returns_the_fallback(engine: LanguageEngine) -> None:
    slots = replace(_slots(engine, 0), metaphor="拨 13800138000 的山谷")
    text = engine.compose(HelpStage.S_EXPLORE, slots)
    assert engine.last_gate is not None and not engine.last_gate.ok
    assert text == engine.gate.fallback


# -- slots ----------------------------------------------------------------------------------


def test_emotion_slot_is_the_taxonomy_chinese_name(tax: Taxonomy, engine: LanguageEngine) -> None:
    assert tax.emotion_name("anxiety") == "焦虑心慌"
    assert engine.emotion_word("anxiety") == "焦虑心慌"
    for eid in tax.values("emotions"):
        assert 2 <= len(engine.emotion_word(eid)) <= 4


def test_unknown_emotion_is_rejected(tax: Taxonomy) -> None:
    from olivia.core.taxonomy import TaxonomyError

    with pytest.raises(TaxonomyError):
        tax.emotion_name("joy-ish")


def test_need_and_metaphor_come_from_the_data(tax: Taxonomy, lang: LanguageData) -> None:
    # Nature images are ZEN_PHILOSOPHER's (F3); the default persona has its own.
    zen = lang.for_persona(PersonaSpectrum.ZEN_PHILOSOPHER)
    engine = LanguageEngine(tax, rng=random.Random(20261022), data=zen)
    for yid in tax.values("satir_yearnings"):
        assert engine.need_phrase(yid) in lang.needs[yid]
        assert engine.metaphor_phrase("04", yid) in lang.metaphors.by_spectrum_yearning["04"][yid]
    assert engine.need_phrase("SAFETY_ORDER") in lang.needs["SAFETY"]
    assert engine.metaphor_phrase(None, None) in lang.metaphors.fallback
    assert engine.metaphor_phrase("99", "SAFETY") in lang.metaphors.fallback


# -- cards ----------------------------------------------------------------------------------


def test_every_card_renders_verbatim_and_passes(
    tax: Taxonomy, lang: LanguageData, engine: LanguageEngine
) -> None:
    for cid, card in lang.cards.cards.items():
        text = engine.render_card(_skeleton(tax, cid))
        assert engine.last_gate is not None and engine.last_gate.ok, (cid, engine.last_gate)
        assert card.title in text and card.intro in text and card.closing in text
        for step in card.steps:
            assert step in text, (cid, step)
        if card.safety_note:
            assert text.index(card.safety_note) < text.index(card.steps[0])


def test_card_from_the_solver_plan(tax: Taxonomy, engine: LanguageEngine) -> None:
    inp = SolverInput(
        HelpStage.S_EMPOWER, 0.3, frozenset(), frozenset(), frozenset(), frozenset(), 0.6
    )
    allowed = allowed_actions(tax, inp)
    plan: ActionPlan = build_plan(tax, allowed.candidates[0], allowed)
    assert "「" in engine.render_card(plan.primary)


def test_cold_water_card_refuses(tax: Taxonomy, engine: LanguageEngine) -> None:
    with pytest.raises(ValueError, match="no follow-along card"):
        engine.render_card(_skeleton(tax, COLD_WATER))


@pytest.mark.parametrize("action_id", [M0_ACTION_ID, "REFERRAL_CARD_PRESENTATION"])
def test_non_card_actions_refuse(tax: Taxonomy, engine: LanguageEngine, action_id: str) -> None:
    with pytest.raises(ValueError, match="not rendered as a follow-along card"):
        engine.render_card(_skeleton(tax, action_id))


# -- D-3 (F13, draft G-0): red-flag-only psychoeducation -----------------------------------


def test_withdrawal_warning_is_no_card_but_rides_on_the_referral(
    tax: Taxonomy, engine: LanguageEngine
) -> None:
    with pytest.raises(ValueError, match="no follow-along card"):
        engine.render_card(_skeleton(tax, "WITHDRAWAL_RISK_WARNING"))
    full = engine.render_referral(["SIT-10-04"])
    assert engine.last_gate is not None and engine.last_gate.ok
    assert "突然停下来" in full and "医生" in full
    for country in ("HK", "US"):
        assert "突然停下来" in engine.render_referral(["SIT-10-04"], country)
    for code in tax.red_flags():
        if code != "SIT-10-04":
            assert "突然停下来" not in engine.render_referral([code])
    # The same card shown again on the next turn keeps its short form.
    assert "突然停下来" not in engine.render_referral(["SIT-10-04"], again=1)


def test_psychoeducation_card_renders_as_tips(tax: Taxonomy, engine: LanguageEngine) -> None:
    skeleton = _skeleton(tax, "CIRCADIAN_RHYTHM_STABILIZATION")
    assert skeleton.action_type is ActionType.PSYCHOEDUCATION
    text = engine.render_card(skeleton)
    assert engine.last_gate is not None and engine.last_gate.ok
    assert text.startswith("「让作息稳一稳」\n")
    assert "1. " not in text and "分钟" not in text.splitlines()[0]
    assert text.count("\n· ") == len(skeleton.core_action_steps)
    exercise = engine.render_card(_skeleton(tax, "SAFE_PLACE_CONTAINER"))
    assert "1. " in exercise and "约 3 分钟" in exercise


def test_alias_resolves_to_its_card(tax: Taxonomy, engine: LanguageEngine) -> None:
    skeleton = replace(_skeleton(tax, "30:grounding"), method_id="GROUNDING_54321")
    assert "5-4-3-2-1" in engine.render_card(skeleton)


# -- info and referral ----------------------------------------------------------------------


def test_every_info_entry_renders_and_passes(lang: LanguageData, engine: LanguageEngine) -> None:
    for eid, entry in lang.info.items():
        text = engine.render_info(eid)
        assert engine.last_gate is not None and engine.last_gate.ok, (eid, engine.last_gate)
        assert entry.title in text and entry.who_offers_it in text
        if entry.grade is SafetyGrade.GRADE_C:
            assert "不建议独自尝试" in text


def test_info_refuses_grade_a(engine: LanguageEngine) -> None:
    with pytest.raises(ValueError):
        engine.render_info("01")


def test_referral_names_places_not_disorders(tax: Taxonomy, engine: LanguageEngine) -> None:
    for code, flag in tax.red_flags().items():
        text = engine.render_referral([code])
        assert engine.last_gate is not None and engine.last_gate.ok, (code, engine.last_gate)
        assert flag.name_zh not in text
        assert any(word in text for word in ("精神科", "心理门诊", "医学科"))
    every = engine.render_referral(tax.red_flags())
    assert engine.last_gate is not None and engine.last_gate.ok
    assert every.count("· ") == len(set(engine.data.render.referral_destinations.values()))


def test_referral_refuses_bad_input(engine: LanguageEngine) -> None:
    with pytest.raises(ValueError):
        engine.render_referral([])
    with pytest.raises(ValueError):
        engine.render_referral(["SIT-99-99"])


# -- crisis ---------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def store() -> ResourceStore:
    return load_store()


def _cards(store: ResourceStore, today: date = TODAY) -> list[ResourceCard]:
    out = []
    for code in store.regions:
        region = UserRegion(code, "UTC") if code != "ZZ" else None
        for level in (CrisisLevel.L2, CrisisLevel.L3):
            for minor in (False, True):
                out.append(
                    resolve(store, region, level, mode=CardMode.CRISIS, today=today, is_minor=minor)
                )
    return out


def _numbers(card: ResourceCard) -> list[str]:
    return [e.number for e in card.emergency] + [ln.number for ln in card.lines]


def test_crisis_card_lists_every_number_and_nothing_else(
    store: ResourceStore, engine: LanguageEngine
) -> None:
    slots = _slots(engine, 0)
    for card in _cards(store):
        text = engine.render_crisis(card, slots)
        assert engine.last_gate is not None and engine.last_gate.ok, (
            card.region_used,
            engine.last_gate,
        )
        for number in _numbers(card):
            assert number in text, (card.region_used, number)
        allowed = {"".join(ch for ch in n if ch.isdigit()) for n in _numbers(card)}
        assert set(phone_like_runs(text)) <= allowed, (card.region_used, text)
        if card.emergency:
            first_line = min(text.index(ln.number) for ln in card.lines) if card.lines else None
            if first_line is not None:
                assert text.index(card.emergency[0].number) < first_line
        assert "可能已过期" not in text


def test_cn_l3_crisis_card(store: ResourceStore, engine: LanguageEngine) -> None:
    card = resolve(
        store, UserRegion("CN", "Asia/Shanghai"), CrisisLevel.L3, mode=CardMode.CRISIS, today=TODAY
    )
    text = engine.render_crisis(card, _slots(engine, 0))
    assert text.index("110") < text.index("120") < text.index("12356")
    assert "12355" not in text
    assert "身边" in text


def test_stale_entries_are_marked(store: ResourceStore, engine: LanguageEngine) -> None:
    card = resolve(
        store,
        UserRegion("HK", "Asia/Hong_Kong"),
        CrisisLevel.L3,
        mode=CardMode.CRISIS,
        today=TODAY + timedelta(days=400),
    )
    assert card.stale_entries
    text = engine.render_crisis(card, _slots(engine, 0))
    assert text.count("可能已过期") == len(card.stale_entries)


def test_crisis_refuses_browsing_cards(store: ResourceStore, engine: LanguageEngine) -> None:
    card = resolve(store, None, CrisisLevel.L0, mode=CardMode.BROWSING, today=TODAY)
    with pytest.raises(ValueError):
        engine.render_crisis(card, _slots(engine, 0))


def test_crisis_gate_block_keeps_every_number(store: ResourceStore, engine: LanguageEngine) -> None:
    card = resolve(
        store, UserRegion("CN", "Asia/Shanghai"), CrisisLevel.L3, mode=CardMode.CRISIS, today=TODAY
    )
    tampered = replace(card, lines=(replace(card.lines[0], name_zh="热线 99999"),))
    text = engine.render_crisis(tampered, _slots(engine, 0))
    assert engine.last_gate is not None and not engine.last_gate.ok
    assert engine.last_gate.reasons == ("number:99999",)
    for number in _numbers(card):
        assert number in text
    assert "99999" not in text
