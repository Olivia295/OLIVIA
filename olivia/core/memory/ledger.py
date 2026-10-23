"""The transparent memory ledger (decision D1, step B2; SDD §3.3, §6.5).

The ledger holds three kinds of entry, and nothing else the user says:

* a **session summary**, built from ids only: start and end time, the stage path, the
  dominant distress-spectrum ids, the exercise cards shown with the feedback each got,
  whether the session entered a crisis (flag and level only), the 0-10 self-ratings
  (filled in by B6) and a significance flag (ruling 29: a turn at L2 or above, or the
  user marked it);
* a **note**: text the user explicitly asked to have remembered (``notes.py``), kept
  verbatim;
* a **journal** record (step B6): when the weekly journal was offered, whether it was
  shown and whether the user found it helpful (yes / no / skipped). No text.

Every entry is a small Markdown document with YAML front-matter; the front-matter is the
record and the body is a short templated summary in Chinese generated from it (for a
note, the body is the note itself)::

    ---
    olivia_ledger: 1
    id: 3f9c0e5d2b7a41c8a9e6d012
    kind: summary
    started_at: '2026-10-22T23:31:00+08:00'
    ...
    ---
    ## 2026-10-22 的一次聊天
    - 经过：开始 → 倾听 → 小练习 → 收尾

**Always encrypted**, whatever the at-rest switch says: each entry is its own file
``<data dir>/ledger/<id>.olv``, sealed with the ``ledger`` data key and the label
``e_<id>``, so an entry renamed or moved onto another id no longer opens. One file per
entry (rather than one sealed file for the whole ledger) keeps an append to one small
write: there is no read-modify-write of the history, so a crash or a bad write can only
ever touch the entry being written, never the ones before it. Each write goes through
``storage.atomic_write_bytes`` (temp file, fsync, rename), without snapshots: an entry
is written once (a summary may be rewritten in place by the same key), and older
plaintext never exists to fall back to. Summaries are keyed by session (and segment), so
writing the same session twice replaces its entry instead of adding one.

Without a usable keychain the ledger is disabled: nothing is written, and operations
raise :class:`LedgerUnavailableError`. :meth:`Ledger.shred` crypto-shreds the ``ledger``
data key (``Vault.shred``) and deletes the entry files.

Entries that fail to decrypt or parse are skipped (``Ledger.skipped`` counts them);
nothing here logs, and errors never carry entry text.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import yaml

from olivia.core.crypto.errors import (
    CryptoError,
    DecryptionError,
    KeychainUnavailableError,
    KeyMissingError,
    NoKeychainError,
)
from olivia.core.crypto.vault import Vault
from olivia.core.memory.text import NO_FEEDBACK, MemoryText, load_memory_text
from olivia.core.methods.bandit import Feedback
from olivia.core.models import CrisisLevel, HelpStage
from olivia.core.storage import app_data_dir, atomic_write_bytes, remove_file

LEDGER_STORE: Final = "ledger"
LEDGER_DIRNAME: Final = "ledger"
FORMAT_VERSION: Final = 1
NOTE_MAX_CHARS: Final = 500
SELF_RATING_RANGE: Final = range(0, 11)

_SUFFIX: Final = ".olv"
_ID: Final = re.compile(r"[0-9a-f]{24}")
_NOTICE_FILE: Final = ".memory-unavailable-told"
_DELIMITER: Final = "---\n"
_SUMMARY_KEYS: Final = frozenset(
    {
        "olivia_ledger",
        "id",
        "kind",
        "started_at",
        "ended_at",
        "stage_path",
        "spectra",
        "methods",
        "crisis",
        "self_rating",
        "significant",
        "marked_by_user",
    }
)
_NOTE_KEYS: Final = frozenset({"olivia_ledger", "id", "kind", "created_at", "significant"})
_JOURNAL_KEYS: Final = frozenset({"olivia_ledger", "id", "kind", "offered_at", "shown", "helpful"})


class LedgerUnavailableError(Exception):
    """The keychain cannot be used, so the ledger can neither be read nor written now.

    Nothing was changed. ``permanent`` is True when this device has no usable keychain.
    """

    def __init__(self, message: str, *, permanent: bool) -> None:
        super().__init__(message)
        self.permanent = permanent


def _aware(moment: datetime, what: str) -> datetime:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError(f"{what} must be timezone-aware")
    return moment


@dataclass(frozen=True)
class MethodRecord:
    """An exercise card shown in the session and the feedback it got (None: none)."""

    method_id: str
    feedback: Feedback | None = None


@dataclass(frozen=True)
class SessionSummary:
    """The templated summary of one session: ids, levels and times only (D1)."""

    started_at: datetime
    ended_at: datetime
    stage_path: tuple[HelpStage, ...]
    """Stages in the order visited, repeats collapsed (S_ready -> ... -> S_closing)."""
    spectra: tuple[str, ...]
    """Dominant distress-spectrum ids, most frequent first."""
    methods: tuple[MethodRecord, ...]
    crisis_level: CrisisLevel | None = None
    """The highest level while in the crisis flow; None when it never entered it."""
    self_rating_before: int | None = None
    self_rating_after: int | None = None
    marked_by_user: bool = False

    def __post_init__(self) -> None:
        _aware(self.started_at, "started_at")
        _aware(self.ended_at, "ended_at")
        if self.ended_at < self.started_at:
            raise ValueError("a session cannot end before it starts")
        if not self.stage_path:
            raise ValueError("a session visits at least one stage")
        if self.crisis_level is not None and self.crisis_level < CrisisLevel.L1:
            raise ValueError("a crisis level is L1 or above")
        for rating in (self.self_rating_before, self.self_rating_after):
            if rating is not None and rating not in SELF_RATING_RANGE:
                raise ValueError("self-ratings are 0-10")

    @property
    def entered_crisis(self) -> bool:
        return self.crisis_level is not None

    @property
    def significant(self) -> bool:
        """Ruling 29: a turn at L2 or above, or the user marked it."""
        reached = self.crisis_level is not None and self.crisis_level >= CrisisLevel.L2
        return reached or self.marked_by_user


@dataclass(frozen=True)
class SummaryEntry:
    entry_id: str
    summary: SessionSummary

    @property
    def time(self) -> datetime:
        return self.summary.started_at

    @property
    def significant(self) -> bool:
        return self.summary.significant


@dataclass(frozen=True)
class NoteEntry:
    entry_id: str
    text: str
    created_at: datetime
    significant: bool = field(default=True, init=False)
    """A note is always significant: the user asked for it to be remembered."""

    @property
    def time(self) -> datetime:
        return self.created_at


@dataclass(frozen=True)
class JournalEntry:
    """The weekly journal (B6): offered at ``offered_at`` (at a chat opening or by
    ``olivia journal``), ``shown`` or declined, and the user's answer to "was it
    helpful" (None: not asked or skipped). Holds no text."""

    entry_id: str
    offered_at: datetime
    shown: bool
    helpful: bool | None = None
    significant: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        _aware(self.offered_at, "offered_at")
        if self.helpful is not None and not self.shown:
            raise ValueError("only a journal that was shown can be rated")

    @property
    def time(self) -> datetime:
        return self.offered_at


LedgerEntry = SummaryEntry | NoteEntry | JournalEntry


def summary_id(key: str) -> str:
    """The entry id for a summary key: stable, so rewriting a session replaces its entry."""
    return hashlib.sha256(f"olivia-ledger-summary:{key}".encode()).hexdigest()[:24]


class Ledger:
    """The encrypted ledger under ``<base_dir>/ledger`` (``base_dir`` defaults to the
    app data directory); ``vault`` holds the keys and should be the profile store's, so
    one process uses one vault.

    ``method_titles`` maps action ids to the card titles the user saw, for the body.
    """

    def __init__(
        self,
        base_dir: Path | None = None,
        vault: Vault | None = None,
        *,
        text: MemoryText | None = None,
        method_titles: Mapping[str, str] | None = None,
    ) -> None:
        base = app_data_dir() if base_dir is None else base_dir
        self.directory: Path = base / LEDGER_DIRNAME
        self.vault: Vault = Vault(base) if vault is None else vault
        self.text: MemoryText = load_memory_text() if text is None else text
        self._titles: Mapping[str, str] = {} if method_titles is None else method_titles
        self.skipped = 0
        """Entries the last :meth:`entries` call could not open or parse."""

    # -- state -----------------------------------------------------------------------------

    def available(self) -> bool:
        """Whether the keychain answers now, so the ledger can be read and written."""
        return self.vault.available()

    def take_unavailable_notice(self) -> bool:
        """True exactly once per device: the "memory isn't available here" notice is due.

        The marker file holds no user data.
        """
        marker = self.directory / _NOTICE_FILE
        if marker.exists():
            return False
        self._ensure_directory()
        atomic_write_bytes(marker, b"", snapshot=False)
        return True

    # -- writing ---------------------------------------------------------------------------

    def append_summary(self, summary: SessionSummary, *, key: str) -> str:
        """Write ``summary``; the same ``key`` (session and segment) replaces its entry."""
        entry = SummaryEntry(summary_id(key), summary)
        self._write(entry)
        return entry.entry_id

    def add_note(self, text: str, *, now: datetime | None = None) -> str:
        """Store a user-requested note verbatim; ``ValueError`` if empty or too long."""
        if not text.strip():
            raise ValueError("a note cannot be empty")
        if len(text) > NOTE_MAX_CHARS:
            raise ValueError("the note is too long")
        moment = datetime.now(UTC) if now is None else _aware(now, "now")
        entry = NoteEntry(secrets.token_hex(12), text, moment)
        self._write(entry)
        return entry.entry_id

    def record_journal(
        self,
        offered_at: datetime,
        *,
        shown: bool,
        helpful: bool | None = None,
        entry_id: str | None = None,
    ) -> str:
        """Record a journal offer; pass the ``entry_id`` it returned to update it later."""
        if entry_id is not None and not _ID.fullmatch(entry_id):
            raise ValueError("not a ledger entry id")
        entry = JournalEntry(
            secrets.token_hex(12) if entry_id is None else entry_id, offered_at, shown, helpful
        )
        self._write(entry)
        return entry.entry_id

    # -- reading ---------------------------------------------------------------------------

    def entry_paths(self) -> list[Path]:
        """The entry files on disk (whether or not they still open)."""
        if not self.directory.is_dir():
            return []
        return sorted(
            p
            for p in self.directory.iterdir()
            if p.is_file() and p.suffix == _SUFFIX and _ID.fullmatch(p.stem)
        )

    def read_markdown(self, entry_id: str) -> str:
        """The decrypted Markdown document of one entry."""
        if not _ID.fullmatch(entry_id):
            raise ValueError("not a ledger entry id")
        blob = (self.directory / f"{entry_id}{_SUFFIX}").read_bytes()
        try:
            return self.vault.open(LEDGER_STORE, blob, label=_label(entry_id)).decode("utf-8")
        except KeychainUnavailableError as exc:
            raise _unavailable(exc) from exc

    def entries(self, since: datetime | None = None) -> tuple[LedgerEntry, ...]:
        """Every readable entry, oldest first; ``since`` keeps those at or after it.

        Raises :class:`LedgerUnavailableError` when entries exist but the keychain cannot
        be used now; entries whose key was shredded or that fail to open are skipped.
        """
        if since is not None:
            _aware(since, "since")
        found: list[LedgerEntry] = []
        skipped = 0
        for path in self.entry_paths():
            try:
                entry = _parse(self.read_markdown(path.stem), path.stem)
            except (KeyMissingError, DecryptionError, UnicodeDecodeError, ValueError):
                skipped += 1
                continue
            if since is None or entry.time >= since:
                found.append(entry)
        self.skipped = skipped
        found.sort(key=lambda e: (e.time, e.entry_id))
        return tuple(found)

    def notes(self) -> tuple[NoteEntry, ...]:
        return tuple(e for e in self.entries() if isinstance(e, NoteEntry))

    def render(self, entry: LedgerEntry) -> str:
        """The Markdown document for ``entry`` (front-matter and body)."""
        if isinstance(entry, NoteEntry):
            front: dict[str, Any] = {
                "olivia_ledger": FORMAT_VERSION,
                "id": entry.entry_id,
                "kind": "note",
                "created_at": entry.created_at.isoformat(),
                "significant": True,
            }
            body = entry.text
        elif isinstance(entry, JournalEntry):
            front = {
                "olivia_ledger": FORMAT_VERSION,
                "id": entry.entry_id,
                "kind": "journal",
                "offered_at": entry.offered_at.isoformat(),
                "shown": entry.shown,
                "helpful": entry.helpful,
            }
            body = self._journal_body(entry)
        else:
            front = _summary_front(entry)
            body = self._summary_body(entry.summary)
        head = yaml.safe_dump(front, allow_unicode=True, sort_keys=False, default_flow_style=None)
        return f"{_DELIMITER}{head}{_DELIMITER}{body}\n"

    # -- forgetting ------------------------------------------------------------------------

    def shred(self) -> None:
        """Crypto-shred the ledger key, then delete every entry file."""
        if self.vault.has_data_key(LEDGER_STORE):
            try:
                self.vault.shred(LEDGER_STORE)
            except KeychainUnavailableError as exc:
                raise _unavailable(exc) from exc
        for path in self.entry_paths():
            remove_file(path)
        if self.directory.is_dir():
            for stray in self.directory.glob(f".*{_SUFFIX}.*.tmp"):
                with contextlib.suppress(OSError):
                    stray.unlink()

    # -- internals -------------------------------------------------------------------------

    def _ensure_directory(self) -> None:
        if not self.directory.is_dir():
            self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            if os.name != "nt":
                self.directory.chmod(0o700)

    def _write(self, entry: LedgerEntry) -> None:
        document = self.render(entry).encode("utf-8")
        try:
            blob = self.vault.seal(LEDGER_STORE, document, label=_label(entry.entry_id))
        except KeychainUnavailableError as exc:
            raise _unavailable(exc) from exc
        except CryptoError as exc:  # the master key is gone while data keys remain
            raise LedgerUnavailableError("the ledger key cannot be used", permanent=False) from exc
        self._ensure_directory()
        atomic_write_bytes(self.directory / f"{entry.entry_id}{_SUFFIX}", blob, snapshot=False)

    def _summary_body(self, s: SessionSummary) -> str:
        t = self.text
        st = t.summary
        lines = [
            st.heading.format(date=s.started_at.date().isoformat()),
            st.time.format(start=s.started_at.strftime("%H:%M"), end=s.ended_at.strftime("%H:%M")),
            st.path.format(path=st.arrow.join(t.stages[stage.value] for stage in s.stage_path)),
            st.spectra.format(
                spectra=st.joiner.join(t.spectra.get(sid, sid) for sid in s.spectra) or st.none
            ),
        ]
        if s.methods:
            shown = st.joiner.join(
                f"{self._titles.get(m.method_id, m.method_id)}"
                f"（{t.feedback[m.feedback.value if m.feedback else NO_FEEDBACK]}）"
                for m in s.methods
            )
            lines.append(st.methods.format(methods=shown))
        else:
            lines.append(st.no_methods)
        if s.self_rating_before is not None or s.self_rating_after is not None:
            lines.append(
                st.self_rating.format(
                    before=_rating(s.self_rating_before, st.none),
                    after=_rating(s.self_rating_after, st.none),
                )
            )
        if s.entered_crisis:
            lines.append(st.crisis)
        if s.significant:
            lines.append(st.significant)
        return "\n".join(lines)

    def _journal_body(self, entry: JournalEntry) -> str:
        st = self.text.summary
        lines = [
            st.journal_heading.format(date=entry.offered_at.date().isoformat()),
            st.journal_shown if entry.shown else st.journal_skipped,
        ]
        if entry.helpful is not None:
            lines.append(st.journal_helpful if entry.helpful else st.journal_not_helpful)
        return "\n".join(lines)


def _rating(value: int | None, none: str) -> str:
    return none if value is None else str(value)


def _label(entry_id: str) -> str:
    return f"e_{entry_id}"


def _unavailable(exc: KeychainUnavailableError) -> LedgerUnavailableError:
    return LedgerUnavailableError(
        "the keychain is unavailable", permanent=isinstance(exc, NoKeychainError)
    )


def _summary_front(entry: SummaryEntry) -> dict[str, Any]:
    s = entry.summary
    return {
        "olivia_ledger": FORMAT_VERSION,
        "id": entry.entry_id,
        "kind": "summary",
        "started_at": s.started_at.isoformat(),
        "ended_at": s.ended_at.isoformat(),
        "stage_path": [stage.value for stage in s.stage_path],
        "spectra": list(s.spectra),
        "methods": [
            {"id": m.method_id, "feedback": m.feedback.value if m.feedback else None}
            for m in s.methods
        ],
        "crisis": {
            "entered": s.entered_crisis,
            "level": s.crisis_level.name if s.crisis_level is not None else None,
        },
        "self_rating": {"before": s.self_rating_before, "after": s.self_rating_after},
        "significant": s.significant,
        "marked_by_user": s.marked_by_user,
    }


# -- parsing ---------------------------------------------------------------------------------


def _parse(document: str, entry_id: str) -> LedgerEntry:
    """Parse one entry document; ``ValueError`` on anything unexpected."""
    if not document.startswith(_DELIMITER):
        raise ValueError("no front-matter")
    head, sep, body = document[len(_DELIMITER) :].partition(f"\n{_DELIMITER}")
    if not sep:
        raise ValueError("unterminated front-matter")
    try:
        front = yaml.safe_load(head)
    except yaml.YAMLError as exc:
        raise ValueError("front-matter is not YAML") from exc
    if not isinstance(front, dict):
        raise ValueError("front-matter is not a mapping")
    if front.get("olivia_ledger") != FORMAT_VERSION or front.get("id") != entry_id:
        raise ValueError("wrong format version or id")
    kind = front.get("kind")
    if kind == "note":
        if set(front) != _NOTE_KEYS or front["significant"] is not True:
            raise ValueError("bad note front-matter")
        if not body.endswith("\n"):
            raise ValueError("truncated note")
        return NoteEntry(entry_id, body[:-1], _time(front["created_at"]))
    if kind == "journal":
        if set(front) != _JOURNAL_KEYS:
            raise ValueError("bad journal front-matter")
        shown, helpful = front["shown"], front["helpful"]
        if not isinstance(shown, bool) or not (helpful is None or isinstance(helpful, bool)):
            raise ValueError("bad journal record")
        return JournalEntry(entry_id, _time(front["offered_at"]), shown, helpful)
    if kind == "summary":
        if set(front) != _SUMMARY_KEYS:
            raise ValueError("bad summary front-matter")
        summary = _summary_from(front)
        if front["significant"] is not summary.significant:
            raise ValueError("significance does not match")
        return SummaryEntry(entry_id, summary)
    raise ValueError("unknown entry kind")


def _time(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("time must be an ISO string")
    return _aware(datetime.fromisoformat(value), "time")


def _str_list(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValueError("expected a list of strings")
    return tuple(value)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("expected an integer")
    return value


def _summary_from(front: Mapping[str, Any]) -> SessionSummary:
    methods_raw = front["methods"]
    if not isinstance(methods_raw, list):
        raise ValueError("methods must be a list")
    methods = []
    for item in methods_raw:
        if not isinstance(item, dict) or set(item) != {"id", "feedback"}:
            raise ValueError("bad method record")
        if not isinstance(item["id"], str):
            raise ValueError("method id must be a string")
        feedback = item["feedback"]
        methods.append(MethodRecord(item["id"], None if feedback is None else Feedback(feedback)))
    crisis = front["crisis"]
    if not isinstance(crisis, dict) or set(crisis) != {"entered", "level"}:
        raise ValueError("bad crisis record")
    try:
        level = None if crisis["level"] is None else CrisisLevel[str(crisis["level"])]
    except KeyError as exc:
        raise ValueError("unknown crisis level") from exc
    if crisis["entered"] is not (level is not None):
        raise ValueError("crisis flag and level disagree")
    rating = front["self_rating"]
    if not isinstance(rating, dict) or set(rating) != {"before", "after"}:
        raise ValueError("bad self-rating record")
    marked = front["marked_by_user"]
    if not isinstance(marked, bool):
        raise ValueError("marked_by_user must be a boolean")
    return SessionSummary(
        started_at=_time(front["started_at"]),
        ended_at=_time(front["ended_at"]),
        stage_path=tuple(HelpStage(s) for s in _str_list(front["stage_path"])),
        spectra=_str_list(front["spectra"]),
        methods=tuple(methods),
        crisis_level=level,
        self_rating_before=_optional_int(rating["before"]),
        self_rating_after=_optional_int(rating["after"]),
        marked_by_user=marked,
    )
