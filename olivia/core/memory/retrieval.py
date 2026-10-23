"""3D retrieval over the memory ledger (step B4; SDD §3.3, PRD MIYI-04, ruling 29, Q-7).

Each ledger entry ``e`` is scored against the current message by the SDD §3.3 weighted
sum::

    score(e) = W_REC * exp(-ALPHA * age_days(e) / TAU_DAYS)   # Ebbinghaus-style recency
             + W_SIM * cos(v_e, v_query)                      # character n-gram TF-IDF
             + W_SAL * S_sal(e)                               # 1 if significant, else 0

with ``W_REC = 0.4``, ``W_SIM = 0.4``, ``W_SAL = 0.2`` and ``ALPHA = 1`` (ruling 29) and
``TAU_DAYS = 7`` (SDD §3.3, PRD Q-7). An entry is significant when a turn reached L2 or
the user marked it (ruling 29); a note is always significant, since the user asked for
it to be remembered (B2). Significant entries are **permanently protected** (Q-7): they
never decay, so their recency term stays 1 whatever their age. Ages are fractional days,
clamped at 0 (an entry stamped in the future gets full weight, never more).

Similarity is the cosine between TF-IDF vectors of character 2- and 3-grams, taken within
runs of word characters after NFKC normalisation and case folding (so ``ＩＥＬＴＳ`` and
``ielts`` match, and punctuation never forms a gram). Term frequency is the raw count;
the IDF is the smoothed ``ln((1 + N) / (1 + df)) + 1`` over the ``N`` entries, which also
gives query grams no entry contains their weight in the query's norm. The SDD does not
fix the vectoriser; these choices are documented here.

What an entry is searchable by (:func:`searchable_text`) is only what the entry already
holds: a note's own text, verbatim; for a session summary, the everyday labels its
templated body is built from (stage names, distress-spectrum labels, the card titles the
user saw with their feedback, and the crisis and significance lines when they apply),
without times, dates or heading boilerplate. Nothing here writes anything.

A consequence of these weights: a significant entry scores at least 0.6 whatever the
query, while an ordinary one reaches 0.6 only when fresh and with a cosine around 0.5,
so notes (always significant) usually rank ahead of session summaries.

Ties are broken newest first, then by entry id, so a ranking is deterministic. The PRD
(MIYI-04) asks for the top three events, hence ``TOP_K = 3``.

Typical use builds one :class:`MemoryIndex` per loaded ledger and ranks each message
against it (the SDD §10.1 budget, P99 2 ms, is for the query); :func:`rank` builds and
ranks in one call.
"""

from __future__ import annotations

import heapq
import math
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from functools import lru_cache
from typing import Final

from olivia.core.memory.ledger import LedgerEntry, NoteEntry
from olivia.core.memory.text import NO_FEEDBACK, MemoryText, load_memory_text

W_REC: Final = 0.4
"""Weight of recency (ruling 29)."""
W_SIM: Final = 0.4
"""Weight of similarity (ruling 29)."""
W_SAL: Final = 0.2
"""Weight of salience (ruling 29)."""
ALPHA: Final = 1.0
"""Decay rate multiplier (ruling 29)."""
TAU_DAYS: Final = 7.0
"""Forgetting time constant in days (SDD §3.3, PRD Q-7)."""
TOP_K: Final = 3
"""How many events a retrieval returns by default (PRD MIYI-04)."""
NGRAM_SIZES: Final = (2, 3)

_SECONDS_PER_DAY: Final = 86_400.0
_WORD_RUN: Final = re.compile(r"\w+")


def char_ngrams(text: str) -> Counter[str]:
    """Character 2- and 3-grams of ``text``, within runs of word characters."""
    counts: Counter[str] = Counter()
    for run in _WORD_RUN.findall(unicodedata.normalize("NFKC", text).casefold()):
        for n in NGRAM_SIZES:
            for i in range(len(run) - n + 1):
                counts[run[i : i + n]] += 1
    return counts


@lru_cache(maxsize=1)
def _default_text() -> MemoryText:
    return load_memory_text()


def searchable_text(
    entry: LedgerEntry,
    *,
    text: MemoryText | None = None,
    method_titles: Mapping[str, str] | None = None,
) -> str:
    """What ``entry`` can be found by: a note's text, or a summary's templated labels.

    ``text`` and ``method_titles`` should be the ledger's own, so a summary is searchable
    by exactly the words its body shows; an untitled card falls back to its id, as there.
    """
    if isinstance(entry, NoteEntry):
        return entry.text
    t = _default_text() if text is None else text
    titles: Mapping[str, str] = {} if method_titles is None else method_titles
    s = entry.summary
    parts = [t.stages[stage.value] for stage in s.stage_path]
    parts += [t.spectra.get(sid, sid) for sid in s.spectra]
    for m in s.methods:
        parts.append(titles.get(m.method_id, m.method_id))
        parts.append(t.feedback[m.feedback.value if m.feedback else NO_FEEDBACK])
    if s.entered_crisis:
        parts.append(_bullet_free(t.summary.crisis))
    if s.significant:
        parts.append(_bullet_free(t.summary.significant))
    return " ".join(parts)


def _bullet_free(line: str) -> str:
    return line.removeprefix("-").strip()


def _aware(moment: datetime) -> datetime:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return moment


def _decay(age_seconds: float) -> float:
    return math.exp(-ALPHA * max(age_seconds, 0.0) / _SECONDS_PER_DAY / TAU_DAYS)


def recency(entry: LedgerEntry, now: datetime) -> float:
    """The recency term: ``exp(-ALPHA * age / TAU_DAYS)``, or 1 for a significant entry."""
    _aware(now)
    if entry.significant:
        return 1.0
    return _decay((now - entry.time).total_seconds())


class MemoryIndex:
    """A TF-IDF index over ledger entries; immutable once built, ranks many queries."""

    def __init__(
        self,
        entries: Iterable[LedgerEntry],
        *,
        text: MemoryText | None = None,
        method_titles: Mapping[str, str] | None = None,
    ) -> None:
        self.entries: tuple[LedgerEntry, ...] = tuple(entries)
        grams = [
            char_ngrams(searchable_text(e, text=text, method_titles=method_titles))
            for e in self.entries
        ]
        df: Counter[str] = Counter()
        for counts in grams:
            df.update(counts.keys())
        n = len(self.entries)
        self._unseen_idf = math.log(1 + n) + 1.0
        self._idf: dict[str, float] = {g: math.log((1 + n) / (1 + d)) + 1.0 for g, d in df.items()}
        postings: dict[str, list[tuple[int, float]]] = {}
        norms: list[float] = []
        for i, counts in enumerate(grams):
            squared = 0.0
            for gram, tf in counts.items():
                weight = tf * self._idf[gram]
                postings.setdefault(gram, []).append((i, weight))
                squared += weight * weight
            norms.append(math.sqrt(squared))
        self._postings = postings
        self._norms = norms
        self._times = [e.time.timestamp() for e in self.entries]
        self._significant = [e.significant for e in self.entries]

    def similarities(self, query: str) -> tuple[float, ...]:
        """Cosine similarity of ``query`` to each entry, in the order the entries came."""
        sims = [0.0] * len(self.entries)
        counts = char_ngrams(query)
        if not counts or not self.entries:
            return tuple(sims)
        dots = [0.0] * len(self.entries)
        squared = 0.0
        for gram, tf in counts.items():
            idf = self._idf.get(gram, self._unseen_idf)
            weight = tf * idf
            squared += weight * weight
            for i, doc_weight in self._postings.get(gram, ()):
                dots[i] += weight * doc_weight
        query_norm = math.sqrt(squared)
        for i, dot in enumerate(dots):
            if dot:
                sims[i] = dot / (query_norm * self._norms[i])
        return tuple(sims)

    def scores(self, query: str, now: datetime) -> tuple[float, ...]:
        """The 3D score of each entry against ``query`` at ``now``, in entry order."""
        current = _aware(now).timestamp()
        out = []
        for sim, moment, significant in zip(
            self.similarities(query), self._times, self._significant, strict=True
        ):
            if significant:
                out.append(W_REC + W_SIM * sim + W_SAL)
            else:
                out.append(W_REC * _decay(current - moment) + W_SIM * sim)
        return tuple(out)

    def rank(self, query: str, now: datetime, k: int = TOP_K) -> list[tuple[LedgerEntry, float]]:
        """The ``k`` best entries for ``query`` at ``now``, best first, with their scores."""
        if k < 0:
            raise ValueError("k cannot be negative")
        scores = self.scores(query, now)
        if k == 0:
            return []
        best = heapq.nsmallest(
            k,
            range(len(self.entries)),
            key=lambda i: (-scores[i], -self._times[i], self.entries[i].entry_id),
        )
        return [(self.entries[i], scores[i]) for i in best]


def rank(
    query: str,
    entries: Sequence[LedgerEntry],
    now: datetime,
    k: int = TOP_K,
    *,
    text: MemoryText | None = None,
    method_titles: Mapping[str, str] | None = None,
) -> list[tuple[LedgerEntry, float]]:
    """Build an index over ``entries`` and return the ``k`` best for ``query`` at ``now``."""
    return MemoryIndex(entries, text=text, method_titles=method_titles).rank(query, now, k)


__all__ = [
    "ALPHA",
    "NGRAM_SIZES",
    "TAU_DAYS",
    "TOP_K",
    "W_REC",
    "W_SAL",
    "W_SIM",
    "MemoryIndex",
    "char_ngrams",
    "rank",
    "recency",
    "searchable_text",
]
