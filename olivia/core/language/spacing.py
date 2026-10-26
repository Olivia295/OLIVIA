"""Slot filling with a space between Chinese and Latin text (dogfood P8, 2026-10-26).

A name the user chose ("Olivia", "Lin") sits in Chinese template text; written as it is
it reads "Olivia都在". :func:`fill` puts one space between a filled value and the template
text next to it when one side is a Chinese character and the other a Latin letter or a
digit: "之后想聊聊，Olivia 都在。", "我是 Olivia"; punctuation needs none ("叫「Olivia」").
Only the template layer does this: the user's own words are never respaced.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Final

SLOT_RE: Final = re.compile(r"\{([^{}]*)\}")
_CJK_RE: Final = re.compile(r"[一-鿿]")


def _latin(char: str) -> bool:
    return char.isascii() and char.isalnum()


def _cjk(char: str) -> bool:
    return _CJK_RE.fullmatch(char) is not None


def _mixed(left: str, right: str) -> bool:
    """A space belongs between ``left`` and ``right`` (one character each)."""
    return (_cjk(left) and _latin(right)) or (_latin(left) and _cjk(right))


def fill(
    template: str,
    values: Mapping[str, str] | Callable[[str], str],
    *,
    pattern: re.Pattern[str] = SLOT_RE,
) -> str:
    """``template`` with every slot filled from ``values`` (a mapping, or a function of
    the slot name), spaced against the template text around it. A missing name raises
    ``KeyError`` as a plain lookup would."""
    get = values if callable(values) else values.__getitem__
    out: list[str] = []
    end = 0
    before = ""  # the last character written so far
    for match in pattern.finditer(template):
        segment = template[end : match.start()]
        out.append(segment)
        before = segment[-1:] or before
        value = get(match.group(1))
        after = template[match.end() : match.end() + 1]
        if value and before and _mixed(before, value[0]):
            value = " " + value
        if value and after and _mixed(value[-1], after):
            value = value + " "
        out.append(value)
        before = value[-1:] or before
        end = match.end()
    out.append(template[end:])
    return "".join(out)
