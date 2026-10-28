"""Text normalization applied before any safety phrase matching."""

from __future__ import annotations

import re
import unicodedata
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
# The ranges are static so the whole fold stays one C-level ``str.translate``;
# tests/safety/test_normalize.py checks them against the running Unicode database.
_DROPPED_RANGES: Final[tuple[tuple[int, int], ...]] = (
    (0x0009, 0x000D),
    (0x001C, 0x0020),
    (0x0085, 0x0085),
    (0x00A0, 0x00A0),
    (0x00AD, 0x00AD),
    (0x0600, 0x0605),
    (0x061C, 0x061C),
    (0x06DD, 0x06DD),
    (0x070F, 0x070F),
    (0x0890, 0x0891),
    (0x08E2, 0x08E2),
    (0x1680, 0x1680),
    (0x180E, 0x180E),
    (0x2000, 0x200F),
    (0x2028, 0x202F),
    (0x205F, 0x2064),
    (0x2066, 0x206F),
    (0x3000, 0x3000),
    (0xFE00, 0xFE0F),
    (0xFEFF, 0xFEFF),
    (0xFFF9, 0xFFFB),
    (0x110BD, 0x110BD),
    (0x110CD, 0x110CD),
    (0x13430, 0x1343F),
    (0x1BCA0, 0x1BCA3),
    (0x1D173, 0x1D17A),
    (0xE0001, 0xE0001),
    (0xE0020, 0xE007F),
    (0xE0100, 0xE01EF),
)

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


# The same fold with spaces kept (whitespace is turned into spaces before it applies).
_FOLD_KEEP_SPACES: Final[dict[int, str | None]] = {**_FOLD, ord(" "): " "}


def normalize(text: str) -> str:
    """Fold text for matching: NFKC, casefold, Traditional -> Simplified, curly quotes
    -> "'", then drop all whitespace and invisible characters, and a single ASCII letter
    standing between two Han characters (a colour code's leftover)."""
    return _drop_stray_letters(unicodedata.normalize("NFKC", text).casefold().translate(_FOLD))


def fold_words(text: str) -> str:
    """:func:`normalize` without dropping word breaks: every run of whitespace becomes one
    space (invisible characters are still dropped), so English words stay apart. Used where
    word boundaries matter (reading a yes or no to the D3 question)."""
    spaced = "".join(" " if ch.isspace() else ch for ch in unicodedata.normalize("NFKC", text))
    return _drop_stray_letters(" ".join(spaced.casefold().translate(_FOLD_KEEP_SPACES).split()))


def clip_for_perception(text: str) -> str:
    """Keep the first ``PERCEPTION_HEAD`` and last ``PERCEPTION_TAIL`` characters."""
    if len(text) <= PERCEPTION_HEAD + PERCEPTION_TAIL:
        return text
    return text[:PERCEPTION_HEAD] + text[-PERCEPTION_TAIL:]
