"""F14 mirror fixes: only the speaker's own goodbye is CLOSING, delight ("笑死我了") is
never mirrored as a hurt state, and the F5b / F6b tables stay as they were (COLBO-01
keeps "你感到她从来没夸过你")."""

from __future__ import annotations

import pytest

from olivia.core.language import LanguageEngine
from olivia.core.language.mirror import Utterance, mirror, utterance_kind

# -- the speaker's own goodbye ----------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "跟过去说拜拜",
        "拜拜那段感情",
        "这个方案先这样吧",
        "工作先这样吧",
        "他说今天就到这里",
        "老板说今天就到这里",
        "我妈说她去睡了",
        "她跟我说再见",
    ],
)
def test_a_goodbye_about_something_else_is_a_statement(text: str) -> None:
    assert utterance_kind(text) is Utterance.STATEMENT, text


@pytest.mark.parametrize(
    "text",
    [
        "拜拜",
        "好的，拜拜",
        "好的拜拜",
        "再见啦",
        "先这样吧",
        "那就先这样",
        "嗯，今天先这样",
        "那我们今天就先这样吧",
        "今天就到这里吧",
        "我去睡了",
        "行，那我先下了",
    ],
)
def test_the_speakers_own_goodbye_stays_closing(text: str) -> None:
    assert utterance_kind(text) is Utterance.CLOSING, text


def test_a_goodbye_to_the_past_is_mirrored() -> None:
    out = mirror("我想跟过去说拜拜")
    assert out.startswith("你") and "拜拜" in out and "我" not in out


# -- delight is no hurt state ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("笑死我了", "你觉得特别好笑"),
        ("哈哈哈笑死我了", "你觉得特别好笑"),
        ("笑死了，他居然穿反了衣服", "你觉得特别好笑，他居然穿反了衣服"),
        ("乐死我了", "你乐得不行"),
        ("萌死我了", "你觉得萌极了"),
        ("美死我了", "你觉得美极了"),
        ("可爱死我了", "你觉得可爱极了"),
        ("开心死了", "你开心极了"),
    ],
)
def test_delight_is_mirrored_as_delight(text: str, expected: str) -> None:
    out = mirror(text)
    assert out == expected
    assert "坏了" not in out and "死" not in out


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("气死我了", "你气坏了"),
        ("累死了，不想上班了", "你累坏了，不想上班了"),
        ("烦死我了", "你烦透了"),
        ("想死你了，好久没见", "你很想念对方，好久没见"),
    ],
)
def test_the_hurt_exclamations_are_unchanged(text: str, expected: str) -> None:
    assert mirror(text) == expected


@pytest.mark.parametrize("text", ["我真的想死", "笑着说我想死", "我想死了"])
def test_a_wish_to_die_is_never_read_as_delight(text: str) -> None:
    out = mirror(text)
    assert "好笑" not in out and "极了" not in out and "不行" not in out


# -- COLBO-01: a view of someone else stays the user's view -----------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("她从来没夸过我", "你感到她从来没夸过你"),
        ("我觉得你根本不在乎我", "你感到对方根本不在乎你"),
        ("他说我太敏感", "你提到他说你太敏感"),
    ],
)
def test_views_and_reports_keep_their_frames(
    engine: LanguageEngine, text: str, expected: str
) -> None:
    assert mirror(text) == expected
    assert engine.safe_mirror(text) == expected
