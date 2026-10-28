"""Round 4 (复测 q3, 2026-10-28; drafts pending G-0): the language layer.

* The mirror guard reads risk components (``guarded.components``): two kinds of them in
  one message (a means and a preparation, an ending and something lasting, a wish and an
  ending ...) keep it from being said back whatever level the turn has, and so does a
  composition's heads and tails without its context words.
* An L1 that only the risk model gives, to a message with none of them, is answered as
  usual; the rule screen's L1 and every L2+ still say nothing back.
* Acknowledgement lines rotate (the least used first), self-blame and the companion's 你
  are not said back, and "你感到" + a whole sentence names only the feeling.
* Drugs as well as drinking: withdrawal from sleeping pills, painkillers and sedatives,
  more signs (chills and fever, aching bones, shaking, a seizure, hearing voices,
  confusion), reasons found for a drink, and a craving for more.
"""

from __future__ import annotations

import random
import shutil
from pathlib import Path

import pytest
import yaml

from olivia.core.language.data import LanguageDataError, load_language_data
from olivia.core.language.engine import LanguageEngine
from olivia.core.language.guard import read_substance
from olivia.core.language.mirror import Utterance
from olivia.core.models import CrisisLevel, PersonaSpectrum
from olivia.core.safety.lexicon import load_safety_lexicons
from olivia.core.taxonomy import Taxonomy, load_taxonomy

TAX = load_taxonomy()
LEX = load_safety_lexicons(TAX)
DATA = load_language_data(TAX)
SAID = DATA.utterances
CUES = DATA.substance
ROOT = Path(__file__).resolve().parents[2] / "olivia" / "data"


def _engine(persona: PersonaSpectrum = PersonaSpectrum.GENTLE_HOLDING) -> LanguageEngine:
    return LanguageEngine(TAX, rng=random.Random(3), data=DATA.for_persona(persona), lexicons=LEX)


# -- risk components ------------------------------------------------------------------------

# Said back word for word in 复测 q3 (rules L0 or model L0).
RISKY = [
    "药我已经准备好了，等家里人睡着就吃",  # a means, a preparation, a time
    "想给这一生画个句号",  # an ending and a whole life
    "是时候说晚安了，很长很长的那种晚安",  # a soft ending made lasting
    "人间不值得，我想提前退场",
    "要是能就这么不存在就好了",  # a wish and an ending
    "有时候走在路上会想，被车撞了也无所谓",
    "我把攒下来的药都放在抽屉里，有时候盯着看很久",
    "手腕上的伤口还没好，我又想划了",
    "我已经在河边了，水很冷",
    "我想好好休息，永远的那种",
    "好想从这个世界下车啊",
]

PLAIN = [
    "孩子不听话，我吼了他，现在又很后悔",
    "面试又挂了，这已经是第五家了",
    "感觉自己做什么都比别人慢半拍",
    "我总是讨好别人，自己累得要命",
    "最近吃饭没胃口，什么都提不起劲",
    "昨天在地铁上突然心跳很快，有点慌",
    "周末想好好休息一下",
    "我计划下周去看看爸妈",
    "晚安，明天还要早起",
]


@pytest.mark.parametrize("text", RISKY)
def test_two_kinds_of_risk_component_are_never_said_back(text: str) -> None:
    engine = _engine()
    engine.note_risk(CrisisLevel.L0)
    assert engine.guarded(text)
    assert engine.risky_words(text)


@pytest.mark.parametrize("text", PLAIN)
def test_plain_words_are_not_guarded(text: str) -> None:
    assert not _engine().risky_words(text)


def test_one_kind_alone_is_not_a_risk() -> None:
    engine = _engine()
    assert engine._guard.kinds("医生给我开了点药") == {"means"}
    assert not engine.risky_words("医生给我开了点药")
    # A soft ending is an ending only with something lasting.
    assert "ending" not in engine._guard.kinds("今晚想早点休息")
    assert "ending" in engine._guard.kinds("想休息，永远的那种")


def test_a_composition_needs_its_heads_and_tails_only() -> None:
    # S1_MEANS_PREPARED: a means made ready, read without its death context.
    assert _engine()._guard.risky("刀片我都备好了")


@pytest.mark.parametrize("text", PLAIN[:5])
def test_a_model_only_l1_without_risk_words_is_answered_as_usual(text: str) -> None:
    engine = _engine()
    engine.note_risk(CrisisLevel.L1, rules=CrisisLevel.L0)
    assert not engine.guarded(text)
    slots = engine.build_slots(user_name="小林", agent_name="Olivia", user_text=text)
    assert slots.mirror not in SAID.guarded_acks
    assert not slots.guarded


@pytest.mark.parametrize(
    ("level", "rules"),
    [(CrisisLevel.L1, CrisisLevel.L1), (CrisisLevel.L2, CrisisLevel.L0), (CrisisLevel.L3, None)],
)
def test_the_rule_l1_and_any_l2_still_say_nothing_back(
    level: CrisisLevel, rules: CrisisLevel | None
) -> None:
    engine = _engine()
    engine.note_risk(level, rules=rules)
    assert engine.guarded(PLAIN[0])


def test_the_mirror_never_quotes_risk_words_whatever_the_level() -> None:
    # The crisis flow's answer to new words uses safe_mirror without a level.
    engine = _engine()
    for text in RISKY:
        assert engine.safe_mirror(text) in SAID.guarded_acks


# -- acknowledgements -------------------------------------------------------------------------


def test_an_acknowledgement_is_not_used_again_while_another_is_left() -> None:
    engine = _engine()
    pool = SAID.acks[Utterance.DIALECT.value]
    texts = ["份工搵钱少", "我今日好攰", "屋企啲人成日嗌交", "佢哋都唔明我", "唔知点算好"]
    texts += ["落咗成日雨", "冇心机做嘢", "我好挂住屋企"]
    picked = [engine.safe_mirror(t) for t in texts]
    assert len(pool) >= 6
    assert len(set(picked[: len(pool)])) == min(len(texts), len(pool))
    assert all(a != b for a, b in zip(picked, picked[1:], strict=False))


def test_the_same_message_read_twice_keeps_its_acknowledgement() -> None:
    engine = _engine()
    assert engine.safe_mirror("份工搵钱少") == engine.safe_mirror("份工搵钱少")


def test_cantonese_feelings_are_named() -> None:
    engine = _engine()
    assert engine.feeling_word(None, "我今日真系好唔开心") == "难过"
    assert engine.feeling_word(None, "返工返到好攰") == "疲惫"


# -- what a mirror says ----------------------------------------------------------------------


def test_self_blame_is_not_said_back_nor_affirmed() -> None:
    engine = _engine()
    slots = engine.build_slots(
        user_name="小林", agent_name="Olivia", user_text="我真是个废物，什么都做不好"
    )
    assert slots.mirror in SAID.self_blame_acks
    assert slots.guarded


def test_the_companion_is_not_turned_into_someone_else() -> None:
    engine = _engine()
    slots = engine.build_slots(
        user_name="小林", agent_name="Olivia", user_text="我知道你不会同意我的做法"
    )
    assert "对方" not in slots.mirror
    assert slots.mirror in SAID.addressed_acks


@pytest.mark.parametrize(
    "text",
    ["领导当着全组的面批评我，我觉得好丢脸", "奶奶今天打电话说想我了，我听着有点想哭"],
)
def test_felt_takes_a_feeling_never_a_whole_sentence(text: str) -> None:
    slots = _engine().build_slots(
        user_name="小林", agent_name="Olivia", user_text=text, emotion_id="sadness"
    )
    if slots.mirror.startswith("你感到"):
        assert len(slots.mirror) <= len("你感到") + 4 + 2, slots.mirror


# -- substance use -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["我在戒止痛药，吃了快两年", "安眠药我想慢慢停掉", "医生让我把镇静药减下来"],
)
def test_pills_are_the_context_too(text: str) -> None:
    assert read_substance(CUES, text, context=False).mentioned


@pytest.mark.parametrize(
    "text",
    [
        "停了以后浑身骨头疼，鼻涕直流",
        "晚上一阵冷一阵热，肚子也不舒服",
        "整个人一直在抖",
        "吐了好几回",
    ],
)
def test_more_withdrawal_signs(text: str) -> None:
    reading = read_substance(CUES, text, context=True)
    assert reading.withdrawal and not reading.severe


@pytest.mark.parametrize(
    "text",
    ["上次停药抽过一下，倒在地上", "耳朵里老有人在说话", "脑子迷迷糊糊，意识模糊"],
)
def test_severe_signs(text: str) -> None:
    assert read_substance(CUES, text, context=True).severe


@pytest.mark.parametrize(
    "text",
    [
        "啤酒度数那么低，应该不算破戒吧",
        "要不我喝无醇的？",
        "大家都喝，我一个人不喝很扫兴",
        "就一小口，尝尝",
    ],
)
def test_a_reason_found_for_a_drink_gets_no_tacit_yes(text: str) -> None:
    assert read_substance(CUES, text, context=True).asks_to_drink


@pytest.mark.parametrize(
    "text",
    [
        "我知道你会担心，但我真的很想",
        "现在特别想再喝一点，把难受压下去",
        "那种感觉，我好想再有一次",
    ],
)
def test_a_craving_for_more(text: str) -> None:
    assert read_substance(CUES, text, context=True).craving


@pytest.mark.parametrize("text", ["我想少喝点", "我忍住了想喝的念头", "我想去喝点热水"])
def test_wanting_less_or_something_else_is_no_craving(text: str) -> None:
    assert not read_substance(CUES, text, context=True).craving


def test_the_lines_say_no_more_than_they_know() -> None:
    lines = SAID.substance_lines
    assert "这些反应" not in lines["ask_to_drink"]
    assert "不赞成" in lines["ask_to_drink"]
    assert "急诊" in lines["withdrawal_severe"]
    assert all(drug in lines["withdrawal"] for drug in ("安眠药", "止痛药", "镇静"))


def test_the_withdrawal_line_alone() -> None:
    engine = _engine()
    assert engine.withdrawal_line("我在戒酒，第三天") == ""
    assert engine.withdrawal_line("手一直在抖") == SAID.substance_lines["withdrawal"]
    assert engine.withdrawal_line("刚才抽搐了一下") == SAID.substance_lines["withdrawal_severe"]


# -- loader ---------------------------------------------------------------------------------


def _copy(tmp_path: Path) -> Path:
    for path in ROOT.rglob("*.yaml"):
        rel = path.relative_to(ROOT)
        if rel.parts[0] in {"language", "templates", "cards", "lexicons"}:
            target = tmp_path / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
    return tmp_path


@pytest.mark.parametrize(
    ("where", "value"),
    [
        (("components", "min_kinds"), 1),
        (("self_blame", "acks"), ["我觉得你很严厉"]),
        (("addressed_acks",), ["你的感受是有来由的"]),
    ],
)
def test_the_loader_rejects_bad_round4_data(
    tmp_path: Path, tax: Taxonomy, where: tuple[str, ...], value: object
) -> None:
    root = _copy(tmp_path)
    path = root / "language" / "utterances.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    node = data["guarded"]
    for key in where[:-1]:
        node = node[key]
    node[where[-1]] = value
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    with pytest.raises(LanguageDataError):
        load_language_data(tax, root)
