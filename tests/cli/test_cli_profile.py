"""``olivia profile``: both names and the taboo topics after the first visit (JTBD 4, F11)."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta

import pytest
from cli_support import NOW, save_profile

from olivia import cli
from olivia.core.chang.onboarding import (
    TABOO_MAX_TOPICS,
    fill_slots,
    load_onboarding_text,
    taboo_hint,
)
from olivia.core.chang.profile import PROFILE_FILENAME, ProfileLockedError, ProfileStore
from olivia.core.language.data import ContentKind, load_language_data
from olivia.core.language.filters import apply_willow
from olivia.core.language.gate import OutputGate
from olivia.core.models import NAME_MAX_LEN, HelpStage
from olivia.core.taxonomy import load_taxonomy

TEXT = load_onboarding_text()
P = TEXT.profile
LATER = NOW + timedelta(days=1)


def _saved(home):
    profile = ProfileStore(home).load()
    assert profile is not None
    return profile


def test_the_menu_shows_both_names_and_the_topics(run_cli, data_home):
    save_profile(data_home, agent_name="阿柳", taboo_topics=("考试", "前任"))
    run = run_cli(["profile"], [""])
    assert run.code == 0
    assert run.lines[:5] == [
        P["heading"],
        "  1. " + fill_slots(P["user_name_item"], user_name="小林"),
        "  2. " + fill_slots(P["agent_name_item"], agent_name="阿柳"),
        "  3. " + fill_slots(P["taboo_item"], topics="考试、前任"),
        P["elsewhere"],
    ]


def test_no_topics_reads_as_none_yet(run_cli, data_home):
    save_profile(data_home)
    run = run_cli(["profile"], [""])
    assert "  3. " + fill_slots(P["taboo_item"], topics=P["no_topics"]) in run.lines


def test_changing_the_user_name_keeps_everything_else(run_cli, data_home):
    before = save_profile(data_home, taboo_topics=("考试",))
    run = run_cli(["profile"], ["1", " 林林 "], now=LATER)
    assert run.code == 0 and run.lines[-1] == fill_slots(P["user_name_saved"], user_name="林林")
    assert fill_slots(P["user_name"], user_name="小林", max_len=str(NAME_MAX_LEN)) in run.out
    assert _saved(data_home) == replace(before, user_name="林林", updated_at=LATER)


def test_changing_the_agent_name(run_cli, data_home):
    save_profile(data_home)
    run = run_cli(["profile"], ["2", "阿柳"])
    assert run.code == 0 and run.lines[-1] == fill_slots(P["agent_name_saved"], agent_name="阿柳")
    assert _saved(data_home).agent_name == "阿柳"


def test_a_name_that_fails_the_onboarding_checks_is_asked_again(run_cli, data_home):
    save_profile(data_home)
    run = run_cli(["profile"], ["1", "名" * (NAME_MAX_LEN + 1), "a\tb", "阿青"])
    assert run.code == 0
    assert fill_slots(TEXT.hints["name_length"], max_len=str(NAME_MAX_LEN)) in run.out
    assert TEXT.hints["name_unprintable"] in run.out
    assert _saved(data_home).user_name == "阿青"


@pytest.mark.parametrize("answer", ["", "小林"])
def test_an_empty_or_unchanged_name_changes_nothing(run_cli, data_home, answer):
    save_profile(data_home)
    before = (data_home / PROFILE_FILENAME).read_bytes()
    run = run_cli(["profile"], ["1", answer])
    assert run.code == 0 and run.lines[-1] == P["unchanged"]
    assert (data_home / PROFILE_FILENAME).read_bytes() == before


def test_new_topics_replace_the_old_ones(run_cli, data_home):
    save_profile(data_home, taboo_topics=("考试",))
    run = run_cli(["profile"], ["3", "前夫，体重、 前夫"])
    assert run.code == 0 and run.lines[-1] == fill_slots(P["taboo_saved"], topics="前夫、体重")
    assert _saved(data_home).taboo_topics == ("前夫", "体重")


@pytest.mark.parametrize("answer", ["0", "清空", "没有", "无"])
def test_topics_can_be_cleared(run_cli, data_home, answer):
    save_profile(data_home, taboo_topics=("考试", "前任"))
    run = run_cli(["profile"], ["3", answer])
    assert run.code == 0 and run.lines[-1] == P["taboo_cleared"]
    assert _saved(data_home).taboo_topics == ()


def test_clearing_nothing_and_an_empty_answer_change_nothing(run_cli, data_home):
    save_profile(data_home)
    before = (data_home / PROFILE_FILENAME).read_bytes()
    assert run_cli(["profile"], ["3", "0"]).lines[-1] == P["unchanged"]
    assert run_cli(["profile"], ["3", ""]).lines[-1] == P["unchanged"]
    assert (data_home / PROFILE_FILENAME).read_bytes() == before


def test_topics_over_the_limits_are_asked_again(run_cli, data_home):
    save_profile(data_home)
    too_many = "，".join(f"话题{n}" for n in range(TABOO_MAX_TOPICS + 1))
    run = run_cli(["profile"], ["3", too_many, "高考"])
    assert run.code == 0 and taboo_hint(TEXT) in run.out
    assert _saved(data_home).taboo_topics == ("高考",)


def test_the_next_chat_uses_the_new_names(run_cli, data_home):
    save_profile(data_home)
    assert run_cli(["profile"], ["2", "阿柳"]).code == 0
    run = run_cli(["chat", "--rules"], ["今天上班好累", "/exit"])
    assert run.code == 0 and "阿柳：" in run.out


def test_the_change_keeps_the_storage_form(run_cli, data_home):
    save_profile(data_home, enable_at_rest_encryption=True)
    assert run_cli(["profile"], ["1", "林林"]).code == 0
    raw = (data_home / PROFILE_FILENAME).read_text(encoding="utf-8")
    assert set(json.loads(raw)) == {"sealed_profile"} and "林林" not in raw
    assert _saved(data_home).user_name == "林林"


def test_unknown_choice_and_end_of_input(run_cli, data_home):
    save_profile(data_home)
    run = run_cli(["profile"], ["9"])
    assert run.code == 1 and run.lines[-1] == P["unknown_choice"]
    assert run_cli(["profile"], []).code == 0
    assert run_cli(["profile"], ["1"]).code == 0
    assert _saved(data_home).user_name == "小林"


def test_a_save_that_fails_is_reported(run_cli, data_home, monkeypatch):
    save_profile(data_home)

    def locked(self: ProfileStore, profile: object) -> None:
        raise ProfileLockedError("the keychain is unavailable", lost=False)

    monkeypatch.setattr(ProfileStore, "save", locked)
    run = run_cli(["profile"], ["1", "林林"])
    assert run.code == 1 and run.lines[-1] == cli.PROFILE_LOCKED_NOW


def test_before_onboarding_and_for_a_minor(run_cli, data_home):
    run = run_cli(["profile"])
    assert run.code == 1 and run.lines == [P["not_onboarded"]]
    save_profile(data_home, age_confirmed_18_plus=False, region=None, age_gate_refused_at=NOW)
    run = run_cli(["profile"])
    assert run.code == 1 and run.lines == [P["adults_only"]]


def test_texts_pass_willow_and_the_output_gate():
    tax = load_taxonomy()
    data = load_language_data(tax)
    gate = OutputGate(tax, data)
    for key, text in P.items():
        filled = fill_slots(
            text, user_name="小林", agent_name="Olivia", topics="考试", max_len=str(NAME_MAX_LEN)
        )
        assert apply_willow(filled, ContentKind.NORMAL, data.willow) == filled, key
        assert gate.reasons(filled, kind=ContentKind.NORMAL, stage=HelpStage.S_EXPLORE) == (), key
