"""The output gate: the last check before any text reaches the user.

:meth:`OutputGate.check` blocks text that

* names a diagnosis (any ``diagnosis_terms`` entry, casefolded; PRD §9.3);
* carries a phone-number-like digit run that is not one of ``allowed_numbers`` (the
  numbers of the current ResourceCard), so a stray or made-up number never leaks;
* names a Grade A method outside ``S_empower`` and card rendering (COLBO-02);
* still says 你应该 or 必须 in content the didactic filter applies to (WILLOW-01; crisis,
  referral and Grade C wording keep their safety phrasing, per ``willow.yaml``).

On a block it never raises: it returns a slot-free ``S_haven`` line and the reasons.

Phone-number-like: after NFKC folding, a maximal run of digits joined by at most single
spaces or hyphens, holding three or more digits. Clock times (``9:00``) and card titles
(``5-4-3-2-1 感官外感受着陆法``) are masked first; a run is allowed when its digits equal
the digits of an allowed number.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from olivia.core.language.data import ContentKind, LanguageData, slots_of
from olivia.core.models import HelpStage
from olivia.core.taxonomy import Taxonomy

MIN_PHONE_DIGITS: Final = 3
DIDACTIC_BANNED: Final = ("你应该", "必须")
_DIGIT_RUN_RE: Final = re.compile(r"\d(?:[ \-]?\d)*")
# Clock times such as 9:00 or 21:30 (NFKC folds the full-width colon to ":").
_CLOCK_RE: Final = re.compile(r"(?<!\d)\d{1,2}:\d{2}(?!\d)")
_MASK: Final = ""
_TITLE_STAGES: Final = frozenset({HelpStage.S_EMPOWER})
_TITLE_KINDS: Final = frozenset({ContentKind.CARD})


@dataclass(frozen=True)
class GateResult:
    ok: bool
    text: str
    """The checked text when ``ok``, otherwise the safe fallback line."""
    reasons: tuple[str, ...]
    """Empty when ``ok``; otherwise ``"<check>:<detail>"`` entries."""


def digits_of(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text)
    return "".join(str(unicodedata.decimal(ch)) for ch in folded if ch.isdecimal())


def phone_like_runs(text: str, masked_literals: Iterable[str] = ()) -> tuple[str, ...]:
    """Digit strings of every phone-number-like run in ``text`` (see module docstring)."""
    folded = unicodedata.normalize("NFKC", text)
    for literal in sorted(set(masked_literals), key=len, reverse=True):
        folded = folded.replace(unicodedata.normalize("NFKC", literal), _MASK)
    folded = _CLOCK_RE.sub(_MASK, folded)
    runs = (digits_of(m.group()) for m in _DIGIT_RUN_RE.finditer(folded))
    return tuple(run for run in runs if len(run) >= MIN_PHONE_DIGITS)


class OutputGate:
    def __init__(self, tax: Taxonomy, data: LanguageData) -> None:
        self._data = data
        self._grade_a_titles = tuple(
            sorted((tax.methods()[mid].name_zh for mid in tax.grade_a_ids()), key=len, reverse=True)
        )
        self._card_titles = tuple(card.title for card in data.cards.cards.values())
        fallback = next(t for t in data.templates.haven if not slots_of(t))
        self._fallback = fallback

    @property
    def fallback(self) -> str:
        return self._fallback

    def check(
        self,
        text: str,
        *,
        kind: ContentKind,
        stage: HelpStage,
        allowed_numbers: Iterable[str] = (),
    ) -> GateResult:
        reasons = self.reasons(text, kind=kind, stage=stage, allowed_numbers=allowed_numbers)
        if reasons:
            return GateResult(False, self._fallback, reasons)
        return GateResult(True, text, ())

    def reasons(
        self,
        text: str,
        *,
        kind: ContentKind,
        stage: HelpStage,
        allowed_numbers: Iterable[str] = (),
    ) -> tuple[str, ...]:
        """Every reason ``text`` would be blocked; empty when it passes."""
        willow = self._data.willow
        if not text.strip():
            return ("empty:",)
        found: list[str] = []
        folded = text.casefold()
        found += [f"diagnosis:{t}" for t in willow.diagnosis_terms if t in folded]
        allowed = {digits_of(n) for n in allowed_numbers}
        for run in phone_like_runs(text, self._card_titles):
            if run not in allowed:
                found.append(f"number:{run}")
        if kind not in _TITLE_KINDS and stage not in _TITLE_STAGES:
            found += [f"grade_a_title:{t}" for t in self._grade_a_titles if t in text]
        if not willow.exempt("didactic_rewrites", kind):
            found += [f"didactic:{w}" for w in DIDACTIC_BANNED if w in text]
        return tuple(dict.fromkeys(found))
