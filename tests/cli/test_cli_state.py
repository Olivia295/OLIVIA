"""``olivia chat`` keeps the posteriors and the kit between sessions (B3)."""

from __future__ import annotations

import io
import json
from datetime import timedelta

from cli_support import NOW, files_under, save_profile

from olivia import cli
from olivia.core.chang.profile import ProfileStore
from olivia.core.crypto.errors import NoKeychainError
from olivia.core.memory.state import FORMAT_VERSION, STATE_FILENAME, STATE_STORE, StateStore
from olivia.core.memory.text import load_memory_text
from olivia.core.models import HelpStage
from olivia.core.session import ReplyKind

LATER = NOW + timedelta(days=1)
# High arousal: exploit-only, so the choice is the highest posterior mean.
HIGH = "心慌得要命，喘不上气，直接给我一个方法"
TEXT = load_memory_text()


def _store(home) -> StateStore:
    return StateStore(home, ProfileStore(home).vault)


class _Interrupting(io.StringIO):
    """Input that ends in Ctrl-C instead of end of input."""

    def readline(self, size: int | None = -1) -> str:
        line = super().readline()
        if not line:
            raise KeyboardInterrupt
        return line


def test_kit_recall_in_the_next_session(run_cli, data_home):
    save_profile(data_home)
    first = run_cli(["chat"], ["给我一个方法", "今天先不做了", "/exit"])
    shown = first.results[0].action_id
    assert shown is not None and first.results[1].inspect["feedback"] == "NOT_NOW"
    assert (data_home / STATE_FILENAME).is_file()

    second = run_cli(["chat"], ["上次存的那个再给我看看"], now=LATER, seed=3)
    (result,) = second.results
    assert result.stage is HelpStage.S_EMPOWER and result.reply_kind is ReplyKind.CARD
    assert result.action_id == shown
    assert f"Olivia：{result.reply}" in second.out


def test_second_session_choice_follows_the_first_sessions_feedback(run_cli, data_home):
    save_profile(data_home)
    first = run_cli(["chat"], [HIGH, "/unhelpful"])
    disliked = first.results[0].action_id
    assert disliked is not None and first.results[1].inspect["feedback"] == "UNHELPFUL"
    second = run_cli(["chat"], [HIGH], now=LATER)  # same seed, same words
    assert second.results[0].reply_kind is ReplyKind.CARD
    assert second.results[0].action_id != disliked
    stored = _store(data_home).load()
    assert stored is not None and disliked in json.dumps(stored.bandit)


def test_state_is_saved_on_the_turn_that_changes_it(run_cli, data_home, monkeypatch, recorder):
    save_profile(data_home)
    saved_after: list[int] = []
    original = StateStore.save

    def spy(self: StateStore, state: object) -> bool:
        saved_after.append(len(recorder.texts))
        return original(self, state)  # type: ignore[arg-type]

    monkeypatch.setattr(StateStore, "save", spy)
    run_cli(["chat"], ["今天上班好累", "给我一个方法", "今天先不做了", "今天上班好累"])
    # Saved right after the shelving turn, before the session ended; nothing new at exit.
    assert saved_after == [3]


def test_ctrl_c_still_saves(run_cli, data_home, monkeypatch):
    save_profile(data_home)
    # Only the exit save may write, so this checks the try/finally path.
    turns = {"n": 0}
    original = StateStore.save

    def at_exit_only(self: StateStore, state: object) -> bool:
        turns["n"] += 1
        return original(self, state) if turns["n"] > 1 else False  # type: ignore[arg-type]

    monkeypatch.setattr(StateStore, "save", at_exit_only)
    run = run_cli(["chat"], stdin=_Interrupting("给我一个方法\n今天先不做了\n"))
    assert run.code == 0 and run.lines[-1] == cli.GOODBYE
    stored = _store(data_home).load()
    assert stored is not None
    assert [e.action_id for e in stored.kit] == [run.results[0].action_id]


def test_a_session_without_feedback_writes_no_state(run_cli, data_home):
    save_profile(data_home)
    run_cli(["chat"], ["今天上班好累", "/exit"])
    assert not (data_home / STATE_FILENAME).exists()


def test_state_is_encrypted_at_rest(run_cli, data_home):
    save_profile(data_home)
    run = run_cli(["chat"], [HIGH, "/not-now"])
    shelved = run.results[0].action_id
    assert shelved is not None and len(shelved) >= 4
    raw = (data_home / STATE_FILENAME).read_bytes()
    for needle in (shelved, "spectra", "alpha", "olivia_state", "kit", "心慌"):
        assert needle.encode() not in raw
    assert (data_home / "keys" / f"{STATE_STORE}.key").is_file()


def test_no_keychain_writes_no_state_and_says_nothing_more(run_cli, data_home, keychain):
    save_profile(data_home)
    keychain.broken = NoKeychainError("none")
    run = run_cli(["chat"], ["给我一个方法", "今天先不做了", "/exit"])
    assert run.code == 0
    assert not (data_home / STATE_FILENAME).exists()
    assert not (data_home / "keys").exists()
    notice = TEXT.replies["memory_unavailable"]
    assert run.out.count(notice) == 1  # B2's one notice, nothing added by B3
    rest = run.out
    for result in run.results:
        rest = rest.replace(f"Olivia：{result.reply}", "")
    assert set(rest.replace(cli.USER_PROMPT, "").splitlines()) <= {
        notice,
        cli.CHAT_HINT,
        "",
        cli.GOODBYE,
    }


def test_a_corrupt_state_starts_fresh_silently_and_is_replaced(run_cli, data_home):
    save_profile(data_home)
    (data_home / STATE_FILENAME).write_bytes(b"\x00garbage")
    calm = run_cli(["chat"], ["上次存的那个再给我看看"])
    assert calm.code == 0
    assert calm.results[0].action_id is None  # empty kit: the gentle "nothing saved" line
    assert (data_home / STATE_FILENAME).read_bytes() == b"\x00garbage"  # nothing changed
    run = run_cli(["chat"], ["给我一个方法", "今天先不做了"])
    stored = _store(data_home).load()
    assert stored is not None
    assert [e.action_id for e in stored.kit] == [run.results[0].action_id]


def test_a_state_from_a_later_version_is_left_alone(run_cli, data_home):
    save_profile(data_home)
    vault = ProfileStore(data_home).vault
    future = json.dumps({"olivia_state": FORMAT_VERSION + 1, "new": True}).encode()
    blob = vault.seal(STATE_STORE, future, label="state")
    (data_home / STATE_FILENAME).write_bytes(blob)
    run = run_cli(["chat"], ["给我一个方法", "今天先不做了"])
    assert run.code == 0
    assert (data_home / STATE_FILENAME).read_bytes() == blob
    assert [p.name for p in files_under(data_home) if STATE_FILENAME in p.name] == [STATE_FILENAME]
