"""Text normalization applied before any safety phrase matching."""

from __future__ import annotations

import unicodedata
from typing import Final

from olivia.core.safety._trad2simp import TRAD_TO_SIMP

# Perception window of SDD section 10.1: only the head and tail of a long
# message are scanned, because crisis cues cluster at the end of a message.
PERCEPTION_HEAD: Final = 128
PERCEPTION_TAIL: Final = 256

# One translate table: Traditional -> Simplified characters, and the curly single quotes
# (NFKC leaves them alone) to the ASCII apostrophe used by English lexicon phrases.
_FOLD: Final[dict[int, str]] = {
    **{ord(trad): simp for trad, simp in TRAD_TO_SIMP.items()},
    0x2018: "'",
    0x2019: "'",
}


def _is_dropped(ch: str) -> bool:
    """Whitespace and invisible characters that can split a phrase to dodge matching.

    Invisible means every format character (category Cf: zero-width space and joiners,
    word joiner, BOM, soft hyphen, direction marks and isolates, tag characters) plus
    the variation selectors, which are combining marks (Mn) that render as nothing.
    """
    return (
        ch.isspace()
        or unicodedata.category(ch) == "Cf"
        or "︀" <= ch <= "️"
        or "\U000e0100" <= ch <= "\U000e01ef"
    )


def normalize(text: str) -> str:
    """Fold text for matching: NFKC, casefold, Traditional -> Simplified, curly quotes
    -> "'", then drop all whitespace and invisible characters."""
    folded = unicodedata.normalize("NFKC", text).casefold().translate(_FOLD)
    return "".join(ch for ch in folded if not _is_dropped(ch))


def clip_for_perception(text: str) -> str:
    """Keep the first ``PERCEPTION_HEAD`` and last ``PERCEPTION_TAIL`` characters."""
    if len(text) <= PERCEPTION_HEAD + PERCEPTION_TAIL:
        return text
    return text[:PERCEPTION_HEAD] + text[-PERCEPTION_TAIL:]
