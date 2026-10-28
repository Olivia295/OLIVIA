"""QA round 4 (q4): ``resources`` beside damaged wording, ``region --clear``, zero-width
characters, the numbers after "其他地区", damaged program files and data-directory hints."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from cli_support import ONBOARD_CN, save_profile

from olivia import cli
from olivia.core.chang import onboarding
from olivia.core.chang.onboarding import load_onboarding_text
from olivia.core.chang.profile import ProfileStore
from olivia.core.chang.safety_plan import (
    Contact,
    SafetyPlan,
    SafetyPlanStore,
    Section,
    load_safety_plan_text,
)
from olivia.core.language.data import load_language_data
from olivia.core.memory.ledger import LEDGER_DIRNAME
from olivia.core.models import UserRegion
from olivia.core.resources.fallback import EMERGENCY, emergency_lines
from olivia.core.resources.store import EmergencyPurpose
from olivia.core.taxonomy import load_taxonomy

GO_ON = "1"
LEAVE = "2"


def _broken(*_args: object, **_kwargs: object) -> object:
    raise ValueError("damaged packaged file")


# -- R2: resources needs only the hotline data and its own words ------------------------------


@pytest.fixture
def damaged_wording(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every packaged wording file but the hotline data fails to load (QA q4: onboarding,
    gentle_holding, utterances, render, taxonomy)."""
    monkeypatch.setattr(cli, "load_onboarding_text", _broken)
    monkeypatch.setattr(cli, "load_language_data", _broken)
    monkeypatch.setattr(cli, "_taxonomy", _broken)
    monkeypatch.setattr(onboarding, "load_onboarding_text", _broken)


def test_resources_for_a_code_needs_no_other_wording(run_cli, damaged_wording):
    run = run_cli(["resources", "HK"])
    assert run.code == 0
    assert run.lines[0] == "求助资源 · 中国香港（HK）"
    assert "18111" in run.out and "· 999（报警、消防与急救）" in run.out
    assert cli.UNEXPECTED_ERROR not in run.out


def test_resources_for_the_saved_region_needs_no_other_wording(run_cli, data_home, damaged_wording):
    save_profile(data_home, region=UserRegion("HK", "Asia/Hong_Kong"))
    run = run_cli(["resources"])
    assert run.code == 0
    assert run.lines[0] == "求助资源 · 中国香港（HK）" and "18111" in run.out
    assert cli.UNEXPECTED_ERROR not in run.out


def test_an_unknown_code_still_lists_the_codes_without_other_wording(run_cli, damaged_wording):
    run = run_cli(["resources", "JP"])
    assert run.code == 2
    assert "求助资源 · 其他地区（ZZ）" in run.out and "  HK  中国香港" in run.out


def test_the_resources_words_match_the_chat_cards():
    """The words ``resources`` keeps for itself are the ones the chat's cards use."""
    render = load_language_data(load_taxonomy()).render
    assert dict(cli.RESOURCES_PURPOSES) == dict(render.emergency_purposes)
    assert set(cli.RESOURCES_PURPOSES) == set(EmergencyPurpose)
    assert render.crisis_stale_mark == cli.RESOURCES_STALE_MARK
    labels = load_onboarding_text().region_labels
    for code, _label, _numbers in EMERGENCY:
        if code != "ZZ":
            assert cli._region_label(code) == labels[code]


# -- P10: region --clear ---------------------------------------------------------------------


def test_after_clearing_the_region_none_is_saved(run_cli, data_home):
    save_profile(data_home)
    assert run_cli(["region", "--clear"]).code == 0
    run = run_cli(["region"])
    assert run.code == 0 and run.lines[0] == cli.NO_REGION
    profile = ProfileStore().load()
    assert profile is not None and profile.region is None
    resources = run_cli(["resources"])
    assert resources.lines[0] == "求助资源 · 其他地区（ZZ）"


# -- P11: zero-width characters ----------------------------------------------------------------


@pytest.mark.parametrize("mark", ["​", "‌", "‍", "⁠", "﻿"])
def test_clean_input_drops_zero_width_characters(mark):
    assert cli.clean_input(f"洗个{mark}热水澡{mark}") == "洗个热水澡"


# -- P9: a number on the command line that names nothing ------------------------------------


@pytest.mark.parametrize("flag", ["--method", "--entry"])
def test_a_number_with_nothing_to_name_is_a_wrong_value(run_cli, data_home, flag):
    save_profile(data_home)
    run = run_cli(["forget", flag, "99"])
    assert run.code == 2


# -- S1: after "其他地区", every region's emergency numbers ------------------------------------


def test_a_crisis_sentence_after_choosing_another_region_lists_every_emergency_number(
    run_cli, data_home
):
    lines = ["1", "1", "", "小林", "", "", "", "9", "真想睡过去不醒了", LEAVE]
    run = run_cli(["chat", "--rules"], lines)
    assert run.code == 1
    assert "\n".join(emergency_lines()) in run.out
    assert run.out.index(cli.SETUP_CRISIS) < run.out.index("911") < run.out.index(cli.SETUP_CHOICE)


def test_a_zz_profile_lists_every_emergency_number_in_the_safety_plan(run_cli, data_home):
    save_profile(data_home, region=UserRegion("ZZ", "UTC"))
    run = run_cli(["safety-plan"], ["我真的不想活了", LEAVE])
    assert "\n".join(emergency_lines()) in run.out


# -- P6: damaged program files say "reinstall" -----------------------------------------------


def test_damaged_program_files_say_reinstall(run_cli, data_home, monkeypatch):
    monkeypatch.setattr(onboarding, "load_onboarding_text", _broken)
    from olivia.core.chang import privacy

    monkeypatch.setattr(privacy, "load_privacy_text", _broken)
    run = run_cli(["chat", "--rules"], ONBOARD_CN)
    assert run.code == 1
    assert cli.UNEXPECTED_ERROR not in run.out
    assert "110" in run.out
    assert "重新安装" in run.lines[-1] and "onboarding.yaml" in run.lines[-1]


# -- P7: a file in place of the data directory -------------------------------------------------


def test_a_file_in_place_of_the_data_directory_is_named_as_such(run_cli, data_home):
    data_home.parent.mkdir(parents=True, exist_ok=True)
    data_home.write_text("not a directory", encoding="utf-8")
    run = run_cli(["region"])
    assert run.code == 1
    assert "换成了文件夹" not in run.out
    assert cli.DATA_DIR_IS_FILE in run.out


@pytest.mark.parametrize(
    "argv", [["region"], ["memory"], ["safety-plan"], ["forget", "--ledger"], ["chat"]]
)
def test_a_file_in_place_of_the_data_directory_reads_the_same_on_windows(
    run_cli, data_home, monkeypatch, argv
):
    """Windows says "not found" (FileNotFoundError) where POSIX says NotADirectoryError
    when ``<file>/profile.json`` is opened: it must not read as "no profile yet"."""
    from olivia.core.chang import profile as profile_module

    def not_found(*_args: object, **_kwargs: object) -> object:
        raise FileNotFoundError("[WinError 3] The system cannot find the path specified")

    monkeypatch.setattr(profile_module, "remove_stray_temps", lambda _path: None)
    monkeypatch.setattr(profile_module, "read_with_recovery", not_found)
    data_home.parent.mkdir(parents=True, exist_ok=True)
    data_home.write_text("not a directory", encoding="utf-8")
    run = run_cli(argv)
    assert run.code == 1
    assert cli.DATA_DIR_IS_FILE in run.out
    assert cli.NO_REGION not in run.out and cli.NOT_SET_UP not in run.out
    assert run.lines[-1] == cli.DATA_DIR_IS_FILE
    if argv == ["chat"]:
        assert run.out.index("112") < run.out.index(cli.DATA_DIR_IS_FILE)


# -- P8: a ledger that cannot be written is said at the start ---------------------------------


POSIX_ONLY = pytest.mark.skipif(
    sys.platform == "win32" or getattr(os, "geteuid", lambda: 1)() == 0,
    reason="POSIX permissions, and root reads everything",
)


@POSIX_ONLY
def test_a_ledger_that_cannot_be_written_is_said_before_the_chat(run_cli, data_home):
    assert run_cli(["chat", "--rules"], [*ONBOARD_CN, "/exit"]).code == 0
    ledger = Path(data_home) / LEDGER_DIRNAME
    ledger.mkdir(exist_ok=True)
    mode = ledger.stat().st_mode & 0o777
    ledger.chmod(0o500)
    try:
        run = run_cli(["chat", "--rules"], ["", "今天有点累", "/exit", ""])
    finally:
        ledger.chmod(mode)
    assert cli.CHAT_RECORDS_UNSAVED in run.out
    assert run.out.index(cli.CHAT_RECORDS_UNSAVED) < run.out.index(cli.CHAT_HINT)


def test_the_other_region_choice_is_the_onboarding_label():
    assert load_onboarding_text().region_labels["ZZ"] == cli.OTHER_REGION_CHOICE


# -- the safety plan (QA q4 P1-P3, P12) -------------------------------------------------------

SP_TEXT = load_safety_plan_text()
SP_CMD = SP_TEXT.command


def _heading(section: Section) -> str:
    number = list(Section).index(section) + 1
    return SP_CMD["section_heading"].format(n=number, total=5, title=SP_TEXT.titles[section])


def test_a_crisis_sentence_first_in_a_section_repeats_nothing_said_before(run_cli, data_home):
    """P1: the section heading was printed again, and "已经写满 5 条了" of the section before."""
    save_profile(data_home)
    full = [f"预警信号{n}" for n in range(1, 6)]
    lines = [*full, "想着一了百了就好了", GO_ON, "泡个热水脚", "", "", "", "", ""]
    run = run_cli(["safety-plan"], lines)
    assert run.code == 0
    assert cli.SETUP_CRISIS in run.out
    assert run.out.count(_heading(Section.COPING)) == 1
    full_line = SP_CMD["section_full"].replace("{max_entries}", "5")
    assert run.out.count(full_line) == 1
    assert SafetyPlanStore().load() is not None


def test_a_crisis_sentence_for_a_person_repeats_only_the_question(run_cli, data_home):
    """P2: "好，表姐和电话都记下了。" was said again after the numbers."""
    save_profile(data_home)
    lines = ["", "", "", "表姐 13800000000", "我真的不想活了", GO_ON, "", ""]
    run = run_cli(["safety-plan"], lines)
    assert run.code == 0
    said = SP_CMD["person_with_phone"].replace("{name}", "表姐")
    assert run.out.count(said) == 1
    after = run.out.split(
        SP_CMD["crisis_not_kept"].replace("{title}", SP_TEXT.titles[Section.PEOPLE])
    )[1]
    assert SP_CMD["person_name"].replace("{n}", "2") in after
    plan = SafetyPlanStore().load()
    assert plan is not None and plan.people == (Contact("表姐", "13800000000"),)


UNSURE_ENTRIES = [
    (["", "", "", ""], "把家里的酒都送人", Section.ENVIRONMENT),
    (["", "", "", ""], "屋里的刀和剪子都让室友收走", Section.ENVIRONMENT),
    ([""], "去河边散散步", Section.COPING),
]


@pytest.mark.parametrize(("before", "entry", "section"), UNSURE_ENTRIES)
def test_an_unsure_model_alone_asks_first_instead_of_the_card(
    run_cli, data_home, before, entry, section
):
    """P3: the student alone, unsure (0.45-0.51), no rule cue. As in a chat (owner decisions
    2026-10-26/28) it asks first; a yes keeps the entry with no card."""
    save_profile(data_home)
    run = run_cli(["safety-plan"], [*before, entry, "1", "", "", "", "", ""])
    assert run.code == 0
    assert cli.PLAN_SAFE_NOW in run.out and cli.PLAN_SAFE_KEPT in run.out
    assert cli.SETUP_CRISIS not in run.out and cli.SETUP_CHOICE not in run.out
    plan = SafetyPlanStore().load()
    assert plan is not None and entry in plan.lines(section)


@pytest.mark.parametrize("answer", ["2", "不太好", "我不想活了"])
def test_anything_but_a_yes_to_the_question_brings_the_numbers(run_cli, data_home, answer):
    save_profile(data_home)
    run = run_cli(["safety-plan"], ["", "去河边散散步", answer, LEAVE])
    assert run.out.index(cli.PLAN_SAFE_NOW) < run.out.index(cli.SETUP_CRISIS)
    assert "12356" in run.out and run.lines[-1] == SP_CMD["crisis_left"]
    assert SafetyPlanStore().load() is None


def test_end_of_input_at_the_question_brings_the_numbers(run_cli, data_home):
    save_profile(data_home)
    run = run_cli(["safety-plan"], ["", "去河边散散步"])
    assert run.out.index(cli.PLAN_SAFE_NOW) < run.out.index("12356")


def test_a_sure_model_alarm_still_brings_the_card_at_once(run_cli, data_home):
    save_profile(data_home)
    run = run_cli(["safety-plan"], ["", "想着一了百了就好了", LEAVE])
    assert cli.SETUP_CRISIS in run.out and "12356" in run.out
    assert cli.PLAN_SAFE_NOW not in run.out


def test_a_rule_cue_brings_the_card_at_once(run_cli, data_home):
    save_profile(data_home)
    run = run_cli(["safety-plan"], ["", "我不想活了", LEAVE])
    assert cli.SETUP_CRISIS in run.out and cli.PLAN_SAFE_NOW not in run.out


def test_the_chat_never_reads_back_an_entry_the_screen_alarms_on(run_cli, data_home):
    """The cautious side: an entry kept after a yes is still left out of a crisis reply
    while the screen alarms on it, unsure or not; the rest is read back."""
    save_profile(data_home)
    SafetyPlanStore().save(SafetyPlan(coping=("洗个热水澡", "去河边散散步", "想着一了百了就好了")))
    run = run_cli(["chat"], ["", "我写了一封遗书", "/exit", ""])
    crisis = [r for r in run.results if r.inspect.get("safety_plan_shown")]
    assert crisis and "洗个热水澡" in crisis[0].reply
    assert "河边" not in crisis[0].reply and "一了百了" not in crisis[0].reply


@pytest.mark.parametrize("lines", [[], [""]])
def test_only_looking_at_the_plan_says_it_is_unchanged(run_cli, data_home, lines):
    """P12: "这次先不保存了" after only looking read as if something was lost."""
    save_profile(data_home)
    SafetyPlanStore().save(SafetyPlan(coping=("洗个热水澡",)))
    run = run_cli(["safety-plan"], lines)
    assert run.code == 0
    assert run.lines[-1] == SP_CMD["unchanged"]
    assert SP_CMD["left"] not in run.out


def test_input_ending_mid_edit_keeps_what_was_saved_and_says_so(run_cli, data_home):
    save_profile(data_home)
    SafetyPlanStore().save(SafetyPlan(coping=("洗个热水澡",)))
    run = run_cli(["safety-plan"], ["1", "2", "听歌", ""])
    assert run.code == 0
    assert SP_CMD["left"] not in run.out and run.lines[-1] == SP_CMD["saved"]
    plan = SafetyPlanStore().load()
    assert plan is not None and plan.coping == ("听歌",)
