import pytest

from olivia.core.safety.normalize import (
    PERCEPTION_HEAD,
    PERCEPTION_TAIL,
    clip_for_perception,
    normalize,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("想 死", "想死"),
        ("想​死", "想死"),
        ("想‌‍⁠﻿死", "想死"),
        ("ＰＴＳＤ", "ptsd"),
        ("BPD", "bpd"),
        ("［５％］ 不想活了", "[5%]不想活了"),
        ("\t活着\n好累 ", "活着好累"),
        ("想　死", "想死"),
    ],
)
def test_normalize_variants(raw, expected):
    assert normalize(raw) == expected


def test_clip_short_text_unchanged():
    text = "好" * (PERCEPTION_HEAD + PERCEPTION_TAIL)
    assert clip_for_perception(text) == text


def test_clip_keeps_tail():
    text = "a" * 1000 + "药已经买好了"
    clipped = clip_for_perception(text)
    assert len(clipped) == 384
    assert clipped.startswith("a" * 128) and clipped.endswith("药已经买好了")
