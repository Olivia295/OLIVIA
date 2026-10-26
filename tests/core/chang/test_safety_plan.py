"""The personal safety plan's data, wording and sealed store (next-phase B10, decision D8).

Every test uses the in-memory keychain from conftest; nothing reaches the OS keychain.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from olivia.core.chang.safety_plan import (
    CRISIS_SECTIONS,
    SAFETY_PLAN_FILENAME,
    SAFETY_PLAN_STORE,
    SECTIONS,
    Contact,
    SafetyPlan,
    SafetyPlanDamagedError,
    SafetyPlanStore,
    SafetyPlanTextError,
    Section,
    clean_phone,
    crisis_block,
    load_safety_plan_text,
    split_contact,
)
from olivia.core.crypto.errors import KeychainUnavailableError, NoKeychainError
from olivia.core.crypto.vault import Vault
from olivia.core.language.data import ContentKind, load_language_data
from olivia.core.language.filters import apply_willow
from olivia.core.language.gate import OutputGate, phone_like_runs
from olivia.core.models import HelpStage
from olivia.core.taxonomy import load_taxonomy

PLAN = SafetyPlan(
    warning_signs=("整夜睡不着觉",),
    coping=("听一首喜欢的歌", "洗个热水澡"),
    distraction=("楼下的小公园",),
    people=(Contact("阿青姐姐", "138-0000-0000"), Contact("小周同学")),
    environment=("把那盒东西交给阿青保管",),
)


def fragments(plan: SafetyPlan, size: int = 4) -> set[bytes]:
    """Every ``size``-byte window of every entry's UTF-8 text."""
    found: set[bytes] = set()
    for section in SECTIONS:
        for line in plan.lines(section):
            raw = line.encode("utf-8")
            found |= {raw[i : i + size] for i in range(len(raw) - size + 1)}
    return found


# -- data -------------------------------------------------------------------------------------


def test_json_round_trip_and_strict_parsing():
    assert SafetyPlan.from_json(PLAN.to_json()) == PLAN
    assert SafetyPlan.from_json(SafetyPlan().to_json()).is_empty
    for bad in (b"[]", b'{"version": 1}', b'{"version": 2, "coping": []}'):
        with pytest.raises(ValueError):
            SafetyPlan.from_json(bad)


def test_contacts_show_name_and_phone():
    assert PLAN.lines(Section.PEOPLE) == ("阿青姐姐：138-0000-0000", "小周同学")


@pytest.mark.parametrize(
    ("raw", "cleaned"),
    [
        ("138-0000-0000", "138-0000-0000"),
        ("１３８ ００００ ００００", "138 0000 0000"),
        ("+86 138 0000 0000", "+86 138 0000 0000"),
        ("(010) 6000-0000", "(010) 6000-0000"),
        ("12", None),
        ("abc", None),
        ("138-0000-0000 分机", None),
        ("1" * 21, None),
    ],
)
def test_phone_cleaning(raw, cleaned):
    assert clean_phone(raw) == cleaned


# -- wording ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("表姐 13800000000", ("表姐", "13800000000")),  # dogfood I10
        ("表姐13800000000", ("表姐", "13800000000")),
        ("阿青：138-0000-0000", ("阿青", "138-0000-0000")),
        ("阿青, +86 138 0000 0000", ("阿青", "+86 138 0000 0000")),
        ("小王2号 13900000000", ("小王2号", "13900000000")),
        ("阿青 (010) 1234-5678", ("阿青", "(010) 1234-5678")),
        ("１３８００００００００", ("", "13800000000")),  # a phone number alone
        ("小王2号", ("小王2号", "")),  # too few digits for a phone
        ("  表  姐  ", ("表 姐", "")),
    ],
)
def test_split_contact(raw, expected):
    assert split_contact(raw) == expected


def test_first_run_notice_says_where_it_stays_and_how_to_delete_it():
    intro = load_safety_plan_text().command["intro"]
    for point in (
        "加密保存在这台电脑上",
        "不会上传",
        "第 2、3、4 部分",  # where it is used
        "olivia forget --safety-plan",  # how to withdraw
        "其他的一切都照常",  # declining changes nothing
    ):
        assert point in intro, point
    raw = (
        Path(__file__).resolve().parents[3] / "olivia/data/templates/safety_plan.yaml"
    ).read_text(encoding="utf-8")
    assert "待 G-4 法务审核" in raw


def test_every_sentence_passes_willow_and_the_gate():
    tax = load_taxonomy()
    data = load_language_data(tax)
    gate = OutputGate(tax, data)
    text = load_safety_plan_text()
    for sentence in text.all_texts():
        assert apply_willow(sentence, ContentKind.NORMAL, data.willow) == sentence, sentence
        assert gate.reasons(sentence, kind=ContentKind.NORMAL, stage=HelpStage.S_CLOSING) == ()
        assert "！" not in sentence and "!" not in sentence
        # No phone numbers of its own: only single-digit choices.
        assert phone_like_runs(sentence) == (), sentence


def test_text_file_is_validated(tmp_path: Path):
    (tmp_path / "safety_plan.yaml").write_text("version: 1\nsections: {}\n", encoding="utf-8")
    with pytest.raises(SafetyPlanTextError):
        load_safety_plan_text(tmp_path)


# -- the crisis block -------------------------------------------------------------------------


def test_crisis_block_holds_sections_two_to_four_only():
    text = load_safety_plan_text()
    block = crisis_block(PLAN)
    assert block.splitlines()[0] == text.crisis_intro
    for section in CRISIS_SECTIONS:
        assert text.titles[section] in block
        for line in PLAN.lines(section):
            assert f"· {line}" in block
    for section in (Section.WARNING_SIGNS, Section.ENVIRONMENT):
        assert text.titles[section] not in block
        for line in PLAN.lines(section):
            assert line not in block


def test_crisis_block_is_empty_without_sections_two_to_four():
    assert crisis_block(None) == ""
    assert crisis_block(SafetyPlan()) == ""
    only_hidden = SafetyPlan(warning_signs=("睡不着",), environment=("把东西放远一点",))
    assert crisis_block(only_hidden) == ""
    assert "我可以求助的人" in crisis_block(SafetyPlan(people=(Contact("阿青"),)))


# -- storage ----------------------------------------------------------------------------------


def test_save_load_is_encrypted_at_rest(tmp_path: Path):
    store = SafetyPlanStore(tmp_path)
    assert store.load() is None
    store.save(PLAN)
    assert store.load() == PLAN
    assert (tmp_path / "keys" / f"{SAFETY_PLAN_STORE}.key").is_file()
    raw = (tmp_path / SAFETY_PLAN_FILENAME).read_bytes()
    leaked = [f for f in fragments(PLAN) if f in raw]
    assert leaked == []
    # Another process (a fresh vault on the same keychain) opens it too.
    assert SafetyPlanStore(tmp_path, Vault(tmp_path)).load() == PLAN


def test_no_keychain_saves_nothing(tmp_path: Path, keychain):
    keychain.broken = NoKeychainError("none")
    store = SafetyPlanStore(tmp_path)
    assert not store.available()
    with pytest.raises(KeychainUnavailableError):
        store.save(PLAN)
    assert not any(tmp_path.rglob("*.*"))
    assert store.load_quietly() is None


def test_unavailable_keychain_keeps_the_file(tmp_path: Path, keychain):
    store = SafetyPlanStore(tmp_path)
    store.save(PLAN)
    keychain.broken = KeychainUnavailableError("locked")
    fresh = SafetyPlanStore(tmp_path, Vault(tmp_path))
    with pytest.raises(KeychainUnavailableError):
        fresh.load()
    assert fresh.load_quietly() is None
    assert fresh.exists()


def test_damaged_file_is_reported_and_kept(tmp_path: Path):
    store = SafetyPlanStore(tmp_path)
    store.save(PLAN)
    path = tmp_path / SAFETY_PLAN_FILENAME
    path.write_bytes(path.read_bytes()[:-3] + b"xyz")
    with pytest.raises(SafetyPlanDamagedError):
        store.load()
    assert store.load_quietly() is None
    assert path.is_file()


def test_clear_and_shred_make_old_copies_unreadable(tmp_path: Path):
    store = SafetyPlanStore(tmp_path)
    store.save(PLAN)
    copy = (tmp_path / SAFETY_PLAN_FILENAME).read_bytes()
    store.clear()
    assert not store.exists()
    assert not (tmp_path / "keys" / f"{SAFETY_PLAN_STORE}.key").exists()
    (tmp_path / SAFETY_PLAN_FILENAME).write_bytes(copy)
    with pytest.raises(SafetyPlanDamagedError):
        SafetyPlanStore(tmp_path, Vault(tmp_path)).load()
    store.shred()  # idempotent, and the forget hook
    assert not store.exists()


def test_saving_an_empty_plan_clears(tmp_path: Path):
    store = SafetyPlanStore(tmp_path)
    store.save(PLAN)
    store.save(SafetyPlan())
    assert not store.exists() and store.load() is None


def test_suggestion_marker(tmp_path: Path, keychain):
    store = SafetyPlanStore(tmp_path)
    assert store.should_suggest()
    store.mark_suggested()
    assert not store.should_suggest()
    assert (tmp_path / "safety_plan_suggested").read_bytes() == b""

    other = SafetyPlanStore(tmp_path / "other")
    other.save(PLAN)
    assert not other.should_suggest()  # a plan exists
    keychain.broken = NoKeychainError("none")
    assert not SafetyPlanStore(tmp_path / "third").should_suggest()  # nothing could be saved
