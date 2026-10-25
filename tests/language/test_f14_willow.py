"""F14 WILLOW polish: card and information paragraphs within 80 characters (WILLOW-03),
the willow image for perfectionism (WILLOW-02, in ``test_dossier_layer.py``) and the gate
refusing bare list openers (WILLOW-01) without losing the user's own words."""

from __future__ import annotations

import pytest

from olivia.core.language import ContentKind, LanguageEngine
from olivia.core.language.data import LanguageData
from olivia.core.language.engine import count_all, paragraphs
from olivia.core.language.mirror import FALLBACK_MIRROR, mirror
from olivia.core.models import HelpStage
from olivia.core.taxonomy import Taxonomy
from tests.language.test_engine import _skeleton

# -- WILLOW-03: every paragraph of a card or an information reply is at most 80 ---------------


def test_every_information_reply_paragraph_fits(lang: LanguageData, engine: LanguageEngine) -> None:
    limit = lang.templates.paragraph_max
    for method_id in [*lang.info, *lang.exercise_info]:
        for lens in (True, False):
            text = engine.render_info_reply(method_id, lens=lens)
            assert engine.last_gate is not None and engine.last_gate.ok, method_id
            for para in paragraphs(text):
                assert count_all(para) <= limit, (method_id, para)


def test_information_card_keeps_title_and_what_it_is_together(
    lang: LanguageData, engine: LanguageEngine
) -> None:
    entry = lang.info["27"]
    shown = paragraphs(engine.render_info("27"))
    assert shown[0] == f"「{entry.title}」\n{lang.render.info_what_label}{entry.what_it_is}"
    assert shown[1] == f"{lang.render.info_how_label}{entry.how_it_helps}"
    assert shown[2] == f"{lang.render.info_who_label}{entry.who_offers_it}"


def test_every_card_paragraph_fits_with_one_step_each(
    tax: Taxonomy, lang: LanguageData, engine: LanguageEngine
) -> None:
    limit = lang.templates.paragraph_max
    for card_id, card in lang.cards.cards.items():
        for at_work in (True, False):
            shown = paragraphs(engine.render_card(_skeleton(tax, card_id), at_work=at_work))
            for para in shown:
                assert count_all(para) <= limit, (card_id, para)
            steps = [f"{i}. {step}" for i, step in enumerate(card.steps, start=1)]
            assert [p for p in shown if p in steps] == steps, card_id


# -- WILLOW-01: bare list openers -------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "word"),
    [
        ("首先深呼吸一下，再慢慢说。", "首先"),
        ("可以先歇一歇。其次也可以喝点水。", "其次"),
        ("总而言之你已经很努力了。", "总而言之"),
        ("我们慢慢来：首先看看身体的感觉。", "首先"),
    ],
)
def test_the_gate_refuses_a_bare_list_opener(engine: LanguageEngine, text: str, word: str) -> None:
    reasons = engine.gate.reasons(text, kind=ContentKind.NORMAL, stage=HelpStage.S_EXPLORE)
    assert f"ordinal:{word}" in reasons
    assert not engine.gate.check(text, kind=ContentKind.NORMAL, stage=HelpStage.S_EXPLORE).ok


@pytest.mark.parametrize(
    "text",
    [
        "他首先发现了这个问题。",  # an adverb inside the clause, not a list opener
        "成绩其次，身体最重要。",
        "那段时间你总而言之也撑过来了。",
    ],
)
def test_an_ordinal_inside_a_clause_passes(engine: LanguageEngine, text: str) -> None:
    reasons = engine.gate.reasons(text, kind=ContentKind.NORMAL, stage=HelpStage.S_EXPLORE)
    assert not [r for r in reasons if r.startswith("ordinal:")], reasons


@pytest.mark.parametrize("kind", [ContentKind.CRISIS, ContentKind.REFERRAL])
def test_safety_wording_keeps_its_exemption(engine: LanguageEngine, kind: ContentKind) -> None:
    reasons = engine.gate.reasons("首先，请确认你是安全的。", kind=kind, stage=HelpStage.S_CRISIS)
    assert not [r for r in reasons if r.startswith("ordinal:")]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("首先，我最近真的好累", "你最近真的好累"),
        ("首先我想说我最近好累", "你想说你最近好累"),
        ("总而言之我很失望", "你很失望"),
        ("其次，我睡不好", "你睡不好"),
    ],
)
def test_the_mirror_keeps_the_users_words_without_the_opener(
    engine: LanguageEngine, text: str, expected: str
) -> None:
    assert mirror(text) == expected
    shown = engine.safe_mirror(text)
    assert shown == expected and shown != FALLBACK_MIRROR
