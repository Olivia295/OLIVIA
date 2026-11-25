"""Text normalization applied before any safety phrase matching."""

from __future__ import annotations

import functools
import re
import unicodedata
from bisect import bisect_left
from typing import Final

from olivia.core.safety._trad2simp import TRAD_TO_SIMP

# Perception window of SDD section 10.1: only the head and tail of a long
# message are scanned, because crisis cues cluster at the end of a message.
PERCEPTION_HEAD: Final = 128
PERCEPTION_TAIL: Final = 256

# Code points dropped before matching: all whitespace (``str.isspace``), every format
# character (category Cf: zero-width space and joiners, word joiner, BOM, soft hyphen,
# direction marks and isolates, tag characters) and the variation selectors, which are
# combining marks (Mn) that render as nothing. All of them can split a phrase invisibly.
# 2026-11-25 (metamorphic testing, tests/safety/metamorphic.py): also every other default
# ignorable code point of Unicode's DerivedCoreProperties (the combining grapheme joiner,
# the Hangul fillers, the Khmer inherent vowels, the Mongolian variation selectors and the
# reserved ones up to U+E00FF), the Braille blank U+2800 (a blank cell, used like the
# Hangul filler U+3164 as an "invisible" character), and the combining diacritical marks
# left after NFKC: a mark NFKC composes (e + U+0301 -> é) is kept, one with no composed
# form only decorates, such as the underline and strike-through of "fancy text" makers
# (想\u0332死\u0332). Before this, one such character between two characters hid any phrase.
# The ranges are static so the whole fold stays one C-level ``str.translate``;
# tests/safety/test_normalize.py checks them against the running Unicode database.
_DROPPED_RANGES: Final[tuple[tuple[int, int], ...]] = (
    (0x0009, 0x000D),
    (0x001C, 0x0020),
    (0x0085, 0x0085),
    (0x00A0, 0x00A0),
    (0x00AD, 0x00AD),
    (0x0300, 0x036F),
    (0x0600, 0x0605),
    (0x061C, 0x061C),
    (0x06DD, 0x06DD),
    (0x070F, 0x070F),
    (0x0890, 0x0891),
    (0x08E2, 0x08E2),
    (0x115F, 0x1160),
    (0x1680, 0x1680),
    (0x17B4, 0x17B5),
    (0x180B, 0x180F),
    (0x1AB0, 0x1AFF),
    (0x1DC0, 0x1DFF),
    (0x2000, 0x200F),
    (0x2028, 0x202F),
    (0x205F, 0x206F),
    (0x20D0, 0x20FF),
    (0x2800, 0x2800),
    (0x3000, 0x3000),
    (0x3164, 0x3164),
    (0xFE00, 0xFE0F),
    (0xFE20, 0xFE2F),
    (0xFEFF, 0xFEFF),
    (0xFFA0, 0xFFA0),
    (0xFFF0, 0xFFFB),
    (0x110BD, 0x110BD),
    (0x110CD, 0x110CD),
    (0x13430, 0x1343F),
    (0x1BCA0, 0x1BCA3),
    (0x1D173, 0x1D17A),
    (0xE0000, 0xE00FF),
    (0xE0100, 0xE01EF),
)

# The blank fillers among them show as an empty space, so :func:`fold_words` reads each as a
# word break instead of dropping it. U+3164 and U+FFA0 reach the fold as U+1160 (NFKC).
_BLANKS: Final = "\u115f\u1160\u2800\u3164\uffa0"

# One translate table: Traditional -> Simplified characters, the curly single quotes (NFKC
# leaves them alone) to the ASCII apostrophe used by English lexicon phrases, and deletion
# of every dropped code point.
_FOLD: Final[dict[int, str | None]] = {
    **{ord(trad): simp for trad, simp in TRAD_TO_SIMP.items()},
    0x2018: "'",
    0x2019: "'",
    **{cp: None for first, last in _DROPPED_RANGES for cp in range(first, last + 1)},
}


# A single ASCII letter with a Han character right before and after it (2026-10-28, re-test
# q4): a terminal whose line editor drops the escape of a colour code leaves its last
# letter behind ("我想<ESC>[31m死<ESC>[0m了算了" arrives as 我想m死m了算了). Matching drops it;
# what is shown and stored keeps the text as typed. Two or more letters (app, zs, die) and
# a letter at either end of the Han run (B站, X光) are kept. Applied after casefold, so only
# lowercase letters remain.
_HAN: Final = "\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
_STRAY_LETTER: Final = re.compile(f"(?<=[{_HAN}])[a-z](?=[{_HAN}])")


def _drop_stray_letters(folded: str) -> str:
    return folded if folded.isascii() else _STRAY_LETTER.sub("", folded)


# The same fold with spaces kept (whitespace is turned into spaces before it applies) and
# the blank fillers read as spaces.
_FOLD_KEEP_SPACES: Final[dict[int, str | None]] = {
    **_FOLD,
    ord(" "): " ",
    **{ord(blank): " " for blank in _BLANKS},
}


# Round 5 (复测 q4 IN-4): the Unicode direction controls. "我想<RLO>杀自<PDF>" is shown as
# 我想自杀, but dropping the controls alone leaves 我想杀自 for the screen and the mirror.
# :func:`display_order` reads the characters in the order they are shown; the screen reads
# both orders (:func:`bidi_readings`, ``crisis.SafetyScreen.assess``) and the text kept is
# :func:`shown_text`.
_LRE, _RLE, _PDF, _LRO, _RLO = "\u202a", "\u202b", "\u202c", "\u202d", "\u202e"
_LRI, _RLI, _FSI, _PDI = "\u2066", "\u2067", "\u2068", "\u2069"
_OPENERS: Final = {_LRE: (False, None), _RLE: (True, None), _LRO: (False, "L"), _RLO: (True, "R")}
_ISOLATES: Final = {_LRI: False, _FSI: False, _RLI: True}
_BIDI_MARKS: Final = frozenset("\u200e\u200f\u061c")
BIDI_CONTROLS: Final = frozenset((*_OPENERS, *_ISOLATES, _PDF, _PDI, *_BIDI_MARKS))
_MAX_DEPTH: Final = 125  # UAX #9 max_depth


def display_order(text: str) -> str:
    """``text`` in the order a terminal shows it, without its direction controls.

    A simplified UAX #9 (rules X1-X10, W/N folded, L2): embeddings, overrides and isolates
    set each character's level; under an override every character takes its direction, and
    otherwise Hebrew and Arabic letters are right-to-left and everything else left-to-right
    (Chinese has no other letters). Runs are then reversed from the highest level down, so
    "我想<RLO>杀自<PDF>" becomes 我想自杀. Text without a direction control is returned as
    it is. An unclosed control runs to the end of the text, as it does on screen.
    """
    return _reorder(text)[0]


def _reorder(text: str) -> tuple[str, bool]:
    """:func:`display_order` and whether every embedding, override and isolate was closed."""
    if BIDI_CONTROLS.isdisjoint(text):
        return text, True
    # Stack entries: (level, override, isolate).
    stack: list[tuple[int, str | None, bool]] = [(0, None, False)]
    chars: list[str] = []
    levels: list[int] = []
    for ch in text:
        level, override, _ = stack[-1]
        if ch in _OPENERS or ch in _ISOLATES:
            rtl, new_override = _OPENERS[ch] if ch in _OPENERS else (_ISOLATES[ch], None)
            new_level = level + 1 if rtl == (level % 2 == 0) else level + 2
            if new_level <= _MAX_DEPTH:
                stack.append((new_level, new_override, ch in _ISOLATES))
            continue
        if ch == _PDF:
            if len(stack) > 1 and not stack[-1][2]:
                stack.pop()
            continue
        if ch == _PDI:
            while len(stack) > 1:
                if stack.pop()[2]:
                    break
            continue
        if ch in _BIDI_MARKS:
            continue
        kind = override or ("R" if unicodedata.bidirectional(ch) in ("R", "AL") else "L")
        chars.append(ch)
        levels.append(level + 1 if (kind == "R") != (level % 2 == 1) else level)
    for lowest in range(max(levels, default=0), 0, -1):
        i = 0
        while i < len(chars):
            if levels[i] < lowest:
                i += 1
                continue
            j = i
            while j < len(chars) and levels[j] >= lowest:
                j += 1
            chars[i:j] = chars[i:j][::-1]
            levels[i:j] = levels[i:j][::-1]
            i = j
    return "".join(chars), len(stack) == 1


def without_bidi(text: str) -> str:
    """``text`` with its direction controls dropped, in the order it was typed."""
    if BIDI_CONTROLS.isdisjoint(text):
        return text
    return "".join(ch for ch in text if ch not in BIDI_CONTROLS)


def bidi_readings(text: str) -> tuple[str, ...]:
    """The ways ``text`` can be read: as typed without its direction controls and, when it
    differs, as shown (:func:`display_order`). The crisis screen reads both and keeps the
    higher level, so neither a reversed run nor a stray control hides a crisis sentence."""
    typed = without_bidi(text)
    shown = display_order(text)
    return (typed,) if shown == typed else (typed, shown)


def shown_text(text: str) -> str:
    """The text kept and said back: as shown when the controls were all closed again (a
    run written to be seen reversed, "我想<RLO>杀自<PDF>"), as typed when one was left open
    (a stray U+202E that would reverse everything after it), without the controls either
    way."""
    shown, closed = _reorder(text)
    return shown if closed else without_bidi(text)


# Round 6 (2026-10-30): one turn folds the same message a dozen times (the screen, red
# flags, reported speech, the mirror and the guard), and NFKC alone costs about 60 µs on
# a 500-character message. The fold is a pure function of its argument, so its last
# results are kept; the cache holds only strings, in memory, and is never written out.
_FOLD_CACHE_SIZE: Final = 256


@functools.lru_cache(maxsize=_FOLD_CACHE_SIZE)
def normalize(text: str) -> str:
    """Fold text for matching: NFKC, casefold, Traditional -> Simplified, curly quotes
    -> "'", then drop all whitespace, invisible characters and leftover combining marks,
    and a single ASCII letter standing between two Han characters (a colour code's
    leftover)."""
    return _drop_stray_letters(unicodedata.normalize("NFKC", text).casefold().translate(_FOLD))


# 2026-11-25 (metamorphic testing, task G3): where the whitespace :func:`normalize` drops
# stood. Phrases still match across it (a space or a filler between every character must not
# hide a phrase), and two parts of a composition still join across it, but the compositions
# read a run of whitespace between two words as the end of a clause for their subject,
# ``leading``, ``trailing`` and clause-bound ``unless`` checks, and a line break as the end
# of a sentence (``safety/compose.py``): in "我想过死 不止一次" the words after the space are
# a clause of their own. Not a break: whitespace between two ASCII characters (the spaces of
# English words; their phrases are written without them), and whitespace next to a word of
# one character (letter spacing, "我 想 死", or a stray character).
_WHITESPACE: Final = re.compile(f"([\\s{_BLANKS}]+)")
# ``(position, line)`` pairs of :func:`clause_breaks`.
Breaks = tuple[tuple[int, bool], ...]
_LINE_BREAKS: Final = frozenset("\n\r\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029")


def _fold(text: str) -> str:
    """:func:`normalize` before the stray letters are dropped."""
    return unicodedata.normalize("NFKC", text).casefold().translate(_FOLD)


@functools.lru_cache(maxsize=_FOLD_CACHE_SIZE)
def clause_breaks(text: str) -> Breaks:
    """The breaks the whitespace of ``text`` makes in ``normalize(text)``, in order: each is
    ``(position, line)``, the break standing right before ``normalize(text)[position]``;
    ``line`` when the whitespace holds a line break (the end of a sentence), else it is a
    clause break. Empty when the text has none, and (never seen; the old reading then
    stands) when the words folded one by one do not join into ``normalize(text)``."""
    if _WHITESPACE.search(text) is None:
        return ()
    pieces = _WHITESPACE.split(text)  # words at even indices, the whitespace between at odd
    words: list[str] = []
    lines: list[bool] = []  # lines[i]: the whitespace before words[i + 1] holds a line break
    line = False
    for i in range(0, len(pieces), 2):
        if i:
            line = line or not _LINE_BREAKS.isdisjoint(pieces[i - 1])
        folded = _fold(pieces[i])
        if not folded:
            continue  # nothing left of it: the whitespace on both sides is one run
        if words:
            lines.append(line)
        words.append(folded)
        line = False
    joined = "".join(words)
    if len(words) < 2 or joined != _fold(text):
        return ()
    stray = [] if joined.isascii() else [m.start() for m in _STRAY_LETTER.finditer(joined)]
    breaks: list[tuple[int, bool]] = []
    end = 0
    for left, right, line in zip(words[:-1], words[1:], lines, strict=True):
        end += len(left)
        if not line and (left[-1].isascii() and right[0].isascii()):
            continue  # the space between two English words
        if len(left) < 2 or len(right) < 2:
            continue  # letter spacing
        breaks.append((end - bisect_left(stray, end), line))
    if _drop_stray_letters(joined) != normalize(text):
        return ()
    return tuple(breaks)


# A message said twice or more over (整句重复, task G3): a phrase or a composition that spans
# the place where one copy meets the next was never said. Copies shorter than this are a
# word said over (哈哈哈哈, 去死去死), not a message.
_MIN_COPY: Final = 4


def repeat_copy(normalized: str) -> int:
    """The length of one copy when ``normalized`` is one text of at least ``_MIN_COPY``
    characters written two or more times over, nothing between the copies (the whitespace
    between them is already gone); 0 otherwise."""
    n = len(normalized)
    # The shortest period: the text is that many characters written n // period times.
    period = (normalized + normalized).find(normalized, 1, 2 * n - 1) if n else -1
    if period <= 0:
        return 0
    copies = n // period
    for times in range(-(-_MIN_COPY // period), copies // 2 + 1):
        if copies % times == 0:
            return period * times
    return 0


def spans_copies(start: int, end: int, copy: int, length: int) -> bool:
    """Does ``[start, end)`` of a text of ``length`` characters made of copies ``copy``
    characters long (:func:`repeat_copy`) span a place where one copy meets the next?"""
    if not copy or end - start < 2:
        return False
    meet = (end - 1) // copy * copy  # the last place a copy begins before ``end``
    return start < meet < length


def fold_words(text: str) -> str:
    """:func:`normalize` without dropping word breaks: every run of whitespace or blank
    fillers (U+2800, the Hangul fillers) becomes one space (invisible characters are still
    dropped), so English words stay apart. Used where word boundaries matter (reading a yes
    or no to the D3 question)."""
    spaced = "".join(" " if ch.isspace() else ch for ch in unicodedata.normalize("NFKC", text))
    return _drop_stray_letters(" ".join(spaced.casefold().translate(_FOLD_KEEP_SPACES).split()))


def clip_for_perception(text: str) -> str:
    """Keep the first ``PERCEPTION_HEAD`` and last ``PERCEPTION_TAIL`` characters."""
    if len(text) <= PERCEPTION_HEAD + PERCEPTION_TAIL:
        return text
    return text[:PERCEPTION_HEAD] + text[-PERCEPTION_TAIL:]
