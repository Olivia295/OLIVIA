"""Explicit "remember this" requests (D1): only a cue at the start of a message counts."""

from __future__ import annotations

import pytest
import yaml

from olivia.core.memory.notes import NoteCuesError, load_note_cues

CUES = load_note_cues()


@pytest.mark.parametrize(
    ("message", "note"),
    [
        ("记住：我下周三有面试", "我下周三有面试"),
        ("记住:我下周三有面试", "我下周三有面试"),
        ("  记住， 我不喜欢被叫全名  ", "我不喜欢被叫全名"),
        ("帮我记一下，明天给妈妈打电话", "明天给妈妈打电话"),
        ("帮我记一下明天给妈妈打电话", "明天给妈妈打电话"),
        ("请记得我对芒果过敏", "我对芒果过敏"),
        ("请记住：周五是外婆的生日", "周五是外婆的生日"),
        ("記住：下週三面試", "下週三面試"),
        ("幫我記一下 明天交報告", "明天交報告"),
        ("记一下：今天跑了三公里！", "今天跑了三公里！"),
        ("记住：第一行\n第二行", "第一行\n第二行"),
    ],
)
def test_requests_return_the_text_after_the_cue_verbatim(message, note):
    assert CUES.find(message) == note


@pytest.mark.parametrize(
    "message",
    [
        "我记住了他说的话",
        "记住了",
        "记住他说的话很难",
        "我想请你帮我记一下",  # not at the start
        "你还记得我上次说的吗",
        "记住：",
        "帮我记一下",
        "请记得 ，  ",
        "/done",
        "",
        "今天好累，记住：别再加班",
    ],
)
def test_everything_else_is_not_a_request(message):
    assert CUES.find(message) is None


def test_longest_cue_wins():
    # "请帮我记住" must not leave "帮我记住" behind as part of the note.
    assert CUES.find("请帮我记住明天八点出门") == "明天八点出门"
    assert CUES.find("你记住：我叫小林") == "我叫小林"


def _write(tmp_path, doc: object) -> None:
    (tmp_path / "memory.yaml").write_text(yaml.safe_dump(doc, allow_unicode=True), "utf-8")


def _doc(needs=("记住",), direct=("请记得",), separators="：", **extra: object) -> dict:
    request: dict[str, object] = {"needs_separator": list(needs), "direct": list(direct)}
    return {"version": 1, "note_request": request, "separators": separators, **extra}


def _without_direct() -> dict:
    doc = _doc()
    del doc["note_request"]["direct"]
    return doc


@pytest.mark.parametrize(
    "doc",
    [
        None,
        {"version": 2},
        _doc(needs=()),
        _doc(direct=("记住",)),  # one cue in both groups
        _doc(separators=""),
        _without_direct(),
        _doc(needs=(" ",)),
        _doc(extra=1),
    ],
)
def test_malformed_lexicon_is_rejected(tmp_path, doc):
    _write(tmp_path, doc)
    with pytest.raises(NoteCuesError):
        load_note_cues(tmp_path)


def test_missing_lexicon_is_rejected(tmp_path):
    with pytest.raises(NoteCuesError):
        load_note_cues(tmp_path)
