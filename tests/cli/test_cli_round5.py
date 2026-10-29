"""CLI, round 5 (2026-10-29, 复测 q4 SP-1, SP-10, IN-4).

* SP-1: a protective step in section 5 ("put the means away") is what the section asks
  for; an unsure student-only alarm on it no longer asks whether the user is safe now.
  Keeping a means close is still asked about, and a rule cue still brings the numbers.
* SP-10: a crisis reply reads sections 2-4 back; an entry naming a height, water's edge or
  a means is left out of it even when the screen let it through.
* IN-4: direction controls are read in the order they are shown before anything else.

Every sentence here was written for this file.
"""

from __future__ import annotations

import pytest
from cli_support import save_profile

from olivia import cli
from olivia.core.chang.safety_plan import SafetyPlan, SafetyPlanStore, Section, protective
from olivia.core.models import CrisisLevel

GO_ON = "1"
LEAVE = "2"


def test_a_protective_step_in_section_5_is_not_asked_about(run_cli, data_home):
    save_profile(data_home)
    entry = "屋里的刀和剪子都让室友收走"
    run = run_cli(["safety-plan"], ["", "", "", "", entry, "", "", "", "", ""])
    assert run.code == 0
    assert cli.PLAN_SAFE_NOW not in run.out and cli.SETUP_CRISIS not in run.out
    plan = SafetyPlanStore().load()
    assert plan is not None and entry in plan.lines(Section.ENVIRONMENT)


def test_a_rule_cue_in_section_5_still_brings_the_numbers(run_cli, data_home):
    save_profile(data_home)
    run = run_cli(["safety-plan"], ["", "", "", "", "把药交给姐姐，因为我不想活了", LEAVE])
    assert cli.SETUP_CRISIS in run.out and "12356" in run.out


@pytest.mark.parametrize(
    "text",
    ["请表哥把我的处方药锁进他的柜子", "家里的农药都倒掉", "不去江边和高架桥", "绳子扔进垃圾站"],
)
def test_protective_steps(text: str) -> None:
    assert protective(text)


@pytest.mark.parametrize(
    "text",
    [
        "把药藏到床垫下面",
        "刀片自己留着以防万一",
        "药放在枕头边随时能拿",
        "再买几瓶备着",
        "今天天气不错",
    ],
)
def test_keeping_a_means_close_is_not_protective(text: str) -> None:
    assert not protective(text)


def test_the_chat_leaves_out_a_place_or_means_entry(run_cli, data_home):
    save_profile(data_home)
    SafetyPlanStore().save(
        SafetyPlan(
            coping=("泡一杯热可可", "到屋顶边上坐着发呆"),
            distraction=("把攒的药片数一遍",),
        )
    )
    run = run_cli(["chat", "--rules"], ["", "我写了一封遗书", "/exit", ""])
    crisis = [r for r in run.results if r.inspect.get("safety_plan_shown")]
    assert crisis and "泡一杯热可可" in crisis[0].reply
    assert "屋顶" not in crisis[0].reply and "药片" not in crisis[0].reply


def test_direction_controls_are_read_in_shown_order(run_cli, data_home):
    save_profile(data_home)
    run = run_cli(["chat", "--rules", "--inspect"], ["真的\u202e了活想不\u202c"])
    assert run.results[0].crisis_level >= CrisisLevel.L2
    assert "\u202e" not in run.out and "\u202c" not in run.out
    assert cli.strip_controls("我想\u202e杀自\u202c") == "我想自杀"
