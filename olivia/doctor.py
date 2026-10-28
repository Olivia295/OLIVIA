"""What ``olivia doctor`` looks at: a read-only check of this computer's setup.

:func:`examine` gathers facts only; the CLI turns them into one marked line each
(``cli.py``, the ``DOCTOR_*`` texts). Every check is read-only and offline:

* the data directory: where it is, whether it exists (it is never created), whether
  this account may read and write it (:func:`access_problem`: a directory without read or
  write permission, or a file in its place, QA r3; every other check then copes with what
  it cannot read instead of failing) and, on POSIX, whether every directory is 0700 and
  every file 0600 (the signed hotline update folder ``resources/`` is placed there by the
  user and holds no personal data, so it is not counted);
* the keychain: :func:`keychain.probe` resolves the backend and touches no item, so a
  locked keychain is not noticed (that would take an item read, which may prompt);
* the profile and every sealed store, **without decrypting anything**: a file must
  exist and look sealed (``aead.looks_sealed``: header and length), its wrapped data
  key must be there and well formed (``vault.key_file_intact``), and the keychain must be
  there. A blob altered after its header, or a master key gone from the keychain, is
  only noticed when the store is opened for real;
* the packaged perception student, loaded and verified as ``chat`` would
  (``student.try_load_student``; nothing is cached);
* the built-in hotline data's signature and compiled date, and whether a signed update
  in ``<data dir>/resources/`` is used (``bundle.load_hotlines_bytes``);
* the packaged wording, lexicons and taxonomy (:data:`PACKAGED_DATA`): each is loaded and
  validated as the commands would, one by one, so a damaged or missing file is named (QA
  r3: a broken crisis lexicon or template used to leave every line ✓), and only that file
  (QA q4 P5: not every file loaded beside it);
* whether the reminder job is installed (``jobs.installed``);
* what the data directory's markers say (robustness fixes): another OLIVIA holding the
  data directory's lock (``datalock.held_elsewhere``: tried and let go, nothing created),
  a ``forget --all`` that did not finish (``forget-all.pending``), and a profile recovered
  from a snapshot that the user has not been told about yet (``profile.recovered``). The
  lock file and both markers are OLIVIA's own and hold no user data.

Nothing here reads a store's contents or a keychain item, so no user text, name, topic,
health code or plan can reach the report: it holds states, dates, counts and versions.
"""

from __future__ import annotations

import functools
import os
import stat
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from importlib import resources
from pathlib import Path
from typing import Any, Final, Literal

from olivia.core.chang.care import CARE_FILENAME, CARE_STORE
from olivia.core.chang.profile import (
    PROFILE_FILENAME,
    PROFILE_STORE,
    profile_shape,
    recovery_pending,
)
from olivia.core.chang.safety_plan import SAFETY_PLAN_FILENAME, SAFETY_PLAN_STORE
from olivia.core.crypto import aead, keychain
from olivia.core.crypto.vault import key_file_intact
from olivia.core.datalock import held_elsewhere
from olivia.core.memory.forget import forget_all_unfinished
from olivia.core.memory.ledger import LEDGER_STORE, entry_files
from olivia.core.memory.state import STATE_FILENAME, STATE_STORE
from olivia.core.perception import student
from olivia.core.resources import bundle
from olivia.core.storage import StorageAccessError, StorageCorruptError, read_text_with_recovery
from olivia.notify import jobs
from olivia.notify.system import Host

HOTLINE_MAX_AGE_DAYS: Final = 90
"""Older hotline data gets a warning; the same limit as the quarterly review
(``scripts/check_hotline_freshness.py``)."""
PRIVATE_DIR_MODE: Final = 0o700
PRIVATE_FILE_MODE: Final = 0o600

_PARSE_ERRORS: Final = (ValueError, TypeError, OverflowError, RecursionError)
_SEALED_FILES: Final = (
    ("state", STATE_FILENAME, STATE_STORE),
    ("care", CARE_FILENAME, CARE_STORE),
    ("safety_plan", SAFETY_PLAN_FILENAME, SAFETY_PLAN_STORE),
)


Access = Literal["file", "unreadable", "unwritable"]
"""What keeps the data directory from being used (:func:`access_problem`)."""


class StoreState(StrEnum):
    ABSENT = "absent"
    READY = "ready"
    """Every file and its key look intact and the keychain is there."""
    PARTLY = "partly"
    """Some ledger entries look damaged; the others are intact."""
    BROKEN = "broken"
    """The data or its wrapped key is damaged or gone: it cannot be opened."""
    LOCKED = "locked"
    """Intact, but the keychain it needs is not there now."""
    UNREADABLE = "unreadable"
    """The operating system will not let this account read it (permissions)."""


@dataclass(frozen=True)
class DataDir:
    location: Path
    kind: Literal["absent", "dir", "other"]
    mismatched: int | None
    """Paths whose mode is not 0700 / 0600; None when not checked (Windows, or no dir)."""
    access: Access | None = None
    """Why the program cannot use the directory (:func:`access_problem`); None when it can."""


@dataclass(frozen=True)
class ProfileFacts:
    state: StoreState
    onboarded: bool | None
    """A profile was saved (first visit done); None when the file cannot be read."""
    notifications: bool | None
    """The reminders switch, when it is readable without the keychain."""


@dataclass(frozen=True)
class HotlineFacts:
    builtin_ok: bool
    builtin_on: date | None
    used: Literal["builtin", "override"] | None
    """None when the built-in data failed, so the update was not looked at."""
    reason: str | None
    """Why an update that is there is not used (``bundle.REASON_*``)."""
    override_on: date | None


@dataclass(frozen=True)
class Activity:
    busy: bool = False
    """Another OLIVIA holds the data directory's lock now."""
    forget_unfinished: bool = False
    """A ``forget --all`` was interrupted and waits to be run again."""
    recovered: bool = False
    """The profile was recovered from a snapshot and the user has not been told yet."""


@dataclass(frozen=True)
class Report:
    data_dir: DataDir
    keychain: keychain.Probe
    profile: ProfileFacts
    stores: dict[str, StoreState]
    """``ledger``, ``state``, ``care``, ``safety_plan``, in that order."""
    model_reason: str | None
    """Why the packaged student is unavailable; None when it loaded and verified."""
    hotlines: HotlineFacts
    reminders: bool | None
    activity: Activity = Activity()
    packaged: PackagedData = field(default_factory=lambda: PackagedData(0, ()))


@dataclass(frozen=True)
class PackagedData:
    checked: int
    """How many packaged files were checked (:func:`packaged_files`)."""
    failed: tuple[str, ...]
    """The files that did not load (paths under ``olivia/data``), in check order."""


def examine(base: Path, *, today: date, host: Callable[[], Host]) -> Report:
    """Look at the data directory ``base`` and the installed package (module docstring)."""
    try:
        kind: Literal["absent", "dir", "other"] = (
            "dir" if base.is_dir() else "other" if base.exists() else "absent"
        )
    except OSError:  # its parent cannot be searched: as good as unreadable
        kind = "dir"
    access = access_problem(base)
    readable = kind == "dir" and access != "unreadable"
    found = keychain.probe()
    there = found in (keychain.Probe.READY, keychain.Probe.UNCHECKED)
    stores: dict[str, StoreState] = {}
    for name, filename, store in (("ledger", "", LEDGER_STORE), *_SEALED_FILES):
        if kind != "dir":  # nothing there to open
            stores[name] = StoreState.ABSENT
        elif filename:
            stores[name] = _guarded(functools.partial(_sealed_file, base, filename, store, there))
        else:
            stores[name] = _guarded(functools.partial(_ledger, base, there))
    profile = (
        _profile(base, there)
        if kind == "dir"
        else ProfileFacts(StoreState.ABSENT, onboarded=False, notifications=None)
    )
    return Report(
        data_dir=DataDir(base, kind, _mismatched(base) if readable else None, access),
        keychain=found,
        profile=profile,
        stores=stores,
        model_reason=student.try_load_student().reason,
        hotlines=_hotlines(base, today),
        reminders=jobs.installed(host()),
        activity=_activity(base) if readable else Activity(),
        packaged=packaged_data(),
    )


def access_problem(base: Path) -> Access | None:
    """Why this account cannot use the data directory ``base``, or None when it can (or
    when there is no directory yet: the first visit makes it).

    ``"file"``: something that is not a directory is in its place. ``"unreadable"``: the
    directory, or a directory or file in it, cannot be read (or a directory not searched).
    ``"unwritable"``: the directory, or a directory in it, cannot be written, so nothing
    can be saved (files are replaced by renaming, so only directories count). The signed
    update folder ``resources/`` is the user's and is not looked at. Read-only.
    """
    try:
        if not base.exists():
            return None
        if not base.is_dir():
            return "file"
    except OSError:
        return "unreadable"
    if not os.access(base, os.R_OK | os.X_OK):
        return "unreadable"
    unwritable = not os.access(base, os.W_OK)
    try:
        inside = list(base.rglob("*"))
    except OSError:
        return "unreadable"
    for path in inside:
        relative = path.relative_to(base).parts
        if relative and relative[0] == bundle.OVERRIDE_DIR_NAME:
            continue
        try:
            info = path.lstat()
        except OSError:
            return "unreadable"
        if stat.S_ISLNK(info.st_mode):
            continue
        if stat.S_ISDIR(info.st_mode):
            if not os.access(path, os.R_OK | os.X_OK):
                return "unreadable"
            unwritable = unwritable or not os.access(path, os.W_OK)
        elif not os.access(path, os.R_OK):
            return "unreadable"
    return "unwritable" if unwritable else None


def _guarded(check: Callable[[], StoreState]) -> StoreState:
    """A store check that a permission problem turns into ``UNREADABLE``, not a failure."""
    try:
        return check()
    except OSError:
        return StoreState.UNREADABLE


def _ledger(base: Path, keychain_there: bool) -> StoreState:
    return _sealed(base, entry_files(base), LEDGER_STORE, keychain_there)


def _sealed_file(base: Path, filename: str, store: str, keychain_there: bool) -> StoreState:
    path = base / filename
    return _sealed(base, [path] if path.exists() else [], store, keychain_there)


def _activity(base: Path) -> Activity:
    try:
        return Activity(
            busy=held_elsewhere(base),
            forget_unfinished=forget_all_unfinished(base),
            recovered=recovery_pending(base),
        )
    except OSError:  # a marker that cannot be read: said by the data directory's own line
        return Activity()


def _looks_sealed(path: Path) -> bool:
    try:
        return aead.looks_sealed(path.read_bytes())
    except PermissionError:
        raise  # not damaged: the store is unreadable (``_guarded``)
    except OSError:
        return False


def _sealed(base: Path, files: list[Path], store: str, keychain_there: bool) -> StoreState:
    if not files:
        return StoreState.ABSENT
    intact = [_looks_sealed(path) for path in files]
    if not any(intact) or not key_file_intact(base, store):
        return StoreState.BROKEN
    if not keychain_there:
        return StoreState.LOCKED
    return StoreState.READY if all(intact) else StoreState.PARTLY


def _profile(base: Path, keychain_there: bool) -> ProfileFacts:
    """The profile file (or, as ``ProfileStore.load`` would, its newest valid snapshot)."""

    def is_valid(text: str) -> bool:
        try:
            profile_shape(text)
        except _PARSE_ERRORS:
            return False
        return True

    try:
        text = read_text_with_recovery(base / PROFILE_FILENAME, is_valid)
    except FileNotFoundError:
        return ProfileFacts(StoreState.ABSENT, onboarded=False, notifications=None)
    except (StorageAccessError, PermissionError):
        return ProfileFacts(StoreState.UNREADABLE, onboarded=None, notifications=None)
    except (StorageCorruptError, OSError):
        return ProfileFacts(StoreState.BROKEN, onboarded=None, notifications=None)
    shape = profile_shape(text)
    state = StoreState.READY
    if shape.sealed:
        try:
            intact = key_file_intact(base, PROFILE_STORE)
        except OSError:
            return ProfileFacts(StoreState.UNREADABLE, True, shape.notifications)
        if not intact:
            state = StoreState.BROKEN
        elif not keychain_there:
            state = StoreState.LOCKED
    return ProfileFacts(state, onboarded=True, notifications=shape.notifications)


def _mismatched(base: Path) -> int | None:
    """How many paths are not 0700 (directories) / 0600 (files); None on Windows."""
    if os.name == "nt":
        return None
    count = 0
    for path in (base, *base.rglob("*")):
        relative = path.relative_to(base).parts
        if relative and relative[0] == bundle.OVERRIDE_DIR_NAME:
            continue  # placed there by the user, holds no personal data
        try:
            info = path.lstat()
        except OSError:
            continue
        if stat.S_ISLNK(info.st_mode):
            continue
        want = PRIVATE_DIR_MODE if stat.S_ISDIR(info.st_mode) else PRIVATE_FILE_MODE
        count += stat.S_IMODE(info.st_mode) != want
    return count


def _hotlines(base: Path, today: date) -> HotlineFacts:
    try:
        builtin = bundle.load_hotlines_bytes(None, today=today)
    except (bundle.BundleIntegrityError, OSError):
        return HotlineFacts(False, None, None, None, None)
    builtin_on = bundle.compiled_on_of(builtin.data)
    try:
        loaded = bundle.load_hotlines_bytes(base / bundle.OVERRIDE_DIR_NAME, today=today)
    except OSError:  # the data directory cannot be read: no update can be used
        return HotlineFacts(True, builtin_on, "builtin", bundle.REASON_UNREADABLE, None)
    if loaded.source == "override":
        return HotlineFacts(True, builtin_on, "override", None, bundle.compiled_on_of(loaded.data))
    reason = None if loaded.reason == bundle.REASON_NO_OVERRIDE else loaded.reason
    return HotlineFacts(True, builtin_on, "builtin", reason, None)


# -- the packaged data ----------------------------------------------------------------------


@dataclass(frozen=True)
class PackagedFiles:
    """Some packaged files and how the program loads them."""

    files: tuple[str, ...]
    """Paths under ``olivia/data``."""
    load: Callable[[Any], object]
    """The program's own loader; it takes the loaded taxonomy (unused by some)."""
    needs_taxonomy: bool = True
    """Whether ``load`` checks against the taxonomy (it cannot be tried without one)."""


def _language(tax: Any) -> object:
    from olivia.core.language.data import load_language_data

    return load_language_data(tax)


def _safety_lexicons(tax: Any) -> object:
    from olivia.core.safety.lexicon import load_safety_lexicons

    return load_safety_lexicons(tax)


def _perception_lexicon(tax: Any) -> object:
    from olivia.core.perception.lexicon import load_perception_lexicon

    return load_perception_lexicon(tax)


def _introspection(tax: Any) -> object:
    from olivia.core.perception.introspector import load_introspection_lexicon

    return load_introspection_lexicon(tax)


def _mirror_lines(tax: Any) -> object:
    from olivia.core.perception.introspector import load_mirror_lines

    return load_mirror_lines(tax)


def _externalize(tax: Any) -> object:
    from olivia.core.perception.externalize import load_externalize_text

    return load_externalize_text(tax)


def _note_cues(_tax: Any) -> object:
    from olivia.core.memory.notes import load_note_cues

    return load_note_cues()


def _memory_text(_tax: Any) -> object:
    from olivia.core.memory.text import load_memory_text

    return load_memory_text()


def _onboarding(_tax: Any) -> object:
    from olivia.core.chang.onboarding import load_onboarding_text

    return load_onboarding_text()


def _privacy(_tax: Any) -> object:
    from olivia.core.chang.privacy import load_privacy_text

    return load_privacy_text()


def _safety_plan(_tax: Any) -> object:
    from olivia.core.chang.safety_plan import load_safety_plan_text

    return load_safety_plan_text()


def _journal(_tax: Any) -> object:
    from olivia.core.chang.journal import load_journal_text

    return load_journal_text()


def _forget(_tax: Any) -> object:
    from olivia.core.memory.forget import load_forget_text

    return load_forget_text()


def _stats(_tax: Any) -> object:
    from olivia.core.chang.stats import load_stats_text

    return load_stats_text()


def _notify(_tax: Any) -> object:
    from olivia.notify.text import load_notify_text

    return load_notify_text()


TAXONOMY_FILE: Final = "taxonomy.yaml"
LANGUAGE_FILES: Final = (
    "language/willow.yaml",
    "language/utterances.yaml",
    "language/metaphors.yaml",
    "language/needs.yaml",
    "language/render.yaml",
    "language/feelings.yaml",
    "lexicons/substance.yaml",
    "cards/grade_a.yaml",
    "cards/grade_bc_info.yaml",
    "templates/gentle_holding.yaml",
    "templates/zen_philosopher.yaml",
    "templates/rational_peer.yaml",
    "templates/silent_anchor.yaml",
)
PACKAGED_DATA: Final[tuple[PackagedFiles, ...]] = (
    PackagedFiles(
        ("lexicons/risk.yaml", "lexicons/red_flags.yaml", "lexicons/perception.yaml"),
        _safety_lexicons,
    ),
    PackagedFiles(("lexicons/perception.yaml",), _perception_lexicon),
    PackagedFiles(("lexicons/perception.yaml",), _introspection),
    PackagedFiles(("language/schema_mirror.yaml",), _mirror_lines),
    PackagedFiles(("language/externalize.yaml",), _externalize),
    PackagedFiles(("lexicons/memory.yaml",), _note_cues, needs_taxonomy=False),
    PackagedFiles(("templates/memory.yaml",), _memory_text, needs_taxonomy=False),
    PackagedFiles(LANGUAGE_FILES, _language),
    PackagedFiles(("templates/onboarding.yaml",), _onboarding, needs_taxonomy=False),
    PackagedFiles(("templates/privacy.yaml",), _privacy, needs_taxonomy=False),
    PackagedFiles(("templates/safety_plan.yaml",), _safety_plan, needs_taxonomy=False),
    PackagedFiles(("templates/journal.yaml",), _journal, needs_taxonomy=False),
    PackagedFiles(("templates/forget.yaml",), _forget, needs_taxonomy=False),
    PackagedFiles(("templates/stats.yaml",), _stats, needs_taxonomy=False),
    PackagedFiles(("templates/notify.yaml",), _notify, needs_taxonomy=False),
)
"""Every packaged file the commands read besides the taxonomy (tried first), the model and
the hotline data (checked on their own lines), with the program's own loaders. Loaded
fresh in ``olivia doctor``'s own process; a loader that caches keeps its first result."""


def packaged_files() -> tuple[str, ...]:
    """Every file :func:`packaged_data` checks, the taxonomy first, each once."""
    names = [TAXONOMY_FILE, *(name for entry in PACKAGED_DATA for name in entry.files)]
    return tuple(dict.fromkeys(names))


def packaged_data() -> PackagedData:
    """Load the taxonomy and every :data:`PACKAGED_DATA` entry; name only the files that do
    not load (QA q4 P5: a damaged file no longer names every file loaded beside it).

    A loader that fails names, of its files, those that are not readable YAML; failing that,
    those its error names; failing that, all of them. Without a taxonomy the loaders that
    need one cannot run, so only their unreadable files are named besides the taxonomy."""
    failed: list[str] = []
    try:
        from olivia.core.taxonomy import load_taxonomy

        tax: Any = load_taxonomy()
    except Exception:  # noqa: BLE001 - whatever the damage, it is named, never raised
        failed.append(TAXONOMY_FILE)
        tax = None
    for entry in PACKAGED_DATA:
        if tax is None and entry.needs_taxonomy:
            failed.extend(name for name in entry.files if not _reads_as_yaml(name))
            continue
        try:
            entry.load(tax)
        except Exception as exc:  # noqa: BLE001 - as above
            failed.extend(_culprits(entry.files, exc))
    return PackagedData(len(packaged_files()), tuple(dict.fromkeys(failed)))


def _culprits(files: tuple[str, ...], exc: BaseException) -> tuple[str, ...]:
    """Which of ``files`` made their loader raise ``exc`` (:func:`packaged_data`)."""
    if len(files) == 1:
        return files
    unreadable = tuple(name for name in files if not _reads_as_yaml(name))
    if unreadable:
        return unreadable
    said = " ".join(str(e) for e in (exc, exc.__cause__, exc.__context__) if e is not None)
    named = tuple(name for name in files if name.rsplit("/", 1)[-1] in said)
    return named or files


def _reads_as_yaml(name: str) -> bool:
    """Whether the packaged file ``olivia/data/<name>`` is there and parses as YAML."""
    from olivia.core.yaml_load import safe_load

    try:
        safe_load(resources.files("olivia").joinpath(f"data/{name}").read_text("utf-8"))
    except Exception:  # noqa: BLE001 - missing, unreadable or not YAML: all the same here
        return False
    return True
