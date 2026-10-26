"""Self-ratings and the weekly journal (next-phase B6; PRD SOP 5, CHANG-04, ruling 30).

**Self-ratings.** One optional 0-10 question (``prompts.rating``) at the opening of
``olivia chat`` and the same question when the session ends: on ``/exit`` and when the
state machine closes a segment (S_closing -> S_ready). Only the integers 0-10 count;
anything else is a skip and is not asked again. The ratings go only into the ledger's
session summary (``self_rating_before`` / ``self_rating_after``); there is no other store.
Never asked:

* without a usable ledger (no keychain, or locked now);
* on a session that opens with the care greeting (A3): that greeting stays first and
  alone, so there is no opening rating and no journal offer on it;
* at the end of a session that entered the crisis flow or asked the direct question about
  intent (D3), at any point, or while it is in S_haven or the battery is at or below the
  haven threshold (ruling 30: "避风港中不问");
* on end of input or Ctrl-C, or at ``/exit`` when the open segment has no turns.

A non-empty answer that is not a rating (or a yes / no below) is not lost: it becomes the
next message of the conversation, so the crisis screen sees anything typed at a question.

**The journal.** A read-only summary of the rolling last :data:`WINDOW` built from the
ledger alone (:func:`render_journal`): how many sessions, the before -> after ratings and
how often the rating rose, the dominant spectra in everyday words, the exercises tried
with their feedback, and how many notes the user asked to have remembered (the count only;
the words stay in the ledger). When a session in the window entered the crisis flow the
card opens and closes in a steadier voice and points to ``olivia resources``. No user
text, no diagnosis words, no numbers but the ratings and the counts. The profile's taboo
topics are a hard filter here too (ruling 21, ONB-04b, F11): a spectrum whose everyday
name or an exercise whose line names one is left out (the line goes when nothing is left
in it), with the same case-folded substring test as the session's taboo filter.

**The voice** (PRD Q-6). The opening, the line that leads into the facts (``bridge``) and
the closing follow the profile's persona: each of the four has a pool of each in the
everyday voice and in the steadier one (``voices`` in the YAML); SILENT_ANCHOR says the
least. The facts, their numbers and the line structure are the same in every voice. A
variant is picked by the day (:func:`variant`), so the same card reads the same all day
and the wording moves from day to day (with two variants, a week later is the other
one). An old profile or an unknown persona reads as GENTLE_HOLDING.

**The battery line** (CHANG-04, "电量走势"). Summaries written since the battery figures
(``ledger.py``) say whether a ``[NN%]`` prefix was given, the lowest reading and whether
the session was in S_haven. The line counts this week's sessions that gave a battery and
those where it was very low (at or below :data:`LOW_BATTERY`, the haven threshold, or in
S_haven), with last week's count of very low ones beside it when last week has battery
data; it states the counts and passes no judgement. No battery data this week (older
summaries, or no prefix given): no line.

**When.** At a chat opening (after the rating), when the window holds at least
:data:`MIN_SESSIONS` session summaries and no journal record (shown or declined) is in the
window: ``prompts.offer``. Yes shows it, then ``prompts.helpful`` (yes / no, skippable).
No, an empty answer or anything else declines it for this window. ``olivia journal``
shows it at any time (:func:`run_command`). Every offer is a ``journal`` ledger entry
(time, shown, helpful), written when offered and rewritten with the answer.

All wording is in ``olivia/data/templates/journal.yaml`` (G-0 draft).
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import cache
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Final

import yaml

from olivia.core.memory.ledger import (
    SELF_RATING_RANGE,
    JournalEntry,
    Ledger,
    LedgerUnavailableError,
    NoteEntry,
    SessionSummary,
    SummaryEntry,
)
from olivia.core.memory.recorder import SessionRecorder
from olivia.core.memory.text import NO_FEEDBACK, MemoryText
from olivia.core.models import CrisisLevel, HelpStage, PersonaSpectrum, SessionState
from olivia.core.session import ReplyKind, TurnResult
from olivia.core.taxonomy import Taxonomy
from olivia.core.yaml_load import safe_load

WINDOW: Final = timedelta(days=7)
MIN_SESSIONS: Final = 2
LOW_BATTERY: Final = 0.20
"""A battery at or below this is "very low": the haven threshold (``battery.thresholds``)."""
MAX_SPECTRA: Final = 3
EXIT_COMMAND: Final = "/exit"

_FILE: Final = "journal.yaml"
_PROMPT_KEYS: Final = ("rating", "offer", "helpful")
_REPLY_KEYS: Final = (
    "rating_saved",
    "helpful_yes",
    "helpful_no",
    "helpful_skipped",
    "offer_declined",
    "empty",
    "unavailable",
    "not_onboarded",
    "adults_only",
)
_CARD_KEYS: Final = (
    "heading",
    "sessions",
    "ratings",
    "no_ratings",
    "rating_missing",
    "rose",
    "battery_low",
    "battery_fine",
    "battery_last_week",
    "spectra",
    "methods",
    "no_methods",
    "notes",
    "joiner",
    "arrow",
)
_FRAGMENTS: Final = frozenset({"rating_missing", "battery_last_week", "joiner", "arrow"})
"""Card pieces never shown on their own (WILLOW and the gate check them inside a line)."""
VOICE_SLOTS: Final = (
    "intro",
    "bridge",
    "closing",
    "intro_solemn",
    "bridge_solemn",
    "closing_solemn",
)
DEFAULT_VOICE: Final = PersonaSpectrum.GENTLE_HOLDING
_RATING: Final = re.compile(r"\d{1,2}")
_TRAILING: Final = "。．.！!？?，,～~ "


class JournalTextError(Exception):
    """``journal.yaml`` is missing, malformed or incomplete."""


@dataclass(frozen=True)
class Voice:
    """One persona's pools around the facts: everyday and steadier (crisis-week) voice."""

    intro: tuple[str, ...]
    bridge: tuple[str, ...]
    closing: tuple[str, ...]
    intro_solemn: tuple[str, ...]
    bridge_solemn: tuple[str, ...]
    closing_solemn: tuple[str, ...]

    def lines(self) -> tuple[str, ...]:
        return (
            *self.intro,
            *self.bridge,
            *self.closing,
            *self.intro_solemn,
            *self.bridge_solemn,
            *self.closing_solemn,
        )


@dataclass(frozen=True)
class JournalText:
    prompts: Mapping[str, str]
    replies: Mapping[str, str]
    card: Mapping[str, str]
    agree: frozenset[str]
    decline: frozenset[str]
    voices: Mapping[str, Voice]
    """Every :class:`PersonaSpectrum` value -> its voice."""

    def voice(self, persona: str | None) -> Voice:
        """The voice for ``persona``; GENTLE_HOLDING for None or an unknown persona."""
        found = self.voices.get(persona) if persona else None
        return self.voices[DEFAULT_VOICE.value] if found is None else found

    def all_texts(self) -> tuple[str, ...]:
        """Every sentence shown on its own, for the WILLOW and gate checks in the tests."""
        return (
            *self.prompts.values(),
            *self.replies.values(),
            *(v for k, v in self.card.items() if k not in _FRAGMENTS),
            *(line for voice in self.voices.values() for line in voice.lines()),
        )


def load_journal_text(directory: Path | None = None) -> JournalText:
    """Load and validate ``journal.yaml``; ``None`` reads the packaged copy (cached)."""
    if directory is None:
        return _packaged_text()
    return _load_text(directory)


@cache
def _packaged_text() -> JournalText:
    return _load_text(resources.files("olivia").joinpath("data/templates"))


def _strings(value: object, keys: tuple[str, ...], where: str) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != set(keys):
        raise JournalTextError(f"{_FILE}: {where} must have exactly {list(keys)}")
    out: dict[str, str] = {}
    for key in keys:
        item = value[key]
        if not isinstance(item, str) or not item.strip(" "):
            raise JournalTextError(f"{_FILE}: {where}.{key} must be a non-empty string")
        out[key] = item
    return out


def _words(value: object, where: str) -> frozenset[str]:
    if not isinstance(value, list) or not value:
        raise JournalTextError(f"{_FILE}: answers.{where} must be a non-empty list")
    return frozenset(_normalise(str(v)) for v in value)


def _pool(value: object, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise JournalTextError(f"{_FILE}: {where} must be a non-empty list")
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise JournalTextError(f"{_FILE}: {where} must hold non-empty strings")
    return tuple(value)


def _voices(value: object) -> dict[str, Voice]:
    personas = {p.value for p in PersonaSpectrum}
    if not isinstance(value, dict) or set(value) != personas:
        raise JournalTextError(f"{_FILE}: voices must have exactly {sorted(personas)}")
    out: dict[str, Voice] = {}
    for persona in sorted(personas):
        slots = value[persona]
        if not isinstance(slots, dict) or set(slots) != set(VOICE_SLOTS):
            raise JournalTextError(f"{_FILE}: voices.{persona} must have {list(VOICE_SLOTS)}")
        pools = {slot: _pool(slots[slot], f"voices.{persona}.{slot}") for slot in VOICE_SLOTS}
        out[persona] = Voice(**pools)
    return out


def _load_text(base: Traversable | Path) -> JournalText:
    try:
        doc = safe_load(base.joinpath(_FILE).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise JournalTextError(f"{_FILE}: cannot read: {exc}") from exc
    expected = {"version", "prompts", "replies", "card", "voices", "answers"}
    if not isinstance(doc, dict) or doc.get("version") != 1 or set(doc) != expected:
        raise JournalTextError(f"{_FILE}: must be version 1 with sections {sorted(expected)}")
    answers = doc["answers"]
    if not isinstance(answers, dict) or set(answers) != {"agree", "decline"}:
        raise JournalTextError(f"{_FILE}: answers must have exactly agree and decline")
    agree, decline = _words(answers["agree"], "agree"), _words(answers["decline"], "decline")
    if agree & decline:
        raise JournalTextError(f"{_FILE}: an answer cannot both agree and decline")
    return JournalText(
        prompts=_strings(doc["prompts"], _PROMPT_KEYS, "prompts"),
        replies=_strings(doc["replies"], _REPLY_KEYS, "replies"),
        card=_strings(doc["card"], _CARD_KEYS, "card"),
        agree=agree,
        decline=decline,
        voices=_voices(doc["voices"]),
    )


# -- parsing answers ---------------------------------------------------------------------------


def _normalise(text: str) -> str:
    return unicodedata.normalize("NFKC", text).strip().rstrip(_TRAILING).strip().casefold()


def parse_rating(text: str) -> int | None:
    """A 0-10 self-rating: digits only (full-width too); anything else is None (a skip)."""
    cleaned = unicodedata.normalize("NFKC", text).strip()
    if not cleaned.isascii() or not _RATING.fullmatch(cleaned):
        return None
    value = int(cleaned)
    return value if value in SELF_RATING_RANGE else None


def parse_yes_no(text: str, words: JournalText) -> bool | None:
    """True / False for a recognised yes / no; None for anything else."""
    cleaned = _normalise(text)
    if cleaned in words.agree:
        return True
    if cleaned in words.decline:
        return False
    return None


# -- the week ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Week:
    """What the ledger holds for the rolling window ending at ``until``."""

    until: datetime
    sessions: tuple[SessionSummary, ...]
    notes: int
    journals: tuple[JournalEntry, ...]
    previous: tuple[SessionSummary, ...] = ()
    """The sessions of the window before (last week), for the battery line only."""

    @property
    def solemn(self) -> bool:
        """A session in the window entered the crisis flow (CHANG-04: a steadier voice)."""
        return any(s.entered_crisis for s in self.sessions)


def gather(ledger: Ledger, now: datetime) -> Week:
    """The window's entries; raises :class:`LedgerUnavailableError` like ``entries``."""
    start = now - WINDOW
    found = ledger.entries(since=start - WINDOW)
    entries = [e for e in found if e.time >= start]
    return Week(
        until=now,
        sessions=tuple(e.summary for e in entries if isinstance(e, SummaryEntry)),
        notes=sum(1 for e in entries if isinstance(e, NoteEntry)),
        journals=tuple(e for e in entries if isinstance(e, JournalEntry)),
        previous=tuple(e.summary for e in found if isinstance(e, SummaryEntry) and e.time < start),
    )


def is_due(week: Week) -> bool:
    """Ruling 30: >= MIN_SESSIONS sessions in the window and no journal offered in it."""
    return len(week.sessions) >= MIN_SESSIONS and not week.journals


def names_taboo(text: str, taboo_topics: tuple[str, ...]) -> bool:
    """Whether ``text`` names one of the taboo topics (case-folded substring, as the
    session's filter)."""
    folded = text.casefold()
    return any(topic.casefold() in folded for topic in taboo_topics if topic.strip())


def variant(pool: tuple[str, ...], until: datetime) -> str:
    """The variant of ``pool`` for the day of ``until``: the same all day, moving daily."""
    return pool[until.date().toordinal() % len(pool)]


def _told_battery(s: SessionSummary) -> bool:
    """The session gave a battery reading (or was in S_haven)."""
    return bool(s.battery_prefix or s.haven)


def _low_battery(s: SessionSummary) -> bool:
    return bool(s.haven) or (s.battery_min is not None and s.battery_min <= LOW_BATTERY)


def _battery_line(week: Week, card: Mapping[str, str]) -> str | None:
    """This week's battery line, or None without battery data this week."""
    told = [s for s in week.sessions if _told_battery(s)]
    if not told:
        return None
    low = sum(1 for s in told if _low_battery(s))
    if low:
        line = card["battery_low"].format(known=len(told), count=low)
    else:
        line = card["battery_fine"].format(known=len(told))
    before = [s for s in week.previous if _told_battery(s)]
    if before:
        line += card["battery_last_week"].format(count=sum(1 for s in before if _low_battery(s)))
    return line


def render_journal(
    week: Week,
    text: JournalText,
    memory: MemoryText,
    method_titles: Mapping[str, str] | None = None,
    *,
    taboo_topics: tuple[str, ...] = (),
    persona: str | None = None,
) -> str:
    """The journal card for ``week`` (which must hold at least one session) in the voice
    of ``persona`` (GENTLE_HOLDING when None or unknown); spectra and exercises that name
    a taboo topic are left out (ruling 21)."""
    if not week.sessions:
        raise ValueError("a journal needs at least one session")
    card = text.card
    voice = text.voice(persona)
    titles = {} if method_titles is None else method_titles
    solemn = week.solemn
    lines = [
        card["heading"],
        variant(voice.intro_solemn if solemn else voice.intro, week.until),
        variant(voice.bridge_solemn if solemn else voice.bridge, week.until),
        card["sessions"].format(count=len(week.sessions)),
    ]

    rated = [s for s in week.sessions if (s.self_rating_before, s.self_rating_after) != (None,) * 2]
    if rated:

        def mark(value: int | None) -> str:
            return card["rating_missing"] if value is None else str(value)

        pairs = card["joiner"].join(
            f"{mark(s.self_rating_before)}{card['arrow']}{mark(s.self_rating_after)}" for s in rated
        )
        lines.append(card["ratings"].format(pairs=pairs))
        rose = sum(
            1
            for s in rated
            if s.self_rating_before is not None
            and s.self_rating_after is not None
            and s.self_rating_after > s.self_rating_before
        )
        if rose:
            lines.append(card["rose"].format(count=rose))
    else:
        lines.append(card["no_ratings"])

    battery = _battery_line(week, card)
    if battery is not None:
        lines.append(battery)

    named = [memory.spectra.get(sid, sid) for sid in _dominant_spectra(week.sessions)]
    named = [name for name in named if not names_taboo(name, taboo_topics)][:MAX_SPECTRA]
    if named:
        lines.append(card["spectra"].format(spectra=card["joiner"].join(named)))

    methods = _methods(week.sessions)
    if methods:
        items = [
            f"{titles.get(mid, mid)}（{card['joiner'].join(memory.feedback[f] for f in labels)}）"
            for mid, labels in methods.items()
        ]
        kept = [item for item in items if not names_taboo(item, taboo_topics)]
        if kept:
            lines.append(card["methods"].format(methods=card["joiner"].join(kept)))
    else:
        lines.append(card["no_methods"])

    if week.notes:
        lines.append(card["notes"].format(count=week.notes))
    lines.append(variant(voice.closing_solemn if solemn else voice.closing, week.until))
    return "\n".join(lines)


def _dominant_spectra(sessions: tuple[SessionSummary, ...]) -> tuple[str, ...]:
    """Spectra by the number of sessions that mention them; first appearance breaks ties
    (every one: the caller drops taboo ones, then keeps :data:`MAX_SPECTRA`)."""
    counts: Counter[str] = Counter()
    order: list[str] = []
    for s in sessions:
        for sid in s.spectra:
            if sid not in counts:
                order.append(sid)
            counts[sid] += 1
    return tuple(sorted(order, key=lambda sid: (-counts[sid], order.index(sid))))


def _methods(sessions: tuple[SessionSummary, ...]) -> dict[str, list[str]]:
    """Method id -> its distinct feedback values in order ("none" only when it had none)."""
    found: dict[str, list[str]] = {}
    for s in sessions:
        for m in s.methods:
            labels = found.setdefault(m.method_id, [])
            if m.feedback is not None and m.feedback.value not in labels:
                labels.append(m.feedback.value)
    return {mid: labels or [NO_FEEDBACK] for mid, labels in found.items()}


# -- the exchanges -----------------------------------------------------------------------------

Ask = Callable[[], str | None]
"""One answer line without its newline; None at end of input."""
Say = Callable[[str], None]


@dataclass(frozen=True)
class Carry:
    """What an exchange leaves for the conversation loop."""

    line: str | None = None
    """Text typed at a question that was not an answer: the next message of the chat."""
    ended: bool = False
    """End of input (or ``/exit`` at an opening question): the chat ends here."""
    answered: bool = False
    """The "was it helpful" question got a yes or a no."""


def _show_and_rate(
    ask: Ask, say: Say, ledger: Ledger, now: datetime, card: str, text: JournalText
) -> Carry:
    """Show the card, record it, then ask whether it helped (and record the answer)."""
    say(card)
    say("")
    entry_id = _record(ledger, now, shown=True)
    say(text.prompts["helpful"])
    answer = ask()
    if answer is None:
        return Carry(ended=True)
    helpful = parse_yes_no(answer, text)
    if helpful is None:
        return Carry(line=answer) if answer.strip() else Carry()
    if entry_id is not None:
        _record(ledger, now, shown=True, helpful=helpful, entry_id=entry_id)
    say(text.replies["helpful_yes" if helpful else "helpful_no"])
    return Carry(answered=True)


def _record(
    ledger: Ledger,
    now: datetime,
    *,
    shown: bool,
    helpful: bool | None = None,
    entry_id: str | None = None,
) -> str | None:
    try:
        return ledger.record_journal(now, shown=shown, helpful=helpful, entry_id=entry_id)
    except LedgerUnavailableError:
        return None


class ChatChecks:
    """The self-ratings and the journal offer around one ``olivia chat`` session.

    ``ask`` reads one answer line and ``say`` prints one; ``recorder`` is the session's
    ledger recorder (nothing is asked when it is disabled); ``taboo_topics`` are the
    profile's, left out of the journal card, and ``persona`` is its voice.
    """

    def __init__(
        self,
        tax: Taxonomy,
        ledger: Ledger,
        recorder: SessionRecorder,
        ask: Ask,
        say: Say,
        *,
        method_titles: Mapping[str, str] | None = None,
        text: JournalText | None = None,
        taboo_topics: tuple[str, ...] = (),
        persona: str | None = None,
    ) -> None:
        self._ledger = ledger
        self._taboo = taboo_topics
        self._persona = persona
        self._recorder = recorder
        self._ask = ask
        self._say = say
        self._titles = method_titles
        self.text: JournalText = load_journal_text() if text is None else text
        self._haven_enter = tax.threshold("battery.thresholds.haven_enter")
        self.crisis_seen = False
        """A turn of this session was in the crisis flow or asked the intent question."""

    @property
    def enabled(self) -> bool:
        return self._recorder.enabled

    def opening(self, now: datetime) -> Carry:
        """The opening rating, then the journal offer when it is due."""
        if not self.enabled:
            return Carry()
        rating, carry = self._rating()
        if rating is not None:
            self._recorder.rate_before(rating)
            self._say(self.text.replies["rating_saved"])
        if not carry.ended and carry.line is None:
            carry = self._offer(now)
        if not carry.ended:
            self._say("")
        return carry

    def observe(self, result: TurnResult) -> None:
        if (
            result.in_crisis
            or result.reply_kind in (ReplyKind.CRISIS, ReplyKind.SAFETY_CHECK)
            or result.crisis_level >= CrisisLevel.L2
        ):
            self.crisis_seen = True

    def may_ask_after(self, state: SessionState) -> bool:
        """Ruling 30: not in S_haven (or at the haven battery), never after a crisis."""
        if not self.enabled or self.crisis_seen:
            return False
        return (
            state.current_stage is not HelpStage.S_HAVEN
            and state.social_battery > self._haven_enter
        )

    def after_turn(self, state: SessionState) -> Carry:
        """The closing rating when the state machine has just closed a segment."""
        if not self._recorder.closed_segment or not self.may_ask_after(state):
            return Carry()
        return self._closing_rating()

    def at_exit(self, state: SessionState) -> Carry:
        """The closing rating on ``/exit`` when the open segment has turns."""
        if not self._recorder.segment_open or not self.may_ask_after(state):
            return Carry()
        return self._closing_rating()

    # -- internals -----------------------------------------------------------------------------

    def _rating(self) -> tuple[int | None, Carry]:
        self._say(self.text.prompts["rating"])
        answer = self._ask()
        if answer is None:
            return None, Carry(ended=True)
        rating = parse_rating(answer)
        if rating is not None:
            return rating, Carry()
        if answer.strip() == EXIT_COMMAND:
            return None, Carry(ended=True)
        return None, Carry(line=answer) if answer.strip() else Carry()

    def _closing_rating(self) -> Carry:
        rating, carry = self._rating()
        if rating is not None and self._recorder.rate_after(rating):
            self._say(self.text.replies["rating_saved"])
        return carry

    def _offer(self, now: datetime) -> Carry:
        try:
            week = gather(self._ledger, now)
        except LedgerUnavailableError:
            return Carry()
        if not is_due(week):
            return Carry()
        self._say("")
        self._say(self.text.prompts["offer"])
        answer = self._ask()
        if answer is None:
            return Carry(ended=True)
        choice = parse_yes_no(answer, self.text)
        if choice is not True:
            _record(self._ledger, now, shown=False)
            stripped = answer.strip()
            if stripped == EXIT_COMMAND:
                return Carry(ended=True)
            if choice is None and stripped:
                return Carry(line=answer)
            self._say(self.text.replies["offer_declined"])
            return Carry()
        card = render_journal(
            week,
            self.text,
            self._ledger.text,
            self._titles,
            taboo_topics=self._taboo,
            persona=self._persona,
        )
        self._say("")
        return _show_and_rate(self._ask, self._say, self._ledger, now, card, self.text)


def run_command(
    ask: Ask,
    say: Say,
    ledger: Ledger,
    now: datetime,
    *,
    method_titles: Mapping[str, str] | None = None,
    text: JournalText | None = None,
    taboo_topics: tuple[str, ...] = (),
    persona: str | None = None,
) -> int:
    """``olivia journal``: show the rolling week's journal now, in the voice of
    ``persona``; the exit status."""
    words = load_journal_text() if text is None else text
    try:
        if not ledger.available():
            raise LedgerUnavailableError("the keychain is unavailable", permanent=False)
        week = gather(ledger, now)
    except LedgerUnavailableError:
        say(words.replies["unavailable"])
        return 1
    if not week.sessions:
        say(words.replies["empty"])
        return 0
    card = render_journal(
        week, words, ledger.text, method_titles, taboo_topics=taboo_topics, persona=persona
    )
    carry = _show_and_rate(ask, say, ledger, now, card, words)
    if not carry.answered and not carry.ended:
        say(words.replies["helpful_skipped"])
    return 0
