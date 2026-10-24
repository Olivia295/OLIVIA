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
_LABEL: Final = "plan"
_VERSION: Final = 1
_TEXT_FILE: Final = "safety_plan.yaml"
_PHONE_RE: Final = re.compile(r"[0-9+\-() ]+")
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

_COMMAND_KEYS: Final = (
    "intro",
    "section_heading",
    "entry_help",
    "rewrite_help",
    "current_heading",
    "entry_too_long",
    "section_full",
    "person_name",
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
    "not_onboarded",
    "adults_only",
)


class SafetyPlanTextError(Exception):
    """``safety_plan.yaml`` is missing, malformed or uses an unknown slot."""


class SafetyPlanDamagedError(Exception):
    """The saved plan cannot be opened (its key is gone or the file was changed)."""


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

    def all_texts(self) -> tuple[str, ...]:
        """Every sentence in the file, for the WILLOW and gate checks in the tests."""
        return (
            *self.titles.values(),
            *self.prompts.values(),
            *self.command.values(),
            self.crisis_intro,
            self.suggestion,
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
    if _SLOT_RE.search(intro) or _SLOT_RE.search(suggestion):
        raise SafetyPlanTextError(f"{_TEXT_FILE}: crisis.intro and suggestion take no slots")
    return SafetyPlanText(titles, prompts, command, intro, suggestion)


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

        Raises :class:`KeychainUnavailableError` while the keychain does not answer and
        :class:`SafetyPlanDamagedError` when the file can never be opened again.
        """
        try:
            blob = self.path.read_bytes()
        except FileNotFoundError:
            return None
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


class _EndOfInput(Exception):
    """The input ended mid-exchange."""


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


class _Command:
    def __init__(self, ask: Ask, say: Say, store: SafetyPlanStore, text: SafetyPlanText) -> None:
        self._ask_raw = ask
        self._say = say
        self._store = store
        self._text = text
        self._cmd = text.command

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
        except SafetyPlanDamagedError:
            self._say(cmd["damaged"])
            self._say("")
            plan = None
        try:
            if plan is None or plan.is_empty:
                return self._new()
            return self._existing(plan)
        except _EndOfInput:
            self._say(cmd["left"])
            return 0
        except KeychainUnavailableError:
            self._say(cmd["locked"])
            return 1

    # -- flows ----------------------------------------------------------------------------

    def _new(self) -> int:
        self._say(self._cmd["intro"])
        self._say("")
        plan = SafetyPlan()
        for section in SECTIONS:
            plan = _with_section(plan, section, self._section(section, None))
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
        self._show(plan)
        self._say("")
        while True:
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
            values = self._section(section, plan)
            self._say("")
            updated = _with_section(plan, section, values)
            if updated != plan:
                plan = updated
                # Saved section by section, so an interrupted edit keeps what was written.
                self._store.save(plan)
                changed = True
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
        self._say(self._cmd["clear_confirm"])
        if _fold(self._ask()) == "1":
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
            self._say("\n".join([cmd["current_heading"], *(f"· {x}" for x in shown)]))
            self._say(_fill(cmd["rewrite_help"], max_entries=MAX_ENTRIES))
        elif section is not Section.PEOPLE:
            self._say(_fill(cmd["entry_help"], max_entries=MAX_ENTRIES))
        if section is Section.PEOPLE:
            return self._people(kept, editing=current is not None)
        return self._entries(kept, editing=current is not None)

    def _entries(self, kept: tuple[object, ...], *, editing: bool) -> tuple[object, ...]:
        entries: list[str] = []
        while len(entries) < MAX_ENTRIES:
            reply = " ".join(self._ask().split())
            if not entries and editing and not reply:
                return kept
            if not entries and _fold(reply) == CLEAR_SECTION:
                return ()
            if not reply:
                return tuple(entries)
            if len(reply) > MAX_ENTRY_CHARS:
                self._say(_fill(self._cmd["entry_too_long"], max_chars=MAX_ENTRY_CHARS))
                continue
            entries.append(reply)
        self._say(_fill(self._cmd["section_full"], max_entries=MAX_ENTRIES))
        return tuple(entries)

    def _people(self, kept: tuple[object, ...], *, editing: bool) -> tuple[object, ...]:
        cmd = self._cmd
        people: list[Contact] = []
        while len(people) < MAX_ENTRIES:
            self._say(_fill(cmd["person_name"], n=len(people) + 1))
            name = " ".join(self._ask().split())
            if not people and editing and not name:
                return kept
            if not people and _fold(name) == CLEAR_SECTION:
                return ()
            if not name:
                return tuple(people)
            if len(name) > MAX_NAME_CHARS:
                self._say(_fill(cmd["entry_too_long"], max_chars=MAX_NAME_CHARS))
                continue
            people.append(Contact(name, self._phone(name)))
        self._say(_fill(cmd["section_full"], max_entries=MAX_ENTRIES))
        return tuple(people)

    def _phone(self, name: str) -> str:
        while True:
            self._say(_fill(self._cmd["person_phone"], name=name))
            reply = self._ask().strip()
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

    def _ask(self) -> str:
        reply = self._ask_raw()
        if reply is None:
            raise _EndOfInput
        return reply


def run_command(
    ask: Ask, say: Say, store: SafetyPlanStore, text: SafetyPlanText | None = None
) -> int:
    """``olivia safety-plan`` for an adult profile: fill a new plan, or show the saved one
    and offer to edit a section or clear it. ``ask`` returns one reply line (None at end
    of input); ``say`` prints one block. Returns the exit status (1: no keychain, or the
    saved plan cannot be opened now)."""
    wording = load_safety_plan_text() if text is None else text
    return _Command(ask, say, store, wording).run()
