"""Seeing, editing and forgetting what OLIVIA remembers (next-phase step B5; PRD JTBD 4,
MIYI-05, feature 5, RSK-06).

``olivia memory`` (:func:`run_memory`) shows, on screen only, what this device holds: the
ledger entries oldest first and numbered, each as its templated summary (a session, or a
B6 journal record: offered, seen or declined, helpful or not) or, for a note, the
user's words verbatim (``Ledger.body``; dates and times in the profile's current timezone,
PRD Q-8), then the other data by name only (the profile, how many taboo topics it holds,
whether health information is filled in, whether a safety plan exists, how many cards the
kit holds, whether a care marker waits). The method preferences are listed one method at
a time, by the card title the user saw, each with one plain sentence and never a number
(``memory/preferences.py``, RSK-06); their numbers are the ones ``forget --method`` takes.
Health details, the topics and the plan itself are never printed here: they have their
own commands. Entries that do not open are counted, never shown. Nothing is written and
nothing is exported.

``olivia memory --edit N`` (:func:`run_edit`) changes the words of note ``N``: the current
words, then the new ones, then the typed confirmation; ``Ledger.edit_note`` re-keys the
ledger like a single-entry forget, so the old words are crypto-shredded. A summary or
journal record is the program's own templated record and cannot be edited.

``olivia forget`` (:func:`run_forget`) removes one of six things, picked from a numbered
menu or by a flag (:class:`Target`):

1. one ledger entry, by the number ``olivia memory`` shows: ``Ledger.forget_entry``
   re-keys the ledger (the other entries are re-sealed under a fresh key through a
   staging store, the old key is shredded), so the entry's old ciphertext never opens
   again; entries that no longer open are dropped and counted;
2. every chat record: the ledger (``Ledger.shred``) and the care marker (``CareStore.shred``);
3. one method's preference, by the number ``olivia memory`` lists it under: its posterior
   is removed in every spectrum and the state re-sealed under a fresh key through a
   staging store (``StateStore.rekey``), the kit and the other methods kept;
4. the kit and the method preferences (``StateStore.shred``);
5. the safety plan (``SafetyPlanStore.shred``);
6. everything (:func:`forget_all`): ``Vault.shred_all`` destroys every wrapped data key
   and the master key in the OS keychain first, then every file this package writes is
   removed (:data:`DATA_FILES`, :data:`DATA_DIRS`, stray temporary files), the profile
   and its snapshots included, so the next ``olivia chat`` starts onboarding afresh;
   first, the ``on_forget_all`` hooks run (the CLI passes the B9 one, which removes the
   reminder job and its "last notified" file). The empty marker :data:`FORGET_ALL_MARKER`
   is written before anything goes and removed after the last file, so a run that was
   killed half-way is recognised (robustness E2: the CLI then asks for ``forget --all``
   again instead of reporting a keychain that does not answer). Without any keychain in
   this session while key files exist, the master key sits in a keychain that cannot be
   reached: the files still go, and the user is told to run it again where the keychain
   works (robustness S5).

Options 1-5 crypto-shred: the store's data key is destroyed and the master key rotated
(``Vault.shred``), so a copy of the old ciphertext, or of the old key file, never opens
again. They need the keychain to answer, so while it is locked nothing is changed. A
store added later must register its files in :data:`DATA_FILES` or :data:`DATA_DIRS`
(the CLI test that runs a whole chat and then ``forget --all`` checks that nothing is
left).

Every deletion (and an edit) first shows what it removes and asks for the typed
confirmation word, 「确认」 or 「确定」, unless ``assume_yes``; anything else or the end of
input cancels and says so. A number given on the command line (``--entry``, ``--method``,
``--edit``) that names nothing is a wrong value, exit 2 (README "退出码"); one typed at a
prompt is exit 1. An age-gate refusal record (a declared minor, ruling 22) holds no
personal data and is kept, so forgetting never reopens onboarding there; ``--all``
removes anything else and says in one line that this record stays and why. All wording
is in ``olivia/data/templates/forget.yaml`` (G-0 draft). Nothing here logs.
"""

from __future__ import annotations

import contextlib
import re
import unicodedata
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, tzinfo
from enum import Enum, StrEnum
from functools import cache
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Final

import yaml

from olivia.core.chang.care import CARE_FILENAME, CARE_STORE, CareStore
from olivia.core.chang.profile import (
    PROFILE_FILENAME,
    PROFILE_REKEY_FILENAME,
    RECOVERED_FILENAME,
    ProfileCorruptError,
    ProfileLockedError,
    ProfileStore,
)
from olivia.core.chang.safety_plan import (
    SAFETY_PLAN_FILENAME,
    SAFETY_PLAN_STORE,
    SUGGESTED_FILENAME,
    SafetyPlanDamagedError,
    SafetyPlanStore,
)
from olivia.core.crypto.errors import KeychainUnavailableError, NoKeychainError
from olivia.core.crypto.vault import KEYS_DIRNAME, Vault
from olivia.core.memory.ledger import (
    LEDGER_DIRNAME,
    LEDGER_STORE,
    NOTE_MAX_CHARS,
    Ledger,
    LedgerEntry,
    LedgerUnavailableError,
    NoteEntry,
)
from olivia.core.memory.preferences import (
    MethodPreference,
    PreferenceStatus,
    method_preferences,
    without_method,
)
from olivia.core.memory.state import (
    STATE_FILENAME,
    STATE_REKEY_FILENAME,
    STATE_REKEY_STORE,
    STATE_STORE,
    CarriedState,
    StateStore,
)
from olivia.core.models import PersonaProfile
from olivia.core.storage import app_data_dir, atomic_write_bytes, remove_file
from olivia.core.taxonomy import Taxonomy, load_taxonomy
from olivia.core.yaml_load import safe_load

DATA_FILES: Final = (
    PROFILE_FILENAME,
    PROFILE_REKEY_FILENAME,
    RECOVERED_FILENAME,
    CARE_FILENAME,
    STATE_FILENAME,
    STATE_REKEY_FILENAME,
    SAFETY_PLAN_FILENAME,
    SUGGESTED_FILENAME,
)
"""Files directly in the data directory that ``forget --all`` removes."""
DATA_DIRS: Final = (LEDGER_DIRNAME, KEYS_DIRNAME, ".snapshots")
"""Directories in the data directory that ``forget --all`` empties and removes."""
FORGET_ALL_MARKER: Final = "forget-all.pending"
"""Empty; present only while a ``forget --all`` is under way (or was killed during one)."""

_TEXT_FILE: Final = "forget.yaml"
_SLOT_RE: Final = re.compile(r"\{([^{}]*)\}")
_ALLOWED_SLOTS: Final = frozenset({"n", "count", "date", "title", "status"})
_MEMORY_KEYS: Final = (
    "heading",
    "empty",
    "note",
    "unreadable",
    "others",
    "profile",
    "health",
    "safety_plan",
    "safety_plan_unreadable",
    "taboo",
    "kit",
    "preferences",
    "preference_item",
    "preference_unhelpful_recently",
    "preference_helpful",
    "preference_recovered",
    "state_unreadable",
    "care",
    "nothing_else",
    "hint",
    "edit_current",
    "edit_prompt",
    "edit_too_long",
    "edit_not_note",
    "edit_about",
    "edit_done",
    "edit_unchanged",
    "no_keychain",
    "locked",
    "adults_only",
)
_FORGET_KEYS: Final = (
    "menu",
    "entry",
    "ledger",
    "method",
    "kit",
    "safety_plan",
    "all",
    "pick_entry",
    "pick_method",
    "no_method",
    "nothing_method",
    "about_method",
    "done_method",
    "unknown_choice",
    "no_entry",
    "about_entry",
    "about_ledger",
    "about_kit",
    "about_safety_plan",
    "about_all",
    "confirm",
    "confirm_word",
    "confirm_also",
    "cancelled",
    "done_entry",
    "done_entry_dropped",
    "done_ledger",
    "done_kit",
    "done_safety_plan",
    "done_all",
    "keychain_left",
    "keychain_unreachable",
    "unfinished",
    "nothing_entry",
    "nothing_ledger",
    "nothing_kit",
    "nothing_safety_plan",
    "nothing_all",
    "locked",
    "adults_only",
    "about_all_minor",
    "done_all_minor",
    "kept_minor",
)

Ask = Callable[[], str | None]
Say = Callable[[str], None]


class Target(StrEnum):
    """What ``olivia forget`` removes; the menu shows them in this order."""

    ENTRY = "entry"
    LEDGER = "ledger"
    METHOD = "method"
    KIT = "kit"
    SAFETY_PLAN = "safety_plan"
    ALL = "all"


MENU: Final = tuple(Target)


# -- wording ----------------------------------------------------------------------------------


class ForgetTextError(Exception):
    """``forget.yaml`` is missing, malformed or incomplete."""


@dataclass(frozen=True)
class ForgetText:
    memory: Mapping[str, str]
    forget: Mapping[str, str]

    def all_texts(self) -> tuple[str, ...]:
        """Every sentence in the file, for the WILLOW and gate checks in the tests."""
        return (*self.memory.values(), *self.forget.values())


def load_forget_text(directory: Path | None = None) -> ForgetText:
    """Load and validate ``forget.yaml``; ``None`` reads the packaged copy (cached)."""
    if directory is None:
        return _packaged_text()
    return _load_text(directory)


@cache
def _packaged_text() -> ForgetText:
    return _load_text(resources.files("olivia").joinpath("data/templates"))


def _section(root: Mapping[str, object], name: str, keys: tuple[str, ...]) -> dict[str, str]:
    raw = root.get(name)
    if not isinstance(raw, dict) or set(raw) != set(keys):
        raise ForgetTextError(f"{_TEXT_FILE}: {name} must hold exactly {list(keys)}")
    out: dict[str, str] = {}
    for key in keys:
        value = raw[key]
        if not isinstance(value, str) or not value.strip():
            raise ForgetTextError(f"{_TEXT_FILE}: {name}.{key} must be a non-empty string")
        unknown = set(_SLOT_RE.findall(value)) - _ALLOWED_SLOTS
        if unknown:
            raise ForgetTextError(f"{_TEXT_FILE}: {name}.{key} uses unknown slots {unknown}")
        out[key] = value
    return out


def _load_text(base: Traversable | Path) -> ForgetText:
    try:
        doc = safe_load(base.joinpath(_TEXT_FILE).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ForgetTextError(f"{_TEXT_FILE}: cannot read: {exc}") from exc
    if not isinstance(doc, dict) or doc.get("version") != 1:
        raise ForgetTextError(f"{_TEXT_FILE}: must be a mapping with version 1")
    if set(doc) != {"version", "memory", "forget"}:
        raise ForgetTextError(f"{_TEXT_FILE}: sections must be version, memory and forget")
    memory = _section(doc, "memory", _MEMORY_KEYS)
    forget = _section(doc, "forget", _FORGET_KEYS)
    for word in ("confirm_word", "confirm_also"):
        if forget[word] not in forget["confirm"]:
            raise ForgetTextError(f"{_TEXT_FILE}: forget.confirm must name the {word}")
    return ForgetText(memory, forget)


def _fill(template: str, **values: object) -> str:
    text = template
    for name, value in values.items():
        text = text.replace("{" + name + "}", str(value))
    return text


# -- the stores -------------------------------------------------------------------------------


@dataclass(frozen=True)
class DataStores:
    """Every store in one data directory, sharing one vault (one view of the keys)."""

    base: Path
    vault: Vault
    profile: ProfileStore
    ledger: Ledger
    state: StateStore
    care: CareStore
    plan: SafetyPlanStore
    on_forget_all: tuple[Callable[[], object], ...] = ()
    """Run by ``forget --all`` before the files go: what lives outside the data
    directory (the B9 reminder job). Each handles its own failures."""
    method_titles: Mapping[str, str] = field(default_factory=dict)
    """Action id -> the card title the user saw, for the method preferences (RSK-06)."""
    taxonomy: Taxonomy | None = None
    """For the method preferences' priors; None loads the packaged taxonomy when needed."""

    def tax(self) -> Taxonomy:
        return load_taxonomy() if self.taxonomy is None else self.taxonomy

    @classmethod
    def open(
        cls,
        base_dir: Path | None = None,
        *,
        method_titles: Mapping[str, str] | None = None,
        on_forget_all: tuple[Callable[[], object], ...] = (),
        zone: tzinfo | None = None,
        taxonomy: Taxonomy | None = None,
    ) -> DataStores:
        """``zone``: the timezone the ledger shows times in (the profile's)."""
        base = app_data_dir() if base_dir is None else base_dir
        profile = ProfileStore(base)
        vault = profile.vault
        return cls(
            base=base,
            vault=vault,
            profile=profile,
            ledger=Ledger(base, vault, method_titles=method_titles, zone=zone),
            state=StateStore(base, vault),
            care=CareStore(base, vault),
            plan=SafetyPlanStore(base, vault),
            on_forget_all=on_forget_all,
            method_titles={} if method_titles is None else dict(method_titles),
            taxonomy=taxonomy,
        )


class _Keychain(Enum):
    OK = "ok"
    NONE = "none"
    LOCKED = "locked"


def _keychain(vault: Vault) -> _Keychain:
    try:
        vault.check()
    except NoKeychainError:
        return _Keychain.NONE
    except KeychainUnavailableError:
        return _Keychain.LOCKED
    return _Keychain.OK


def _profile_quietly(stores: DataStores) -> tuple[bool, PersonaProfile | None]:
    """(the profile file exists, the profile when it can be read now)."""
    exists = stores.profile.path.is_file()
    try:
        return exists, stores.profile.load()
    except (ProfileCorruptError, ProfileLockedError):
        return exists, None


# -- olivia memory ----------------------------------------------------------------------------


def _entry_lines(ledger: Ledger, number: int, entry: LedgerEntry, text: ForgetText) -> list[str]:
    body = ledger.body(entry).splitlines() or [""]
    if isinstance(entry, NoteEntry):
        heading = _fill(text.memory["note"], date=ledger.local(entry.created_at).date().isoformat())
        rest = body
    else:
        heading, rest = body[0].lstrip("#").strip(), body[1:]
    return [f"{number}. {heading}", *(f"   {line}" for line in rest)]


def _preferences(
    stores: DataStores, now: datetime
) -> tuple[CarriedState | None, tuple[MethodPreference, ...]]:
    """The kit store's state and its method preferences (RSK-06); none when it does
    not open now."""
    state = stores.state.load()
    if state is None:
        return None, ()
    return state, method_preferences(stores.tax(), state.bandit, now, stores.method_titles)


_STATUS_KEYS: Final = {
    PreferenceStatus.UNHELPFUL_RECENTLY: "preference_unhelpful_recently",
    PreferenceStatus.HELPFUL: "preference_helpful",
    PreferenceStatus.RECOVERED: "preference_recovered",
}


def _preference_lines(preferences: tuple[MethodPreference, ...], text: ForgetText) -> list[str]:
    """One numbered line per method: its title and a plain sentence, never numbers."""
    m = text.memory
    return [
        "   " + _fill(m["preference_item"], n=n, title=p.title, status=m[_STATUS_KEYS[p.status]])
        for n, p in enumerate(preferences, start=1)
    ]


def _other_lines(
    stores: DataStores,
    profile: PersonaProfile | None,
    profile_exists: bool,
    text: ForgetText,
    now: datetime,
) -> list[str]:
    """The other data by name, one ``- `` line each; the method preferences are listed
    under theirs."""
    m = text.memory
    found: list[str] = []
    if profile_exists:
        found.append(f"- {m['profile']}")
    if profile is not None and profile.taboo_topics:  # dogfood P9: a count, not the topics
        found.append("- " + _fill(m["taboo"], count=len(profile.taboo_topics)))
    if profile is not None and (profile.clinical_history or profile.contraindications):
        found.append(f"- {m['health']}")
    if stores.plan.exists():
        found.append(f"- {m[_plan_key(stores.plan)]}")
    state, preferences = _preferences(stores, now)
    if state is not None:
        if state.kit:
            found.append("- " + _fill(m["kit"], count=len(state.kit)))
        if preferences:
            found.append(f"- {m['preferences']}")
            found.extend(_preference_lines(preferences, text))
    elif stores.state.path.is_file():
        found.append(f"- {m['state_unreadable']}")
    if stores.care.path.is_file():
        found.append(f"- {m['care']}")
    return found


def _plan_key(plan: SafetyPlanStore) -> str:
    """Saved, or saved but not opening now (robustness E3: never "saved" for a file that
    the keychain, its key or the system will not open)."""
    try:
        plan.load()
    except (KeychainUnavailableError, SafetyPlanDamagedError):
        return "safety_plan_unreadable"
    return "safety_plan"


def run_memory(
    say: Say, stores: DataStores, text: ForgetText | None = None, *, now: datetime | None = None
) -> int:
    """``olivia memory``: print what is stored here; returns the exit status. ``now``
    (default: the current time) decides whether a "not for me" still counts as recent."""
    t = load_forget_text() if text is None else text
    moment = datetime.now(UTC) if now is None else now
    m = t.memory
    profile_exists, profile = _profile_quietly(stores)
    if profile is not None and profile.is_age_gate_refusal:
        say(m["adults_only"])
        return 0
    keychain = _keychain(stores.vault)
    if keychain is _Keychain.LOCKED:
        say(m["locked"])
        return 1
    entries: tuple[LedgerEntry, ...] = ()
    if keychain is _Keychain.NONE:
        say(m["no_keychain"])
        say("")
        unreadable = len(stores.ledger.entry_paths())
    else:
        try:
            entries = stores.ledger.entries()
        except LedgerUnavailableError:
            say(m["locked"])
            return 1
        unreadable = stores.ledger.skipped
        say(m["heading"])
        say("")
        if not entries:
            say(m["empty"])
            say("")
        for number, entry in enumerate(entries, start=1):
            for line in _entry_lines(stores.ledger, number, entry, t):
                say(line)
            say("")
    if unreadable:
        say(_fill(m["unreadable"], count=unreadable))
        say("")
    others = _other_lines(stores, profile, profile_exists, t, moment)
    if others:
        say(m["others"])
        for line in others:
            say(line)
    else:
        say(m["nothing_else"])
    if entries or unreadable or others:
        say("")
        say(m["hint"])
    return 0


# -- forgetting -------------------------------------------------------------------------------


def _shred_ledger(ledger: Ledger) -> None:
    """``Ledger.shred``; the key file and the entry files go even if the keychain fails."""
    with contextlib.suppress(LedgerUnavailableError):
        ledger.shred()


def _quietly(shred: Callable[[], None]) -> None:
    """Run a store's shred; its file and key file go even if the keychain fails after."""
    with contextlib.suppress(KeychainUnavailableError):
        shred()


def forget_ledger(stores: DataStores) -> None:
    """Every chat record: the ledger and the care marker, crypto-shredded."""
    _shred_ledger(stores.ledger)
    _quietly(stores.care.shred)


def forget_kit(stores: DataStores) -> None:
    """The kit and the method preferences, crypto-shredded."""
    _quietly(stores.state.shred)


def forget_safety_plan(stores: DataStores) -> None:
    """The safety plan, crypto-shredded (the "suggested" marker stays, so it is not
    suggested again)."""
    _quietly(stores.plan.shred)


def _owned_paths(base: Path) -> Iterator[Path]:
    """Every file this package writes in ``base`` (temporary siblings included)."""
    for name in DATA_FILES:
        yield base / name
        yield from base.glob(f".{name}.*.tmp")
    for dirname in DATA_DIRS:
        directory = base / dirname
        if directory.is_dir():
            yield from (p for p in directory.rglob("*") if p.is_file() or p.is_symlink())


def _remove_dirs(base: Path) -> None:
    for dirname in DATA_DIRS:
        directory = base / dirname
        if not directory.is_dir():
            continue
        nested = sorted((p for p in directory.rglob("*") if p.is_dir()), reverse=True)
        for path in (*nested, directory):
            with contextlib.suppress(OSError):
                path.rmdir()


def forget_all(stores: DataStores, *, keep: frozenset[Path] = frozenset()) -> bool:
    """Destroy every key, then remove every file except ``keep`` (plaintext files only:
    the age-gate refusal record); False when the keychain item remains (the keychain
    did not answer, or there is none in this session although key files existed: the
    files are gone and nothing left opens, but the master key could not be deleted)."""
    marker = stores.base / FORGET_ALL_MARKER
    atomic_write_bytes(marker, b"", snapshot=False)
    for hook in stores.on_forget_all:
        hook()
    had_keys = stores.vault.has_data_keys()
    cleared = True
    try:
        stores.vault.shred_all()
    except NoKeychainError:
        cleared = not had_keys  # no keys, no master key; with keys, one we cannot reach
    except KeychainUnavailableError:
        cleared = False
    for path in list(_owned_paths(stores.base)):
        if path not in keep:
            remove_file(path)
    _remove_dirs(stores.base)
    remove_file(marker)
    return cleared


def forget_all_unfinished(base: Path) -> bool:
    """Whether a ``forget --all`` in ``base`` was interrupted (robustness E2)."""
    return (base / FORGET_ALL_MARKER).is_file()


def _has_any(stores: DataStores, target: Target) -> bool:
    if target is Target.LEDGER:
        return bool(
            stores.ledger.entry_paths()
            or stores.care.path.is_file()
            or stores.vault.has_data_key(LEDGER_STORE)
            or stores.vault.has_data_key(CARE_STORE)
        )
    if target is Target.KIT:
        return (
            stores.state.path.is_file()
            or stores.state.staging.is_file()
            or stores.vault.has_data_key(STATE_STORE)
            or stores.vault.has_data_key(STATE_REKEY_STORE)
        )
    if target is Target.SAFETY_PLAN:
        return stores.plan.exists() or stores.vault.has_data_key(SAFETY_PLAN_STORE)
    return any(path.exists() for path in _owned_paths(stores.base))


def _fold(answer: str) -> str:
    return unicodedata.normalize("NFKC", answer).strip()


class _Command:
    def __init__(
        self, ask: Ask, say: Say, stores: DataStores, text: ForgetText, now: datetime
    ) -> None:
        self.ask = ask
        self.say = say
        self.stores = stores
        self.f = text.forget
        self.text = text
        self.now = now

    def run(
        self, target: Target | None, entry: int | None, method: int | None, assume_yes: bool
    ) -> int:
        _, profile = _profile_quietly(self.stores)
        if profile is not None and profile.is_age_gate_refusal:
            if target is Target.ALL:
                return self._all_minor(assume_yes)
            self.say(self.f["adults_only"])
            return 0
        if entry is not None:
            target = Target.ENTRY
        elif method is not None:
            target = Target.METHOD
        if target is None:
            picked = self._menu()
            if isinstance(picked, int):
                return picked
            target = picked
        if target is Target.ALL:
            return self._all(assume_yes)
        if _keychain(self.stores.vault) is _Keychain.LOCKED:
            self.say(self.f["locked"])
            return 1
        if target is Target.ENTRY:
            return self._entry(entry, assume_yes)
        if target is Target.METHOD:
            return self._method(method, assume_yes)
        if not _has_any(self.stores, target):
            self.say(self.f[f"nothing_{target.value}"])
            return 0
        if not self._confirmed(self.f[f"about_{target.value}"], assume_yes):
            return 0
        if target is Target.LEDGER:
            forget_ledger(self.stores)
        elif target is Target.KIT:
            forget_kit(self.stores)
        else:
            forget_safety_plan(self.stores)
        self.say(self.f[f"done_{target.value}"])
        return 0

    def _menu(self) -> Target | int:
        """The picked target, or the exit status when nothing was picked."""
        self.say(self.f["menu"])
        for number, option in enumerate(MENU, start=1):
            self.say(f"  {number}. {self.f[option.value]}")
        answer = self.ask()
        choice = _fold(answer) if answer is not None else ""
        if not choice:
            self.say(self.f["cancelled"])
            return 0
        if choice.isdigit() and 1 <= int(choice) <= len(MENU):
            return MENU[int(choice) - 1]
        self.say(self.f["unknown_choice"])
        return 1

    def _pick(self, lines: list[str], prompt: str) -> int | None:
        """Show ``lines`` and ask for a number. Returns the number; None when Enter or
        the end of input cancelled; -1 when the reply was not a number. Both are said."""
        for line in lines:
            self.say(line)
        self.say("")
        self.say(prompt)
        answer = self.ask()
        choice = _fold(answer) if answer is not None else ""
        if not choice:
            self.say(self.f["cancelled"])
            return None
        if not choice.isdigit():
            self.say(self.f["unknown_choice"])
            return -1
        return int(choice)

    def _entry(self, number: int | None, assume_yes: bool) -> int:
        """One ledger entry. A number given on the command line that names no entry is a
        wrong value (exit 2, README "退出码"); one typed at the prompt is exit 1."""
        try:
            entries = self.stores.ledger.entries()
        except LedgerUnavailableError as exc:
            if not exc.permanent:
                self.say(self.f["locked"])
                return 1
            entries = ()
        if not entries:
            self.say(self.f["nothing_entry"])
            return 0
        bad_number = 2 if number is not None else 1
        if number is None:
            lines = [
                line
                for i, entry in enumerate(entries, start=1)
                for line in _entry_lines(self.stores.ledger, i, entry, self.text)
            ]
            number = self._pick(lines, self.f["pick_entry"])
            if number is None:
                return 0
            if number < 0:
                return 1
        if not 1 <= number <= len(entries):
            self.say(_fill(self.f["no_entry"], n=number))
            return bad_number
        chosen = entries[number - 1]
        # Dogfood P4: say which entry, exactly as ``olivia memory`` shows it.
        preview = _entry_lines(self.stores.ledger, number, chosen, self.text)
        about = _fill(self.f["about_entry"], n=number)
        if not self._confirmed(about, assume_yes, preview):
            return 0
        try:
            dropped = self.stores.ledger.forget_entry(chosen.entry_id)
        except LedgerUnavailableError:
            self.say(self.f["locked"])
            return 1
        self.say(_fill(self.f["done_entry"], n=number))
        if dropped:
            self.say(_fill(self.f["done_entry_dropped"], count=dropped))
        return 0

    def _method(self, number: int | None, assume_yes: bool) -> int:
        """One method's preference (RSK-06): its posterior in every spectrum is removed
        and the kit store re-sealed under a fresh key; the kit and the other methods stay.
        Numbers as ``olivia memory`` lists them; exit codes as :meth:`_entry`."""
        state, preferences = _preferences(self.stores, self.now)
        if state is None or not preferences:
            self.say(self.f["nothing_method"])
            return 0
        bad_number = 2 if number is not None else 1
        if number is None:
            number = self._pick(_preference_lines(preferences, self.text), self.f["pick_method"])
            if number is None:
                return 0
            if number < 0:
                return 1
        if not 1 <= number <= len(preferences):
            self.say(_fill(self.f["no_method"], n=number))
            return bad_number
        chosen = preferences[number - 1]
        if not self._confirmed(_fill(self.f["about_method"], title=chosen.title), assume_yes):
            return 0
        bandit = without_method(self.stores.tax(), state.bandit, chosen.action_id)
        try:
            self.stores.state.rekey(CarriedState(bandit, state.kit))
        except KeychainUnavailableError:
            self.say(self.f["locked"])
            return 1
        self.say(_fill(self.f["done_method"], title=chosen.title))
        return 0

    def _all(self, assume_yes: bool) -> int:
        if not _has_any(self.stores, Target.ALL):
            for hook in self.stores.on_forget_all:
                hook()  # the reminder job, should it outlive the data
            with contextlib.suppress(KeychainUnavailableError):
                self.stores.vault.shred_all()  # a master key left behind, if any
            remove_file(self.stores.base / FORGET_ALL_MARKER)  # killed after the last file
            self.say(self.f["nothing_all"])
            return 0
        if not self._confirmed(self.f["about_all"], assume_yes):
            return 0
        if forget_all(self.stores):
            self.say(self.f["done_all"])
            return 0
        self.say(self._keychain_left())
        return 1

    def _keychain_left(self) -> str:
        """Why the master key is still in the keychain: it did not answer, or there is
        no keychain in this session at all (S5)."""
        if _keychain(self.stores.vault) is _Keychain.NONE:
            return self.f["keychain_unreachable"]
        return self.f["keychain_left"]

    def _all_minor(self, assume_yes: bool) -> int:
        """``--all`` on a device holding the age-gate refusal record (ruling 22): remove
        anything else, keep that one record, and say why in one line."""
        record = self.stores.profile.path
        others = [p for p in _owned_paths(self.stores.base) if p != record and p.exists()]
        code = 0
        if others:
            if not self._confirmed(self.f["about_all_minor"], assume_yes):
                return 0
            if forget_all(self.stores, keep=frozenset({record})):
                self.say(self.f["done_all_minor"])
            else:
                self.say(self._keychain_left())
                code = 1
        self.say(self.f["kept_minor"])
        return code

    def _confirmed(self, about: str, assume_yes: bool, preview: list[str] | None = None) -> bool:
        if assume_yes:
            return True
        self.say(about)
        for line in preview or ():
            self.say(line)
        return _typed_confirmation(self.ask, self.say, self.f)


def _typed_confirmation(ask: Ask, say: Say, f: Mapping[str, str]) -> bool:
    """Ask for the confirmation word: 「确认」 or 「确定」 (dogfood P4); anything else,
    or the end of input, cancels and says so."""
    say(f["confirm"])
    answer = ask()
    if answer is not None and _fold(answer) in {f["confirm_word"], f["confirm_also"]}:
        return True
    say(f["cancelled"])
    return False


def run_forget(
    ask: Ask,
    say: Say,
    stores: DataStores,
    *,
    target: Target | None = None,
    entry: int | None = None,
    method: int | None = None,
    assume_yes: bool = False,
    text: ForgetText | None = None,
    now: datetime | None = None,
) -> int:
    """``olivia forget``: the menu (``target`` None) or one target; the exit status.

    ``entry`` is a number as ``olivia memory`` shows it and implies :attr:`Target.ENTRY`;
    ``method`` likewise for the method preferences and :attr:`Target.METHOD`.
    """
    t = load_forget_text() if text is None else text
    moment = datetime.now(UTC) if now is None else now
    return _Command(ask, say, stores, t, moment).run(target, entry, method, assume_yes)


# -- editing a note ---------------------------------------------------------------------------


def run_edit(
    ask: Ask,
    say: Say,
    stores: DataStores,
    number: int,
    *,
    text: ForgetText | None = None,
) -> int:
    """``olivia memory --edit N`` (PRD feature 5, "查看、编辑与加密擦除权"): replace the
    words of note ``N`` (the number ``olivia memory`` shows) with a new line.

    Only a note can be edited: a session summary or journal record is written by the
    program from ids, not the user's words, and says so (exit 2, like a number that names
    no entry). The new text needs the typed confirmation; then ``Ledger.edit_note``
    re-keys the ledger, so the old words are crypto-shredded like a forgotten entry.
    Enter, the same text or the end of input changes nothing (exit 0).
    """
    t = load_forget_text() if text is None else text
    m, f = t.memory, t.forget
    keychain = _keychain(stores.vault)
    if keychain is not _Keychain.OK:
        say(m["no_keychain"] if keychain is _Keychain.NONE else m["locked"])
        return 1
    try:
        entries = stores.ledger.entries()
    except LedgerUnavailableError:
        say(m["locked"])
        return 1
    if not entries:
        say(f["nothing_entry"])
        return 0
    if not 1 <= number <= len(entries):
        say(_fill(f["no_entry"], n=number))
        return 2
    entry = entries[number - 1]
    if not isinstance(entry, NoteEntry):
        say(_fill(m["edit_not_note"], n=number))
        return 2
    say(_fill(m["edit_current"], n=number))
    for line in entry.text.splitlines() or [""]:
        say(f"   {line}")
    say("")
    new_text = _ask_note(ask, say, m)
    if new_text is None or new_text == entry.text:
        say(m["edit_unchanged"])
        return 0
    say(_fill(m["edit_about"], n=number))
    if not _typed_confirmation(ask, say, f):
        return 0
    try:
        dropped = stores.ledger.edit_note(entry.entry_id, new_text)
    except LedgerUnavailableError:
        say(m["locked"])
        return 1
    say(_fill(m["edit_done"], n=number))
    if dropped:
        say(_fill(f["done_entry_dropped"], count=dropped))
    return 0


def _ask_note(ask: Ask, say: Say, m: Mapping[str, str]) -> str | None:
    """The new words for a note, trimmed; None for Enter or the end of input. Too long
    is said, never cut: the user writes it again or presses Enter to keep the note."""
    say(_fill(m["edit_prompt"], count=NOTE_MAX_CHARS))
    while True:
        answer = ask()
        reply = "" if answer is None else answer.strip()
        if not reply:
            return None
        if len(reply) <= NOTE_MAX_CHARS:
            return reply
        say(_fill(m["edit_too_long"], count=NOTE_MAX_CHARS))
