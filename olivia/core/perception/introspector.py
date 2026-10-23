"""The introspector: cognitive distortions, schemas and Satir yearnings (decision D4, C2).

PRD 特性三 / MIYI-03, SDD §3.2. Three parts, all rule-based and offline:

* :class:`Introspector` reads one message with the ``introspection`` lexicon of
  ``perception.yaml`` (:func:`load_introspection_lexicon`) and fills the
  ``PerceptionContext`` fields the rule stub leaves as placeholders, in both modes:
  ``detected_distortions`` (taxonomy ids in order of first appearance),
  ``detected_schemas`` (the same, at most :data:`MAX_SCHEMAS`) and ``deep_yearning``.
  The yearning is the one with the most phrase hits (ties: the earlier hit); with no
  yearning phrase, the ``schema_yearnings`` entry of the first schema; with neither, the
  context's own value (the stub's default, the first taxonomy yearning). The yearning
  feeds the WILLOW metaphor grid (spectrum x yearning) and the S_clarify need phrase
  through ``LanguageEngine.build_slots``.

  Matching folds the message like the rule stub (``normalize``, the perception window)
  and also strips punctuation and symbols, so a comma never splits a phrase. Within one
  section a hit inside a longer hit is dropped, and a hit directly preceded by a negation
  prefix is void (the rule stub's rule: exceptions such as 特别 do not negate, nor does
  the second half of 是不是 / 有没有 / 会不会, nor a negation after another negation).

* :class:`SchemaMirror` is the per-session schema mirror (D4): a gentle question that
  reflects the belief behind a schema the session has seen ("心里好像有个声音一直在说
  “我不够好”，是这样吗？"). The session asks it only in model mode, only in S_clarify,
  only below the somatic arousal line, at most once per session, and never on a crisis,
  haven, L1-screen or red-flag turn; rules mode never asks (ruling 25, widened by D4). The
  schema to mirror is the one seen on the most turns below the arousal line outside
  crisis (ties: the most recently seen). The next turn is read as the answer
  (:func:`read_mirror_answer`); a yes is the PRD C_2 "核心信念识别" and moves S_clarify to
  S_empower (``Reason.CLARIFY_CORE_BELIEF``). Only ids are kept, never text.

* :func:`shame_spiral` is the pure test behind the ``TOXIC_SHAME_SPIRAL``
  contraindication's perception source ("DEFECTIVENESS + 强烈自责"), for the solver hook.

The mirror lines live in ``language/schema_mirror.yaml`` (:func:`load_mirror_lines`),
draft pending G-0.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

import yaml

from olivia.core.models import PerceptionContext
from olivia.core.perception.lexicon import strip_marks
from olivia.core.safety.matcher import Match, PhraseMatcher
from olivia.core.safety.normalize import clip_for_perception, fold_words, normalize
from olivia.core.taxonomy import Taxonomy

MAX_SCHEMAS: Final = 3
"""``PerceptionContext.detected_schemas`` holds at most three ids (SDD §2.3)."""

SHAME_SCHEMA: Final = "DEFECTIVENESS"
SELF_BLAME_SCHEMAS: Final = frozenset({"PUNITIVENESS"})
SELF_BLAME_DISTORTIONS: Final = frozenset({"PERSONALIZATION"})
SELF_BLAME_EMOTIONS: Final = frozenset({"shame"})
"""Canonical ids only: the stub folds the self_criticism alias into shame."""

_LEXICON_FILE: Final = "perception.yaml"
_MIRROR_FILE: Final = "schema_mirror.yaml"
_SECTION: Final = "introspection"
_KEYS: Final = frozenset(
    {"distortions", "schemas", "yearnings", "schema_yearnings", "mirror_answers"}
)
_ANSWER_KEYS: Final = ("affirm_whole", "affirm_start", "decline_whole", "decline_start", "unsure")
_MIN_PHRASES: Final = 2
_MIN_START: Final = 2
_DISTORTION: Final = "distortions"
_SCHEMA: Final = "schemas"
_YEARNING: Final = "yearnings"
# (head, negation) pairs that form an A-not-A question rather than a denial (as the stub).
_A_NOT_A: Final = (("是", "不是"), ("有", "没有"), ("会", "不会"))
# Clause ends after fold_words (as safety/intent_check.py reads the D3 answer).
_CLAUSE_END: Final = re.compile(r"[,.!?;:。、~…\n\"“”]")
_FILLERS: Final = "啊呃额哦噢喔诶欸哎"
_PARTICLES: Final = "吧啦啊呀哦喔的呢嘛哈噢"


class IntrospectionLexiconError(Exception):
    """Raised when the introspection lexicon or the mirror lines are missing or invalid."""


@dataclass(frozen=True)
class MirrorAnswers:
    """Phrases for reading the answer to the mirror question (folded, marks kept)."""

    affirm_whole: frozenset[str]
    affirm_start: tuple[str, ...]
    decline_whole: frozenset[str]
    decline_start: tuple[str, ...]
    unsure: tuple[str, ...]


@dataclass(frozen=True)
class IntrospectionLexicon:
    distortions: Mapping[str, tuple[str, ...]]
    """Taxonomy distortion id -> phrases (folded, marks stripped), taxonomy order."""
    schemas: Mapping[str, tuple[str, ...]]
    yearnings: Mapping[str, tuple[str, ...]]
    schema_yearnings: Mapping[str, str]
    """Every schema id -> the yearning it points to."""
    answers: MirrorAnswers
    negation_prefixes: tuple[str, ...]
    negation_exceptions: tuple[str, ...]


@dataclass(frozen=True)
class Introspection:
    """What one message shows: taxonomy ids only."""

    distortions: tuple[str, ...] = ()
    schemas: tuple[str, ...] = ()
    yearning: str | None = None


def load_introspection_lexicon(
    tax: Taxonomy, directory: Path | None = None
) -> IntrospectionLexicon:
    """Load and validate the ``introspection`` section of ``perception.yaml``.

    Rejects unknown keys, ids the taxonomy does not define, an id with fewer than two
    phrases, a missing id, a phrase listed for two ids (across all three sections), a
    phrase lying inside another id's phrase of the same section, a schema whose yearning
    is unknown, and mirror answers that are both a yes and a no.
    """
    doc = _read(_base("lexicons", directory), _LEXICON_FILE)
    section = _mapping(doc.get(_SECTION), _SECTION)
    _only(section, _KEYS, _SECTION)
    owners: dict[str, str] = {}
    groups = {
        _DISTORTION: _ids(tax, section, _DISTORTION, "cognitive_distortions", owners),
        _SCHEMA: _ids(tax, section, _SCHEMA, "schemas", owners),
        _YEARNING: _ids(tax, section, _YEARNING, "satir_yearnings", owners),
    }
    for name, group in groups.items():
        _no_nesting(group, f"{_SECTION}.{name}")
    links = _mapping(section.get("schema_yearnings"), f"{_SECTION}.schema_yearnings")
    yearnings = set(tax.values("satir_yearnings"))
    schema_ids = tax.values("schemas")
    _only(links, set(schema_ids), f"{_SECTION}.schema_yearnings")
    mapped: dict[str, str] = {}
    for sid in schema_ids:
        target = links.get(sid)
        if not isinstance(target, str) or target not in yearnings:
            raise IntrospectionLexiconError(
                f"{_LEXICON_FILE}: schema_yearnings.{sid} must be a satir_yearnings id"
            )
        mapped[sid] = target
    negation = _mapping(doc.get("negation"), "negation")
    return IntrospectionLexicon(
        distortions=MappingProxyType(groups[_DISTORTION]),
        schemas=MappingProxyType(groups[_SCHEMA]),
        yearnings=MappingProxyType(groups[_YEARNING]),
        schema_yearnings=MappingProxyType(mapped),
        answers=_answers(section.get("mirror_answers")),
        negation_prefixes=tuple(
            normalize(p) for p in _strings(negation.get("prefixes"), "negation.prefixes")
        ),
        negation_exceptions=tuple(
            normalize(p) for p in _strings(negation.get("exceptions"), "negation.exceptions")
        ),
    )


def load_mirror_lines(
    tax: Taxonomy, directory: Path | None = None
) -> Mapping[str, tuple[str, ...]]:
    """Load ``language/schema_mirror.yaml``: every schema id -> its mirror questions.

    Each line is slot-free (no braces) and holds a question mark; the session runs it
    through WILLOW and the output gate when it is shown.
    """
    doc = _read(_base("language", directory), _MIRROR_FILE)
    _only(doc, {"version", "by_schema"}, _MIRROR_FILE)
    raw = _mapping(doc.get("by_schema"), "by_schema")
    schema_ids = tax.values("schemas")
    _only(raw, set(schema_ids), f"{_MIRROR_FILE} by_schema")
    lines: dict[str, tuple[str, ...]] = {}
    for sid in schema_ids:
        texts = _strings(raw.get(sid), f"by_schema.{sid}", file=_MIRROR_FILE)
        for text in texts:
            if "{" in text or "}" in text:
                raise IntrospectionLexiconError(f"{_MIRROR_FILE}: {sid}: no slots: {text!r}")
            if "？" not in text and "?" not in text:
                raise IntrospectionLexiconError(f"{_MIRROR_FILE}: {sid}: not a question: {text!r}")
        lines[sid] = texts
    return MappingProxyType(lines)


class Introspector:
    """Reads distortions, schemas and the yearning from one message; see the module doc."""

    def __init__(self, lexicon: IntrospectionLexicon) -> None:
        self._lexicon = lexicon
        tags: dict[str, tuple[str, str]] = {}
        for group, entries in (
            (_DISTORTION, lexicon.distortions),
            (_SCHEMA, lexicon.schemas),
            (_YEARNING, lexicon.yearnings),
        ):
            for label, phrases in entries.items():
                for phrase in phrases:
                    tags[phrase] = (group, label)
        self._tags = tags
        self._matcher = PhraseMatcher({phrase: phrase for phrase in tags})

    def read(self, text: str) -> Introspection:
        body = strip_marks(clip_for_perception(normalize(text)))
        grouped: dict[str, list[tuple[str, Match]]] = {}
        for match in self._matcher.find_all(body):
            group, label = self._tags[match.key]
            grouped.setdefault(group, []).append((label, match))
        kept: dict[str, list[tuple[str, Match]]] = {}
        for group, items in grouped.items():
            kept[group] = [
                (label, m) for label, m in _outermost(items) if not self._negated(body, m.start)
            ]
        distortions = _first_seen(kept.get(_DISTORTION, ()))
        schemas = _first_seen(kept.get(_SCHEMA, ()))[:MAX_SCHEMAS]
        return Introspection(distortions, schemas, self._yearning(kept.get(_YEARNING, ()), schemas))

    def apply(self, text: str, context: PerceptionContext) -> PerceptionContext:
        """``context`` with this message's distortions, schemas and yearning."""
        found = self.read(text)
        return replace(
            context,
            detected_distortions=found.distortions,
            detected_schemas=found.schemas,
            deep_yearning=found.yearning if found.yearning is not None else context.deep_yearning,
        )

    def _yearning(self, hits: Iterable[tuple[str, Match]], schemas: tuple[str, ...]) -> str | None:
        counts: Counter[str] = Counter()
        first: dict[str, int] = {}
        for label, match in hits:
            counts[label] += 1
            first.setdefault(label, match.start)
        if counts:
            return min(counts, key=lambda y: (-counts[y], first[y]))
        if schemas:
            return self._lexicon.schema_yearnings[schemas[0]]
        return None

    def _negated(self, text: str, start: int) -> bool:
        lex = self._lexicon
        if any(text.endswith(word, 0, start) for word in lex.negation_exceptions):
            return False
        for negation in lex.negation_prefixes:
            if not text.endswith(negation, 0, start):
                continue
            head = start - len(negation)
            if any(neg == negation and text.endswith(a, 0, head) for a, neg in _A_NOT_A):
                continue
            if any(text.endswith(other, 0, head) for other in lex.negation_prefixes):
                continue
            return True
        return False


def shame_spiral(context: PerceptionContext) -> bool:
    """``TOXIC_SHAME_SPIRAL`` from perception: DEFECTIVENESS with strong self-blame.

    Self-blame is a PUNITIVENESS schema, a PERSONALIZATION distortion ("都是我的错") or
    the shame emotion (self-criticism folds into it) on the same turn. Pure; the solver
    hook decides what the contraindication masks.
    """
    if SHAME_SCHEMA not in context.detected_schemas:
        return False
    return (
        not SELF_BLAME_SCHEMAS.isdisjoint(context.detected_schemas)
        or not SELF_BLAME_DISTORTIONS.isdisjoint(context.detected_distortions)
        or context.fine_grained_emotion in SELF_BLAME_EMOTIONS
    )


class MirrorAnswer(StrEnum):
    CONFIRMED = "confirmed"
    DECLINED = "declined"


class MirrorStatus(StrEnum):
    """``inspect["schema_mirror"]`` on the turn it asks or reads the answer."""

    ASKED = "asked"
    CONFIRMED = "confirmed"
    DECLINED = "declined"


def read_mirror_answer(answers: MirrorAnswers, text: str) -> MirrorAnswer | None:
    """Read one turn as the answer to the mirror question; None when it is unclear.

    The first clause that is more than fillers is read ("哦，是的" reads "是的").
    """
    clauses = (c.strip().lstrip(_FILLERS).strip() for c in _CLAUSE_END.split(fold_words(text)))
    clause = next((c for c in clauses if c), "")
    bare = clause.rstrip(_PARTICLES)
    if not bare:
        return None
    if bare in answers.decline_whole or bare.startswith(answers.decline_start):
        return MirrorAnswer.DECLINED
    if any(word in clause for word in answers.unsure):
        return None
    if any(word in clause for word in answers.decline_start):
        return None
    if bare in answers.affirm_whole or bare.startswith(answers.affirm_start):
        return MirrorAnswer.CONFIRMED
    return None


class SchemaMirror:
    """Session state for the schema mirror: evidence, the one question, its answer.

    ``enabled`` is model mode. The session calls :meth:`answer` before the state machine
    runs, :meth:`observe` once per turn, :meth:`choose` when an S_clarify reply could
    carry the question and :meth:`mark_asked` when it was shown.
    """

    def __init__(
        self,
        answers: MirrorAnswers,
        lines: Mapping[str, tuple[str, ...]],
        *,
        enabled: bool,
    ) -> None:
        self._answers = answers
        self._lines = lines
        self.enabled = enabled
        self._seen: Counter[str] = Counter()
        self._last_seen: dict[str, int] = {}
        self._turn = 0
        self._asked = False
        self._waiting = False
        self.status: MirrorStatus | None = None
        """The status after the question was asked: asked, confirmed or declined."""

    def answer(self, text: str, *, readable: bool) -> MirrorAnswer | None:
        """Read this turn as the answer when the question was asked on the turn before.

        ``readable`` is False on a turn that must not be read (crisis, an L1 screen, high
        arousal, the D3 question, or the session left S_clarify): the question then
        lapses unanswered. The question waits for exactly one turn.
        """
        waiting, self._waiting = self._waiting, False
        if not waiting or not readable:
            return None
        found = read_mirror_answer(self._answers, text)
        if found is not None:
            self.status = MirrorStatus(found.value)
        return found

    def observe(self, schemas: Iterable[str], *, counts: bool) -> None:
        """Count this turn's schemas as evidence when ``counts`` (calm, no crisis)."""
        self._turn += 1
        if not counts:
            return
        for sid in schemas:
            self._seen[sid] += 1
            self._last_seen[sid] = self._turn

    def choose(self) -> str | None:
        """The schema to mirror now, or None (disabled, already asked, no evidence)."""
        if not self.enabled or self._asked or not self._seen:
            return None
        return min(self._seen, key=lambda s: (-self._seen[s], -self._last_seen[s]))

    def lines(self, schema: str) -> tuple[str, ...]:
        return self._lines[schema]

    def mark_asked(self) -> None:
        self._asked = True
        self._waiting = True
        self.status = MirrorStatus.ASKED


# -- loading helpers --------------------------------------------------------------------------


def _base(folder: str, directory: Path | None) -> Traversable | Path:
    if directory is not None:
        return directory
    return resources.files("olivia").joinpath(f"data/{folder}")


def _read(base: Traversable | Path, name: str) -> Mapping[str, Any]:
    try:
        text = base.joinpath(name).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise IntrospectionLexiconError(f"{name}: cannot read file: {exc}") from exc
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise IntrospectionLexiconError(f"{name}: invalid YAML: {exc}") from exc
    if not isinstance(doc, dict):
        raise IntrospectionLexiconError(f"{name}: top level must be a mapping")
    return doc


def _mapping(node: Any, where: str) -> Mapping[Any, Any]:
    if not isinstance(node, dict) or not node:
        raise IntrospectionLexiconError(f"'{where}' must be a non-empty mapping")
    return node


def _only(node: Mapping[Any, Any], keys: Iterable[str], where: str) -> None:
    extra = sorted(str(key) for key in node if key not in set(keys))
    if extra:
        raise IntrospectionLexiconError(f"{where}: unknown keys {extra}")


def _strings(node: Any, where: str, *, file: str = _LEXICON_FILE) -> tuple[str, ...]:
    if not isinstance(node, list) or not node:
        raise IntrospectionLexiconError(f"{file}: '{where}' must be a non-empty list")
    out: list[str] = []
    for raw in node:
        if not isinstance(raw, str) or not raw.strip():
            raise IntrospectionLexiconError(f"{file}: {where}: {raw!r} is not a phrase")
        if raw in out:
            raise IntrospectionLexiconError(f"{file}: {where}: {raw!r} is repeated")
        out.append(raw)
    return tuple(out)


def _ids(
    tax: Taxonomy, section: Mapping[Any, Any], key: str, axis: str, owners: dict[str, str]
) -> dict[str, tuple[str, ...]]:
    """Every taxonomy id of ``axis`` -> folded, mark-free phrases, in taxonomy order."""
    where = f"{_SECTION}.{key}"
    node = _mapping(section.get(key), where)
    known = tax.values(axis)
    _only(node, set(known), where)
    missing = [i for i in known if i not in node]
    if missing:
        raise IntrospectionLexiconError(f"{_LEXICON_FILE}: {where} has no entry for {missing}")
    out: dict[str, tuple[str, ...]] = {}
    for label in known:
        phrases: list[str] = []
        for raw in _strings(node[label], f"{where}.{label}"):
            phrase = strip_marks(normalize(raw))
            if not phrase:
                raise IntrospectionLexiconError(
                    f"{_LEXICON_FILE}: {where}.{label}: {raw!r} is empty"
                )
            owner = owners.setdefault(phrase, label)
            if owner != label or phrase in phrases:
                raise IntrospectionLexiconError(
                    f"{_LEXICON_FILE}: phrase {phrase!r} is listed for both {owner} and {label}"
                )
            phrases.append(phrase)
        if len(phrases) < _MIN_PHRASES:
            raise IntrospectionLexiconError(
                f"{_LEXICON_FILE}: {where}.{label} needs at least {_MIN_PHRASES} phrases"
            )
        out[label] = tuple(phrases)
    return out


def _no_nesting(group: Mapping[str, tuple[str, ...]], where: str) -> None:
    """Reject a phrase inside another id's phrase: the longer hit would hide it."""
    pairs = [(phrase, label) for label, phrases in group.items() for phrase in phrases]
    for inner, inner_label in pairs:
        for outer, outer_label in pairs:
            if inner_label != outer_label and inner in outer:
                raise IntrospectionLexiconError(
                    f"{_LEXICON_FILE}: {where}: {inner!r} ({inner_label}) lies inside "
                    f"{outer!r} ({outer_label})"
                )


def _answers(node: Any) -> MirrorAnswers:
    where = f"{_SECTION}.mirror_answers"
    section = _mapping(node, where)
    _only(section, _ANSWER_KEYS, where)
    lists = {
        key: tuple(fold_words(p) for p in _strings(section.get(key), f"{where}.{key}"))
        for key in _ANSWER_KEYS
    }
    for key in ("affirm_start", "decline_start"):
        short = [p for p in lists[key] if len(p) < _MIN_START]
        if short:
            raise IntrospectionLexiconError(f"{_LEXICON_FILE}: {where}.{key}: too short {short}")
    yes = set(lists["affirm_whole"]) | set(lists["affirm_start"])
    no = set(lists["decline_whole"]) | set(lists["decline_start"]) | set(lists["unsure"])
    both = sorted(yes & no)
    if both:
        raise IntrospectionLexiconError(f"{_LEXICON_FILE}: {where}: both a yes and a no: {both}")
    return MirrorAnswers(
        affirm_whole=frozenset(lists["affirm_whole"]),
        affirm_start=lists["affirm_start"],
        decline_whole=frozenset(lists["decline_whole"]),
        decline_start=lists["decline_start"],
        unsure=lists["unsure"],
    )


def _outermost(items: list[tuple[str, Match]]) -> list[tuple[str, Match]]:
    """Drop every hit that lies fully inside another hit of the same section."""
    ordered = sorted(items, key=lambda item: (item[1].start, -item[1].end))
    kept: list[tuple[str, Match]] = []
    furthest = -1
    for label, match in ordered:
        if match.end > furthest:
            kept.append((label, match))
            furthest = match.end
    return kept


def _first_seen(hits: Iterable[tuple[str, Match]]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(label for label, _ in sorted(hits, key=lambda h: h[1].start)))
