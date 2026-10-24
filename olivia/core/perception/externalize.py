"""Narrative externalization: naming the inner critic (PRD 特性四, step C3).

White & Epston's externalizing move ("那个追求完美的严苛督察员") separates the person from
the problem by giving the problem a name. OLIVIA offers it once per session, as a gentle
question with two or three ready-made names, and only where the schema mirror could be
asked (decision D4): model mode, S_clarify, below the somatic arousal line, never on a
crisis, haven, L1-screen, red-flag, listening-lock or D3 turn, never for SILENT_ANCHOR, and
never on the mirror's own turn or the turn that reads its answer (the mirror comes first).

* The pattern: an "inner critic" schema (:data:`CRITIC_SCHEMAS`) on one calm turn, or a
  critic distortion (:data:`CRITIC_DISTORTIONS`) on at least :data:`DISTORTION_TURNS`
  calm turns, counted over the session like the mirror's evidence.
* The answer, read on the next turn only (:func:`read_naming_answer`): a number or one of
  the offered names accepts that name; a clear no (the mirror's and the rule stub's
  answer words, plus this file's ``declines``) declines; anything else, a plain yes or a
  mixed reply included, is no answer and the turn goes on as an ordinary message.
* After a yes the reply acknowledges the name, and later replies may call the pattern by
  it when the pattern shows up again (:meth:`Externalizer.callback_due`), at most once
  every :data:`NAMING_GAP` turns.

Names are template names (``language/externalize.yaml``), never user text, so the session
keeps only their ids. Session-only: nothing is carried to the next session.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

import yaml

from olivia.core.language.engine import count_all
from olivia.core.perception.introspector import MirrorAnswer, MirrorAnswers, read_mirror_answer
from olivia.core.safety.normalize import fold_words
from olivia.core.taxonomy import Taxonomy
from olivia.core.yaml_load import safe_load

CRITIC_SCHEMAS: Final = frozenset(
    {"DEFECTIVENESS", "PUNITIVENESS", "UNRELENTING_STANDARDS", "FAILURE"}
)
CRITIC_DISTORTIONS: Final = frozenset({"SHOULD_STATEMENTS", "ALL_OR_NOTHING"})
DISTORTION_TURNS: Final = 2
"""Calm turns a critic distortion needs before it counts as the pattern."""
NAMING_GAP: Final = 3
"""Turns between two replies that use the accepted name (the acknowledgement included)."""
NAME_SLOT: Final = "{name}"
LINE_MAX: Final = 80
"""Every line is one paragraph (WILLOW-03)."""

_FILE: Final = "externalize.yaml"
_KEYS: Final = frozenset(
    {"version", "names", "offers", "declines", "accepted", "declined", "callbacks"}
)
_MIN_MATCH: Final = 2
_MIN_NAMES: Final = 2
_MAX_NAMES: Final = 3
_ID_RE: Final = re.compile(r"[A-Z][A-Z_]*")
_SLOT_RE: Final = re.compile(r"\{[^{}]*\}")
_CLAUSE_END: Final = re.compile(r"[,.!?;:。、~…\n\"“”]")
_FILLERS: Final = "啊呃额哦噢喔诶欸哎嗯"
_PARTICLES: Final = "吧啦啊呀哦喔的呢嘛哈噢"
_NEGATIONS: Final = ("不", "别", "没")
_NEGATION_REACH: Final = 4
_NUMERALS: Final = {"一": 1, "二": 2, "两": 2, "三": 3}
# The whole first clause is a pick by number: "2", "第二个", "选1", "就叫第三个吧".
_PICK_RE: Final = re.compile(
    r"(?:我)?(?:就)?(?:选|要|用|叫)?(?:它)?(?:第)?([1-9]|[一二两三])(?:个|号)?(?:就好|好了|吧)?"
)


class ExternalizeTextError(Exception):
    """Raised when ``language/externalize.yaml`` is missing or invalid."""


class ExternalizeStatus(StrEnum):
    """``inspect["externalize"]`` on the turn the offer is shown or its answer read."""

    OFFERED = "offered"
    ACCEPTED = "accepted"
    DECLINED = "declined"


@dataclass(frozen=True)
class Offer:
    names: tuple[str, ...]
    """The name ids this question offers, in its order (1, 2, 3)."""
    line: str


@dataclass(frozen=True)
class ExternalizeText:
    names: Mapping[str, str]
    """Name id -> the name as shown."""
    matches: Mapping[str, tuple[str, ...]]
    """Name id -> folded phrases that pick it in an answer."""
    offers: tuple[Offer, ...]
    declines: tuple[str, ...]
    accepted: tuple[str, ...]
    declined: tuple[str, ...]
    callbacks: tuple[str, ...]

    def fill(self, line: str, name_id: str) -> str:
        return line.replace(NAME_SLOT, self.names[name_id])


@dataclass(frozen=True)
class NamingAnswer:
    status: ExternalizeStatus
    """ACCEPTED or DECLINED."""
    name: str | None = None
    """The accepted name id."""


def load_externalize_text(tax: Taxonomy, directory: Path | None = None) -> ExternalizeText:
    """Load and validate ``language/externalize.yaml`` (see the file's header).

    Rejects unknown keys, a name id that is not an upper-case id, fewer than two match
    phrases, a match phrase shared by or lying inside another name's phrase, an offer
    with other than two or three known names or without "1「name」"... in order or without
    a question mark, slots other than ``{name}`` (and any slot in offers and declined
    lines), and any line over :data:`LINE_MAX` characters (with the longest name).
    ``tax`` is accepted for symmetry with the other loaders; the trigger ids are checked
    against it.
    """
    for sid in CRITIC_SCHEMAS:
        if sid not in tax.values("schemas"):
            raise ExternalizeTextError(f"unknown schema id {sid}")
    for did in CRITIC_DISTORTIONS:
        if did not in tax.values("cognitive_distortions"):
            raise ExternalizeTextError(f"unknown distortion id {did}")
    doc = _read(directory)
    extra = sorted(str(k) for k in doc if k not in _KEYS)
    if extra:
        raise ExternalizeTextError(f"{_FILE}: unknown keys {extra}")
    names, matches = _names(doc.get("names"))
    longest = max(names.values(), key=len)
    offers = _offers(doc.get("offers"), names)
    accepted = _lines(doc.get("accepted"), "accepted", slot=True, longest=longest)
    declined = _lines(doc.get("declined"), "declined", slot=False, longest=longest)
    callbacks = _lines(doc.get("callbacks"), "callbacks", slot=True, longest=longest)
    declines = tuple(fold_words(p) for p in _strings(doc.get("declines"), "declines"))
    if any(len(p) < _MIN_MATCH for p in declines):
        raise ExternalizeTextError(f"{_FILE}: declines: phrases need two characters")
    return ExternalizeText(
        names=MappingProxyType(names),
        matches=MappingProxyType(matches),
        offers=offers,
        declines=declines,
        accepted=accepted,
        declined=declined,
        callbacks=callbacks,
    )


def critic_pattern(schemas: Iterable[str], distortions: Iterable[str]) -> bool:
    """This turn shows an inner-critic schema or distortion."""
    return not CRITIC_SCHEMAS.isdisjoint(schemas) or not CRITIC_DISTORTIONS.isdisjoint(distortions)


def read_naming_answer(
    answers: MirrorAnswers,
    text: ExternalizeText,
    offered: Sequence[str],
    message: str,
    *,
    stub_declined: bool = False,
) -> NamingAnswer | None:
    """Read one turn as the answer to the naming question; None when it is unclear.

    ``offered`` is the offered name ids in order. A pick is a number in range as the
    whole first clause ("2", "第二个吧") or an offered name anywhere in the message; a name
    right after a negation in its clause ("不喜欢挑刺先生") makes the reply unclear. A no
    is the mirror's no (:func:`read_mirror_answer`), the rule stub's whole-message no
    (``stub_declined``) or a ``declines`` phrase opening the first clause. Exactly one
    pick and no no accepts; a no and no pick declines; anything else is unclear.
    """
    folded = fold_words(message)
    clause = _first_clause(folded)
    bare = clause.rstrip(_PARTICLES)
    picks, negated = _named(text, offered, folded)
    if negated:
        return None
    found = _PICK_RE.fullmatch(bare) if bare else None
    if found is not None:
        raw = found.group(1)
        number = _NUMERALS.get(raw) or int(raw)
        if 1 <= number <= len(offered):
            picks.add(offered[number - 1])
    declined = (
        stub_declined
        or read_mirror_answer(answers, message) is MirrorAnswer.DECLINED
        or (bool(bare) and bare.startswith(text.declines))
    )
    if declined:
        return NamingAnswer(ExternalizeStatus.DECLINED) if not picks else None
    if len(picks) == 1:
        (name,) = picks
        return NamingAnswer(ExternalizeStatus.ACCEPTED, name)
    return None


class Externalizer:
    """Session state for externalization: evidence, the one offer, its answer, the name.

    ``enabled`` is model mode. The session calls :meth:`answer` before the state machine
    runs, :meth:`observe` once per turn, :meth:`due` when an S_clarify reply could carry
    the offer and :meth:`mark_offered` when it was shown; :meth:`callback_due` and
    :meth:`mark_named` pace the replies that use the accepted name.
    """

    def __init__(self, text: ExternalizeText, answers: MirrorAnswers, *, enabled: bool) -> None:
        self.text = text
        self._answers = answers
        self.enabled = enabled
        self._schemas = False
        self._distortions: Counter[str] = Counter()
        self._turn = 0
        self._offered: tuple[str, ...] | None = None
        self._waiting = False
        self._last_named: int | None = None
        self.status: ExternalizeStatus | None = None
        """None, then offered, then accepted or declined."""
        self.name: str | None = None
        """The accepted name id."""

    def answer(
        self, message: str, *, readable: bool, stub_declined: bool = False
    ) -> NamingAnswer | None:
        """Read this turn as the answer when the offer was shown on the turn before.

        ``readable`` is False on a turn that must not be read (as for the mirror); the
        offer then lapses unanswered. The offer waits for exactly one turn.
        """
        waiting, self._waiting = self._waiting, False
        if not waiting or not readable or self._offered is None:
            return None
        found = read_naming_answer(
            self._answers, self.text, self._offered, message, stub_declined=stub_declined
        )
        if found is not None:
            self.status = found.status
            self.name = found.name
        return found

    def observe(self, schemas: Iterable[str], distortions: Iterable[str], *, counts: bool) -> None:
        """Count this turn's critic schemas and distortions when ``counts`` (calm)."""
        self._turn += 1
        if not counts:
            return
        if not CRITIC_SCHEMAS.isdisjoint(schemas):
            self._schemas = True
        for did in set(distortions) & CRITIC_DISTORTIONS:
            self._distortions[did] += 1

    def due(self) -> bool:
        """The offer may be shown now: enabled, never offered, and the pattern was seen."""
        if not self.enabled or self.status is not None:
            return False
        return self._schemas or any(n >= DISTORTION_TURNS for n in self._distortions.values())

    def mark_offered(self, offer: Offer) -> None:
        self._offered = offer.names
        self._waiting = True
        self.status = ExternalizeStatus.OFFERED

    def callback_due(self, schemas: Iterable[str], distortions: Iterable[str]) -> bool:
        """A name was accepted, the pattern shows up this turn and the gap has passed."""
        if self.name is None or not critic_pattern(schemas, distortions):
            return False
        return self._last_named is None or self._turn - self._last_named >= NAMING_GAP

    def mark_named(self) -> None:
        self._last_named = self._turn


# -- loading helpers --------------------------------------------------------------------------


def _read(directory: Path | None) -> Mapping[str, Any]:
    base: Traversable | Path = (
        directory if directory is not None else resources.files("olivia").joinpath("data/language")
    )
    try:
        raw = base.joinpath(_FILE).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ExternalizeTextError(f"{_FILE}: cannot read file: {exc}") from exc
    try:
        doc = safe_load(raw)
    except yaml.YAMLError as exc:
        raise ExternalizeTextError(f"{_FILE}: invalid YAML: {exc}") from exc
    if not isinstance(doc, dict):
        raise ExternalizeTextError(f"{_FILE}: top level must be a mapping")
    return doc


def _strings(node: Any, where: str) -> tuple[str, ...]:
    if not isinstance(node, list) or not node:
        raise ExternalizeTextError(f"{_FILE}: '{where}' must be a non-empty list")
    out: list[str] = []
    for raw in node:
        if not isinstance(raw, str) or not raw.strip():
            raise ExternalizeTextError(f"{_FILE}: {where}: {raw!r} is not a phrase")
        if raw in out:
            raise ExternalizeTextError(f"{_FILE}: {where}: {raw!r} is repeated")
        out.append(raw)
    return tuple(out)


def _names(node: Any) -> tuple[dict[str, str], dict[str, tuple[str, ...]]]:
    if not isinstance(node, dict) or len(node) < _MIN_NAMES:
        raise ExternalizeTextError(f"{_FILE}: 'names' needs at least {_MIN_NAMES} entries")
    names: dict[str, str] = {}
    matches: dict[str, tuple[str, ...]] = {}
    for nid, entry in node.items():
        if not isinstance(nid, str) or not _ID_RE.fullmatch(nid):
            raise ExternalizeTextError(f"{_FILE}: names: {nid!r} is not an upper-case id")
        if not isinstance(entry, dict) or set(entry) != {"text", "match"}:
            raise ExternalizeTextError(f"{_FILE}: names.{nid} needs exactly text and match")
        shown = entry["text"]
        if not isinstance(shown, str) or not shown.strip() or _SLOT_RE.search(shown):
            raise ExternalizeTextError(f"{_FILE}: names.{nid}.text is not a name")
        phrases = tuple(fold_words(p) for p in _strings(entry["match"], f"names.{nid}.match"))
        if len(phrases) < _MIN_MATCH:
            raise ExternalizeTextError(f"{_FILE}: names.{nid}.match needs {_MIN_MATCH} phrases")
        if fold_words(shown) not in phrases:
            raise ExternalizeTextError(f"{_FILE}: names.{nid}.match must include the name")
        names[nid] = shown
        matches[nid] = phrases
    for nid, phrases in matches.items():
        for other, theirs in matches.items():
            if other == nid:
                continue
            for phrase in phrases:
                if any(phrase in outer for outer in theirs):
                    raise ExternalizeTextError(
                        f"{_FILE}: match {phrase!r} ({nid}) lies inside a phrase of {other}"
                    )
    return names, matches


def _offers(node: Any, names: Mapping[str, str]) -> tuple[Offer, ...]:
    if not isinstance(node, list) or not node:
        raise ExternalizeTextError(f"{_FILE}: 'offers' must be a non-empty list")
    out: list[Offer] = []
    for index, entry in enumerate(node):
        where = f"offers[{index}]"
        if not isinstance(entry, dict) or set(entry) != {"names", "line"}:
            raise ExternalizeTextError(f"{_FILE}: {where} needs exactly names and line")
        ids = _strings(entry["names"], f"{where}.names")
        if not _MIN_NAMES <= len(ids) <= _MAX_NAMES:
            raise ExternalizeTextError(f"{_FILE}: {where} offers 2 or 3 names")
        unknown = [i for i in ids if i not in names]
        if unknown:
            raise ExternalizeTextError(f"{_FILE}: {where}: unknown names {unknown}")
        line = entry["line"]
        if not isinstance(line, str) or _SLOT_RE.search(line):
            raise ExternalizeTextError(f"{_FILE}: {where}: the line takes no slots")
        if "？" not in line and "?" not in line:
            raise ExternalizeTextError(f"{_FILE}: {where}: not a question")
        position = -1
        for number, nid in enumerate(ids, start=1):
            found = line.find(f"{number}「{names[nid]}」")
            if found <= position:
                raise ExternalizeTextError(
                    f"{_FILE}: {where}: needs {number}「{names[nid]}」 after the names before it"
                )
            position = found
        masked = line
        for number, nid in enumerate(ids, start=1):
            masked = masked.replace(f"{number}「{names[nid]}」", "")
        if any(ch.isdigit() for ch in masked):
            raise ExternalizeTextError(f"{_FILE}: {where}: digits only before the names")
        _fits(line, where)
        out.append(Offer(ids, line))
    return tuple(out)


def _lines(node: Any, where: str, *, slot: bool, longest: str) -> tuple[str, ...]:
    lines = _strings(node, where)
    for line in lines:
        slots = _SLOT_RE.findall(line)
        if slot and slots != [NAME_SLOT]:
            raise ExternalizeTextError(f"{_FILE}: {where}: {line!r} needs {NAME_SLOT} once")
        if not slot and slots:
            raise ExternalizeTextError(f"{_FILE}: {where}: {line!r} takes no slots")
        _fits(line.replace(NAME_SLOT, longest), where)
    return lines


def _fits(line: str, where: str) -> None:
    if "\n" in line or count_all(line) > LINE_MAX:
        raise ExternalizeTextError(f"{_FILE}: {where}: one paragraph of at most {LINE_MAX}")


def _named(text: ExternalizeText, offered: Sequence[str], folded: str) -> tuple[set[str], bool]:
    """Offered names in the message, and whether one follows a negation in its clause
    ("不喜欢挑刺先生")."""
    picks: set[str] = set()
    negated = False
    for clause in _CLAUSE_END.split(folded):
        for nid in offered:
            for phrase in text.matches[nid]:
                start = clause.find(phrase)
                while start != -1:
                    if any(
                        w in clause[max(0, start - _NEGATION_REACH) : start] for w in _NEGATIONS
                    ):
                        negated = True
                    else:
                        picks.add(nid)
                    start = clause.find(phrase, start + 1)
    return picks, negated


def _first_clause(folded: str) -> str:
    """The first clause that is more than fillers (as the mirror answer reads it)."""
    clauses = (c.strip().lstrip(_FILLERS).strip() for c in _CLAUSE_END.split(folded))
    return next((c for c in clauses if c), "")
