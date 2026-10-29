"""A minor in the chat leaves nothing about them (round 6, re-test q4 F5; PRD ruling 22).

After the user confirms in the chat that they are under 18, the chat writes no summary, and
when it ends only the refusal record (no personal data) is left: the earlier profile's
snapshots, the ledger, the kit, the care marker and the safety plan are removed, so what
``olivia memory`` then says ("nothing about you is stored here") is true. Without a
confirmation nothing is recorded about the age and this chat leaves no summary; the rest
stays. Names and messages are made up.
"""

from __future__ import annotations

from cli_support import files_under, save_profile

from olivia.core.chang.profile import PROFILE_FILENAME, ProfileStore
from olivia.core.chang.safety_plan import Contact, SafetyPlan, SafetyPlanStore
from olivia.core.crypto.vault import Vault
from olivia.core.memory.forget import load_forget_text
from olivia.core.memory.ledger import Ledger

FORGET = load_forget_text()


def _entries(home) -> int:
    return len(Ledger(home, Vault(home)).entries())


def _adult_with_history(home) -> None:
    save_profile(home)
    save_profile(home, user_name="阿林")  # a second save leaves a snapshot of the first
    vault = ProfileStore(home).vault
    SafetyPlanStore(home, vault).save(
        SafetyPlan(warning_signs=("睡不着",), people=(Contact("表姐", "138-0000-0000"),))
    )


def test_a_confirmed_minor_leaves_only_the_refusal_record(run_cli, data_home):
    _adult_with_history(data_home)
    talk = run_cli(["chat", "--rules"], ["今天上班好累", "/exit"])
    assert talk.code == 0 and _entries(data_home) >= 1
    assert any(".snapshots" in p.parts for p in files_under(data_home))
    run = run_cli(["chat", "--rules"], ["我才十五，同桌又不理我了", "嗯嗯，对呀", "/exit"])
    assert run.code == 0
    assert files_under(data_home) == [data_home / PROFILE_FILENAME]
    memory = run_cli(["memory"], [])
    assert FORGET.memory["adults_only"] in memory.out
    again = run_cli(["chat", "--rules"], ["你好"])
    assert again.code == 1 and again.sessions == [] and "12355" in again.out


def test_an_unconfirmed_minor_leaves_no_summary_of_this_chat(run_cli, data_home):
    saved = save_profile(data_home)
    run_cli(["chat", "--rules"], ["今天上班好累", "/exit"])
    before = _entries(data_home)
    run = run_cli(["chat", "--rules"], ["我才十五，同桌又不理我了", "不是", "/exit"])
    assert run.code == 0
    assert _entries(data_home) == before
    assert ProfileStore(data_home).load() == saved


def test_a_confirmed_minor_in_a_crisis_leaves_only_the_refusal_record(run_cli, data_home):
    _adult_with_history(data_home)
    run = run_cli(
        ["chat", "--rules"], ["我才十五，真的不想活了", "是的", "我现在是安全的", "/exit"]
    )
    assert run.code == 0
    assert "12355" in run.out
    assert files_under(data_home) == [data_home / PROFILE_FILENAME]
