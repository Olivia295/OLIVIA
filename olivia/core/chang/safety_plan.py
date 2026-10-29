"""The personal safety plan (Stanley-Brown style; next-phase B10, decision D8).

Five sections, each optional, each a few short entries:

1. ``warning_signs``: 我的预警信号
2. ``coping``: 我自己能做的安抚方法
3. ``distraction``: 能让我分心的人或地方
4. ``people``: 我可以求助的人 (a name and, optionally, a phone number)
5. ``environment``: 让环境更安全 (keeping dangerous things away)

The plan is filled, shown, edited and cleared only in ``olivia safety-plan``
(:func:`run_command`); the chat never stores user text. It is always sealed with its own
data key (store ``safety_plan``), whatever the at-rest switch says, and without a
keychain nothing is saved. :meth:`SafetyPlanStore.shred` is the hook for ``olivia forget``
(B5).

In a crisis reply the session shows sections 2, 3 and 4 only, as one block introduced by
``crisis.intro`` (:func:`crisis_block`); section 5 is never shown there. The CLI loads the
plan and hands it to ``Session.open``; the session never writes it.

Crisis sentences typed here (QA r3, 2026-10-27): with a ``screen`` (the CLI's setup
screen), every reply is screened first, and each one at L2 or above brings the numbers and
the choice to go on or to leave (:class:`Screened`), however many there are in one run.
Sections 1 and 5 keep such a sentence after "go on": warning signs and the means to put
away are written in those words. Sections 2, 3 and 4 never keep one, since a crisis reply
reads them back to the user ("能让我分心的人或地方：· 我打算去楼顶待着，然后就结束"): the
user is told why and asked to write it another way or to press Enter to skip. Leaving there
keeps what was written before that reply. :func:`without_crisis_entries` drops such entries
from a plan saved before this check (round 5: the chat also drops entries naming a place or
a means, ``setup_screen.SetupScreen.risky_words``).

Protective steps in section 5 (round 5, 复测 q4 SP-1): "把多余的药交给室友保管" is what
section 5 asks for, yet the student alone was unsure about it and the user was asked
whether they are safe now. A section 5 reply that :func:`protective` reads as putting a
means away (handing it over, locking it up, throwing it out, keeping away from a place) and
that holds nothing of keeping it close (藏, 自己留着, 以防万一, 随时) goes through
``protective_screen`` instead: the CLI then takes an unsure student-only alarm as clear.
Structural narrowing, not a word list: a rule cue, a model failure or a sure student
still bring the numbers, and the entry stays in section 5, which a crisis reply never
shows. After the numbers only the question itself comes
again (QA q4): a menu's lines, or the one line asking for a person; never a section
heading or a line said about the entry before ("已经写满 5 条了", "表姐和电话都记下了").

Discoverability: when no plan exists and none was suggested on this device before, the
first S_closing reply of a session ends with one ``suggestion`` line; the CLI then writes
an empty marker file (``safety_plan_suggested``, no user data) so it is said once per
device.

Files in the app data directory: ``safety_plan.bin`` (the raw sealed JSON, written
atomically without snapshots, so an edit or clear leaves no older copy) and the marker.
All wording is in ``olivia/data/templates/safety_plan.yaml`` (G-0 draft).
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from functools import cache
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Final

import yaml

from olivia.core.crypto.errors import (
    DecryptionError,
    KeychainUnavailableError,
    KeyMissingError,
)
from olivia.core.crypto.vault import Vault
from olivia.core.storage import app_data_dir, atomic_write_bytes, remove_file
from olivia.core.yaml_load import safe_load

SAFETY_PLAN_STORE: Final = "safety_plan"
SAFETY_PLAN_FILENAME: Final = "safety_plan.bin"
SUGGESTED_FILENAME: Final = "safety_plan_suggested"
MAX_ENTRIES: Final = 5
"""Entries (or people) per section."""
MAX_ENTRY_CHARS: Final = 40
MAX_NAME_CHARS: Final = 12
MAX_PHONE_CHARS: Final = 20
MIN_PHONE_DIGITS: Final = 3
CLEAR_SECTION: Final = "0"
CLEAR_CONFIRMATIONS: Final = frozenset({"1", "确认", "确定"})
"""What confirms clearing the whole plan: 1, or the words ``olivia forget`` takes (QA q4
SP-9)."""
_LABEL: Final = "plan"
_VERSION: Final = 1
_TEXT_FILE: Final = "safety_plan.yaml"
_PHONE_RE: Final = re.compile(r"[0-9+\-() ]+")
# A name followed by a phone number on one line ("表姐 13800000000", "阿青：138-0000-0000"):
# the name ends in a non-digit, then optional separators, then the number.
_CONTACT_RE: Final = re.compile(r"(?P<name>.*?\D)[\s:,、]*(?P<phone>[+(]?\d[0-9\-() ]*\d)")
_NAME_TRIM: Final = " :,、"
_SLOT_RE: Final = re.compile(r"\{([^{}]*)\}")
_ALLOWED_SLOTS: Final = frozenset({"n", "total", "title", "name", "max_chars", "max_entries"})


class Section(StrEnum):
    WARNING_SIGNS = "warning_signs"
    COPING = "coping"
    DISTRACTION = "distraction"
    PEOPLE = "people"
    ENVIRONMENT = "environment"


SECTIONS: Final = tuple(Section)
CRISIS_SECTIONS: Final = (Section.COPING, Section.DISTRACTION, Section.PEOPLE)
"""What a crisis reply shows; ``ENVIRONMENT`` (means) and the warning signs never."""
KEPT_CRISIS_SECTIONS: Final = (Section.WARNING_SIGNS, Section.ENVIRONMENT)
"""Where a crisis sentence is kept after the numbers (it is what these sections ask for)."""

_COMMAND_KEYS: Final = (
    "intro",
    "section_heading",
    "entry_help",
    "rewrite_help",
    "current_heading",
    "current_empty",
    "entry_too_long",
    "entry_not_saved",
    "section_full",
    "person_name",
    "name_too_long",
    "name_for_phone",
    "person_with_phone",
    "person_phone",
    "phone_invalid",
    "show_heading",
    "empty_section",
    "menu",
    "menu_edit",
    "menu_clear",
    "menu_unknown",
    "pick_section",
    "pick_unknown",
    "clear_confirm",
    "saved",
    "unchanged",
    "cleared",
    "nothing_saved",
    "left",
    "no_keychain",
    "locked",
    "damaged",
    "unreadable",
    "not_onboarded",
    "adults_only",
    "crisis_kept",
    "crisis_not_kept",
    "crisis_retry",
    "crisis_left",
    "crisis_left_saved",
    "left_saved",
    "edit_not_saved",
)


class SafetyPlanTextError(Exception):
    """``safety_plan.yaml`` is missing, malformed or uses an unknown slot."""


class SafetyPlanDamagedError(Exception):
    """The saved plan cannot be opened (its key is gone or the file was changed)."""


class SafetyPlanUnreadableError(SafetyPlanDamagedError):
    """The plan's file exists but the operating system will not read it (a directory in
    its place, no permission); it may well be intact, so nothing replaces it."""


# -- the plan ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Contact:
    name: str
    phone: str = ""

    def display(self) -> str:
        return f"{self.name}：{self.phone}" if self.phone else self.name


@dataclass(frozen=True)
class SafetyPlan:
    warning_signs: tuple[str, ...] = ()
    coping: tuple[str, ...] = ()
    distraction: tuple[str, ...] = ()
    people: tuple[Contact, ...] = ()
    environment: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not any(self.lines(section) for section in SECTIONS)

    def lines(self, section: Section) -> tuple[str, ...]:
        """The section's entries as shown (a contact as ``name：phone``)."""
        if section is Section.PEOPLE:
            return tuple(contact.display() for contact in self.people)
        entries: tuple[str, ...] = getattr(self, section.value)
        return entries

    def to_json(self) -> bytes:
        data: dict[str, object] = {"version": _VERSION}
        for section in SECTIONS:
            if section is Section.PEOPLE:
                data[section.value] = [{"name": c.name, "phone": c.phone} for c in self.people]
            else:
                data[section.value] = list(self.lines(section))
        return json.dumps(data, ensure_ascii=False).encode("utf-8")

    @classmethod
    def from_json(cls, raw: bytes) -> SafetyPlan:
        """Parse :meth:`to_json` output; ``ValueError`` for anything else."""
        data = json.loads(raw.decode("utf-8"))
        expected = {"version", *(s.value for s in SECTIONS)}
        if not isinstance(data, dict) or set(data) != expected or data["version"] != _VERSION:
            raise ValueError("not a safety plan")
        fields: dict[str, object] = {}
        for section in SECTIONS:
            items = data[section.value]
            if not isinstance(items, list) or len(items) > MAX_ENTRIES:
                raise ValueError("not a safety plan")
            if section is Section.PEOPLE:
                fields[section.value] = tuple(_contact(item) for item in items)
            else:
                if not all(isinstance(item, str) and item for item in items):
                    raise ValueError("not a safety plan")
                fields[section.value] = tuple(items)
        return cls(**fields)  # type: ignore[arg-type]


def _contact(item: object) -> Contact:
    if not isinstance(item, dict) or set(item) != {"name", "phone"}:
        raise ValueError("not a safety plan contact")
    name, phone = item["name"], item["phone"]
    if not isinstance(name, str) or not name or not isinstance(phone, str):
        raise ValueError("not a safety plan contact")
    return Contact(name, phone)


def _with_section(plan: SafetyPlan, section: Section, values: tuple[object, ...]) -> SafetyPlan:
    if section is Section.PEOPLE:
        return replace(plan, people=tuple(v for v in values if isinstance(v, Contact)))
    entries = tuple(v for v in values if isinstance(v, str))
    if section is Section.WARNING_SIGNS:
        return replace(plan, warning_signs=entries)
    if section is Section.COPING:
        return replace(plan, coping=entries)
    if section is Section.DISTRACTION:
        return replace(plan, distraction=entries)
    return replace(plan, environment=entries)


# -- wording ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class SafetyPlanText:
    titles: Mapping[Section, str]
    prompts: Mapping[Section, str]
    command: Mapping[str, str]
    crisis_intro: str
    suggestion: str
    crisis_reminder: str = ""
    """S5: the one line a crisis reply carries after the plan was shown in full once."""
    crisis_reminder_people: str = ""
    """The same with the names of section 4 (slot ``{name}``)."""
    farewell_people: str = ""
    """The heading of section 4's people in a crisis farewell."""
    crisis_unreadable: str = ""
    """Said in a crisis reply in place of a saved plan that cannot be opened now."""

    def all_texts(self) -> tuple[str, ...]:
        """Every sentence in the file, for the WILLOW and gate checks in the tests."""
        return (
            *self.titles.values(),
            *self.prompts.values(),
            *self.command.values(),
            self.crisis_intro,
            self.suggestion,
            self.crisis_reminder,
            self.crisis_reminder_people,
            self.farewell_people,
            self.crisis_unreadable,
        )


def _string(value: object, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SafetyPlanTextError(f"{_TEXT_FILE}: {where} must be a non-empty string")
    unknown = set(_SLOT_RE.findall(value)) - _ALLOWED_SLOTS
    if unknown:
        raise SafetyPlanTextError(f"{_TEXT_FILE}: {where} uses unknown slots {sorted(unknown)}")
    return value


def _mapping(value: object, where: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise SafetyPlanTextError(f"{_TEXT_FILE}: {where} must be a mapping")
    return value


def load_safety_plan_text(directory: Path | None = None) -> SafetyPlanText:
    """Load and validate ``safety_plan.yaml``; ``None`` reads the packaged copy (cached)."""
    if directory is None:
        return _packaged_text()
    return _load_text(directory)


@cache
def _packaged_text() -> SafetyPlanText:
    return _load_text(resources.files("olivia").joinpath("data/templates"))


def _load_text(base: Traversable | Path) -> SafetyPlanText:
    try:
        doc = safe_load(base.joinpath(_TEXT_FILE).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise SafetyPlanTextError(f"{_TEXT_FILE}: cannot read: {exc}") from exc
    root = _mapping(doc, "the file")
    if root.get("version") != 1:
        raise SafetyPlanTextError(f"{_TEXT_FILE}: version must be 1")
    sections = _mapping(root.get("sections"), "sections")
    if set(sections) != {s.value for s in SECTIONS}:
        raise SafetyPlanTextError(f"{_TEXT_FILE}: sections must be exactly the five sections")
    titles: dict[Section, str] = {}
    prompts: dict[Section, str] = {}
    for section in SECTIONS:
        entry = _mapping(sections[section.value], f"sections.{section.value}")
        titles[section] = _string(entry.get("title"), f"sections.{section.value}.title")
        prompts[section] = _string(entry.get("prompt"), f"sections.{section.value}.prompt")
    command_raw = _mapping(root.get("command"), "command")
    missing = [key for key in _COMMAND_KEYS if key not in command_raw]
    if missing:
        raise SafetyPlanTextError(f"{_TEXT_FILE}: command is missing {missing}")
    command = {key: _string(command_raw[key], f"command.{key}") for key in _COMMAND_KEYS}
    crisis = _mapping(root.get("crisis"), "crisis")
    intro = _string(crisis.get("intro"), "crisis.intro")
    suggestion = _string(root.get("suggestion"), "suggestion")
    reminder = _string(crisis.get("reminder"), "crisis.reminder")
    reminder_people = _string(crisis.get("reminder_people"), "crisis.reminder_people")
    people_heading = _string(crisis.get("farewell_people"), "crisis.farewell_people")
    unreadable = _string(crisis.get("unreadable"), "crisis.unreadable")
    unslotted = (intro, suggestion, reminder, people_heading, unreadable)
    if any(_SLOT_RE.search(text) for text in unslotted):
        raise SafetyPlanTextError(
            f"{_TEXT_FILE}: crisis.intro, crisis.reminder, crisis.farewell_people, "
            "crisis.unreadable and suggestion take no slots"
        )
    if set(_SLOT_RE.findall(reminder_people)) != {"name"}:
        raise SafetyPlanTextError(f"{_TEXT_FILE}: crisis.reminder_people needs exactly {{name}}")
    return SafetyPlanText(
        titles,
        prompts,
        command,
        intro,
        suggestion,
        reminder,
        reminder_people,
        people_heading,
        unreadable,
    )


def _fill(template: str, **values: object) -> str:
    text = template
    for name, value in values.items():
        text = text.replace("{" + name + "}", str(value))
    return text


# -- the crisis block -------------------------------------------------------------------------


def crisis_block(plan: SafetyPlan | None, text: SafetyPlanText | None = None) -> str:
    """The plan block for a crisis reply: the fixed intro line, then sections 2-4.

    Only sections with entries are listed. ``""`` when there is nothing to show (no plan,
    or none of the three sections filled). Section 5 is never part of it.
    """
    if plan is None:
        return ""
    wording = load_safety_plan_text() if text is None else text
    parts: list[str] = []
    for section in CRISIS_SECTIONS:
        lines = plan.lines(section)
        if lines:
            parts.append("\n".join([f"{wording.titles[section]}：", *(f"· {x}" for x in lines)]))
    if not parts:
        return ""
    return "\n".join([wording.crisis_intro, *parts])


def crisis_reminder(plan: SafetyPlan | None, text: SafetyPlanText | None = None) -> str:
    """The one line a crisis reply carries once the plan was shown in full (S5).

    With people in section 4 it names them (names only, never a number): "你的安全计划里有
    表姐、小周……"; with only sections 2 or 3 filled it points back at the plan in general.
    ``""`` when :func:`crisis_block` would be empty too.
    """
    if not crisis_block(plan, text) or plan is None:
        return ""
    wording = load_safety_plan_text() if text is None else text
    if plan.people:
        names = "、".join(contact.name for contact in plan.people)
        return _fill(wording.crisis_reminder_people, name=names)
    return wording.crisis_reminder


def farewell_people(plan: SafetyPlan | None, text: SafetyPlanText | None = None) -> str:
    """Section 4's people (name and phone) under ``crisis.farewell_people``, for a crisis
    farewell (S5); ``""`` without any."""
    if plan is None or not plan.people:
        return ""
    wording = load_safety_plan_text() if text is None else text
    lines = plan.lines(Section.PEOPLE)
    return "\n".join([wording.farewell_people, *(f"· {line}" for line in lines)])


def without_crisis_entries(
    plan: SafetyPlan | None, alarms: Callable[[str], bool]
) -> SafetyPlan | None:
    """``plan`` without the entries of sections 2-4 that ``alarms`` (a crisis sentence),
    so a crisis reply never reads one back; a contact goes by its name. Sections 1 and 5
    are kept whole (a crisis reply never shows them). For plans saved before the command
    screened these sections; nothing is written."""
    if plan is None:
        return None
    return replace(
        plan,
        coping=tuple(x for x in plan.coping if not alarms(x)),
        distraction=tuple(x for x in plan.distraction if not alarms(x)),
        people=tuple(c for c in plan.people if not alarms(c.name)),
    )


# -- storage ----------------------------------------------------------------------------------


class SafetyPlanStore:
    """The sealed plan under ``base_dir`` (default: the app data directory).

    Pass the profile store's ``vault`` so every store shares one view of the keys.
    """

    def __init__(self, base_dir: Path | None = None, vault: Vault | None = None) -> None:
        directory = app_data_dir() if base_dir is None else base_dir
        self.path: Path = directory / SAFETY_PLAN_FILENAME
        self.marker: Path = directory / SUGGESTED_FILENAME
        self.vault: Vault = Vault(directory) if vault is None else vault

    def exists(self) -> bool:
        return self.path.is_file()

    def available(self) -> bool:
        """Whether the keychain answers now, so a plan can be sealed and opened."""
        return self.vault.available()

    def load(self) -> SafetyPlan | None:
        """The saved plan, or None when there is none.

        Raises :class:`KeychainUnavailableError` while the keychain does not answer,
        :class:`SafetyPlanDamagedError` when the file can never be opened again and its
        :class:`SafetyPlanUnreadableError` when the system will not read the file.
        """
        try:
            blob = self.path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise SafetyPlanUnreadableError("the safety plan's file cannot be read") from exc
        try:
            raw = self.vault.open(SAFETY_PLAN_STORE, blob, label=_LABEL)
            return SafetyPlan.from_json(raw)
        except KeychainUnavailableError:
            raise
        except (KeyMissingError, DecryptionError, ValueError) as exc:
            raise SafetyPlanDamagedError("the saved safety plan cannot be opened") from exc

    def load_quietly(self) -> SafetyPlan | None:
        """:meth:`load` for the chat: any failure is just "no plan" and nothing changes."""
        try:
            return self.load()
        except (KeychainUnavailableError, SafetyPlanDamagedError):
            return None

    def save(self, plan: SafetyPlan) -> None:
        """Seal and write ``plan``; an empty plan clears the store instead.

        Raises :class:`KeychainUnavailableError` (nothing written) without a keychain.
        """
        if plan.is_empty:
            self.clear()
            return
        blob = self.vault.seal(SAFETY_PLAN_STORE, plan.to_json(), label=_LABEL)
        atomic_write_bytes(self.path, blob, snapshot=False)

    def clear(self) -> None:
        """Delete the plan and make every copy ever sealed unreadable."""
        self.shred()

    def shred(self) -> None:
        """Make every plan ever written unreadable (``olivia forget``, B5)."""
        remove_file(self.path)
        if self.vault.has_data_key(SAFETY_PLAN_STORE):
            self.vault.shred(SAFETY_PLAN_STORE)

    def should_suggest(self) -> bool:
        """No plan, never suggested on this device, and a keychain to save one with."""
        return not self.marker.exists() and not self.exists() and self.available()

    def mark_suggested(self) -> None:
        """Remember (an empty file, no user data) that the suggestion line was said."""
        if not self.marker.exists():
            self.marker.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_bytes(self.marker, b"", snapshot=False)


# -- the command ------------------------------------------------------------------------------

Ask = Callable[[], str | None]
Say = Callable[[str], None]


class Screened(StrEnum):
    """What the crisis screen made of one reply (the CLI shows the numbers and asks)."""

    CLEAR = "clear"
    """Not a crisis sentence."""
    GO_ON = "go_on"
    """A crisis sentence: the numbers were shown and the user chose to go on."""
    LEAVE = "leave"
    """A crisis sentence: the numbers were shown and the user chose to leave (or the
    input ended at that choice)."""


Screen = Callable[[str], Screened]

# Round 5 (复测 q4 SP-1): what puts a means out of reach, and what keeps it close.
_PROTECTIVE: Final = re.compile(
    r"交给|交出|上交|保管|收走|拿走|锁起来|锁上|锁好|上锁|锁进|扔掉|扔了|扔进|丢掉|丢了|丢进|倒掉|冲掉|"
    r"还给|退掉|退货|取消|删掉|不放在|不留在|不囤|不攒|不存|不买|远离|不去|不一个人去|不靠近|按天领|每次只拿"
)
_KEEPS_CLOSE: Final = re.compile(
    r"藏|自己留|自己保管|自己收|只有我|偷偷|随时|以防万一|万一用|备着|带在身上|放在身边|放在床头|枕头|不告诉|"
    r"多攒|多买|再买|继续"
)


def protective(text: str) -> bool:
    """Whether a section 5 reply puts a means away (module docstring, round 5): a step
    that hands it over, locks it up, throws it out or keeps away from a place, with nothing
    of keeping it close."""
    folded = _fold(text)
    return bool(_PROTECTIVE.search(folded)) and not _KEEPS_CLOSE.search(folded)


class _EndOfInput(Exception):
    """The input ended mid-exchange, or Ctrl-C was pressed (``interrupted``); ``partial``
    holds what the section being written had before it (QA q4 SP-7, SP-12)."""

    def __init__(self, partial: tuple[object, ...] = (), *, interrupted: bool = False) -> None:
        super().__init__("end of input")
        self.partial = partial
        self.interrupted = interrupted


class _Left(Exception):
    """The user chose to leave after a crisis sentence; ``partial`` holds what the
    section being written had before it."""

    def __init__(self, partial: tuple[object, ...] = ()) -> None:
        super().__init__("left")
        self.partial = partial


def _fold(text: str) -> str:
    """NFKC (full-width digits and spaces), trimmed: the reply folding for choices."""
    return unicodedata.normalize("NFKC", text).strip()


def clean_phone(raw: str) -> str | None:
    """The phone number as it will be shown, or None when it is not one."""
    phone = " ".join(_fold(raw).split())
    digits = sum(ch.isdigit() for ch in phone)
    if len(phone) > MAX_PHONE_CHARS or digits < MIN_PHONE_DIGITS or not _PHONE_RE.fullmatch(phone):
        return None
    return phone


def split_contact(raw: str) -> tuple[str, str]:
    """``(name, phone)`` from one reply in section 4; ``phone`` is ``""`` when the reply
    holds none, ``name`` is ``""`` when it is a phone number alone.

    People often write both on one line ("表姐 13800000000"); the number is taken off
    the end only when :func:`clean_phone` accepts it, so a name with a digit in it
    ("小王2号") stays whole. Without a number the reply is returned as typed, with its
    whitespace squashed; with one, both parts are NFKC-folded.
    """
    folded = _fold(raw)
    alone = clean_phone(folded)
    if alone is not None:
        return "", alone
    match = _CONTACT_RE.fullmatch(folded)
    if match is not None:
        name = " ".join(match["name"].strip(_NAME_TRIM).split())
        phone = clean_phone(match["phone"])
        if name and phone is not None:
            return name, phone
    return " ".join(raw.split()), ""


class _Command:
    def __init__(
        self,
        ask: Ask,
        say: Say,
        store: SafetyPlanStore,
        text: SafetyPlanText,
        screen: Screen | None = None,
        protective_screen: Screen | None = None,
    ) -> None:
        self._ask_raw = ask
        self._say_raw = say
        self._store = store
        self._text = text
        self._cmd = text.command
        self._screen = screen
        self._protective_screen = screen if protective_screen is None else protective_screen
        self._since_ask: list[str] = []
        """What was said since the question began (:meth:`_question`), to ask it again."""
        self._saved_any = False
        self._had_plan = False
        self._new_plan = False

    def run(self) -> int:
        cmd = self._cmd
        if not self._store.available():
            self._say(cmd["locked"] if self._store.exists() else cmd["no_keychain"])
            return 1
        try:
            plan = self._store.load()
        except KeychainUnavailableError:
            self._say(cmd["locked"])
            return 1
        except SafetyPlanUnreadableError:
            self._say(cmd["unreadable"])
            return 1
        except SafetyPlanDamagedError:
            self._say(cmd["damaged"])
            self._say("")
            plan = None
        try:
            if plan is None or plan.is_empty:
                return self._new()
            return self._existing(plan)
        except _EndOfInput as ended:
            # QA q4 P12: only looking at a saved plan loses nothing; an edit cut short
            # keeps the sections already saved. QA q4 SP-12: a new plan cut short keeps
            # what was written, and Ctrl-C ends here with this command's own words.
            if ended.interrupted:
                self._say("")
            if self._saved_any:
                self._say(cmd["left_saved"] if self._new_plan else cmd["saved"])
            else:
                self._say(cmd["unchanged"] if self._had_plan else cmd["left"])
            return 0
        except _Left:
            self._say(cmd["crisis_left_saved"] if self._saved_any else cmd["crisis_left"])
            return 0
        except KeychainUnavailableError:
            self._say(cmd["locked"])
            return 1

    # -- flows ----------------------------------------------------------------------------

    def _new(self) -> int:
        self._new_plan = True
        self._say(self._cmd["intro"])
        self._say("")
        plan = SafetyPlan()
        for section in SECTIONS:
            try:
                values = self._section(section, None)
            except _EndOfInput as ended:
                # QA q4 SP-12: what was written before the input ended (or Ctrl-C) is kept.
                plan = _with_section(plan, section, ended.partial)
                if not plan.is_empty:
                    self._store.save(plan)
                    self._saved_any = True
                raise
            except _Left as left:
                # What was written before the crisis sentence is kept: sections 2-4 are
                # what a crisis reply shows, and they may be needed soon.
                plan = _with_section(plan, section, left.partial)
                if not plan.is_empty:
                    self._store.save(plan)
                    self._saved_any = True
                raise
            plan = _with_section(plan, section, values)
            self._say("")
        if plan.is_empty:
            self._say(self._cmd["nothing_saved"])
            return 0
        self._store.save(plan)
        self._show(plan)
        self._say("")
        self._say(self._cmd["saved"])
        return 0

    def _existing(self, plan: SafetyPlan) -> int:
        cmd = self._cmd
        self._had_plan = True
        self._show(plan)
        self._say("")
        while True:
            self._question()
            self._say(cmd["menu"])
            self._say(f"  1. {cmd['menu_edit']}")
            self._say(f"  2. {cmd['menu_clear']}")
            choice = _fold(self._ask())
            self._say("")
            if not choice:
                self._say(cmd["unchanged"])
                return 0
            if choice == "1":
                return self._edit(plan)
            if choice == "2":
                return self._clear()
            self._say(cmd["menu_unknown"])

    def _edit(self, plan: SafetyPlan) -> int:
        cmd = self._cmd
        changed = False
        while True:
            self._question()
            self._say(cmd["pick_section"])
            for number, section in enumerate(SECTIONS, start=1):
                self._say(f"  {number}. {self._text.titles[section]}")
            choice = _fold(self._ask())
            self._say("")
            if not choice:
                break
            if not (choice.isdigit() and 1 <= int(choice) <= len(SECTIONS)):
                self._say(cmd["pick_unknown"])
                continue
            section = SECTIONS[int(choice) - 1]
            # Leaving mid-section keeps that section as it was (an edit replaces it whole);
            # lines already typed for it are said not to be saved (QA q4 SP-7).
            try:
                values = self._section(section, plan)
            except _EndOfInput as ended:
                if ended.partial:
                    if ended.interrupted:
                        self._say("")
                        ended.interrupted = False
                    title = self._text.titles[section]
                    self._say(_fill(cmd["edit_not_saved"], title=title))
                raise
            self._say("")
            updated = _with_section(plan, section, values)
            if updated != plan:
                plan = updated
                # Saved section by section, so an interrupted edit keeps what was written.
                self._store.save(plan)
                self._saved_any = changed = True
        if not changed:
            self._say(cmd["unchanged"])
        elif plan.is_empty:
            self._say(cmd["cleared"])
        else:
            self._show(plan)
            self._say("")
            self._say(cmd["saved"])
        return 0

    def _clear(self) -> int:
        self._question()
        self._say(self._cmd["clear_confirm"])
        if _fold(self._ask()) in CLEAR_CONFIRMATIONS:
            self._store.clear()
            self._say(self._cmd["cleared"])
        else:
            self._say(self._cmd["unchanged"])
        return 0

    # -- one section ----------------------------------------------------------------------

    def _section(self, section: Section, current: SafetyPlan | None) -> tuple[object, ...]:
        """New values for ``section``; with ``current`` (an edit), an empty first reply
        keeps the current values and ``0`` clears them."""
        cmd = self._cmd
        number = SECTIONS.index(section) + 1
        title = self._text.titles[section]
        self._say(_fill(cmd["section_heading"], n=number, total=len(SECTIONS), title=title))
        self._say(self._text.prompts[section])
        kept: tuple[object, ...] = ()
        if current is not None:
            kept = current.people if section is Section.PEOPLE else current.lines(section)
            shown = current.lines(section)
            if shown:
                self._say("\n".join([cmd["current_heading"], *(f"· {x}" for x in shown)]))
                self._say(_fill(cmd["rewrite_help"], max_entries=MAX_ENTRIES))
            else:  # dogfood P7: never "现在写的是：" with nothing after it
                self._say(cmd["current_empty"])
                if section is not Section.PEOPLE:
                    self._say(_fill(cmd["entry_help"], max_entries=MAX_ENTRIES))
        elif section is not Section.PEOPLE:
            self._say(_fill(cmd["entry_help"], max_entries=MAX_ENTRIES))
        if section is Section.PEOPLE:
            people: list[Contact] = []
            try:
                return self._people(kept, people, editing=current is not None)
            except _Left:
                raise _Left(tuple(people)) from None
            except _EndOfInput as ended:
                raise _EndOfInput(tuple(people), interrupted=ended.interrupted) from None
        entries: list[str] = []
        try:
            return self._entries(section, kept, entries, editing=current is not None)
        except _Left:
            raise _Left(tuple(entries)) from None
        except _EndOfInput as ended:
            raise _EndOfInput(tuple(entries), interrupted=ended.interrupted) from None

    def _entries(
        self, section: Section, kept: tuple[object, ...], entries: list[str], *, editing: bool
    ) -> tuple[object, ...]:
        while len(entries) < MAX_ENTRIES:
            reply = " ".join(self._ask(section).split())
            if not entries and editing and not reply:
                return kept
            if not entries and _fold(reply) == CLEAR_SECTION:
                return ()
            if not reply:
                return tuple(entries)
            while len(reply) > MAX_ENTRY_CHARS:
                # Said, never silent: the entry is not kept until a shorter one is written,
                # and Enter here drops only this entry, not the rest of the section.
                self._say(_fill(self._cmd["entry_too_long"], max_chars=MAX_ENTRY_CHARS))
                reply = " ".join(self._ask(section).split())
            if not reply:
                self._say(self._cmd["entry_not_saved"])
                continue
            entries.append(reply)
        self._say(_fill(self._cmd["section_full"], max_entries=MAX_ENTRIES))
        return tuple(entries)

    def _people(
        self, kept: tuple[object, ...], people: list[Contact], *, editing: bool
    ) -> tuple[object, ...]:
        cmd = self._cmd
        while len(people) < MAX_ENTRIES:
            self._say(_fill(cmd["person_name"], n=len(people) + 1))
            name = " ".join(self._ask(Section.PEOPLE).split())
            if not people and editing and not name:
                return kept
            if not people and _fold(name) == CLEAR_SECTION:
                return ()
            if not name:
                return tuple(people)
            contact = self._contact(name)
            if contact is None:
                self._say(cmd["entry_not_saved"])
            else:
                people.append(contact)
        self._say(_fill(cmd["section_full"], max_entries=MAX_ENTRIES))
        return tuple(people)

    def _contact(self, reply: str) -> Contact | None:
        """One person from the reply to "名字或称呼" (dogfood I10).

        A phone number on the same line is kept and not asked for again; a number alone
        asks for the name; a name over :data:`MAX_NAME_CHARS` asks for a shorter one and
        keeps the number. None only when the user then presses Enter (the caller says
        that this person was not saved).
        """
        cmd = self._cmd
        phone = ""
        while True:
            name, found = split_contact(reply)
            phone = found or phone
            if name and len(name) <= MAX_NAME_CHARS:
                break
            if name:
                self._say(_fill(cmd["name_too_long"], max_chars=MAX_NAME_CHARS))
            else:
                self._say(cmd["name_for_phone"])
            reply = " ".join(self._ask(Section.PEOPLE).split())
            if not reply:
                return None
        if phone:
            self._say(_fill(cmd["person_with_phone"], name=name))
            return Contact(name, phone)
        return Contact(name, self._phone(name))

    def _phone(self, name: str) -> str:
        while True:
            self._say(_fill(self._cmd["person_phone"], name=name))
            reply = self._ask(Section.PEOPLE).strip()
            if not reply:
                return ""
            phone = clean_phone(reply)
            if phone is not None:
                return phone
            self._say(self._cmd["phone_invalid"])

    # -- helpers --------------------------------------------------------------------------

    def _show(self, plan: SafetyPlan) -> None:
        cmd = self._cmd
        blocks = [cmd["show_heading"]]
        for number, section in enumerate(SECTIONS, start=1):
            lines = plan.lines(section)
            body = [f"· {x}" for x in lines] if lines else [cmd["empty_section"]]
            blocks.append("\n".join([f"{number}. {self._text.titles[section]}", *body]))
        self._say("\n".join(blocks))

    def _say(self, text: str) -> None:
        self._since_ask.append(text)
        self._say_raw(text)

    def _question(self) -> None:
        """What is said from here on is the question a crisis sentence brings back."""
        self._since_ask = []

    def _ask(self, section: Section | None = None) -> str:
        """One reply, screened first when there is a screen. ``section`` is the section the
        reply is for (None for a menu choice): a crisis sentence is kept in sections 1 and
        5 after "go on"; anywhere else it is dropped and the question asked again."""
        while True:
            question, self._since_ask = self._since_ask, []
            try:
                reply = self._ask_raw()
            except KeyboardInterrupt:  # QA q4 SP-12: like the end of input, said here
                raise _EndOfInput(interrupted=True) from None
            if reply is None:
                raise _EndOfInput
            screen = self._screen
            if section is Section.ENVIRONMENT and protective(reply):
                screen = self._protective_screen
            try:
                verdict = Screened.CLEAR if screen is None else screen(reply)
            except KeyboardInterrupt:  # at the crisis choice: as when the input ends there
                raise _Left from None
            if verdict is Screened.CLEAR:
                return reply
            if verdict is Screened.LEAVE:
                raise _Left
            cmd = self._cmd
            if section in KEPT_CRISIS_SECTIONS:
                self._say_raw(_fill(cmd["crisis_kept"], title=self._text.titles[section]))
                self._say_raw("")
                return reply
            if section is None:
                self._say_raw(cmd["crisis_retry"])
            else:
                self._say_raw(_fill(cmd["crisis_not_kept"], title=self._text.titles[section]))
            self._say_raw("")
            # Only the question comes again (QA q4 P1, P2): a menu's lines; for a person the
            # one line asking for them; for an entry nothing, since crisis_not_kept already
            # says to write another or press Enter.
            if section is not None:
                lines = [line for line in question if line]
                question = lines[-1:] if section is Section.PEOPLE else []
            while question and not question[0]:
                question.pop(0)
            for line in question:
                self._say(line)


def run_command(
    ask: Ask,
    say: Say,
    store: SafetyPlanStore,
    text: SafetyPlanText | None = None,
    *,
    screen: Screen | None = None,
    protective_screen: Screen | None = None,
) -> int:
    """``olivia safety-plan`` for an adult profile: fill a new plan, or show the saved one
    and offer to edit a section or clear it. ``ask`` returns one reply line (None at end
    of input); ``say`` prints one block; ``screen`` (the CLI's crisis screen: it shows the
    numbers and asks whether to go on) sees every reply first (module docstring), except a
    protective section 5 reply, which ``protective_screen`` sees when given (round 5).
    Returns the exit status (1: no keychain, or the saved plan cannot be opened now)."""
    wording = load_safety_plan_text() if text is None else text
    return _Command(ask, say, store, wording, screen, protective_screen).run()
