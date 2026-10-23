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
from types import MappingProxyType
from typing import Final

from olivia.core.language.data import ContentKind, WillowData, load_willow

_MASK_BASE: Final = 0xE000  # Unicode private use area; never appears in any table
_MASK_LIMIT: Final = 0xF8FF
# A sentence ends at 。！？!? (plus any trailing closers); newlines are their own tokens.
_TOKEN_RE: Final = re.compile(r"\n|[^。！？!?\n]+[。！？!?…]*[”’」』）)]*|[。！？!?…]+")
_BLANK_RUNS_RE: Final = re.compile(r"\n{3,}")


@functools.lru_cache(maxsize=32)
def _matcher(items: tuple[tuple[str, str], ...]) -> tuple[re.Pattern[str] | None, dict[str, str]]:
    """One alternation of the phrases, longest first, and their replacements.

    ``re`` tries the alternatives in order at each position and moves on past a match, so
    with the phrases sorted longest first this is the same scan as trying every phrase at
    every position: the longest phrase starting there wins (two phrases of one length
    cannot both start at one position), text without a match is copied one character at a
    time, and replaced text is never rescanned. The scan runs in C and only stops at
    characters that can start a phrase. An empty phrase never matches.
    """
    table = dict(items)
    keys = sorted((k for k in table if k), key=len, reverse=True)
    if not keys:
        return None, table
    return re.compile("|".join(map(re.escape, keys))), table


def replace_longest(text: str, table: Mapping[str, str]) -> str:
    """Longest-match, left-to-right substitution that never rescans replaced text."""
    if not table:
        return text
    pattern, replacements = _matcher(tuple(table.items()))
    if pattern is None:
        return text
    return pattern.sub(lambda m: replacements[m.group()], text)


@functools.lru_cache(maxsize=32)
def _masks(terms: tuple[str, ...]) -> tuple[Mapping[str, str], Mapping[int, str]]:
    """Each term's placeholder, and the ``str.translate`` table that restores the terms."""
    if len(terms) > _MASK_LIMIT - _MASK_BASE:
        raise ValueError("too many protected terms to mask")
    placeholders = {term: chr(_MASK_BASE + i) for i, term in enumerate(terms)}
    restore = {ord(ph): term for term, ph in placeholders.items()}
    return MappingProxyType(placeholders), MappingProxyType(restore)


def mask_terms(text: str, terms: Sequence[str]) -> tuple[str, dict[str, str]]:
    """Swap each occurrence of ``terms`` for a placeholder; returns the text and the key."""
    placeholders, restore = _masks(tuple(terms))
    masked = replace_longest(text, placeholders)
    return masked, {chr(ph): term for ph, term in restore.items()}


def unmask(text: str, key: Mapping[str, str]) -> str:
    # A key longer than one character never equals a single character of ``text``.
    return text.translate({ord(ph): term for ph, term in key.items() if len(ph) == 1})


@functools.lru_cache(maxsize=32)
def _any_of(terms: tuple[str, ...]) -> re.Pattern[str]:
    """Matches somewhere in a text exactly when one of ``terms`` is a substring of it."""
    return re.compile("|".join(map(re.escape, terms)) if terms else r"(?!)")


def contains_any(text: str, terms: Sequence[str]) -> bool:
    """``any(term in text for term in terms)``, in one C-level scan of ``text``."""
    return _any_of(tuple(terms)).search(text) is not None


def find_diagnosis_terms(text: str, willow: WillowData) -> tuple[str, ...]:
    folded = text.casefold()
    if not contains_any(folded, willow.diagnosis_terms):
        return ()
    return tuple(term for term in willow.diagnosis_terms if term in folded)


def drop_diagnosis_sentences(text: str, willow: WillowData) -> str:
    """Remove every sentence that names a diagnosis; tidy the blank lines left behind."""
    # Casefolding maps character by character, so a term in no part of the whole text is
    # in none of its sentences either.
    if not contains_any(text.casefold(), willow.diagnosis_terms):
        return text
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
    placeholders, restore = _masks(tuple(willow.protected_terms))
    masked = replace_longest(text, placeholders)
    masked = drop_diagnosis_sentences(masked, willow)
    if not willow.exempt("depathologize", kind):
        masked = replace_longest(masked, willow.depathologize)
    if not willow.exempt("didactic_rewrites", kind):
        masked = replace_longest(masked, willow.didactic_rewrites)
    return masked.translate(restore)
