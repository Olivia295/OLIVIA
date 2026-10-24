"""``olivia memory`` and ``olivia forget`` (next-phase B5; PRD JTBD 4, MIYI-05).

After each forget option the targeted data stays unreadable even when the old ciphertext
and the old key file are copied back, while everything else still opens; ``--all`` leaves
no file and no keychain item, and the next ``chat`` starts onboarding. Every deletion
needs the typed confirmation, and end of input cancels. Names and numbers are made up.
"""

from __future__ import annotations

import shutil
from datetime import timedelta
from pathlib import Path

import pytest
from cli_support import L3_SENTENCE, NOW, files_under, save_profile

from olivia import cli
from olivia.core.chang.care import CARE_FILENAME, CARE_STORE, CareKind, CareMarker, CareStore
from olivia.core.chang.onboarding import OnboardingFlow
from olivia.core.chang.profile import ProfileLockedError, ProfileStore
from olivia.core.chang.safety_plan import (
    SAFETY_PLAN_FILENAME,
    SAFETY_PLAN_STORE,
    SUGGESTED_FILENAME,
    Contact,
    SafetyPlan,
    SafetyPlanDamagedError,
    SafetyPlanStore,
)
from olivia.core.crypto.errors import KeychainUnavailableError, NoKeychainError
from olivia.core.crypto.vault import KEYS_DIRNAME, MASTER_ITEM, Vault
from olivia.core.memory.forget import DataStores, load_forget_text
from olivia.core.memory.ledger import (
    LEDGER_DIRNAME,
    LEDGER_STORE,
    JournalEntry,
    Ledger,
    MethodRecord,
    NoteEntry,
    SessionSummary,
)
from olivia.core.memory.state import STATE_FILENAME, STATE_STORE, CarriedState, KitEntry, StateStore
from olivia.core.methods.bandit import Feedback
from olivia.core.models import CrisisLevel, HelpStage
from olivia.core.taxonomy import load_taxonomy

TEXT = load_forget_text()
M, F = TEXT.memory, TEXT.forget
YES = F["confirm_word"]
NOTE = "下周三面试，我有点紧张"
PLAN = SafetyPlan(
    warning_signs=("整夜睡不着觉",),
    coping=("听一首喜欢的歌",),
    distraction=("楼下的小公园",),
    people=(Contact("阿青", "138-0000-0000"),),
    environment=("把那盒东西交给阿青保管",),
)
HEALTH = {
    "clinical_history": ("SIT-08-04",),
    "contraindications": ("CARDIORESPIRATORY_INSTABILITY",),
}
BANDIT = {
    "spectra": {
        "05": {"30:grounding": {"alpha": 3.0, "beta": 1.0, "last_unhelpful_at": None}},
    }
}


def _summary(start, *, crisis: CrisisLevel | None = None) -> SessionSummary:
    return SessionSummary(
        started_at=start,
        ended_at=start + timedelta(minutes=20),
        stage_path=(HelpStage.S_READY, HelpStage.S_EXPLORE, HelpStage.S_CLOSING),
        spectra=("05",),
        methods=(MethodRecord("30:grounding", Feedback.HELPFUL),),
        crisis_level=crisis,
    )


def _populate(home: Path) -> None:
    """A profile with health information, three ledger entries (summary, note, crisis
    summary), a kit with two cards and learned preferences, a care marker and a plan."""
    save_profile(home, **HEALTH)
    vault = ProfileStore(home).vault
    ledger = Ledger(home, vault)
    ledger.append_summary(_summary(NOW - timedelta(days=2)), key="s1")
    ledger.add_note(NOTE, now=NOW - timedelta(days=1))
    ledger.append_summary(_summary(NOW, crisis=CrisisLevel.L3), key="s2")
    kit = (KitEntry("29:pmr_release", NOW), KitEntry("30:grounding", NOW))
    assert StateStore(home, vault).save(CarriedState(BANDIT, kit))
    assert CareStore(home, vault).save(CareMarker(NOW, CareKind.L3))
    SafetyPlanStore(home, vault).save(PLAN)


def _fresh(home: Path) -> DataStores:
    """Stores on a new vault, as the next process would see them."""
    return DataStores.open(home)


def _entries(home: Path) -> tuple[int, int]:
    ledger = Ledger(home, Vault(home))
    return len(ledger.entries()), ledger.skipped


def _copy(home: Path, names: list[str], aside: Path) -> None:
    for name in names:
        source = home / name
        target = aside / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True)
        else:
            shutil.copy2(source, target)


def _restore(home: Path, aside: Path) -> None:
    shutil.copytree(aside, home, dirs_exist_ok=True)


def _key(store: str) -> str:
    return f"{KEYS_DIRNAME}/{store}.key"


# -- olivia memory ----------------------------------------------------------------------------


def test_memory_shows_entries_and_notes_and_only_names_of_the_rest(run_cli, data_home):
    _populate(data_home)
    before = {p: p.read_bytes() for p in files_under(data_home)}
    run = run_cli(["memory"])
    assert run.code == 0
    out = run.out
    first = out.index(f"1. {(NOW - timedelta(days=2)).date().isoformat()} 的一次聊天")
    note_day = (NOW - timedelta(days=1)).date().isoformat()
    second = out.index("2. " + M["note"].replace("{date}", note_day))
    third = out.index(f"3. {NOW.date().isoformat()} 的一次聊天")
    assert first < second < third
    assert f"   {NOTE}" in run.lines  # verbatim
    assert "   - 经过：开始 → 倾听 → 收尾" in run.lines
    for line in (M["profile"], M["health"], M["safety_plan"], M["preferences"], M["care"]):
        assert f"- {line}" in run.lines
    assert "- " + M["kit"].replace("{count}", "2") in run.lines
    # Names only: never the plan, the health details, ids or front-matter.
    secrets = ("阿青", "138", "听一首", "睡不着", "SIT-08-04", "CARDIO", "olivia_ledger", "id:")
    for secret in secrets:
        assert secret not in out, secret
    # Nothing written, nothing exported.
    assert {p: p.read_bytes() for p in files_under(data_home)} == before


def test_memory_lists_journal_records_in_the_numbered_list(run_cli, data_home):
    _populate(data_home)
    Ledger(data_home, Vault(data_home)).record_journal(
        NOW + timedelta(minutes=25), shown=True, helpful=True
    )
    run = run_cli(["memory"])
    assert run.code == 0
    assert f"4. {NOW.date().isoformat()} 的一周小结" in run.lines
    assert "   - 看了这一周的小结。" in run.lines and "   - 觉得有帮助。" in run.lines
    # ... and that number forgets it, by re-keying like any other entry.
    forget = run_cli(["forget", "--entry", "4", "--yes"])
    assert forget.code == 0 and forget.lines == [F["done_entry"].replace("{n}", "4")]
    left = Ledger(data_home, Vault(data_home)).entries()
    assert len(left) == 3 and not any(isinstance(e, JournalEntry) for e in left)


def test_memory_counts_entries_that_do_not_open(run_cli, data_home):
    _populate(data_home)
    (data_home / LEDGER_DIRNAME / f"{'ab' * 12}.olv").write_bytes(b"not a sealed entry")
    run = run_cli(["memory"])
    assert run.code == 0
    assert M["unreadable"].replace("{count}", "1") in run.lines
    assert "3. " in run.out and "4. " not in run.out


def test_memory_with_nothing_stored(run_cli, data_home):
    save_profile(data_home)
    run = run_cli(["memory"])
    assert run.code == 0
    assert M["empty"] in run.lines
    assert f"- {M['profile']}" in run.lines
    assert f"- {M['health']}" not in run.lines


def test_memory_without_a_keychain(run_cli, data_home, keychain):
    save_profile(data_home)
    keychain.broken = NoKeychainError("none")
    run = run_cli(["memory"])
    assert run.code == 0
    assert run.lines[0] == M["no_keychain"]
    assert M["heading"] not in run.out
    assert files_under(data_home) == [data_home / "profile.json"]


def test_memory_with_a_locked_keychain(run_cli, data_home, keychain):
    _populate(data_home)
    keychain.broken = KeychainUnavailableError("locked")
    run = run_cli(["memory"])
    assert run.code == 1
    assert M["locked"] in run.lines
    assert NOTE not in run.out


def test_memory_for_an_age_gate_refusal_record(run_cli, data_home):
    run_cli(["chat"], ["1", "2", "1"])  # accept, "under 18", confirmed
    assert ProfileStore(data_home).load().is_age_gate_refusal
    run = run_cli(["memory"])
    assert run.code == 1 and run.lines == [M["adults_only"]]


# -- olivia forget: one store -----------------------------------------------------------------


def _ledger_names(home: Path) -> list[str]:
    return [f"{LEDGER_DIRNAME}/{p.name}" for p in (home / LEDGER_DIRNAME).glob("*.olv")]


def _assert_ledger_and_care_readable(home: Path) -> None:
    assert _entries(home) == (3, 0)
    assert CareStore(home, Vault(home)).take(NOW) is not None


def _assert_state_readable(home: Path) -> None:
    state = StateStore(home, Vault(home)).load()
    assert state is not None and len(state.kit) == 2


def _assert_plan_readable(home: Path) -> None:
    assert SafetyPlanStore(home, Vault(home)).load() == PLAN


def _assert_profile_readable(home: Path) -> None:
    profile = ProfileStore(home).load()
    assert profile is not None and profile.clinical_history == HEALTH["clinical_history"]


@pytest.mark.parametrize(
    ("flag", "menu", "done", "stores"),
    [
        ("--ledger", "2", "done_ledger", (LEDGER_STORE, CARE_STORE)),
        ("--kit", "3", "done_kit", (STATE_STORE,)),
        ("--safety-plan", "4", "done_safety_plan", (SAFETY_PLAN_STORE,)),
    ],
)
@pytest.mark.parametrize("via_menu", [False, True])
def test_each_option_shreds_its_store_and_keeps_the_rest(
    run_cli, data_home, tmp_path, flag, menu, done, stores, via_menu
):
    _populate(data_home)
    files = {
        LEDGER_STORE: _ledger_names(data_home),
        CARE_STORE: [CARE_FILENAME],
        STATE_STORE: [STATE_FILENAME],
        SAFETY_PLAN_STORE: [SAFETY_PLAN_FILENAME],
    }
    aside = tmp_path / "aside"
    _copy(data_home, [n for s in stores for n in (*files[s], _key(s))], aside)

    argv, lines = (["forget"], [menu, YES]) if via_menu else (["forget", flag], [YES])
    run = run_cli(argv, lines)
    assert run.code == 0
    assert F["confirm"] in run.lines and run.lines[-1] == F[done]
    for store in stores:
        assert not (data_home / _key(store)).exists()
        assert not any((data_home / name).exists() for name in files[store])

    # Everything else still opens, under the rotated master key.
    _assert_profile_readable(data_home)
    if LEDGER_STORE not in stores:
        _assert_ledger_and_care_readable(data_home)
    if STATE_STORE not in stores:
        _assert_state_readable(data_home)
    if SAFETY_PLAN_STORE not in stores:
        _assert_plan_readable(data_home)

    # The old ciphertext and the old key file, copied back, never open again.
    _restore(data_home, aside)
    if LEDGER_STORE in stores:
        assert _entries(data_home) == (0, 3)
        assert CareStore(data_home, Vault(data_home)).take(NOW) is None
    if STATE_STORE in stores:
        assert StateStore(data_home, Vault(data_home)).load() is None
    if SAFETY_PLAN_STORE in stores:
        with pytest.raises(SafetyPlanDamagedError):
            SafetyPlanStore(data_home, Vault(data_home)).load()


def test_one_entry_by_number_is_crypto_shredded(run_cli, data_home, tmp_path):
    _populate(data_home)
    (note,) = Ledger(data_home, Vault(data_home)).notes()
    note_file = f"{LEDGER_DIRNAME}/{note.entry_id}.olv"
    aside = tmp_path / "aside"
    _copy(data_home, [note_file, _key(LEDGER_STORE)], aside)

    run = run_cli(["forget", "--entry", "2", "--yes"])
    assert run.code == 0 and run.lines == [F["done_entry"].replace("{n}", "2")]
    assert not (data_home / note_file).exists()
    entries = Ledger(data_home, Vault(data_home)).entries()
    assert len(entries) == 2 and not any(isinstance(e, NoteEntry) for e in entries)
    _assert_state_readable(data_home)
    _assert_plan_readable(data_home)
    _assert_profile_readable(data_home)
    assert CareStore(data_home, Vault(data_home)).take(NOW) is not None

    # The note's old ciphertext, copied back, does not open under the new ledger key ...
    shutil.copy2(aside / note_file, data_home / note_file)
    assert _entries(data_home) == (2, 1)
    # ... nor with the old key file: the master key that wrapped it is gone.
    _restore(data_home, aside)
    readable = Ledger(data_home, Vault(data_home)).entries()
    assert not any(isinstance(e, NoteEntry) for e in readable)


def test_entries_that_no_longer_open_are_dropped_and_counted(run_cli, data_home):
    _populate(data_home)
    junk = data_home / LEDGER_DIRNAME / f"{'ab' * 12}.olv"
    junk.write_bytes(b"not a sealed entry")
    run = run_cli(["forget", "--entry", "1", "--yes"])
    assert run.code == 0
    assert run.lines == [
        F["done_entry"].replace("{n}", "1"),
        F["done_entry_dropped"].replace("{count}", "1"),
    ]
    assert not junk.exists() and _entries(data_home) == (2, 0)


def test_one_entry_from_the_menu(run_cli, data_home):
    _populate(data_home)
    run = run_cli(["forget"], ["1", "2", YES])
    assert run.code == 0
    assert f"   {NOTE}" in run.lines  # the list to pick from
    assert F["about_entry"].replace("{n}", "2") in run.lines
    assert run.lines[-1] == F["done_entry"].replace("{n}", "2")
    assert _entries(data_home) == (2, 0)


def test_an_entry_number_that_does_not_exist(run_cli, data_home):
    _populate(data_home)
    run = run_cli(["forget", "--entry", "4", "--yes"])
    assert run.code == 1 and run.lines == [F["no_entry"].replace("{n}", "4")]
    assert _entries(data_home) == (3, 0)


# -- olivia forget --all ----------------------------------------------------------------------


def _use_everything(run_cli, home: Path) -> None:
    """Every writer the CLI has: profile (with a snapshot), ledger, kit and preferences,
    care marker, safety plan and its suggestion marker."""
    save_profile(home)
    chat = run_cli(["chat"], ["给我一个方法", "今天先不做了", f"记住：{NOTE}", L3_SENTENCE])
    assert chat.code == 0
    assert run_cli(["journal"], []).code == 0  # shows the week, records the offer
    assert any(isinstance(e, JournalEntry) for e in Ledger(home, Vault(home)).entries())
    save_profile(home, **HEALTH)  # after the chat: a recorded diagnosis allows no card
    assert run_cli(["persona", "2"]).code == 0  # later saves leave snapshots
    store = SafetyPlanStore(home)
    store.save(PLAN)
    store.mark_suggested()
    for name in (STATE_FILENAME, CARE_FILENAME, SAFETY_PLAN_FILENAME, SUGGESTED_FILENAME):
        assert (home / name).is_file(), name
    assert (home / ".snapshots").is_dir() and _ledger_names(home)


def test_all_leaves_no_file_and_no_keychain_item(run_cli, data_home, keychain, tmp_path):
    _use_everything(run_cli, data_home)
    aside = tmp_path / "aside"
    shutil.copytree(data_home, aside)
    assert keychain.items

    run = run_cli(["forget", "--all"], [YES])
    assert run.code == 0
    assert F["about_all"] in run.lines and run.lines[-1] == F["done_all"]
    assert files_under(data_home) == []
    assert keychain.items == {}

    # Copied back, nothing opens: the master key is gone from the keychain.
    _restore(data_home, aside)
    with pytest.raises(ProfileLockedError):
        ProfileStore(data_home).load()
    readable, unreadable = _entries(data_home)
    assert readable == 0 and unreadable >= 2
    assert StateStore(data_home).load() is None


def test_after_all_the_next_chat_starts_onboarding(run_cli, data_home, tmp_path):
    _use_everything(run_cli, data_home)
    assert run_cli(["forget", "--all", "--yes"]).code == 0
    first = OnboardingFlow(load_taxonomy(), ProfileStore(tmp_path / "blank"), NOW).prompt()
    run = run_cli(["chat"], [])
    assert run.code == 1
    assert first.text in run.out and cli.CHAT_HINT not in run.out
    assert ProfileStore(data_home).load() is None


def test_all_from_the_menu(run_cli, data_home, keychain):
    _populate(data_home)
    run = run_cli(["forget"], ["5", YES])
    assert run.code == 0 and run.lines[-1] == F["done_all"]
    assert files_under(data_home) == [] and keychain.items == {}


def test_all_with_a_locked_keychain_removes_the_files_and_says_the_key_is_left(
    run_cli, data_home, keychain
):
    _populate(data_home)
    keychain.broken = KeychainUnavailableError("locked")
    run = run_cli(["forget", "--all", "--yes"])
    assert run.code == 1 and run.lines == [F["keychain_left"]]
    assert files_under(data_home) == []
    assert MASTER_ITEM in keychain.items
    keychain.broken = None
    again = run_cli(["forget", "--all", "--yes"])
    assert again.code == 0 and again.lines == [F["nothing_all"]]
    assert keychain.items == {}


def test_all_without_a_keychain(run_cli, data_home, keychain):
    save_profile(data_home)
    keychain.broken = NoKeychainError("none")
    run = run_cli(["forget", "--all", "--yes"])
    assert run.code == 0 and run.lines == [F["done_all"]]
    assert files_under(data_home) == []


def test_an_age_gate_refusal_record_is_kept_and_said_so(run_cli, data_home):
    run_cli(["chat"], ["1", "2", "1"])
    before = files_under(data_home)
    run = run_cli(["forget", "--all"], [])
    assert run.code == 0 and run.lines == [F["kept_minor"]]
    assert files_under(data_home) == before
    other = run_cli(["forget", "--kit"])
    assert other.code == 1 and other.lines == [F["adults_only"]]


def test_all_beside_a_refusal_record_removes_the_rest(run_cli, data_home, keychain):
    run_cli(["chat"], ["1", "2", "1"])
    SafetyPlanStore(data_home).mark_suggested()
    StateStore(data_home).save(CarriedState(BANDIT))
    assert keychain.items
    run = run_cli(["forget", "--all"], [YES])
    assert run.code == 0
    assert F["about_all_minor"] in run.lines
    assert run.lines[-2:] == [F["done_all_minor"], F["kept_minor"]]
    assert files_under(data_home) == [data_home / "profile.json"]
    assert ProfileStore(data_home).load().is_age_gate_refusal
    assert keychain.items == {}


# -- confirmation -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("argv", "lines"),
    [
        (["forget", "--all"], ["好的"]),  # anything but the word
        (["forget", "--all"], []),  # end of input at the confirmation
        (["forget", "--ledger"], ["确定"]),
        (["forget", "--entry", "1"], []),
        (["forget"], []),  # end of input at the menu
        (["forget"], [""]),  # just Enter
        (["forget"], ["5"]),  # picked, then end of input
        (["forget"], ["1", ""]),  # no entry picked
    ],
)
def test_nothing_is_removed_without_the_confirmation_word(
    run_cli, data_home, keychain, argv, lines
):
    _populate(data_home)
    before = {p: p.read_bytes() for p in files_under(data_home)}
    items = dict(keychain.items)
    run = run_cli(argv, lines)
    assert run.code == 0 and run.lines[-1] == F["cancelled"]
    assert {p: p.read_bytes() for p in files_under(data_home)} == before
    assert keychain.items == items


def test_an_unknown_menu_choice_changes_nothing(run_cli, data_home):
    _populate(data_home)
    before = files_under(data_home)
    run = run_cli(["forget"], ["9"])
    assert run.code == 1 and run.lines[-1] == F["unknown_choice"]
    assert files_under(data_home) == before


@pytest.mark.parametrize(
    ("flag", "nothing"),
    [
        ("--ledger", "nothing_ledger"),
        ("--kit", "nothing_kit"),
        ("--safety-plan", "nothing_safety_plan"),
        ("--entry=1", "nothing_entry"),
    ],
)
def test_nothing_to_forget_asks_nothing(run_cli, data_home, flag, nothing):
    save_profile(data_home)
    run = run_cli(["forget", flag], [])
    assert run.code == 0 and run.lines == [F[nothing]]
    assert files_under(data_home) == [data_home / "profile.json"]


def test_a_locked_keychain_changes_nothing(run_cli, data_home, keychain):
    _populate(data_home)
    before = {p: p.read_bytes() for p in files_under(data_home)}
    keychain.broken = KeychainUnavailableError("locked")
    run = run_cli(["forget", "--ledger", "--yes"])
    assert run.code == 1 and run.lines == [F["locked"]]
    assert {p: p.read_bytes() for p in files_under(data_home)} == before


def test_flags_are_mutually_exclusive(run_cli):
    with pytest.raises(SystemExit) as raised:
        run_cli(["forget", "--all", "--kit"])
    assert raised.value.code == 2
