"""The check functions of ``scripts/privacy_audit.py`` (next-phase B8; G-4, ruling 32).

Each check is shown to fail on a planted problem, so a green audit means something. The
audit itself only ever uses an in-memory keychain (and so does this suite, conftest).
"""

from __future__ import annotations

import base64
import importlib.util
import json
import socket
import sys
from pathlib import Path

import pytest

from olivia.core.crypto.vault import encode_master

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("privacy_audit", ROOT / "scripts/privacy_audit.py")
assert _spec is not None and _spec.loader is not None
audit = importlib.util.module_from_spec(_spec)
sys.modules["privacy_audit"] = audit
_spec.loader.exec_module(audit)

OLVD = b"OLVD\x01" + bytes(40)
OLVK = b"OLVK\x01" + bytes(40)
SEALED_B64 = base64.b64encode(OLVD).decode("ascii")


# -- network ----------------------------------------------------------------------------------


def test_network_imports_finds_every_form(tmp_path):
    package = tmp_path / "olivia"
    package.mkdir()
    (package / "net.py").write_text(
        "import socket\n"
        "import urllib.parse\n"
        "from urllib import request\n"
        "from http.client import HTTPConnection\n"
        "from json import dumps\n"
        "import importlib\n"
        "importlib.import_module('ssl')\n"
        "__import__('requests')\n"
        "from . import sibling\n",
        encoding="utf-8",
    )
    hits = audit.network_imports(package)
    assert [hit.split(" ", 1)[1] for hit in hits] == [
        "socket",
        "urllib.request",
        "http.client",
        "http.client.HTTPConnection",
        "ssl",
        "requests",
    ]
    assert all(hit.startswith("olivia/net.py:") for hit in hits)


def test_the_package_imports_no_networking_module():
    assert audit.network_imports(audit.PACKAGE_DIR) == []


def test_network_block_refuses_records_and_restores():
    connect, resolve = socket.socket.connect, socket.getaddrinfo
    with audit.NetworkBlock() as block:
        with pytest.raises(OSError):
            socket.create_connection(("127.0.0.1", 9))
        with socket.socket() as sock, pytest.raises(OSError):
            sock.connect(("127.0.0.1", 9))
        with pytest.raises(OSError):
            socket.getaddrinfo("example.org", 443)
    assert len(block.attempts) == 3
    assert "('127.0.0.1', 9)" in block.attempts[1]
    assert socket.socket.connect is connect and socket.getaddrinfo is resolve


# -- typed text in files ----------------------------------------------------------------------


def test_fragments_are_whole_characters_of_at_least_four_bytes():
    assert audit.fragments("青禾") == {"青禾"}
    assert audit.fragments("我写了一封遗书") == {
        "我写了一封遗书",
        "我写",
        "写了",
        "了一",
        "一封",
        "封遗",
        "遗书",
    }
    # All-ASCII runs need six bytes; a mixed run needs four.
    assert audit.fragments("139 0571") == {"139 0571", "139 05", "39 057", "9 0571"}
    assert "姐A" in audit.fragments("表姐A")
    assert audit.fragments("  ") == set()


def test_leaked_text_searches_utf8_and_json_escapes():
    files = [
        ("ledger/a.olv", OLVD + "我写了".encode()),
        ("profile.json", json.dumps({"user_name": "青禾"}).encode("ascii")),
        (".snapshots/profile.json/1", '{"user_name": "青禾"}'.encode()),
        ("state.bin", OLVD + "青禾".encode()),
        ("care.bin", OLVD),
    ]
    found = audit.leaked_text(files, ["我写了一封遗书", "青禾"])
    assert sorted(found) == [
        ".snapshots/profile.json/1: 「青禾」",
        "ledger/a.olv: 「我写了一封遗书」",  # a fragment is enough
        "profile.json: 「青禾」",  # as JSON escapes
        "state.bin: 「青禾」",
    ]
    # The plaintext-profile exception covers the profile and its snapshots only.
    allowed = audit.leaked_text(files, ["我写了一封遗书", "青禾"], profile_plain=["青禾"])
    assert sorted(allowed) == ["ledger/a.olv: 「我写了一封遗书」", "state.bin: 「青禾」"]


def _good_files(whole: bool) -> list[tuple[str, bytes]]:
    profile = (
        {"sealed_profile": SEALED_B64}
        if whole
        else {"user_name": "青禾", "sealed_fields": SEALED_B64}
    )
    return [
        ("profile.json", json.dumps(profile).encode()),
        (".snapshots/profile.json/1", json.dumps(profile).encode()),
        ("ledger/0a.olv", OLVD),
        ("state.bin", OLVD),
        ("care.bin", OLVD),
        ("safety_plan.bin", OLVD),
        ("safety_plan_suggested", b""),
        ("keys/ledger.key", OLVK),
    ]


@pytest.mark.parametrize("whole", [False, True])
def test_unsealed_passes_a_sealed_directory(whole):
    assert audit.unsealed(_good_files(whole), whole, health_recorded=True) == []


@pytest.mark.parametrize(
    ("rel", "data", "whole", "problem"),
    [
        ("ledger/0a.olv", b"---\nkind: note", False, "ledger/0a.olv: not sealed (no OLVD)"),
        ("state.bin", b"{}", False, "state.bin: not sealed (no OLVD)"),
        ("keys/ledger.key", b"raw-key", False, "keys/ledger.key: not a wrapped key (no OLVK)"),
        (
            "profile.json",
            json.dumps({"clinical_history": ["SIT-02-04"]}).encode(),
            False,
            "profile.json: clinical_history in the clear",
        ),
        (
            "profile.json",
            json.dumps({"user_name": "青禾", "sealed_profile": SEALED_B64}).encode(),
            True,
            "profile.json: switch on but not only sealed_profile",
        ),
        (
            "profile.json",
            json.dumps({"sealed_fields": base64.b64encode(b"plain").decode()}).encode(),
            False,
            "profile.json: sealed_fields is not an OLVD blob",
        ),
        ("profile.json", b"{broken", False, "profile.json: not JSON"),
        ("notes.txt", b"", False, "notes.txt: unexpected file"),
        ("safety_plan_suggested", b"x", False, "safety_plan_suggested: marker is not empty"),
    ],
)
def test_unsealed_names_each_problem(rel, data, whole, problem):
    files = [(r, d) for r, d in _good_files(whole) if r != rel] + [(rel, data)]
    assert problem in audit.unsealed(files, whole, health_recorded=False)


def test_unsealed_fails_when_a_store_was_never_written():
    files = [(r, d) for r, d in _good_files(False) if r not in {"care.bin", "ledger/0a.olv"}]
    problems = audit.unsealed(files, False, health_recorded=True)
    assert "care.bin: not written by the scripted run" in problems
    assert "ledger/: not written by the scripted run" in problems
    plain = [("profile.json", b'{"user_name": "x"}')] + files[1:]
    assert "profile.json: health recorded but no sealed_fields" in audit.unsealed(
        plain, False, health_recorded=True
    )


def test_keys_on_disk_finds_the_master_key_in_any_encoding():
    key = bytes(range(32))
    items = [("master-key", encode_master(bytes(8), key))]
    for data in (key, base64.b64encode(key), key.hex().encode(), items[0][1].encode()):
        found = audit.keys_on_disk([("keys/x.key", OLVK + data)], items)
        assert found and set(found) == {"keys/x.key: master-key"}, data
    assert audit.keys_on_disk([("keys/x.key", OLVK)], items) == []


def test_permission_problems():
    modes = [("", True, 0o700), ("keys", True, 0o755), ("profile.json", False, 0o644)]
    assert audit.permission_problems(modes) == [
        "keys: 0o755 (want 0o700)",
        "profile.json: 0o644 (want 0o600)",
    ]
    assert audit.permission_problems([("", True, 0o700), ("a", False, 0o600)]) == []


# -- typed text in output ---------------------------------------------------------------------


def _capture(command: str, console: str = "", **fields: object) -> object:
    values: dict[str, object] = {"replies": [], "stray": "", "logs": [], "warned": []}
    values.update(fields)
    return audit.Capture((command,), 0, console, **values)  # type: ignore[arg-type]


def test_output_exceptions_are_explicit():
    note, plan = audit.NOTE, audit.PLAN[0]
    assert audit.output_leaks(_capture("memory", f"2. 你让我记住的话：\n   {note}"), [note]) == []
    assert audit.output_leaks(_capture("safety-plan", f"· {plan}"), [plan]) == []
    assert audit.output_leaks(_capture("journal", f"· {note}"), [note]) == [
        f"journal console: 「{note}」"
    ]
    # F15: chat shows the note only inside the recall sentence; anywhere else it is a leak.
    assert audit.output_leaks(_capture("chat", f"阿屿：{audit.RECALLED}"), [note]) == []
    assert audit.output_leaks(_capture("chat", f"阿屿：{note}"), [note]) == [
        f"chat console: 「{note}」"
    ]
    # Names address the user everywhere on the console.
    assert audit.output_leaks(_capture("chat", f"{audit.AGENT_NAME}：好"), audit.NAMES) == []


def test_session_replies_are_removed_before_the_search():
    message = audit.MESSAGES[0]
    reply = f"我感觉到你{message}。"
    capture = _capture("chat", f"你：\n阿屿：{reply}\n", replies=[reply])
    assert audit.output_leaks(capture, [message]) == []
    printed = _capture("chat", f"你：{message}\n阿屿：{reply}\n", replies=[reply])
    assert audit.output_leaks(printed, [message]) != []


@pytest.mark.parametrize("where", ["stray", "logs", "warned"])
def test_nothing_typed_in_stderr_logs_or_warnings(where):
    text = f"debug: {audit.NOTE} {audit.USER_NAME}"
    capture = _capture("memory", **{where: text if where == "stray" else [text]})
    problems = audit.output_leaks(capture, [audit.NOTE, audit.USER_NAME])
    assert any(audit.USER_NAME in p for p in problems)  # names are allowed on the console only
    assert any(audit.NOTE[:4] in p for p in problems)  # the memory exception is console only


def test_panel_lines_hold_no_typed_text_not_even_names():
    clean = _capture("chat", "┌ inspect · 第 1 轮\n│ 风险 L0\n└ 热线数据 builtin")
    assert audit.panel_leaks(clean, audit.ALL_TYPED) == []
    leaky = _capture("chat", f"┌ inspect\n│ 称呼 {audit.USER_NAME}\n└")
    assert audit.panel_leaks(leaky, audit.ALL_TYPED) == [f"chat: 「{audit.USER_NAME}」"]


def _stats_output(*extra: str) -> str:
    words = audit.load_stats_text().lines
    lines = [
        words["heading"],
        words["sessions"].format(total=3, week=1, month=2),
        words["late_night"].format(start="00:00", end="05:00", count=1, known=2, percent=50)
        + words["unknown"].format(count=1),
        words["support"].format(count=3, turns=20, percent=15),
        words["rating"].format(change="-0.5", count=2),
        words["rose"].format(count=1, rated=2, percent=50),
        words["journal_helpful"].format(answered=3, count=2, percent=67),
        *extra,
    ]
    return "\n".join(lines) + "\n"


def test_stats_output_of_numbers_only_passes():
    text = audit.load_stats_text()
    assert audit.stats_problems(_capture("stats", _stats_output()), audit.ALL_TYPED, text) == []


def test_stats_output_with_typed_text_or_another_line_fails():
    text = audit.load_stats_text()
    named = _capture("stats", _stats_output(f"- {audit.USER_NAME}"))
    problems = audit.stats_problems(named, audit.ALL_TYPED, text)
    assert f"typed text: 「{audit.USER_NAME}」" in problems and "not a stats line: 8" in problems
    worded = text.lines["sessions"].replace("{total}", "很多").format(week=1, month=2)
    other = _capture("stats", f"{text.lines['heading']}\n{worded}\n")
    assert audit.stats_problems(other, audit.ALL_TYPED, text) == ["not a stats line: 2"]


@pytest.mark.parametrize("key", ["rose_none", "journal_helpful_none"])
def test_the_rose_and_journal_lines_are_numbers_only_too(key):
    """The two §11.1 lines (the share that rose, the journal answers) are stats lines, and
    only with numbers in their slots."""
    text = audit.load_stats_text()
    shown = _capture("stats", _stats_output(text.lines[key]))
    assert audit.stats_problems(shown, audit.ALL_TYPED, text) == []
    worded = text.lines["journal_helpful"].format(answered="很多", count=2, percent=67)
    other = _capture("stats", _stats_output(worded))
    assert audit.stats_problems(other, audit.ALL_TYPED, text) == ["not a stats line: 8"]


def test_stats_that_printed_no_numbers_fail():
    text = audit.load_stats_text()
    capture = _capture("stats", text.replies["unavailable"] + "\n")
    assert audit.stats_problems(capture, audit.ALL_TYPED, text) == ["no numbers were printed"]


# -- the whole audit --------------------------------------------------------------------------


def test_the_plaintext_profile_really_is_searched():
    run = audit.run_scripted(whole=False)
    # Without the exception the names are found in the plaintext profile: the search
    # sees what is on disk, so its green result is not vacuous.
    found = audit.leaked_text(run.files, audit.PROFILE_TYPED)
    assert found and all(audit.is_profile(hit.split(":", 1)[0]) for hit in found)
    assert audit.leaked_text(run.files, audit.ALL_TYPED, audit.PROFILE_TYPED) == []


def test_the_audit_passes_on_this_tree(capsys, keychain):
    assert audit.main() == 0
    out = capsys.readouterr().out
    assert "all checks passed" in out and "FAIL" not in out
    names = ("network-imports", "network-runtime", "forget-all-clean [switch-on]")
    for name in (*names, "stats-numbers-only [switch-off]"):
        assert name in out
    assert keychain.items == {}  # the suite's keychain was never used either
