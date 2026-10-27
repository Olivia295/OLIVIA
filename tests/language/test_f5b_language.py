"""Quality fix F5b in the language layer: one frame around the mirror, crisis openings
after a confirmation, the short referral card, the confirmation hint and images that are
not reused within a session."""

from __future__ import annotations

import random
import shutil
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml

from olivia.core.language import LanguageEngine
from olivia.core.language.data import LanguageDataError, load_language_data
from olivia.core.language.engine import Slots
from olivia.core.models import CrisisLevel, PersonaSpectrum, UserRegion
from olivia.core.resources.card import CardMode, ResourceCard
from olivia.core.resources.resolver import resolve
from olivia.core.resources.store import ResourceStore, load_store
from olivia.core.taxonomy import Taxonomy

DATA = Path(__file__).resolve().parents[2] / "olivia" / "data"
SUBSTANCE = "lexicons/substance.yaml"  # read by the language loader too (round 3)
SAFETY_QUESTIONS = ("安全吗", "是安全的吗")


def _copy(tmp_path: Path) -> Path:
    for path in DATA.rglob("*.yaml"):
        rel = path.relative_to(DATA)
        if rel.parts[0] in {"language", "templates", "cards"} or rel.as_posix() == SUBSTANCE:
            target = tmp_path / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
    return tmp_path


def _edit(root: Path, rel: str, change: Callable[[dict[str, Any]], None]) -> None:
    path = root / rel
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def _double_frame(data: dict[str, Any]) -> None:
    reflect = data["stages"]["S_explore"]["parts"][0]
    reflect["variants"][0] = "从你的话里，我感觉到{mirror}。那份{emotion}一直都在。"


def _confirmed_asks_again(data: dict[str, Any]) -> None:
    data["stages"]["S_crisis"]["after_confirmed"][0] = (
        "我在这里。你现在安全吗？下面的电话都可以拨打。"
    )


def _confirmed_without_numbers(data: dict[str, Any]) -> None:
    data["stages"]["S_crisis"]["after_confirmed"][0] = "我在这里，一直陪着你。"


def _no_after_confirmed(data: dict[str, Any]) -> None:
    del data["stages"]["S_crisis"]["after_confirmed"]


@pytest.mark.parametrize(
    "change",
    [_double_frame, _confirmed_asks_again, _confirmed_without_numbers, _no_after_confirmed],
)
def test_bad_f5b_templates_fail_fast(
    tmp_path: Path, tax: Taxonomy, change: Callable[[dict[str, Any]], None]
) -> None:
    root = _copy(tmp_path)
    _edit(root, "templates/gentle_holding.yaml", change)
    with pytest.raises(LanguageDataError):
        load_language_data(tax, root)


def _engine(tax: Taxonomy, persona: PersonaSpectrum, seed: int = 0) -> LanguageEngine:
    data = load_language_data(tax).for_persona(persona)
    return LanguageEngine(tax, rng=random.Random(seed), data=data)


TODAY = date(2026, 10, 24)
SLOTS = Slots(user_name="小林", agent_name="Olivia")


@pytest.fixture(scope="module")
def store() -> ResourceStore:
    return load_store()


def _card(store: ResourceStore, region: UserRegion | None, level: CrisisLevel) -> ResourceCard:
    return resolve(store, region, level, mode=CardMode.CRISIS, today=TODAY, is_minor=False)


@pytest.mark.parametrize("persona", list(PersonaSpectrum))
def test_after_a_confirmation_the_crisis_reply_asks_nothing_and_keeps_every_number(
    tax: Taxonomy, store: ResourceStore, persona: PersonaSpectrum
) -> None:
    engine = _engine(tax, persona)
    for code in store.regions:
        region = UserRegion(code, "UTC") if code != "ZZ" else None
        for level in (CrisisLevel.L2, CrisisLevel.L3):
            card = _card(store, region, level)
            numbers = [e.number for e in card.emergency] + [ln.number for ln in card.lines]
            asked = engine.render_crisis(card, SLOTS)
            assert any(q in asked for q in SAFETY_QUESTIONS)
            quiet = engine.render_crisis(card, SLOTS, confirmed=True)
            assert engine.last_gate is not None and engine.last_gate.ok
            assert not any(q in quiet for q in SAFETY_QUESTIONS), quiet
            assert "？" not in quiet
            for number in numbers:
                assert number in quiet, (code, level, number)


def test_the_confirmation_hint_comes_after_the_opening(tax: Taxonomy, store: ResourceStore) -> None:
    engine = _engine(tax, PersonaSpectrum.GENTLE_HOLDING)
    card = _card(store, UserRegion("CN", "Asia/Shanghai"), CrisisLevel.L2)
    hint = engine.data.render.crisis_confirm_hint
    text = engine.render_crisis(card, SLOTS, hint=True)
    opening, second, *_ = text.split("\n\n")
    assert second == hint
    assert any(q in opening for q in SAFETY_QUESTIONS)
    assert "12356" in text
    assert hint not in engine.render_crisis(card, SLOTS)


@pytest.mark.parametrize(
    ("text", "reassures"),
    [
        ("我没事", True),
        ("我已经好多了", True),
        ("放心吧", True),
        ("我不想活了", False),
        ("嗯", False),
    ],
)
def test_reassurance_words(tax: Taxonomy, text: str, reassures: bool) -> None:
    assert _engine(tax, PersonaSpectrum.GENTLE_HOLDING).reassures(text) is reassures


@pytest.mark.parametrize("country", ["CN", "HK", "US"])
def test_the_referral_shown_again_is_short_but_names_every_place(
    tax: Taxonomy, country: str
) -> None:
    engine = _engine(tax, PersonaSpectrum.GENTLE_HOLDING)
    render = engine.data.render
    codes = ["SIT-02-04", "SIT-09-01"]
    full = engine.render_referral(codes, country)
    places = [line for line in full.splitlines() if line.startswith("· ")]
    assert len(places) == 2
    shown = []
    for again in (1, 2, 3, 4):
        short = engine.render_referral(codes, country, again=again)
        lines = short.splitlines()
        assert lines[0] in render.referral_again
        assert lines[1:] == places
        assert render.referral_closing not in short
        shown.append(lines[0])
    # The short intros take turns: never the same one twice in a row.
    assert all(a != b for a, b in zip(shown, shown[1:], strict=False))
    assert render.referral_intro in full and render.referral_closing in full


@pytest.mark.parametrize("persona", list(PersonaSpectrum))
@pytest.mark.parametrize("seed", range(5))
def test_an_image_is_not_used_twice_while_others_are_left(
    tax: Taxonomy, persona: PersonaSpectrum, seed: int
) -> None:
    engine = _engine(tax, persona, seed)
    situations = frozenset({"SIT-06-03"})
    seen: list[str] = []
    for _ in range(4):
        image = engine.metaphor_phrase("06", "SAFETY", situations)
        assert image not in seen
        engine.note_image(f"……{image}……", image)
        seen.append(image)


def test_with_every_image_used_it_is_never_the_one_just_before(tax: Taxonomy) -> None:
    engine = _engine(tax, PersonaSpectrum.ZEN_PHILOSOPHER, 3)
    last = None
    for _ in range(60):
        image = engine.metaphor_phrase(None, None)
        assert image != last
        engine.note_image(image, image)
        last = image
