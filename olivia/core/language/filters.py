"""W.I.L.L.O.W. word filters (WILLOW-01, WILLOW-04, PRD §9.3; SDD §5.1).

:func:`apply_willow` runs, in order:

1. **Protected-term masking.** Every ``protected_terms`` occurrence (longest match, left to
   right) is swapped for a private-use placeholder, so no later step can alter it.
2. **Diagnosis gate** (no exemptions). A sentence that contains any ``diagnosis_terms``
   entry (casefolded) is dropped whole; it is never patched word by word.
3. **Depathologize** (WILLOW-04), unless the content kind is exempt.
4. **Didactic rewrites** (WILLOW-01), unless the content kind is exempt.

Steps 3 and 4 scan left to right, take the longest pattern at each position and never
rescan replaced text. Placeholders are restored last.
"""

from __future__ import annotations

import functools
import re
from collections.abc import Mapping, Sequence
from typing import Final

from olivia.core.language.data import ContentKind, WillowData, load_willow

_MASK_BASE: Final = 0xE000  # Unicode private use area; never appears in any table
_MASK_LIMIT: Final = 0xF8FF
# A sentence ends at 。！？!? (plus any trailing closers); newlines are their own tokens.
_TOKEN_RE: Final = re.compile(r"\n|[^。！？!?\n]+[。！？!?…]*[”’」』）)]*|[。！？!?…]+")
_BLANK_RUNS_RE: Final = re.compile(r"\n{3,}")


def replace_longest(text: str, table: Mapping[str, str]) -> str:
    """Longest-match, left-to-right substitution that never rescans replaced text."""
    if not table:
        return text
    keys = sorted(table, key=len, reverse=True)
    out: list[str] = []
    i = 0
    while i < len(text):
        for key in keys:
            if text.startswith(key, i):
                out.append(table[key])
                i += len(key)
                break
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def mask_terms(text: str, terms: Sequence[str]) -> tuple[str, dict[str, str]]:
    """Swap each occurrence of ``terms`` for a placeholder; returns the text and the key."""
    if len(terms) > _MASK_LIMIT - _MASK_BASE:
        raise ValueError("too many protected terms to mask")
    placeholders = {term: chr(_MASK_BASE + i) for i, term in enumerate(terms)}
    masked = replace_longest(text, placeholders)
    return masked, {ph: term for term, ph in placeholders.items()}


def unmask(text: str, key: Mapping[str, str]) -> str:
    return "".join(key.get(ch, ch) for ch in text)


def find_diagnosis_terms(text: str, willow: WillowData) -> tuple[str, ...]:
    folded = text.casefold()
    return tuple(term for term in willow.diagnosis_terms if term in folded)


def drop_diagnosis_sentences(text: str, willow: WillowData) -> str:
    """Remove every sentence that names a diagnosis; tidy the blank lines left behind."""
    tokens = _TOKEN_RE.findall(text)
    kept = [t for t in tokens if t == "\n" or not find_diagnosis_terms(t, willow)]
    if len(kept) == len(tokens):
        return text
    joined = "".join(kept)
    lines = [line.rstrip() for line in joined.split("\n")]
    return _BLANK_RUNS_RE.sub("\n\n", "\n".join(lines)).strip()


@functools.cache
def _default_willow() -> WillowData:
    return load_willow()


def apply_willow(text: str, kind: ContentKind, willow: WillowData | None = None) -> str:
    """Run the W.I.L.L.O.W. filters on ``text`` for content of ``kind``.

    ``willow`` defaults to the packaged ``willow.yaml``.
    """
    if willow is None:
        willow = _default_willow()
    masked, key = mask_terms(text, willow.protected_terms)
    masked = drop_diagnosis_sentences(masked, willow)
    if not willow.exempt("depathologize", kind):
        masked = replace_longest(masked, willow.depathologize)
    if not willow.exempt("didactic_rewrites", kind):
        masked = replace_longest(masked, willow.didactic_rewrites)
    return unmask(masked, key)
