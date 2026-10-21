"""Text normalization applied before any safety phrase matching."""

from __future__ import annotations

import unicodedata
from typing import Final

# Perception window of SDD section 10.1: only the head and tail of a long
# message are scanned, because crisis cues cluster at the end of a message.
PERCEPTION_HEAD: Final = 128
PERCEPTION_TAIL: Final = 256

# Zero-width characters are not whitespace for ``str.isspace`` but are used to
# split a phrase and dodge matching: ZWSP, ZWNJ, ZWJ, word joiner, BOM.
_ZERO_WIDTH: Final = frozenset("​‌‍⁠﻿")


def normalize(text: str) -> str:
    """NFKC-fold, casefold, then drop all whitespace and zero-width characters."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    return "".join(ch for ch in folded if not ch.isspace() and ch not in _ZERO_WIDTH)


def clip_for_perception(text: str) -> str:
    """Keep the first ``PERCEPTION_HEAD`` and last ``PERCEPTION_TAIL`` characters."""
    if len(text) <= PERCEPTION_HEAD + PERCEPTION_TAIL:
        return text
    return text[:PERCEPTION_HEAD] + text[-PERCEPTION_TAIL:]
