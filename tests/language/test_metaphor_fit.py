"""Images and warnings that fit the topic (trial report 2026-10-26, items 11 and 13).

* The withdrawal warning on the SIT-10-04 referral card read as "don't quit" to someone
  stopping drinking ("请不要…自己骤然停用…猛地戒掉"). It now says that stopping is worth it,
  that stopping suddenly can be dangerous, and that the doctor helps with how.
* "渴了的鹿，找到了清凉的泉" after "没忍住喝了两杯": no image about drinking for substance
  use; no drink at all once the topic is substance use (spectrum 10, the SIT-10-04 card).
* "两只挨在一起的杯子" / "一起撑过雨的那把伞" / "潮水会退，也总会回来" after a breakup:
  no pair and no "it comes back" image for grief or a breakup (spectra 06, 07 and their
  dossiers), for the rest of the session once the topic came up.
* "一封慢慢写、还没寄出的信" for a returning user after a crisis, at L1: no image of a letter,
  a farewell, a long journey or a sleep without waking, in any context (the language engine
  is not told the risk level or the crisis history, so it never uses one).

The word lists here are the floor the data must keep; ``metaphors.yaml`` ``avoid`` may
list more.
"""

from __future__ import annotations

import itertools
import random
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from olivia.core.language import LanguageEngine
from olivia.core.language.data import LanguageData, LanguageDataError, load_language_data
from olivia.core.models import PersonaProfile, PersonaSpectrum, UserRegion
from olivia.core.session import Session
from olivia.core.taxonomy import Taxonomy, load_taxonomy

DATA = Path(__file__).resolve().parents[2] / "olivia" / "data"
SUBSTANCE = "lexicons/substance.yaml"  # read by the language loader too (round 3)
TAX = load_taxonomy()
NOW = datetime(2026, 10, 22, 15, 30, tzinfo=UTC)
IMAGE_PERSONAS = (
    PersonaSpectrum.GENTLE_HOLDING,
    PersonaSpectrum.ZEN_PHILOSOPHER,
    PersonaSpectrum.RATIONAL_PEER,
)

# Never, in any image: death, drowning, falling (the old comment rule) and what can read as
# a suicide note or death (letters, farewells, a long journey, sleeping and not waking).
NEVER = (
    "死", "亡", "溺", "淹", "坠", "跌落", "坟", "墓", "葬", "崖", "渊", "跳", "绳",
    "信", "寄", "告别", "道别", "永别", "晚安", "远行", "启程", "走了", "离开",
    "睡去", "睡着", "长眠", "不醒", "安息", "最后", "谢幕",
    # Drinking as relief.
    "渴", "解渴", "一饮而尽", "痛饮", "酒", "醉", "干杯",
)  # fmt: skip
DRINK = ("喝", "饮", "杯", "壶", "茶", "牛奶", "温水", "清水", "泉")
PAIR_OR_RETURN = (
    "两只", "两棵", "两条", "两个", "一对", "一双", "成双", "成对", "挨在一起", "一起",
    "并肩", "相握", "相伴", "回来", "归来", "如约", "归途", "重逢", "等你",
)  # fmt: skip
SUBSTANCE_SPECTRA = ("10",)
LOSS_SPECTRA = ("06", "07")
LOSS_SITUATIONS = (
    "SIT-06-03", "SIT-06-04", "SIT-07-01", "SIT-07-02", "SIT-07-03", "SIT-07-04",
    "SIT-07-05", "SIT-07-06",
)  # fmt: skip


def _engine(tax: Taxonomy, lang: LanguageData, persona: PersonaSpectrum) -> LanguageEngine:
    return LanguageEngine(tax, rng=random.Random(0), data=lang.for_persona(persona))


def _pool(
    engine: LanguageEngine, spectrum: str | None, yearning: str | None, sits: Any
) -> set[str]:
    return {
        image for tier in engine.image_tiers(spectrum, yearning, frozenset(sits)) for image in tier
    }


def _every_image(lang: LanguageData) -> set[str]:
    m = lang.metaphors
    images = set(m.fallback)
    images |= {i for cell in m.by_spectrum_yearning.values() for c in cell.values() for i in c}
    images |= {i for images in m.by_situation.values() for i in images}
    for own in m.by_persona.values():
        images |= {*own.fallback, *(i for imgs in own.by_spectrum.values() for i in imgs)}
    return images


# -- 1. the withdrawal warning ---------------------------------------------------------------


@pytest.mark.parametrize("country", ["CN", "HK", "US"])
def test_withdrawal_warning_supports_stopping(engine: LanguageEngine, country: str) -> None:
    text = engine.render_referral(["SIT-10-04"], country)
    assert engine.last_gate is not None and engine.last_gate.ok
    for old in ("骤然", "猛地戒掉", "请不要在没有医生指导", "请不要自己突然停用"):
        assert old not in text, old
    assert "不是要你继续用" in text
    assert "突然停下来" in text and "危险" in text
    assert "医生指导下" in text


# -- 2. images that fit the topic -------------------------------------------------------------


def test_no_image_anywhere_reads_as_death_farewell_or_drinking(lang: LanguageData) -> None:
    hits = sorted(i for i in _every_image(lang) if any(w in i for w in NEVER))
    assert not hits


@pytest.mark.parametrize("persona", IMAGE_PERSONAS)
def test_substance_topic_draws_no_drink(
    tax: Taxonomy, lang: LanguageData, persona: PersonaSpectrum
) -> None:
    yearnings = [*tax.values("satir_yearnings"), None]
    for spectrum in SUBSTANCE_SPECTRA:
        for yearning in yearnings:
            pool = _pool(_engine(tax, lang, persona), spectrum, yearning, ())
            assert pool
            assert not [i for i in pool if any(w in i for w in DRINK)], (spectrum, yearning)


@pytest.mark.parametrize("persona", IMAGE_PERSONAS)
def test_after_the_substance_card_no_drink_on_any_spectrum(
    tax: Taxonomy, lang: LanguageData, persona: PersonaSpectrum
) -> None:
    engine = _engine(tax, lang, persona)
    engine.render_referral(["SIT-10-04"])
    for spectrum in [*tax.spectrum_ids(), None]:
        for sits in ((), ("SIT-11-03",), ("SIT-02-03",)):
            pool = _pool(engine, spectrum, "SAFETY", sits)
            assert pool
            assert not [i for i in pool if any(w in i for w in DRINK)], (spectrum, sits)


@pytest.mark.parametrize("persona", IMAGE_PERSONAS)
def test_grief_and_breakup_draw_no_pair_or_return(
    tax: Taxonomy, lang: LanguageData, persona: PersonaSpectrum
) -> None:
    yearnings = [*tax.values("satir_yearnings"), None]
    triggers = [(s, ()) for s in LOSS_SPECTRA] + [(None, (c,)) for c in LOSS_SITUATIONS]
    for (spectrum, sits), yearning in itertools.product(triggers, yearnings):
        pool = _pool(_engine(tax, lang, persona), spectrum, yearning, sits)
        assert pool
        bad = [i for i in pool if any(w in i for w in PAIR_OR_RETURN)]
        assert not bad, (spectrum, sits, yearning, bad)


@pytest.mark.parametrize("persona", IMAGE_PERSONAS)
def test_the_topic_stays_for_the_session(
    tax: Taxonomy, lang: LanguageData, persona: PersonaSpectrum
) -> None:
    # A breakup turn, then one read as another spectrum: still no pair image.
    engine = _engine(tax, lang, persona)
    engine.metaphor_phrase("07", "CONNECTION")
    for spectrum in tax.spectrum_ids():
        for sits in ((), ("SIT-01-06",)):
            pool = _pool(engine, spectrum, "CONNECTION", sits)
            assert pool
            assert not [i for i in pool if any(w in i for w in PAIR_OR_RETURN)], (spectrum, sits)


@pytest.mark.parametrize(
    ("said", "banned"),
    [("今天同事聚会，没忍住喝了两杯", DRINK), ("我们分手了，在一起五年", PAIR_OR_RETURN)],
)
def test_the_users_words_turn_the_topic_on(
    tax: Taxonomy, lang: LanguageData, said: str, banned: tuple[str, ...]
) -> None:
    # In rule mode the turn may get no spectrum at all; the words alone are enough.
    for persona in IMAGE_PERSONAS:
        engine = _engine(tax, lang, persona)
        engine.metaphor_phrase(None, None, user_text=said)
        for spectrum in [*tax.spectrum_ids(), None]:
            pool = _pool(engine, spectrum, "SAFETY", ())
            assert not [i for i in pool if any(w in i for w in banned)], (persona, spectrum)


def test_the_topics_leave_other_images_alone(tax: Taxonomy, lang: LanguageData) -> None:
    # Without the topic, a cup of tea for anxiety is still a warm image.
    engine = _engine(tax, lang, PersonaSpectrum.GENTLE_HOLDING)
    assert "一杯热茶捧在手心，慢慢变暖" in _pool(engine, "01", "SAFETY", ())


def test_rewritten_images_for_the_reported_cases(tax: Taxonomy, lang: LanguageData) -> None:
    gone = {
        "渴了的鹿，找到了清凉的泉",
        "两只挨在一起的杯子",
        "一起撑过雨的那把伞",
        "潮水会退，也总会回来",
        "一封慢慢写、还没寄出的信",
        # Being told off in front of everyone: not "sloppy but usable".
        "没叠整齐的被子，也能盖着睡",
    }
    assert not gone & _every_image(lang)


# -- the reported sentences, through a session -----------------------------------------------


def _session(persona: PersonaSpectrum, seed: int, history: tuple[str, ...] = ()) -> Session:
    profile = PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        user_name="小林",
        region=UserRegion("CN", "Asia/Shanghai"),
        persona_spectrum=persona,
        clinical_history=history,
    )
    return Session.open(TAX, profile, rng=random.Random(seed), now=lambda: NOW)


@pytest.mark.parametrize("persona", IMAGE_PERSONAS)
def test_reported_relapse_breakup_and_l1_turns(persona: PersonaSpectrum) -> None:
    scenes: list[tuple[tuple[str, ...], list[str], tuple[str, ...]]] = [
        (("SIT-10-04",), ["今天同事聚会，没忍住喝了两杯", "现在有点手抖，心里很烦"], DRINK),
        (
            (),
            [
                "我们分手了，在一起五年",
                "他还说我太黏人，什么都要报备",
                "我现在每天都忍不住看他朋友圈",
                "他昨天发了一张跟朋友喝酒的照片，笑得很开心",
                "我们一起养的猫归他了",
            ],
            PAIR_OR_RETURN,
        ),
        ((), ["我好像撑不了多久了", "活着好没意思"], NEVER),
    ]
    for history, lines, banned in scenes:
        for seed in range(6):
            session = _session(persona, seed, history)
            for line in lines:
                session.turn(line)
                image = session._engine._last_image  # noqa: SLF001 (the image last shown)
                assert not (image and any(w in image for w in banned)), (line, image)


# -- the data rule is enforced at load time --------------------------------------------------


def _copy(tmp_path: Path) -> Path:
    for path in DATA.rglob("*.yaml"):
        rel = path.relative_to(DATA)
        if rel.parts[0] in {"language", "templates", "cards"} or rel.as_posix() == SUBSTANCE:
            target = tmp_path / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
    return tmp_path


def _edit(root: Path, change: Callable[[dict[str, Any]], None]) -> None:
    path = root / "language" / "metaphors.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    change(doc)
    path.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")


def test_loader_rejects_an_image_with_a_never_word(tmp_path: Path, tax: Taxonomy) -> None:
    root = _copy(tmp_path)
    _edit(root, lambda d: d["by_persona"]["GENTLE_HOLDING"]["fallback"].append("一封没寄出的信"))
    with pytest.raises(LanguageDataError, match="never"):
        load_language_data(tax, root)


def test_loader_rejects_a_topic_that_empties_a_fallback(tmp_path: Path, tax: Taxonomy) -> None:
    root = _copy(tmp_path)

    def every_fallback_word(d: dict[str, Any]) -> None:
        d["avoid"]["topics"]["loss"]["words"].append("小")
        d["avoid"]["topics"]["loss"]["words"].extend(["风", "云", "灯", "溪", "树", "晨"])

    _edit(root, every_fallback_word)
    with pytest.raises(LanguageDataError, match="fallback"):
        load_language_data(tax, root)
