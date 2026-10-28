#!/usr/bin/env python3
"""Automatic privacy audit: the automatic part of gate G-4 (ruling 32; next-phase plan B8).

    python scripts/privacy_audit.py

Prints one table row per check and exits 0 only when every check passes (a check that
cannot apply on this platform is SKIP, never FAIL). The legal report is G-4's external
part and is not replaced by this script.

How it runs: the ``olivia`` command line is driven in this process, twice, on scripted
input, each time in a fresh temporary ``OLIVIA_HOME``: once with the ONB-06 switch off
(only sensitive data encrypted) and once with it on (everything encrypted). Each run
goes through ``chat --rules --inspect`` (onboarding with the health consent and a checklist
item, an opening self-rating, a message, a card and its feedback, a note "记住：……", a
crisis turn), ``health``, ``safety-plan``, ``journal``, ``stats``, ``memory``, ``privacy``,
``doctor``, a second
``chat --inspect`` (care greeting, model path: the default since F7, and a question about
the note, "周四要见的那个人是谁来着", F15), ``memory --edit`` (the note rewritten, PRD
feature 5), ``forget --method`` (one method's preference reset, RSK-06), ``health`` twice
more (a clinical-history code in and a checklist item out, then ``0``: delete
everything), then ``forget --all``.

The real OS keychain is never reached: ``PYTHON_KEYRING_BACKEND`` names keyring's failing
backend before ``keyring`` is imported, ``keyring.get_keyring`` is replaced by a function
that fails, and OLIVIA's key backend is an in-memory one (as in ``tests/conftest.py``).
The platform's user data directory is never resolved either.

Checks (names as printed):

network-imports
    No module of the ``olivia`` package imports a networking module (AST scan of every
    ``import``, ``from ... import`` and literal ``importlib.import_module``/``__import__``;
    :data:`NETWORK_MODULES`).
network-runtime
    While the scripted runs execute, ``socket`` connect/bind/sendto, ``create_connection``
    and name resolution are patched to record and refuse; no attempt may be recorded.
data-stays-local
    Nothing resolves the platform's user data directory, and nothing is written in the
    temporary root outside ``OLIVIA_HOME``.
files-no-typed-text [mode]
    No file under ``OLIVIA_HOME`` (snapshots and key files included) contains any typed
    sentence or fragment of one (:func:`fragments`: whole characters, at least 4 UTF-8
    bytes, at least 6 when the fragment is all ASCII so random ciphertext or base64 cannot
    match by chance), in UTF-8 or as JSON ``\\u`` escapes. Exception, switch off only: the
    profile's non-sensitive fields the user typed (both names, taboo topics) may appear in
    ``profile.json`` and its snapshots.
sensitive-sealed [mode]
    Every sensitive store exists and is sealed whatever the switch says: ledger entries,
    ``state.bin``, ``care.bin`` and ``safety_plan.bin`` (and the staging ``state.rekey``,
    when present) start with ``OLVD``, key files with ``OLVK``; ``profile.json`` (and
    snapshots) never holds a sensitive field in the clear, its
    ``sealed_fields``/``sealed_profile`` decode to ``OLVD``, and with the switch on it
    holds nothing but ``sealed_profile``. The data directory's lock, recorded while a
    command holds it, must be empty. Any file the audit does not know fails.
master-key-off-disk [mode]
    No keychain value, and no master key in any encoding, appears in a file.
permissions [mode]
    On POSIX every directory is 0700 and every file 0600 (SKIP on Windows).
output-no-typed-text [mode]
    stderr, anything printed past the console, log records and warnings contain no typed
    text at all. On the console (fragments of at least 10 bytes), the explicit exceptions:
    the names the user chose (used to address them, every command); the session's own
    replies, removed before the search (they may reflect the user's words back, SDD §4.1);
    ``memory``: the note, shown verbatim on purpose; ``chat``: the note inside the one
    recall sentence that answers the question about it (F15; the note elsewhere on the
    console still fails); ``safety-plan``: the plan, shown back after it is written.
inspect-no-text [mode]
    The ``--inspect`` panel lines contain no typed text, names included.
stats-numbers-only [mode]
    ``olivia stats`` (F12) printed its numbers (not an "unavailable" or "empty" line), and
    its output holds no typed text, names included, and no line that is not one of the
    ``stats.yaml`` lines with numbers (or the late-night clock times) in its slots. The
    journal answered "有" just before, so the journal-answers line must be there with its
    numbers (the §11.1 lines added after F12 are covered by the same line check).
doctor-no-personal [mode]
    ``olivia doctor`` exited 0, its output holds no typed text, names included, and every
    line is one of its ``DOCTOR_*`` lines (slots filled), the footer last.
doctor-read-only [mode]
    ``olivia doctor`` changed no file or directory under ``OLIVIA_HOME`` (list and
    contents) and read, wrote or deleted no keychain item.
note-recall [mode]
    The second chat answered the question about the note with the note (F15), and its
    panel says so by ids only (``调出笔记 question（found）``), so the two checks above
    really cover a recalled note.
health-cleared-shredded [mode]
    After ``health`` with ``0`` no file under ``OLIVIA_HOME`` (snapshots included) holds
    any health item the run ever recorded, in the clear or as ciphertext that opens under
    a data key the current keychain unwraps (every key file, with the profile's labels):
    deleting health information is a crypto-shred, and a damaged main file can never
    bring it back. Not vacuous: the items are read from the sealed profile beforehand,
    and the same search must find them there just before the deletion.
edit-and-reset-erase [mode]
    After ``memory --edit`` the note reads back with its new words only, and after
    ``forget --method`` the preference is gone; with the old note file, the old
    ``state.bin`` and their old key files copied back (into a copy of ``OLIVIA_HOME``
    elsewhere), neither the old words nor the old preferences open: both were
    crypto-shredded, not just overwritten. The new words are also part of the typed text
    every check above searches for. A card is put in the kit first (as ``/not-now`` would)
    and must survive the reset. ``forget --method`` stages the new state first: the
    data directory is also recorded at that commit point (what a crash there would
    leave, ``state.rekey`` included, so every check above covers it), and afterwards no
    staging copy or staging key is left.
forget-all-clean [mode]
    After ``forget --all --yes`` no file is left under ``OLIVIA_HOME`` and the keychain
    holds no item.
"""

from __future__ import annotations

import os
import re

# Before anything imports keyring: keyring itself only knows its failing backend.
os.environ["PYTHON_KEYRING_BACKEND"] = "keyring.backends.fail.Keyring"

import ast  # noqa: E402
import base64  # noqa: E402
import binascii  # noqa: E402
import contextlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import random  # noqa: E402
import shutil  # noqa: E402
import socket  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
import warnings  # noqa: E402
from collections.abc import Callable, Iterable, Iterator, Mapping  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402
from datetime import UTC, datetime  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any, Final  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

ROOT: Final = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import keyring  # noqa: E402
import keyring.backends.fail  # noqa: E402
import platformdirs  # noqa: E402

keyring.set_keyring(keyring.backends.fail.Keyring())

from olivia import cli  # noqa: E402
from olivia.core.chang.care import CARE_FILENAME  # noqa: E402
from olivia.core.chang.onboarding import load_onboarding_text  # noqa: E402
from olivia.core.chang.profile import PROFILE_FILENAME, SENSITIVE_FIELDS  # noqa: E402
from olivia.core.chang.safety_plan import SAFETY_PLAN_FILENAME, SUGGESTED_FILENAME  # noqa: E402
from olivia.core.chang.stats import StatsText, load_stats_text  # noqa: E402
from olivia.core.crypto import keychain as keychain_module  # noqa: E402
from olivia.core.crypto.aead import DATA_MAGIC  # noqa: E402
from olivia.core.crypto.errors import CryptoError  # noqa: E402
from olivia.core.crypto.keychain import KeyBackend  # noqa: E402
from olivia.core.crypto.vault import KEYS_DIRNAME, Vault  # noqa: E402
from olivia.core.datalock import LOCK_FILENAME  # noqa: E402
from olivia.core.memory.forget import load_forget_text  # noqa: E402
from olivia.core.memory.ledger import LEDGER_DIRNAME, LEDGER_STORE, Ledger  # noqa: E402
from olivia.core.memory.state import (  # noqa: E402
    STATE_FILENAME,
    STATE_REKEY_FILENAME,
    STATE_REKEY_STORE,
    STATE_STORE,
    CarriedState,
    KitEntry,
    StateStore,
)
from olivia.core.memory.text import load_memory_text  # noqa: E402
from olivia.core.session import Session, TurnResult  # noqa: E402
from olivia.core.taxonomy import load_taxonomy  # noqa: E402

PACKAGE_DIR: Final = ROOT / "olivia"
KEY_MAGIC: Final = b"OLVK"
SNAPSHOT_DIRNAME: Final = ".snapshots"
SEALED_FILES: Final = (STATE_FILENAME, CARE_FILENAME, SAFETY_PLAN_FILENAME)
"""Sensitive stores kept as one sealed file each, directly in the data directory."""
STAGED_FILES: Final = (STATE_REKEY_FILENAME,)
"""Sealed staging copies that exist only while a re-key is under way (not required)."""
SHELVED_ACTION: Final = "29:pmr_release"
"""The card put in the kit before ``forget --method`` (edit-and-reset-erase)."""
SEALED_PROFILE: Final = "sealed_profile"
SEALED_FIELDS: Final = "sealed_fields"

NETWORK_MODULES: Final = frozenset(
    {
        "socket",
        "ssl",
        "http",
        "urllib.request",
        "urllib3",
        "requests",
        "httpx",
        "aiohttp",
        "websocket",
        "websockets",
        "ftplib",
        "smtplib",
        "poplib",
        "imaplib",
        "telnetlib",
        "nntplib",
        "xmlrpc",
        "socketserver",
        "webbrowser",
        "grpc",
        "paramiko",
    }
)
"""Modules (and their submodules) that open network connections."""

FILE_FRAGMENT_BYTES: Final = 4
ASCII_FRAGMENT_BYTES: Final = 6
OUTPUT_FRAGMENT_BYTES: Final = 10

# -- what the scripted user types --------------------------------------------------------------

USER_NAME: Final = "青禾"
AGENT_NAME: Final = "阿屿"
TABOO: Final = ("老家的房子", "相亲")
MESSAGES: Final = ("这几天加班到深夜，脑袋一直嗡嗡作响", "给我一个方法")
NOTE: Final = "周四下午要去见搬家公司的人"
EDITED_NOTE: Final = "改到周五上午见搬家师傅老秦"
CRISIS: Final = "我写了一封遗书"
SECOND_MESSAGE: Final = "今晚还是睡不着，翻来覆去地想白天的事"
RECALL_QUESTION: Final = "周四要见的那个人是谁来着"
PLAN: Final = (
    "半夜反复刷手机停不下来",
    "泡一杯热牛奶慢慢喝",
    "绕着小区的湖走一圈",
    "表姐阿禾",
    "139 0571 2468",
    "把那盒安眠药交给室友保管",
)
NAMES: Final = (USER_NAME, AGENT_NAME)
PROFILE_TYPED: Final = (*NAMES, *TABOO)
"""The profile's non-sensitive fields the user typed (plaintext in ``profile.json`` with
the ONB-06 switch off)."""
ALL_TYPED: Final = (
    *PROFILE_TYPED,
    *MESSAGES,
    NOTE,
    EDITED_NOTE,
    CRISIS,
    SECOND_MESSAGE,
    RECALL_QUESTION,
    *PLAN,
)

STDOUT_ECHOES: Final[Mapping[str, tuple[str, ...]]] = {"memory": (NOTE,), "safety-plan": PLAN}
"""Typed text a command shows back on purpose (besides the names, allowed everywhere)."""
RECALLED: Final = load_memory_text().replies["recall_found"].replace("{note}", NOTE)
"""The one sentence in which ``chat`` shows the note back (F15)."""
RECALL_PANEL: Final = "调出笔记 question（found）"

NOW: Final = datetime(2026, 10, 22, 20, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
SEED: Final = 7
PANEL_PREFIXES: Final = ("┌", "│", "└")


def _onboarding(whole: bool) -> list[str]:
    consent = load_onboarding_text().consent_sentence
    return [
        "1",  # disclaimer accepted
        "1",  # 18+
        "2" if whole else "",  # ONB-06: everything encrypted, or only sensitive data
        USER_NAME,
        AGENT_NAME,
        "",  # default persona
        "、".join(TABOO),
        "1",  # mainland China, timezone set automatically
        consent,  # the health consent (a fixed sentence, not user content)
        "",  # no clinical history
        "1",  # one checklist item
    ]


def script(whole: bool) -> list[tuple[list[str], list[str]]]:
    """The commands of one run, each with its input lines."""
    first_chat = [
        *_onboarding(whole),
        "7",  # opening self-rating
        MESSAGES[0],
        MESSAGES[1],  # a card
        "/done",  # its feedback
        f"记住：{NOTE}",
        CRISIS,
        "/exit",
        "/exit",
    ]
    plan = [PLAN[0], "", PLAN[1], "", PLAN[2], "", PLAN[3], PLAN[4], "", PLAN[5], ""]
    # olivia health numbers the clinical-history codes first, then the three checklist items.
    flags = len(load_taxonomy().red_flags())
    return [
        (["chat", "--rules", "--inspect"], first_chat),
        (["health"], [f"{flags + 1}，{flags + 2}"]),  # the first two checklist items
        (["safety-plan"], plan),
        (["journal"], ["有"]),
        (["stats"], []),
        (["memory"], []),
        (["privacy"], []),
        (["doctor"], []),
        (["chat", "--inspect"], [SECOND_MESSAGE, RECALL_QUESTION, "/exit", "/exit"]),
    ]


# -- check building blocks (unit-tested in tests/scripts/test_privacy_audit.py) ---------------


@dataclass(frozen=True)
class Result:
    name: str
    status: str
    """``PASS``, ``FAIL`` or ``SKIP``."""
    detail: str

    @property
    def ok(self) -> bool:
        return self.status != "FAIL"


def _result(name: str, problems: Iterable[str], passed: str) -> Result:
    found = sorted(set(problems))
    if not found:
        return Result(name, "PASS", passed)
    shown = "; ".join(found[:4]) + (f"; ... ({len(found)} in all)" if len(found) > 4 else "")
    return Result(name, "FAIL", shown)


def _is_network(module: str) -> bool:
    parts = module.split(".")
    return any(".".join(parts[:i]) in NETWORK_MODULES for i in range(1, len(parts) + 1))


def _imported_names(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
        return [node.module, *(f"{node.module}.{alias.name}" for alias in node.names)]
    if isinstance(node, ast.Call) and node.args:
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        first = node.args[0]
        if (
            name in {"import_module", "__import__"}
            and isinstance(first, ast.Constant)
            and isinstance(first.value, str)
        ):
            return [first.value]
    return []


def network_imports(package_dir: Path) -> list[str]:
    """``path:line module`` for every networking import in the package's sources."""
    hits: list[str] = []
    for path in sorted(package_dir.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            for name in _imported_names(node):
                if _is_network(name):
                    where = path.relative_to(package_dir.parent).as_posix()
                    hits.append(f"{where}:{getattr(node, 'lineno', 0)} {name}")
    return hits


class NetworkBlock:
    """Record and refuse every outgoing network attempt while active."""

    _SOCKET_METHODS: Final = ("connect", "connect_ex", "bind", "sendto")
    _MODULE_FUNCTIONS: Final = ("create_connection", "getaddrinfo", "gethostbyname")

    def __init__(self) -> None:
        self.attempts: list[str] = []
        self._saved: list[tuple[object, str, object]] = []

    def _refuse(self, what: str) -> Callable[..., Any]:
        def refused(*args: object, **_kwargs: object) -> Any:
            target = args[1] if what in self._SOCKET_METHODS and len(args) > 1 else args[:1]
            self.attempts.append(f"{what}{target!r}")
            raise OSError(f"network access refused by the privacy audit ({what})")

        return refused

    def __enter__(self) -> NetworkBlock:
        for owner, names in (
            (socket.socket, self._SOCKET_METHODS),
            (socket, self._MODULE_FUNCTIONS),
        ):
            for name in names:
                self._saved.append((owner, name, getattr(owner, name)))
                setattr(owner, name, self._refuse(name))
        return self

    def __exit__(self, *_exc: object) -> None:
        while self._saved:
            owner, name, original = self._saved.pop()
            setattr(owner, name, original)


class MemoryKeychain:
    """An in-memory key backend (the shape of ``KeyBackend``); never the OS keychain.

    ``accesses`` counts item reads, writes and deletes; ``ready`` touches no item."""

    def __init__(self) -> None:
        self.items: dict[str, str] = {}
        self.accesses = 0

    def ready(self) -> None:
        return None

    def get(self, name: str) -> str | None:
        self.accesses += 1
        return self.items.get(name)

    def set(self, name: str, value: str) -> None:
        self.accesses += 1
        self.items[name] = value

    def delete(self, name: str) -> None:
        self.accesses += 1
        self.items.pop(name, None)


def fragments(text: str, min_bytes: int = FILE_FRAGMENT_BYTES) -> set[str]:
    """``text`` itself and every shortest run of whole characters of it whose UTF-8 form
    has at least ``min_bytes`` bytes (at least :data:`ASCII_FRAGMENT_BYTES` for an
    all-ASCII run, so random ciphertext or base64 cannot match it by chance)."""
    found = {text} if text.strip() else set()
    for start in range(len(text)):
        size = 0
        for end in range(start, len(text)):
            size += len(text[end].encode("utf-8"))
            run = text[start : end + 1]
            floor = max(min_bytes, ASCII_FRAGMENT_BYTES) if run.isascii() else min_bytes
            if size >= floor:
                if run.strip():
                    found.add(run)
                break
    return found


def encodings(fragment: str) -> set[bytes]:
    """The byte forms searched for: UTF-8 and JSON's ``\\u`` escapes."""
    return {fragment.encode("utf-8"), json.dumps(fragment)[1:-1].encode("ascii")}


def needles(texts: Iterable[str], min_bytes: int = FILE_FRAGMENT_BYTES) -> dict[bytes, str]:
    """Byte needle -> the typed text it is a fragment of, for every fragment of ``texts``."""
    return {
        form: text
        for text in texts
        for frag in fragments(text, min_bytes)
        for form in encodings(frag)
    }


Files = Iterable[tuple[str, bytes]]
"""(path relative to the data directory, contents); a path may come in several versions."""


def text_hits(data: bytes, wanted: Mapping[bytes, str]) -> set[str]:
    """The typed texts some fragment of which occurs in ``data``."""
    return {text for form, text in wanted.items() if form in data}


def is_profile(rel: str) -> bool:
    return rel == PROFILE_FILENAME or rel.startswith(f"{SNAPSHOT_DIRNAME}/{PROFILE_FILENAME}/")


def leaked_text(files: Files, typed: Iterable[str], profile_plain: Iterable[str] = ()) -> list[str]:
    """``file: typed text`` for each typed text with a fragment in a file; fragments of
    ``profile_plain`` are allowed in the profile and its snapshots."""
    wanted = needles(typed)
    allowed = needles(profile_plain)
    in_profile = {form: text for form, text in wanted.items() if form not in allowed}
    problems = []
    for rel, data in files:
        for text in text_hits(data, in_profile if is_profile(rel) else wanted):
            problems.append(f"{rel}: 「{text}」")
    return problems


def _b64_sealed(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return base64.b64decode(value, validate=True).startswith(DATA_MAGIC)
    except (binascii.Error, ValueError):
        return False


def _profile_problems(rel: str, data: bytes, whole: bool) -> list[str]:
    try:
        doc = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return [f"{rel}: not JSON"]
    if not isinstance(doc, dict):
        return [f"{rel}: not a JSON object"]
    problems = [f"{rel}: {name} in the clear" for name in SENSITIVE_FIELDS if name in doc]
    if whole and set(doc) != {SEALED_PROFILE}:
        problems.append(f"{rel}: switch on but not only {SEALED_PROFILE}")
    for key in (SEALED_PROFILE, SEALED_FIELDS):
        if key in doc and not _b64_sealed(doc[key]):
            problems.append(f"{rel}: {key} is not an OLVD blob")
    return problems


def unsealed(files: Files, whole: bool, *, health_recorded: bool) -> list[str]:
    """Problems with how the data directory's files are sealed (see the module docstring).

    Every sensitive store must occur in some version: an audit that never saw one would
    pass vacuously."""
    versions = list(files)
    names = {rel for rel, _ in versions}
    problems: list[str] = []
    for rel, data in versions:
        if is_profile(rel):
            problems += _profile_problems(rel, data, whole)
        elif (
            rel in SEALED_FILES
            or rel in STAGED_FILES
            or (rel.startswith(f"{LEDGER_DIRNAME}/") and rel.endswith(".olv"))
        ):
            if not data.startswith(DATA_MAGIC):
                problems.append(f"{rel}: not sealed (no OLVD)")
        elif rel.startswith(f"{KEYS_DIRNAME}/") and rel.endswith(".key"):
            if not data.startswith(KEY_MAGIC):
                problems.append(f"{rel}: not a wrapped key (no OLVK)")
        elif rel in (SUGGESTED_FILENAME, LOCK_FILENAME):  # the lock: held mid-command
            if data:
                problems.append(f"{rel}: marker is not empty")
        else:
            problems.append(f"{rel}: unexpected file")
    for name in SEALED_FILES:
        if name not in names:
            problems.append(f"{name}: not written by the scripted run")
    if not any(rel.startswith(f"{LEDGER_DIRNAME}/") for rel in names):
        problems.append(f"{LEDGER_DIRNAME}/: not written by the scripted run")
    profiles = [data for rel, data in versions if rel == PROFILE_FILENAME]
    if not profiles:
        problems.append(f"{PROFILE_FILENAME}: not written by the scripted run")
    elif health_recorded and not whole and SEALED_FIELDS.encode() not in profiles[-1]:
        problems.append(f"{PROFILE_FILENAME}: health recorded but no {SEALED_FIELDS}")
    return problems


def key_forms(keychain_items: Iterable[tuple[str, str]]) -> dict[bytes, str]:
    """Byte forms of every keychain value and of the key inside it -> the item name."""
    forms: dict[bytes, str] = {}
    for name, value in keychain_items:
        forms[value.encode("utf-8")] = name
        secret = value.rsplit(":", 1)[-1]
        forms[secret.encode("ascii", "ignore")] = name
        with contextlib.suppress(binascii.Error, ValueError):
            raw = base64.b64decode(secret, validate=True)
            forms[raw] = name
            forms[raw.hex().encode("ascii")] = name
    return {form: name for form, name in forms.items() if len(form) >= 16}


def keys_on_disk(files: Files, keychain_items: Iterable[tuple[str, str]]) -> list[str]:
    forms = key_forms(keychain_items)
    return [f"{rel}: {name}" for rel, data in files for form, name in forms.items() if form in data]


OPEN_LABELS: Final = ("", "fields", "whole", "staged")
"""The labels the profile store seals under (``olivia/core/chang/profile.py``), and none."""
Opener = Callable[[bytes], list[bytes]]
"""A blob -> every plaintext it opens to under the keys on hand."""


def ciphertexts(data: bytes) -> list[bytes]:
    """The OLVD blobs a file holds: the file itself, or base64 values of a JSON object."""
    found = [data] if data.startswith(DATA_MAGIC) else []
    try:
        doc = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return found
    if isinstance(doc, dict):
        for value in doc.values():
            if isinstance(value, str):
                with contextlib.suppress(binascii.Error, ValueError):
                    blob = base64.b64decode(value, validate=True)
                    if blob.startswith(DATA_MAGIC):
                        found.append(blob)
    return found


def key_opener(home: Path, backend: KeyBackend) -> Opener:
    """Opens a blob under every data key in ``home`` that ``backend`` unwraps now."""
    vault = Vault(home, backend)
    keys = home / KEYS_DIRNAME
    stores = sorted(p.stem for p in keys.glob("*.key")) if keys.is_dir() else []

    def open_all(blob: bytes) -> list[bytes]:
        plain = []
        for store in stores:
            for label in OPEN_LABELS:
                with contextlib.suppress(CryptoError, ValueError):
                    plain.append(vault.open(store, blob, label=label))
        return plain

    return open_all


def held_health(files: Files, opener: Opener) -> set[str]:
    """The health items the sealed ``profile.json`` holds (its fields or the whole profile)."""
    items: set[str] = set()
    for rel, data in files:
        if rel != PROFILE_FILENAME:
            continue
        for blob in ciphertexts(data):
            for plain in opener(blob):
                with contextlib.suppress(UnicodeDecodeError, ValueError, RecursionError):
                    doc = json.loads(plain.decode("utf-8"))
                    if isinstance(doc, dict):
                        for name in SENSITIVE_FIELDS:
                            values = doc.get(name)
                            if isinstance(values, list):
                                items.update(v for v in values if isinstance(v, str))
    return items


def readable_health(files: Files, opener: Opener, items: Iterable[str]) -> list[str]:
    """``file: item`` for each health item a file holds in the clear or opens to."""
    wanted = {json.dumps(item, ensure_ascii=False).encode("utf-8"): item for item in items}
    problems = []
    for rel, data in files:
        if rel.startswith(f"{KEYS_DIRNAME}/"):
            continue
        texts = [data, *(plain for blob in ciphertexts(data) for plain in opener(blob))]
        for form, item in wanted.items():
            if any(form in text for text in texts):
                problems.append(f"{rel}: {item}")
    return problems


def health_erasure(
    before: list[str], after: list[str], items: Iterable[str], *, deleted: bool
) -> list[str]:
    """Problems of ``health-cleared-shredded``: ``before``/``after`` are
    :func:`readable_health` just before and after ``health`` with ``0``."""
    problems = [] if deleted else ["health 0 did not delete the health information"]
    if not set(items):
        problems.append("no health item was recorded by the scripted run")
    elif not before:
        problems.append("the recorded health items were not found before the deletion")
    return problems + [f"still opens after 0: {hit}" for hit in after]


def permission_problems(modes: Iterable[tuple[str, bool, int]]) -> list[str]:
    """``modes``: (relative path, is a directory, permission bits)."""
    problems = []
    for rel, is_dir, mode in modes:
        want = 0o700 if is_dir else 0o600
        if mode != want:
            problems.append(f"{rel or '.'}: {oct(mode)} (want {oct(want)})")
    return problems


@dataclass
class Capture:
    """One command's run."""

    argv: tuple[str, ...]
    code: int
    console: str
    replies: list[str]
    stray: str
    """Written to the real ``sys.stdout``/``sys.stderr`` (``print``, tracebacks)."""
    logs: list[str]
    warned: list[str]

    @property
    def command(self) -> str:
        return self.argv[0]


def output_leaks(capture: Capture, typed: Iterable[str]) -> list[str]:
    """Typed text in a command's output beyond the explicit exceptions (module docstring)."""
    texts = tuple(typed)
    strict = needles(texts, OUTPUT_FRAGMENT_BYTES)
    for name in NAMES:  # short names are searched whole
        strict.update({form: name for form in encodings(name) if name in texts})
    label = " ".join(capture.argv)
    problems = []
    quiet = [("stderr/print", capture.stray), *(("log", r) for r in capture.logs)]
    quiet += [("warning", w) for w in capture.warned]
    for where, text in quiet:
        problems += [f"{label} {where}: 「{f}」" for f in text_hits(text.encode(), strict)]
    console = capture.console
    for reply in sorted(capture.replies, key=len, reverse=True):
        console = console.replace(reply, "")
    if capture.command == "chat":
        console = console.replace(RECALLED, "")
    lines = [ln for ln in console.splitlines() if not ln.startswith(PANEL_PREFIXES)]
    allowed = set(NAMES) | set(STDOUT_ECHOES.get(capture.command, ()))
    console_needles = needles((t for t in texts if t not in allowed), OUTPUT_FRAGMENT_BYTES)
    hits = text_hits("\n".join(lines).encode(), console_needles)
    problems += [f"{label} console: 「{f}」" for f in hits]
    return problems


def panel_leaks(capture: Capture, typed: Iterable[str]) -> list[str]:
    texts = tuple(typed)
    wanted = needles(texts, FILE_FRAGMENT_BYTES)
    for text in texts:
        wanted.update({form: text for form in encodings(text)})
    panel = "\n".join(ln for ln in capture.console.splitlines() if ln.startswith(PANEL_PREFIXES))
    return [f"{' '.join(capture.argv)}: 「{f}」" for f in text_hits(panel.encode(), wanted)]


_NUMBER: Final = r"(?:\d{2}:\d{2}|[+-]?\d+(?:\.\d+)?)"


def numbers_pattern(template: str) -> str:
    """``template`` as a regular expression with a number in each of its slots."""
    return _NUMBER.join(re.escape(part) for part in re.split(r"\{\w+\}", template))


def stats_patterns(text: StatsText) -> list[re.Pattern[str]]:
    """Every line ``olivia stats`` may print: a ``lines`` template with numbers in its
    slots (``unknown`` only appended to another line), or a ``replies`` sentence."""
    pattern = numbers_pattern

    unknown = pattern(text.lines["unknown"])
    lines = [pattern(t) for key, t in text.lines.items() if key != "unknown"]
    replies = [re.escape(r) for r in text.replies.values()]
    return [re.compile(f"{p}(?:{unknown})?") for p in lines] + [re.compile(r) for r in replies]


def stats_problems(capture: Capture, typed: Iterable[str], text: StatsText) -> list[str]:
    """What is wrong with one ``olivia stats`` run (see ``stats-numbers-only``)."""
    # Console-length fragments (the template's own two-character words, such as 深夜,
    # would match shorter ones), plus every typed text whole: the names too. The line
    # check below is the stronger one: a line that is a template with numbers in its
    # slots cannot carry typed text.
    texts = tuple(typed)
    wanted = needles(texts, OUTPUT_FRAGMENT_BYTES)
    for item in texts:
        wanted.update({form: item for form in encodings(item)})
    problems = [f"typed text: 「{f}」" for f in text_hits(capture.console.encode(), wanted)]
    patterns = stats_patterns(text)
    lines = capture.console.splitlines()
    problems += [
        f"not a stats line: {i + 1}"
        for i, line in enumerate(lines)
        if not any(p.fullmatch(line) for p in patterns)
    ]
    if not lines or lines[0] != text.lines["heading"]:
        problems.append("no numbers were printed")
    return problems


def doctor_patterns() -> list[re.Pattern[str]]:
    """Every line ``olivia doctor`` may print: a ``DOCTOR_*`` text behind its mark (or as
    an indented note), slots filled with anything on one line, the stale suffixes
    appended to their lines."""

    def pattern(template: str) -> str:
        return r"[^\n]+?".join(re.escape(part) for part in re.split(r"\{\w+\}", template))

    suffixes = f"(?:{pattern(cli.DOCTOR_HOTLINES_STALE)}|{pattern(cli.DOCTOR_UPDATE_STALE)})?"
    marks = "|".join(re.escape(m) for m in (cli.DOCTOR_OK, cli.DOCTOR_WARN, cli.DOCTOR_FAIL))
    lines = [re.escape(cli.DOCTOR_HEADING), re.escape(cli.DOCTOR_FOOTER)]
    lines.append(f"  {re.escape(cli.DOCTOR_STORES_NOTE)}")
    states = [
        template.replace("{name}", name)
        for name in cli.DOCTOR_STORE_NAMES.values()
        for _, template in cli.DOCTOR_STORE_STATES.values()
    ]
    skip = {
        cli.DOCTOR_HEADING,
        cli.DOCTOR_FOOTER,
        cli.DOCTOR_STORES_NOTE,
        cli.DOCTOR_HOTLINES_STALE,
        cli.DOCTOR_UPDATE_STALE,
        *cli.DOCTOR_STORE_NAMES.values(),
    }
    bodies = [t for t in cli.DOCTOR_TEXTS if t not in skip and "{name}" not in t] + states
    lines += [f"(?:{marks}) {pattern(body)}{suffixes}" for body in bodies]
    return [re.compile(line) for line in lines]


def doctor_problems(capture: Capture, typed: Iterable[str]) -> list[str]:
    """What is wrong with one ``olivia doctor`` run (see ``doctor-no-personal``)."""
    texts = tuple(typed)
    wanted = needles(texts, OUTPUT_FRAGMENT_BYTES)
    for item in texts:
        wanted.update({form: item for form in encodings(item)})
    problems = [f"typed text: 「{f}」" for f in text_hits(capture.console.encode(), wanted)]
    if capture.code != 0:
        problems.append(f"exited {capture.code}")
    patterns = doctor_patterns()
    lines = capture.console.splitlines()
    problems += [
        f"not a doctor line: {i + 1}"
        for i, line in enumerate(lines)
        if not any(p.fullmatch(line) for p in patterns)
    ]
    if not lines or lines[-1] != cli.DOCTOR_FOOTER:
        problems.append("the footer is not the last line")
    return problems


def tree(home: Path) -> dict[str, bytes | None]:
    """Every path under ``home`` with its contents (directories: None)."""
    return {
        p.relative_to(home).as_posix(): (p.read_bytes() if p.is_file() else None)
        for p in sorted(home.rglob("*"))
    }


def tree_changes(
    before: Mapping[str, bytes | None], after: Mapping[str, bytes | None]
) -> list[str]:
    changed = [f"added: {rel}" for rel in after if rel not in before]
    changed += [f"removed: {rel}" for rel in before if rel not in after]
    changed += [f"changed: {rel}" for rel in before if rel in after and before[rel] != after[rel]]
    return changed


# -- the scripted run --------------------------------------------------------------------------


@contextlib.contextmanager
def _patched(owner: object, name: str, value: object) -> Iterator[None]:
    original = getattr(owner, name)
    setattr(owner, name, value)
    try:
        yield
    finally:
        setattr(owner, name, original)


@contextlib.contextmanager
def _env(name: str, value: str) -> Iterator[None]:
    before = os.environ.get(name)
    os.environ[name] = value
    try:
        yield
    finally:
        if before is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = before


class _LogCatcher(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.records: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record.getMessage())


@dataclass
class Run:
    """What one scripted run saw. The data directory and the keychain are recorded after
    every command (all versions kept), since later commands remove some stores (the care
    marker is used up by the next chat)."""

    whole: bool
    captures: list[Capture] = field(default_factory=list)
    files: list[tuple[str, bytes]] = field(default_factory=list)
    modes: list[tuple[str, bool, int]] = field(default_factory=list)
    keychain_seen: list[tuple[str, str]] = field(default_factory=list)
    left_after_forget: list[str] = field(default_factory=list)
    keychain_after: dict[str, str] = field(default_factory=dict)
    erase_problems: list[str] = field(default_factory=list)
    network: list[str] = field(default_factory=list)
    doctor_changes: list[str] = field(default_factory=list)
    """What ``olivia doctor`` changed in the data directory or the keychain."""
    user_dir_calls: int = 0
    outside_home: list[str] = field(default_factory=list)
    health_items: list[str] = field(default_factory=list)
    health_before: list[str] = field(default_factory=list)
    health_after: list[str] = field(default_factory=list)
    health_deleted: bool = False

    @property
    def mode(self) -> str:
        return "switch-on" if self.whole else "switch-off"

    def record(self, home: Path, keychain_items: Mapping[str, str]) -> None:
        def add(items: list[Any], item: Any) -> None:
            if item not in items:
                items.append(item)

        add(self.modes, ("", True, home.stat().st_mode & 0o777))
        for path in sorted(home.rglob("*")):
            rel = path.relative_to(home).as_posix()
            add(self.modes, (rel, path.is_dir(), path.stat().st_mode & 0o777))
            if path.is_file():
                add(self.files, (rel, path.read_bytes()))
        for item in keychain_items.items():
            add(self.keychain_seen, item)


def _invoke(argv: list[str], lines: list[str]) -> Capture:
    replies: list[str] = []
    original_turn = Session.turn

    def spy(self: Session, text: str) -> TurnResult:
        result = original_turn(self, text)
        replies.append(result.reply)
        return result

    console = io.StringIO()
    stray = io.StringIO()
    catcher = _LogCatcher()
    root = logging.getLogger()
    level = root.level
    root.addHandler(catcher)
    root.setLevel(logging.DEBUG)
    try:
        with (
            _patched(Session, "turn", spy),
            contextlib.redirect_stdout(stray),
            contextlib.redirect_stderr(stray),
            warnings.catch_warnings(record=True) as caught,
        ):
            warnings.simplefilter("always")
            try:
                code = cli.main(
                    argv,
                    stdin=io.StringIO("".join(f"{line}\n" for line in lines)),
                    stdout=console,
                    clock=lambda: NOW,
                    rng=random.Random(SEED),
                )
            except SystemExit as exc:  # argparse refusing the command line
                code = exc.code if isinstance(exc.code, int) else 1
    finally:
        root.removeHandler(catcher)
        root.setLevel(level)
    return Capture(
        tuple(argv),
        code,
        console.getvalue(),
        replies,
        stray.getvalue(),
        catcher.records,
        [str(w.message) for w in caught],
    )


def _home_files(home: Path) -> list[tuple[str, bytes]]:
    return [
        (path.relative_to(home).as_posix(), path.read_bytes())
        for path in sorted(home.rglob("*"))
        if path.is_file()
    ]


def _clear_health(run: Run, home: Path, backend: MemoryKeychain) -> None:
    """``health`` twice: a clinical-history code in and a checklist item out (a re-key
    while health stays recorded), then ``0``; see ``health-cleared-shredded``."""
    items = held_health(_home_files(home), key_opener(home, backend))
    flags = len(load_taxonomy().red_flags())
    run.captures.append(_invoke(["health"], [f"1，{flags + 1}"]))
    run.record(home, backend.items)  # still recorded: the other checks cover this version
    items |= held_health(_home_files(home), key_opener(home, backend))
    run.health_before = readable_health(_home_files(home), key_opener(home, backend), items)
    capture = _invoke(["health"], ["0"])
    run.captures.append(capture)
    run.health_deleted = load_onboarding_text().health["cleared"] in capture.console
    run.health_after = readable_health(_home_files(home), key_opener(home, backend), items)
    run.health_items = sorted(items)


def _old_copies_open(home: Path, old: Mapping[str, bytes]) -> list[str]:
    """Put the files in ``old`` (relative paths) back into a copy of ``home`` made outside
    the audit's temporary root, and say what of the old data still opens there."""
    problems = []
    with tempfile.TemporaryDirectory(prefix="olivia-privacy-audit-old-") as aside:
        copy = Path(aside) / "home"
        shutil.copytree(home, copy)
        for rel, data in old.items():
            target = copy / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        if any(n.text == NOTE for n in Ledger(copy, Vault(copy)).notes()):
            problems.append("the old note opens again with its old files")
        if StateStore(copy, Vault(copy)).load() is not None:
            problems.append("the old preferences open again with their old files")
    return problems


def _edit_and_reset(home: Path, run: Run, backend: MemoryKeychain) -> None:
    """``memory --edit`` on the note, then ``forget --method 1``; see the module docstring."""
    note_files = sorted((home / LEDGER_DIRNAME).glob("*.olv"))
    old_paths = [
        *note_files,
        home / STATE_FILENAME,
        home / KEYS_DIRNAME / f"{LEDGER_STORE}.key",
        home / KEYS_DIRNAME / f"{STATE_STORE}.key",
    ]
    old = {p.relative_to(home).as_posix(): p.read_bytes() for p in old_paths if p.is_file()}
    entries = Ledger(home, Vault(home)).entries()
    number = next((i for i, e in enumerate(entries, 1) if getattr(e, "text", None) == NOTE), 0)
    problems = [] if number else ["no note to edit"]
    edit = _invoke(["memory", "--edit", str(number)], [EDITED_NOTE, "确认"])
    run.captures.append(edit)
    run.record(home, backend.items)
    # One shelved card, as ``/not-now`` would leave it, so the reset has a kit to keep and
    # has to stage the new state (a state left empty is only shredded).
    store = StateStore(home, Vault(home))
    held = store.load()
    shelved = KitEntry(SHELVED_ACTION, datetime.now(UTC))
    if held is None or not store.save(CarriedState(held.bandit, (*held.kit, shelved))):
        problems.append("no state to reset")
    staged: list[bool] = []
    apply_rekey = StateStore._apply_rekey

    def at_commit_point(store: StateStore, state: CarriedState) -> bool:
        """The data directory as a crash right after the commit point would leave it."""
        staged.append(store.staging.is_file())
        run.record(home, backend.items)
        return apply_rekey(store, state)

    with _patched(StateStore, "_apply_rekey", at_commit_point):
        reset = _invoke(["forget", "--method", "1"], ["确定"])
    run.captures.append(reset)
    run.record(home, backend.items)
    if staged != [True]:
        problems.append("forget --method did not stage the new state first")
    after = StateStore(home, Vault(home)).load()
    if after is None or shelved not in after.kit:
        problems.append("forget --method did not keep the kit")
    if (home / STATE_REKEY_FILENAME).exists() or Vault(home).has_data_key(STATE_REKEY_STORE):
        problems.append("forget --method left its staging copy behind")
    if [n.text for n in Ledger(home, Vault(home)).notes()] != [EDITED_NOTE]:
        problems.append("the edited note does not read back with its new words")
    done = load_forget_text().forget["done_method"].split("{title}")[-1]
    if done not in reset.console:
        problems.append("no method preference was reset")
    problems += _old_copies_open(home, old)
    run.erase_problems = problems


def run_scripted(whole: bool) -> Run:
    """One scripted run in a fresh temporary ``OLIVIA_HOME``; see the module docstring."""
    run = Run(whole)
    backend = MemoryKeychain()

    def no_keyring(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("the privacy audit never uses the OS keychain")

    def no_user_dir(*_args: object, **_kwargs: object) -> Path:
        run.user_dir_calls += 1
        raise RuntimeError("the privacy audit never resolves the real user data directory")

    with tempfile.TemporaryDirectory(prefix="olivia-privacy-audit-") as tmp:
        root = Path(tmp)
        home = root / "home"
        with (
            _env("OLIVIA_HOME", str(home)),
            _patched(keychain_module, "default_backend", lambda: backend),
            _patched(keyring, "get_keyring", no_keyring),
            _patched(platformdirs, "user_data_path", no_user_dir),
            _patched(platformdirs, "user_data_dir", no_user_dir),
            NetworkBlock() as block,
        ):
            for argv, lines in script(whole):
                before, accesses = tree(home), backend.accesses
                run.captures.append(_invoke(argv, lines))
                if argv[0] == "doctor":
                    run.doctor_changes = tree_changes(before, tree(home))
                    if backend.accesses != accesses:
                        run.doctor_changes.append("a keychain item was accessed")
                run.record(home, backend.items)
            _edit_and_reset(home, run, backend)
            _clear_health(run, home, backend)
            run.captures.append(_invoke(["forget", "--all", "--yes"], []))
            run.left_after_forget = sorted(
                p.relative_to(home).as_posix() for p in home.rglob("*") if p.is_file()
            )
            run.keychain_after = dict(backend.items)
            run.network = list(block.attempts)
            run.outside_home = sorted(p.name for p in root.iterdir() if p.name != "home")
    return run


def run_checks(run: Run) -> list[Result]:
    mode = run.mode
    failed = [f"{' '.join(c.argv)} exited {c.code}" for c in run.captures if c.code != 0]
    versions = len(run.files)
    results = [
        _result(f"scripted-run [{mode}]", failed, f"{len(run.captures)} commands, all exit 0")
    ]
    profile_plain = () if run.whole else PROFILE_TYPED
    results.append(
        _result(
            f"files-no-typed-text [{mode}]",
            leaked_text(run.files, ALL_TYPED, profile_plain),
            f"{versions} file versions searched"
            + ("" if run.whole else "; names and taboo topics allowed in the profile only"),
        )
    )
    results.append(
        _result(
            f"sensitive-sealed [{mode}]",
            unsealed(run.files, run.whole, health_recorded=True),
            "ledger, state, care, safety plan OLVD; keys OLVK; profile as expected",
        )
    )
    results.append(
        _result(
            f"master-key-off-disk [{mode}]",
            keys_on_disk(run.files, run.keychain_seen),
            f"{len(run.keychain_seen)} keychain value(s) seen, none on disk",
        )
    )
    if os.name == "nt":
        results.append(Result(f"permissions [{mode}]", "SKIP", "Windows: POSIX modes do not apply"))
    else:
        results.append(
            _result(
                f"permissions [{mode}]",
                permission_problems(run.modes),
                f"{len(run.modes)} paths: dirs 0700, files 0600",
            )
        )
    leaks = [p for c in run.captures for p in output_leaks(c, ALL_TYPED)]
    results.append(
        _result(
            f"output-no-typed-text [{mode}]",
            leaks,
            "exceptions: names; session replies; memory note; recall line; safety-plan plan",
        )
    )
    panels = [p for c in run.captures for p in panel_leaks(c, ALL_TYPED)]
    shown = sum(c.console.count("┌ inspect") for c in run.captures)
    results.append(_result(f"inspect-no-text [{mode}]", panels, f"{shown} panels"))
    stats_runs = [c for c in run.captures if c.command == "stats"]
    words = load_stats_text()
    numbers = [p for c in stats_runs for p in stats_problems(c, ALL_TYPED, words)]
    if len(stats_runs) != 1:
        numbers.append(f"{len(stats_runs)} stats runs, expected 1")
    answered = re.compile(numbers_pattern(words.lines["journal_helpful"]))
    if not any(answered.fullmatch(ln) for c in stats_runs for ln in c.console.splitlines()):
        numbers.append("no journal-answers line with numbers")
    printed = sum(len(c.console.splitlines()) for c in stats_runs)
    results.append(
        _result(f"stats-numbers-only [{mode}]", numbers, f"{printed} lines, numbers only")
    )
    doctors = [c for c in run.captures if c.command == "doctor"]
    found = [p for c in doctors for p in doctor_problems(c, ALL_TYPED)]
    if len(doctors) != 1:
        found.append(f"{len(doctors)} doctor runs, expected 1")
    printed = sum(len(c.console.splitlines()) for c in doctors)
    results.append(
        _result(f"doctor-no-personal [{mode}]", found, f"{printed} lines, all doctor lines")
    )
    results.append(
        _result(
            f"doctor-read-only [{mode}]",
            run.doctor_changes,
            "no file or keychain item touched",
        )
    )
    chats = [c for c in run.captures if c.command == "chat"]
    recall = [] if RECALLED in chats[-1].console else ["the note question got no recalled note"]
    if RECALL_PANEL not in chats[-1].console:
        recall.append(f"no panel line {RECALL_PANEL}")
    results.append(_result(f"note-recall [{mode}]", recall, "recalled in the reply, ids in panel"))
    erasure = health_erasure(
        run.health_before, run.health_after, run.health_items, deleted=run.health_deleted
    )
    results.append(
        _result(
            f"health-cleared-shredded [{mode}]",
            erasure,
            f"{len(run.health_items)} health item(s) recorded, none opens after 0",
        )
    )
    results.append(
        _result(
            f"edit-and-reset-erase [{mode}]",
            run.erase_problems,
            "old note and old preferences do not open with their old files",
        )
    )
    forget = [f"file left: {rel}" for rel in run.left_after_forget]
    forget += [f"keychain item left: {name}" for name in run.keychain_after]
    results.append(_result(f"forget-all-clean [{mode}]", forget, "no file, no keychain item"))
    return results


def audit() -> list[Result]:
    results = [
        _result(
            "network-imports",
            network_imports(PACKAGE_DIR),
            f"{sum(1 for _ in PACKAGE_DIR.rglob('*.py'))} modules scanned",
        )
    ]
    runs = [run_scripted(whole=False), run_scripted(whole=True)]
    attempts = [a for run in runs for a in run.network]
    results.append(_result("network-runtime", attempts, "no connection attempt"))
    local = [f"user data directory resolved {r.user_dir_calls}x" for r in runs if r.user_dir_calls]
    local += [f"written outside OLIVIA_HOME: {name}" for r in runs for name in r.outside_home]
    results.append(_result("data-stays-local", local, "only OLIVIA_HOME was used"))
    for run in runs:
        results += run_checks(run)
    return results


def render(results: Iterable[Result]) -> str:
    rows = [("check", "result", "detail"), *((r.name, r.status, r.detail) for r in results)]
    widths = [max(len(row[i]) for row in rows) for i in range(2)]
    lines = []
    for index, (name, status, detail) in enumerate(rows):
        lines.append(f"{name.ljust(widths[0])}  {status.ljust(widths[1])}  {detail}")
        if index == 0:
            lines.append(f"{'-' * widths[0]}  {'-' * widths[1]}  {'-' * 6}")
    return "\n".join(lines)


def main() -> int:
    started = time.perf_counter()
    results = audit()
    print(render(results))
    failed = sum(1 for r in results if not r.ok)
    elapsed = time.perf_counter() - started
    verdict = "all checks passed" if not failed else f"{failed} check(s) failed"
    print(f"\nprivacy audit: {verdict} ({elapsed:.1f} s)")
    return 0 if not failed else 1


if __name__ == "__main__":
    # The table holds Chinese fragments; do not depend on the locale's encoding.
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8")
    raise SystemExit(main())
