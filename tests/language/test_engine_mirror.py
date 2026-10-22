"""Pronoun-safe mirroring (COLBO-01, SDD §4.1)."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from olivia.core.language import LanguageEngine, mirror
from olivia.core.language.mirror import FALLBACK_MIRROR, MAX_MIRROR

NON_PRONOUN = ("你死我活", "自我", "忘我", "无我", "唯我", "敌我", "你我")


@pytest.mark.parametrize(
    ("user_text", "expected"),
    [
        # SDD §4.1 / COLBO-01: never "你觉得我不在乎你".
        ("我觉得你根本不在乎我", "你感到对方根本不在乎你"),
        # First-person main clause: flip; a second 我 in the clause becomes 自己.
        ("我觉得我很失败", "你觉得自己很失败"),
        ("我对我自己很失望", "你对你自己很失望"),
        ("我丢了我的工作", "你丢了你的工作"),
        ("我们家总是吵架", "你们家总是吵架"),
        # Third-party conflict: humanistic framing, no mechanical flip.
        ("领导当着大家的面批评我", "你感到领导当着大家的面批评你"),
        ("我觉得他不爱我了", "你感到他不爱你了"),
        ("我老公从来不听我说话", "你老公从来不听你说话"),
        ("你们都不懂我", "你感到他们都不懂你"),
        ("您根本不在乎我的感受", "你感到对方根本不在乎你的感受"),
        ("我觉得你们只是在敷衍我", "你感到他们只是在敷衍你"),
        # Not a pronoun.
        ("我总在自我怀疑", "你总在自我怀疑"),
        ("其他事我都还好", "你感到其他事你都还好"),
        # Sentence and clause choice, battery prefix.
        ("唉。我真的好累", "你真的好累"),
        ("唉，我真的好累", "你真的好累"),
        ("[5%] 好累", "你感到好累"),
        ("工作好多", "你感到工作好多"),
        # Trim at a clause boundary.
        ("我最近总是睡不着，一闭眼就想到工作上的事情，越想越心慌", "你最近总是睡不着"),
        ("我很累，也很烦，不想说话", "你很累，也很烦，不想说话"),
    ],
)
def test_mirror_cases(user_text: str, expected: str) -> None:
    assert mirror(user_text) == expected


def test_conflict_never_flips_into_the_agent() -> None:
    out = mirror("我觉得你根本不在乎我")
    assert "我" not in out
    assert out != "你觉得我根本不在乎你"
    assert "对方" in out


@pytest.mark.parametrize("user_text", ["", "   ", "。。。", "……", "[5%]"])
def test_empty_input_uses_the_fallback(user_text: str) -> None:
    assert mirror(user_text) == FALLBACK_MIRROR


def test_long_single_clause_is_cut_to_the_limit() -> None:
    out = mirror("我" + "非常" * 20 + "累")
    assert len(out) == MAX_MIRROR
    assert out.startswith("你")


_ALPHABET = st.sampled_from(list("我你您们他她的觉得很累想说不在乎老板妈妈自己，。！？ 自我好"))


@settings(max_examples=300, deadline=None)
@given(st.text(alphabet=_ALPHABET, max_size=60))
def test_mirror_invariants(user_text: str) -> None:
    out = mirror(user_text)
    assert 0 < len(out) <= MAX_MIRROR
    assert out.startswith("你")
    plain = out
    for word in NON_PRONOUN:
        plain = plain.replace(word, "")
    assert "我" not in plain, (user_text, out)
    assert "您" not in out


def test_safe_mirror_hides_diagnosis_and_numbers(engine: LanguageEngine) -> None:
    assert engine.safe_mirror("我有抑郁症") == FALLBACK_MIRROR
    assert engine.safe_mirror("我的电话是13800138000") == FALLBACK_MIRROR
    assert engine.safe_mirror("我在学接纳承诺疗法") == FALLBACK_MIRROR
    assert engine.safe_mirror("我觉得我很失败") == "你觉得自己很失败"
