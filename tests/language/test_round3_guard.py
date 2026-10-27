"""Round 3 (B2a, 2026-10-27; drafts pending G-0): what the user's words allow the reply to
say back (``language/guard.py``): risk words and drinking cues."""

from __future__ import annotations

import random
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from olivia.core.language.data import LanguageDataError, load_language_data
from olivia.core.language.engine import LanguageEngine
from olivia.core.language.guard import MirrorGuard, read_substance
from olivia.core.models import CrisisLevel, HelpStage, PersonaSpectrum
from olivia.core.safety.lexicon import load_safety_lexicons
from olivia.core.taxonomy import Taxonomy, load_taxonomy

TAX = load_taxonomy()
LEX = load_safety_lexicons(TAX)
DATA = load_language_data(TAX)
CUES = DATA.substance
GUARD = MirrorGuard(LEX, DATA.utterances.extra_risk_words)
ROOT = Path(__file__).resolve().parents[2] / "olivia" / "data"


def _engine(persona: PersonaSpectrum = PersonaSpectrum.ZEN_PHILOSOPHER) -> LanguageEngine:
    return LanguageEngine(TAX, rng=random.Random(1), data=DATA.for_persona(persona), lexicons=LEX)


# -- risk words -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "我打算明天下班后去江边那座桥上往下跳",  # a composition read loosely
        "真的想自鲨，撑不住",  # slang the screen does not read yet
        "我諗住今晚上天台跳落去",  # a height and a jump
        "你就叫送行人吧，我快不在了",  # one clause is enough
        "我不想活了",
    ],
)
def test_risky_messages_are_guarded(text: str) -> None:
    assert _engine().guarded(text)


@pytest.mark.parametrize(
    "text",
    [
        "累死了，终于下班",  # hyperbole
        "想死你了，什么时候回来",
        "周末去体验了跳伞，太刺激了",  # an everyday sense the lexicon lists
        "今天上班好累",
        "我在戒酒，今天是第十二天。",
    ],
)
def test_everyday_messages_are_not_guarded(text: str) -> None:
    assert not _engine().guarded(text)


def test_an_l1_turn_is_guarded_whatever_its_words() -> None:
    engine = _engine()
    engine.note_risk(CrisisLevel.L1)
    assert engine.guarded("今天上班好累")
    engine.note_risk(CrisisLevel.L0)
    assert not engine.guarded("今天上班好累")


def test_without_the_lexicon_only_the_level_and_slang_guard() -> None:
    bare = MirrorGuard(None, ["自鲨"])
    assert bare.risky("真的想自鲨")
    assert not bare.risky("我不想活了") and not bare.flagged("我不想活了")


@pytest.mark.parametrize("persona", list(PersonaSpectrum))
@pytest.mark.parametrize("stage", [HelpStage.S_EXPLORE, HelpStage.S_CLARIFY])
def test_a_guarded_reply_quotes_nothing_and_affirms_nothing(
    persona: PersonaSpectrum, stage: HelpStage
) -> None:
    text = "我打算明天下班后去江边那座桥上往下跳"
    for seed in range(12):
        engine = LanguageEngine(
            TAX, rng=random.Random(seed), data=DATA.for_persona(persona), lexicons=LEX
        )
        slots = engine.build_slots(
            user_name="阿周",
            agent_name="Olivia",
            user_text=text,
            emotion_id="sadness",
            yearning_id="SAFETY",
            spectrum_id="02",
        )
        assert slots.guarded and slots.need == ""
        assert slots.mirror in DATA.utterances.guarded_acks
        reply = engine.compose(stage, slots)
        assert "往下跳" not in reply and "桥上" not in reply
        assert not any(a in reply for a in DATA.utterances.affirmations), reply


def test_a_calm_message_is_still_mirrored() -> None:
    slots = _engine().build_slots(user_name="阿周", agent_name="Olivia", user_text="今天上班好累")
    assert not slots.guarded
    assert "上班好累" in slots.mirror


# -- drinking --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("context", "text"),
    [
        (True, "前几天手抖得厉害，出了好多汗，有点吓人。"),
        (False, "有朋友说突然不喝会出问题，是真的吗？"),
        (True, "我一停下来就心慌，整晚睡不着。"),
        (True, "今天手有点抖，心跳也快。"),
        (True, "全身冒汗，心慌，手一直在抖。"),
        (False, "我戒酒第三天，戒断反应很难受。"),
    ],
)
def test_withdrawal_signs(context: bool, text: str) -> None:
    reading = read_substance(CUES, text, context=context)
    assert reading.withdrawal and not reading.severe


def test_a_severe_sign() -> None:
    reading = read_substance(CUES, "上次停的时候，半夜看到墙上有东西在爬，挺害怕的。", context=True)
    assert reading.severe and reading.withdrawal


@pytest.mark.parametrize(
    "text",
    [
        "前几天手抖得厉害，出了好多汗，有点吓人。",  # no drinking in the conversation
        "开会前紧张得手抖",
        "我没有手抖，就是有点困",
    ],
)
def test_no_withdrawal_without_drinking_or_with_a_negation(text: str) -> None:
    assert not read_substance(CUES, text, context="没有" in text).withdrawal


@pytest.mark.parametrize(
    "text",
    [
        "我就想问问，喝一点点能不能帮助睡眠？",
        "我就想喝一小杯，应该没事吧？",
        "晚上不喝真的睡不着，喝一点帮助睡眠总可以吧？",
        "那我是不是先别戒了，等过完年再说。",
        "我想要不要喝一点缓一缓。",
        "那我是不是干脆别戒了，反正停了也难受。",
    ],
)
def test_asking_whether_a_little_drink_is_all_right(text: str) -> None:
    assert read_substance(CUES, text, context=True).asks_to_drink


@pytest.mark.parametrize(
    "text",
    ["喝茶有用吗，还是换点别的喝？", "睡前喝杯牛奶好吗", "我想再戒一次，这次一定行"],
)
def test_other_drinks_and_trying_again_are_no_such_question(text: str) -> None:
    assert not read_substance(CUES, text, context=True).asks_to_drink


@pytest.mark.parametrize(
    "text",
    [
        "今天特别想那种冰啤酒下肚的感觉。",
        "我好想喝一口冰凉的啤酒。",
        "以前一杯下去整个人都舒坦了。",
        "那种一口闷下去的痛快我到现在都忘不了。",
        "有时候觉得只有喝了酒才能放松下来。",
    ],
)
def test_relishing_a_drink(text: str) -> None:
    assert read_substance(CUES, text, context=True).craving


@pytest.mark.parametrize(
    "text",
    [
        "我在戒酒，今天是第十二天。",
        "我想把酒量一点点降下来。",
        "我回家灌了一大杯凉白开才压下去。",
        "今天下班有点累，想喝口热乎的东西。",
    ],
)
def test_quitting_and_other_drinks_are_not_relished(text: str) -> None:
    assert not read_substance(CUES, text, context=True).craving


def test_a_craving_is_reflected_never_quoted() -> None:
    engine = _engine()
    engine.boundary_line("我戒酒快一个月了。")
    slots = engine.build_slots(
        user_name="老周", agent_name="Olivia", user_text="以前一杯下去整个人都舒坦了。"
    )
    assert slots.guarded
    assert slots.mirror in DATA.utterances.craving_acks
    assert "舒坦" not in slots.mirror and "舒坦" not in slots.emotion


def test_drinking_stays_the_context_once_it_came_up() -> None:
    engine = _engine()
    assert engine.boundary_line("今天手有点抖。") == ""
    engine.boundary_line("我在试着戒酒，第五天了。")
    assert "医生指导" in engine.boundary_line("今天手有点抖，心跳也快。")


def test_the_lines_before_the_reply() -> None:
    lines = DATA.utterances.substance_lines
    engine = _engine()
    engine.boundary_line("我在戒酒")
    asked = engine.boundary_line("晚上不喝真的睡不着，喝一点帮助睡眠总可以吧？")
    assert asked == lines["ask_to_drink"] + lines["withdrawal"]
    assert engine.boundary_line("半夜看到墙上有东西在爬") == lines["withdrawal_severe"]


# -- data checks --------------------------------------------------------------------------------


def _copy(tmp_path: Path) -> Path:
    for path in ROOT.rglob("*.yaml"):
        rel = path.relative_to(ROOT)
        if rel.parts[0] in {"language", "templates", "cards", "lexicons"}:
            target = tmp_path / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
    return tmp_path


def _edit(root: Path, rel: str, change: Callable[[dict[str, Any]], None]) -> None:
    path = root / rel
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    change(doc)
    path.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")


def _affirm_everything(doc: dict[str, Any]) -> None:
    doc["guarded"]["affirmations"].append("。")


def _dose(doc: dict[str, Any]) -> None:
    doc["substance"]["withdrawal"] = "每天少喝一两，慢慢减，出现情况请就医。"


def _no_doctor(doc: dict[str, Any]) -> None:
    doc["substance"]["withdrawal_severe"] = "你说的这种情况很危险，请身边的人陪着你。"


def _quoting_ack(doc: dict[str, Any]) -> None:
    doc["guarded"]["acks"].append("我听见你说想跳下去")


@pytest.mark.parametrize("change", [_affirm_everything, _dose, _no_doctor, _quoting_ack])
def test_the_loader_rejects_bad_round3_lines(
    tmp_path: Path, change: Callable[[dict[str, Any]], None]
) -> None:
    root = _copy(tmp_path)
    _edit(root, "language/utterances.yaml", change)
    with pytest.raises(LanguageDataError):
        load_language_data(TAX, root)


def test_the_loader_rejects_an_unknown_image_topic(tmp_path: Path, tax: Taxonomy) -> None:
    root = _copy(tmp_path)
    _edit(root, "lexicons/substance.yaml", lambda d: d.update(image_topic="nope"))
    with pytest.raises(LanguageDataError, match="image_topic"):
        load_language_data(tax, root)


def test_the_new_files_are_drafts() -> None:
    assert "草稿：待 G-0" in (ROOT / "lexicons" / "substance.yaml").read_text(encoding="utf-8")
