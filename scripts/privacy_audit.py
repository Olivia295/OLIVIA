#!/usr/bin/env python3
"""Automatic privacy audit: the automatic part of gate G-4 (ruling 32; next-phase plan B8).

    python scripts/privacy_audit.py

Prints one table row per check and exits 0 only when every check passes (a check that
cannot apply on this platform is SKIP, never FAIL). The legal report is G-4's external
part and is not replaced by this script.

How it runs: the ``olivia`` command line is driven in this process, twice, on scripted
input, each time in a fresh temporary ``OLIVIA_HOME``: once with the ONB-06 switch off
(only sensitive data encrypted) and once with it on (everything encrypted). Each run
goes through ``chat --inspect`` (onboarding with the health consent and a checklist item,
an opening self-rating, a message, a card and its feedback, a note "记住：……", a crisis
turn), ``health``, ``safety-plan``, ``journal``, ``memory``, ``privacy``, a second
``chat --model --inspect`` (care greeting, model path), then ``forget --all``.

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
    ``state.bin``, ``care.bin`` and ``safety_plan.bin`` start with ``OLVD``, key files with
    ``OLVK``; ``profile.json`` (and snapshots) never holds a sensitive field in the clear,
    its ``sealed_fields``/``sealed_profile`` decode to ``OLVD``, and with the switch on it
    holds nothing but ``sealed_profile``. Any file the audit does not know fails.
master-key-off-disk [mode]
    No keychain value, and no master key in any encoding, appears in a file.
permissions [mode]
    On POSIX every directory is 0700 and every file 0600 (SKIP on Windows).
output-no-typed-text [mode]
    stderr, anything printed past the console, log records and warnings contain no typed
    text at all. On the console (fragments of at least 10 bytes), the explicit exceptions:
    the names the user chose (used to address them, every command); the session's own
    replies, removed before the search (they may reflect the user's words back, SDD §4.1);
    ``memory``: the note, shown verbatim on purpose; ``safety-plan``: the plan, shown back
    after it is written.
inspect-no-text [mode]
    The ``--inspect`` panel lines contain no typed text, names included.
forget-all-clean [mode]
    After ``forget --all --yes`` no file is left under ``OLIVIA_HOME`` and the keychain
    holds no item.
"""

from __future__ import annotations

import os

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
import socket  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
import warnings  # noqa: E402
from collections.abc import Callable, Iterable, Iterator, Mapping  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402
from datetime import datetime  # noqa: E402
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
from olivia.core.crypto import keychain as keychain_module  # noqa: E402
from olivia.core.crypto.aead import DATA_MAGIC  # noqa: E402
from olivia.core.crypto.vault import KEYS_DIRNAME  # noqa: E402
from olivia.core.memory.ledger import LEDGER_DIRNAME  # noqa: E402
from olivia.core.memory.state import STATE_FILENAME  # noqa: E402
from olivia.core.session import Session, TurnResult  # noqa: E402
from olivia.core.taxonomy import load_taxonomy  # noqa: E402

PACKAGE_DIR: Final = ROOT / "olivia"
KEY_MAGIC: Final = b"OLVK"
SNAPSHOT_DIRNAME: Final = ".snapshots"
SEALED_FILES: Final = (STATE_FILENAME, CARE_FILENAME, SAFETY_PLAN_FILENAME)
"""Sensitive stores kept as one sealed file each, directly in the data directory."""
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
CRISIS: Final = "我写了一封遗书"
SECOND_MESSAGE: Final = "今晚还是睡不着，翻来覆去地想白天的事"
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
ALL_TYPED: Final = (*PROFILE_TYPED, *MESSAGES, NOTE, CRISIS, SECOND_MESSAGE, *PLAN)

STDOUT_ECHOES: Final[Mapping[str, tuple[str, ...]]] = {"memory": (NOTE,), "safety-plan": PLAN}
"""Typed text a command shows back on purpose (besides the names, allowed everywhere)."""

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
        (["chat", "--inspect"], first_chat),
        (["health"], [f"{flags + 1}，{flags + 2}"]),  # the first two checklist items
        (["safety-plan"], plan),
        (["journal"], ["有"]),
        (["memory"], []),
        (["privacy"], []),
        (["chat", "--model", "--inspect"], [SECOND_MESSAGE, "/exit", "/exit"]),
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
    """An in-memory key backend (the shape of ``KeyBackend``); never the OS keychain."""

    def __init__(self) -> None:
        self.items: dict[str, str] = {}

    def get(self, name: str) -> str | None:
        return self.items.get(name)

    def set(self, name: str, value: str) -> None:
        self.items[name] = value

    def delete(self, name: str) -> None:
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
        elif rel in SEALED_FILES or (rel.startswith(f"{LEDGER_DIRNAME}/") and rel.endswith(".olv")):
            if not data.startswith(DATA_MAGIC):
                problems.append(f"{rel}: not sealed (no OLVD)")
        elif rel.startswith(f"{KEYS_DIRNAME}/") and rel.endswith(".key"):
            if not data.startswith(KEY_MAGIC):
                problems.append(f"{rel}: not a wrapped key (no OLVK)")
        elif rel == SUGGESTED_FILENAME:
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
    network: list[str] = field(default_factory=list)
    user_dir_calls: int = 0
    outside_home: list[str] = field(default_factory=list)

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
                run.captures.append(_invoke(argv, lines))
                run.record(home, backend.items)
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
            "exceptions: names; session replies; memory note; safety-plan plan",
        )
    )
    panels = [p for c in run.captures for p in panel_leaks(c, ALL_TYPED)]
    shown = sum(c.console.count("┌ inspect") for c in run.captures)
    results.append(_result(f"inspect-no-text [{mode}]", panels, f"{shown} panels"))
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
