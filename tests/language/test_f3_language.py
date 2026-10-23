"""Quality fix F3: how replies name feelings, repeat themselves, picture things and frame
cards, and the one-line answers to medication and diagnosis questions."""

from __future__ import annotations

import random
from datetime import UTC, datetime
from pathlib import Path

import pytest

from olivia.core.language import ContentKind, LanguageEngine, Slots, apply_willow
from olivia.core.language.data import LanguageData
from olivia.core.language.dossiers import fitting_spectra
from olivia.core.language.engine import at_work, count_all, count_cjk, is_short_input, paragraphs
from olivia.core.language.mirror import MAX_MIRROR, Utterance
from olivia.core.models import (
    ActionSkeleton,
    ActionType,
    HelpStage,
    PersonaSpectrum,
    SafetyGrade,
)
from olivia.core.perception.lexicon import load_perception_lexicon
from olivia.core.perception.rule_stub import FALLBACK_EMOTION
from olivia.core.taxonomy import Taxonomy

FULL = [
    PersonaSpectrum.GENTLE_HOLDING,
    PersonaSpectrum.ZEN_PHILOSOPHER,
    PersonaSpectrum.RATIONAL_PEER,
]
ALL = [*FULL, PersonaSpectrum.SILENT_ANCHOR]
CALM_NAME = "平静安详"
NATURE_WORDS = ("柳", "溪", "草木", "树", "山", "云", "月", "湖", "雨", "田野", "种子", "潮", "浪")


def _engine(tax: Taxonomy, lang: LanguageData, persona: PersonaSpectrum, seed: int = 1):
    return LanguageEngine(tax, rng=random.Random(seed), data=lang.for_persona(persona))


def _slots(engine: LanguageEngine, text: str, emotion: str | None) -> Slots:
    return engine.build_slots(
        user_name="小林",
        agent_name="Olivia",
        user_text=text,
        emotion_id=emotion,
        yearning_id="SAFETY",
        spectrum_id="02",
    )


# -- 1. the {emotion} slot -------------------------------------------------------------------


def test_the_rule_stub_fallback_is_never_named(lang: LanguageData) -> None:
    assert FALLBACK_EMOTION in lang.feelings.never_named


@pytest.mark.parametrize("persona", ALL)
@pytest.mark.parametrize(
    "text",
    [
        "我们分手了，在一起五年",
        "上个月外婆也走了",
        "😭😭😭",
        "老板下午又临时加了个需求",
        "谢谢你一直在",
        "嗯",
    ],
)
def test_a_fallback_emotion_is_never_named(
    tax: Taxonomy, lang: LanguageData, persona: PersonaSpectrum, text: str
) -> None:
    for seed in range(8):
        engine = _engine(tax, lang, persona, seed)
        for emotion in (FALLBACK_EMOTION, None):
            slots = _slots(engine, text, emotion)
            assert slots.emotion == ""
            for stage in (HelpStage.S_EXPLORE, HelpStage.S_CLARIFY, HelpStage.S_HAVEN):
                reply = engine.compose(stage, slots)
                assert CALM_NAME not in reply
                assert "{" not in reply


@pytest.mark.parametrize(
    ("text", "emotion", "word"),
    [
        ("今天上班好累", "sadness", "疲惫"),
        ("我累了", "calm", "疲惫"),
        ("I just feel so tired of everything", "sadness", "疲惫"),
        ("最近心累", "overwhelm", "疲惫"),
        ("好烦", "anger", "烦躁"),
        ("我真的很委屈", "sadness", "委屈"),
        ("其实我也很想家", "loneliness", "想家的心情"),
        ("外婆去世了", "grief", "哀伤"),
        ("气死我了", "anger", "气愤"),
        ("心跳好快", "panic", "慌乱"),
        ("好累，撑不下去了", "hopelessness", "绝望无力"),  # the user's word never masks this
        ("我很焦虑", "anxiety", "焦虑心慌"),
    ],
)
def test_feeling_words(engine: LanguageEngine, text: str, emotion: str, word: str) -> None:
    assert engine.feeling_word(emotion, text) == word


@pytest.mark.parametrize(
    "text",
    [
        "今天不累",
        "其实不是很累",
        "积累了不少经验",
        "没那么烦了",
        "麻烦你了",
        "谢谢你",
        "他说他累了",
    ],
)
def test_negated_or_borrowed_feeling_words_name_nothing(engine: LanguageEngine, text: str) -> None:
    assert engine.feeling_word("calm", text) == ""


def test_tiredness_is_not_called_sadness(engine: LanguageEngine) -> None:
    slots = _slots(engine, "今天上班好累", "sadness")
    assert slots.emotion == "疲惫"
    reply = engine.compose(HelpStage.S_EXPLORE, slots)
    assert "悲伤" not in reply


@pytest.mark.parametrize("persona", FULL)
def test_every_reflect_part_has_unnamed_variants(
    lang: LanguageData, persona: PersonaSpectrum
) -> None:
    tpl = lang.personas[persona]
    for stage in (HelpStage.S_EXPLORE, HelpStage.S_CLARIFY):
        reflect = tpl.parts[stage][0]
        assert len(reflect.unnamed) >= 3
        for text in reflect.unnamed:
            assert "{emotion}" not in text and "{mirror}" in text
            assert CALM_NAME not in text
            filled = text.replace("{mirror}", "你" * MAX_MIRROR).replace("{user_name}", "小林")
            assert count_all(filled) <= tpl.paragraph_max
            assert apply_willow(text, ContentKind.NORMAL, lang.willow) == text


def test_feelings_data_is_clean(tax: Taxonomy, lang: LanguageData) -> None:
    feelings = lang.feelings
    words = [w.word for w in feelings.words] + list(feelings.display.values())
    for word in words:
        assert 2 <= len(word) <= 6, word
        assert apply_willow(word, ContentKind.NORMAL, lang.willow) == word
        assert not [t for t in lang.willow.diagnosis_terms if t in word.casefold()]
        assert CALM_NAME not in word
    assert set(feelings.display) <= set(tax.emotion_profiles())


# -- 2. acknowledgements instead of mirrors ---------------------------------------------------


def test_every_non_statement_kind_has_acknowledgements(lang: LanguageData) -> None:
    kinds = {u.value for u in Utterance} - {Utterance.STATEMENT.value}
    assert set(lang.utterances.acks) == kinds
    for lines in lang.utterances.acks.values():
        for line in lines:
            assert line.startswith("你") and "我" not in line and len(line) <= MAX_MIRROR
            assert "感到" not in line
            assert apply_willow(line, ContentKind.NORMAL, lang.willow) == line


# -- 3. repetition and length -----------------------------------------------------------------


@pytest.mark.parametrize("persona", ALL)
def test_no_paragraph_repeats_across_30_seeded_turns(
    tax: Taxonomy, lang: LanguageData, persona: PersonaSpectrum
) -> None:
    texts = ["嗯", "嗯", "好", "😭", "今天上班好累", "嗯", "谢谢你", "我不知道"]
    stages = [HelpStage.S_EXPLORE, HelpStage.S_CLARIFY, HelpStage.S_HAVEN, HelpStage.S_CLOSING]
    for seed in range(3):
        engine = _engine(tax, lang, persona, seed)
        previous: set[str] = set()
        for turn in range(30):
            text = texts[turn % len(texts)]
            stage = stages[(turn // 10) % len(stages)] if turn % 10 else stages[0]
            reply = engine.compose(stage, _slots(engine, text, "calm"), short=is_short_input(text))
            current = set(paragraphs(reply))
            assert not current & previous, (persona, seed, turn, current & previous)
            previous = current


def test_a_crisis_opening_never_repeats_twice_in_a_row(tax: Taxonomy, lang: LanguageData) -> None:
    engine = _engine(tax, lang, PersonaSpectrum.GENTLE_HOLDING)
    variants = lang.templates.crisis
    picks = [engine.pick_line(variants) for _ in range(30)]
    assert all(a != b for a, b in zip(picks, picks[1:], strict=False))


@pytest.mark.parametrize("persona", FULL)
@pytest.mark.parametrize("text", ["嗯", "好吧", "😭😭😭", "……", "不知道", "好累"])
def test_a_very_short_message_gets_a_short_reply(
    tax: Taxonomy, lang: LanguageData, persona: PersonaSpectrum, text: str
) -> None:
    assert is_short_input(text)
    low, high = lang.personas[persona].short_window or (0, 0)
    assert high < lang.personas[persona].normal_window[1]
    for seed in range(5):
        engine = _engine(tax, lang, persona, seed)
        for stage in (HelpStage.S_EXPLORE, HelpStage.S_CLARIFY):
            reply = engine.compose(stage, _slots(engine, text, "calm"), short=True)
            assert len(paragraphs(reply)) == 2
            assert low <= count_cjk(reply) and count_all(reply) <= high, reply
            assert "{" not in reply


def test_silent_anchor_has_no_short_window(tax: Taxonomy, lang: LanguageData) -> None:
    engine = _engine(tax, lang, PersonaSpectrum.SILENT_ANCHOR)
    assert lang.personas[PersonaSpectrum.SILENT_ANCHOR].short_window is None
    reply = engine.compose(HelpStage.S_EXPLORE, _slots(engine, "嗯", "calm"), short=True)
    assert len(paragraphs(reply)) == 1


@pytest.mark.parametrize(
    "text", ["我今天在公司被领导骂了", "好累，今天不想动脑", "嗯，好一点了", "我不够好", "睡不着"]
)
def test_longer_messages_are_not_short(text: str) -> None:
    assert not is_short_input(text)


# -- 4. persona imagery -----------------------------------------------------------------------


def _nature(lang: LanguageData) -> set[str]:
    m = lang.metaphors
    images = set(m.fallback) | {i for imgs in m.by_situation.values() for i in imgs}
    images |= {
        i for cell in m.by_spectrum_yearning.values() for imgs in cell.values() for i in imgs
    }
    return images


@pytest.mark.parametrize("persona", [PersonaSpectrum.GENTLE_HOLDING, PersonaSpectrum.RATIONAL_PEER])
def test_gentle_and_peer_never_get_nature_images(
    tax: Taxonomy, lang: LanguageData, persona: PersonaSpectrum
) -> None:
    nature = _nature(lang)
    own = lang.metaphors.by_persona[persona]
    allowed = set(own.fallback) | {i for imgs in own.by_spectrum.values() for i in imgs}
    for seed in range(10):
        engine = _engine(tax, lang, persona, seed)
        for spectrum in (*tax.spectrum_ids(), None):
            image = engine.metaphor_phrase(spectrum, "SAFETY", frozenset({"SIT-05-02"}))
            assert image in allowed and image not in nature
    for image in allowed:
        assert len(image) <= 16, image
        assert apply_willow(image, ContentKind.NORMAL, lang.willow) == image


def test_peer_images_are_plain_everyday_analogies(lang: LanguageData) -> None:
    own = lang.metaphors.by_persona[PersonaSpectrum.RATIONAL_PEER]
    for image in [*own.fallback, *(i for imgs in own.by_spectrum.values() for i in imgs)]:
        assert not any(word in image for word in NATURE_WORDS), image


def test_gentle_image_frames_do_not_talk_about_nature(lang: LanguageData) -> None:
    image = lang.personas[PersonaSpectrum.GENTLE_HOLDING].parts[HelpStage.S_EXPLORE][1]
    for text in image.variants:
        assert "自然" not in text and "风雨" not in text and "天色" not in text, text


def test_zen_keeps_the_nature_images(tax: Taxonomy, lang: LanguageData) -> None:
    assert PersonaSpectrum.ZEN_PHILOSOPHER not in lang.metaphors.by_persona
    nature = _nature(lang)
    for seed in range(10):
        engine = _engine(tax, lang, PersonaSpectrum.ZEN_PHILOSOPHER, seed)
        assert engine.metaphor_phrase("02", "SAFETY") in nature


# -- 5. cards: context line, exercise names, lens fit --------------------------------------------


@pytest.mark.parametrize(
    ("when", "expected"),
    [
        (datetime(2026, 10, 22, 2, 0, tzinfo=UTC), True),  # Thu 10:00 in Shanghai
        (datetime(2026, 10, 22, 9, 59, tzinfo=UTC), True),  # Thu 17:59
        (datetime(2026, 10, 22, 10, 0, tzinfo=UTC), False),  # Thu 18:00
        (datetime(2026, 10, 22, 13, 0, tzinfo=UTC), False),  # Thu 21:00
        (datetime(2026, 10, 21, 22, 0, tzinfo=UTC), False),  # Thu 06:00
        (datetime(2026, 10, 24, 2, 0, tzinfo=UTC), False),  # Sat 10:00
    ],
)
def test_working_hours_follow_the_local_clock(when: datetime, expected: bool) -> None:
    assert at_work(when, "Asia/Shanghai") is expected


def test_an_unknown_timezone_reads_the_clock_as_given() -> None:
    assert at_work(datetime(2026, 10, 22, 10, 0, tzinfo=UTC), "Mars/Base") is True


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


@pytest.mark.parametrize("card_id", ["62", "13", "14", "30:grounding"])
def test_the_card_context_line_follows_the_hour(
    tax: Taxonomy, lang: LanguageData, engine: LanguageEngine, card_id: str
) -> None:
    r = lang.render
    office = engine.render_card(_skeleton(tax, card_id), at_work=True)
    home = engine.render_card(_skeleton(tax, card_id), at_work=False)
    assert r.card_stealth_label in office and r.card_home_line not in office
    assert r.card_home_line in home and r.card_stealth_label not in home


def test_cards_are_shown_as_exercises(
    tax: Taxonomy, lang: LanguageData, engine: LanguageEngine
) -> None:
    for cid, card in lang.cards.cards.items():
        assert card.title != card.taxonomy_title, cid
        assert not card.title.endswith(("疗法", "治疗", "方案", "模型")), cid
        text = engine.render_card(_skeleton(tax, cid), at_work=False)
        assert text.startswith(f"「{card.title}」"), cid
    assert lang.cards.cards["14"].title == "正念小练习（源自正念认知疗法）"


@pytest.mark.parametrize(
    ("situations", "spectrum", "expected"),
    [
        (frozenset({"SIT-06-03"}), "07", {"06"}),
        (frozenset({"SIT-06-03", "SIT-05-02"}), None, {"05", "06"}),
        (frozenset(), "07", {"07"}),
        (frozenset(), None, set()),
    ],
)
def test_a_lens_must_fit_the_turn(
    situations: frozenset[str], spectrum: str | None, expected: set[str]
) -> None:
    assert fitting_spectra(situations, spectrum) == expected


# -- 6. Grade A practices by name -------------------------------------------------------------


def test_every_named_practice_has_an_explainer_and_a_card(
    tax: Taxonomy, lang: LanguageData
) -> None:
    lexicon = load_perception_lexicon(tax)
    methods = tax.methods()
    practices = {
        mid
        for mid in lexicon.therapy_names
        if mid not in methods or methods[mid].grade is SafetyGrade.GRADE_A
    }
    assert practices == set(lang.exercise_info)
    assert practices <= set(lang.cards.cards)


@pytest.mark.parametrize("method_id", ["01", "15", "28", "30:grounding", "11", "12"])
def test_a_practice_explainer_passes_the_gate(engine: LanguageEngine, method_id: str) -> None:
    text = engine.render_info_reply(method_id, lens=False)
    assert engine.last_gate is not None and engine.last_gate.ok, engine.last_gate
    assert engine.data.render.info_a_closing in text


# -- 7. medication and diagnosis questions ----------------------------------------------------


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("我在吃舍曲林，最近效果不好，我能自己把剂量加倍吗", "medication"),
        ("褪黑素一次吃多少比较好", "medication"),
        ("安眠药能不能停", "medication"),
        ("医生开的药我想自己减量", "medication"),
        ("你觉得我是不是抑郁症", "diagnosis"),
        ("我是不是有焦虑症啊，你帮我判断一下", "diagnosis"),
        ("我这样算不算双相", "diagnosis"),
    ],
)
def test_medication_and_diagnosis_questions_get_one_plain_line(
    lang: LanguageData, engine: LanguageEngine, text: str, kind: str
) -> None:
    line = engine.boundary_line(text)
    assert line == lang.utterances.boundaries[kind].line
    assert "\n" not in line
    assert not any(ch.isdigit() for ch in line)
    assert engine.gate.reasons(line, kind=ContentKind.NORMAL, stage=HelpStage.S_EXPLORE) == ()


@pytest.mark.parametrize(
    "text",
    [
        "今天上班好累",
        "我今天加倍努力了",
        "我是不是太焦虑了",
        "他是不是不爱我了",
        "我妈每天吃药",
        "我有双相，确诊两年了",
    ],
)
def test_other_messages_get_no_boundary_line(engine: LanguageEngine, text: str) -> None:
    assert engine.boundary_line(text) == ""


def test_boundary_lines_point_to_professionals(lang: LanguageData) -> None:
    bounds = lang.utterances.boundaries
    assert "医生" in bounds["medication"].line and "药剂师" in bounds["medication"].line
    assert "没法下诊断" in bounds["diagnosis"].line
    assert "精神科" in bounds["diagnosis"].line or "心理科" in bounds["diagnosis"].line
    for b in bounds.values():
        assert apply_willow(b.line, ContentKind.NORMAL, lang.willow) == b.line
        assert "必须" not in b.line and "你应该" not in b.line


@pytest.mark.parametrize("name", ["language/feelings.yaml", "language/utterances.yaml"])
def test_new_copy_is_marked_as_a_g0_draft(name: str) -> None:
    path = Path(__file__).resolve().parents[2] / "olivia" / "data" / name
    assert path.read_text(encoding="utf-8").startswith("# 草稿：待 G-0 两名注册心理师审核")
