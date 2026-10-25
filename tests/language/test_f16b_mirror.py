"""F16b mirror fixes: a list of things is one reported list, and someone's news run
together with the user's own feeling is two clauses (F5b, F6b and F14 tables unchanged)."""

from __future__ import annotations

import pytest

from olivia.core.language.mirror import MAX_MIRROR, Utterance, mirror, utterance_kind


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Rational peer, usage s81: never "你提到是周报，是PPT".
        ("首先是周报，其次是PPT", "你提到周报、PPT"),
        ("一是周报，二是PPT，三是报销", "你提到周报、PPT、报销"),
        ("第一是周报，第二是PPT", "你提到周报、PPT"),
        ("首先是周报，首先是周报", "你提到周报"),
        # A list clause that names the user is a statement about the user.
        ("首先是我太累了", "你太累了"),
        ("首先是我妈不理解我", "你妈不理解你"),
        # List items after a first clause that is not one are left out.
        ("工作好多，首先是周报，其次是PPT", "你感到工作好多"),
        # Usage s80: never "你感到爸爸走了好几年了你还是放不下".
        ("爸爸走了好几年了我还是放不下，有什么方法吗", "你爸爸走了好几年了，你还是放不下"),
        ("妈妈住院了我很担心", "你妈妈住院了，你很担心"),
        ("他走了我好难过", "你提到他走了，你好难过"),
    ],
)
def test_f16b_mirrors(text: str, expected: str) -> None:
    assert mirror(text) == expected
    assert utterance_kind(text) is Utterance.STATEMENT


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # No one else in front of the 我: the F5b fronting stays.
        ("工作丢了我好难受", "你工作丢了好难受"),
        # 我 after a view verb is that view's subject, not a second clause.
        ("她觉得我很烦", "你感到她觉得你很烦"),
        # A reason is no list item.
        ("首先是因为工作", "你提到是因为工作"),
        # F14: a list opener on its own is still dropped.
        ("首先，我最近真的好累", "你最近真的好累"),
        ("其次，我睡不好", "你睡不好"),
    ],
)
def test_unchanged_neighbours(text: str, expected: str) -> None:
    assert mirror(text) == expected


def test_a_long_list_is_cut_at_an_item() -> None:
    out = mirror("首先是季度汇报材料，其次是项目复盘文档，最后是团队周会纪要")
    assert out == "你提到季度汇报材料、项目复盘文档"
    assert len(out) <= MAX_MIRROR
