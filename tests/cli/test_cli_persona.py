"""``olivia persona``: show and switch the companion persona (PRD JTBD 4, ONB-03; plan D-1)."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
from cli_support import NOW, ONBOARD_CN, save_profile

from olivia import cli
from olivia.core.chang.onboarding import load_onboarding_text
from olivia.core.chang.profile import PROFILE_FILENAME, ProfileStore
from olivia.core.language.data import load_language_data
from olivia.core.models import HelpStage, PersonaProfile, PersonaSpectrum, UserRegion
from olivia.core.session import ReplyKind
from olivia.core.taxonomy import load_taxonomy

LABELS = load_onboarding_text().persona_labels
TEMPLATES = load_language_data(load_taxonomy()).personas


def test_show_lists_the_four_and_marks_the_current_one(run_cli, data_home):
    save_profile(data_home)
    run = run_cli(["persona"])
    assert run.code == 0
    assert cli.PERSONA_SHOW.format(label=LABELS[PersonaSpectrum.GENTLE_HOLDING]) in run.out
    for number, persona in enumerate(PersonaSpectrum, start=1):
        assert f"{number}. {LABELS[persona]}" in run.out
    assert f"1. {LABELS[PersonaSpectrum.GENTLE_HOLDING]}{cli.PERSONA_CURRENT_MARK}" in run.out
    assert run.out.count(cli.PERSONA_CURRENT_MARK) == 1
    assert "olivia persona" in run.out


@pytest.mark.parametrize(
    ("choice", "persona"),
    [
        ("2", PersonaSpectrum.ZEN_PHILOSOPHER),
        ("平视战友", PersonaSpectrum.RATIONAL_PEER),
        ("silent_anchor", PersonaSpectrum.SILENT_ANCHOR),
    ],
)
def test_switch_saves_the_persona_and_keeps_everything_else(run_cli, data_home, choice, persona):
    before = save_profile(data_home, taboo_topics=("考试",))
    run = run_cli(["persona", choice])
    assert run.code == 0
    assert cli.PERSONA_SAVED.format(name=LABELS[persona].split("：")[0]) in run.out
    after = ProfileStore(data_home).load()
    assert after is not None and after.persona_spectrum is persona
    assert after == replace(before, persona_spectrum=persona, updated_at=NOW)


def test_the_next_chat_speaks_with_the_new_persona(run_cli, data_home):
    save_profile(data_home)
    assert run_cli(["persona", "4"]).code == 0
    run = run_cli(["chat"], ["[5%] 好累，今天不想动脑，只想躺着", "/exit"])
    (haven,) = run.results
    assert haven.stage is HelpStage.S_HAVEN and haven.reply_kind is ReplyKind.HAVEN
    silent = {
        v.replace("{user_name}", "小林") for v in TEMPLATES[PersonaSpectrum.SILENT_ANCHOR].haven
    }
    assert haven.reply in silent


def test_onboarding_choice_reaches_the_first_session(run_cli, data_home):
    answers = list(ONBOARD_CN)
    answers[5] = "3"  # the persona step
    run = run_cli(["chat"], [*answers, "[5%] 好累", "/exit"])
    assert run.code == 0
    profile = ProfileStore(data_home).load()
    assert profile is not None and profile.persona_spectrum is PersonaSpectrum.RATIONAL_PEER
    (haven,) = run.results
    rational = {
        v.replace("{user_name}", "小林") for v in TEMPLATES[PersonaSpectrum.RATIONAL_PEER].haven
    }
    assert haven.reply in rational


def test_same_persona_is_left_alone(run_cli, data_home):
    save_profile(data_home)
    before = (data_home / PROFILE_FILENAME).read_bytes()
    run = run_cli(["persona", "1"])
    assert run.code == 0
    assert cli.PERSONA_UNCHANGED.format(name="温和包裹") in run.out
    assert (data_home / PROFILE_FILENAME).read_bytes() == before


@pytest.mark.parametrize("choice", ["9", "随便", "0"])
def test_unknown_choice_changes_nothing(run_cli, data_home, choice):
    save_profile(data_home)
    before = (data_home / PROFILE_FILENAME).read_bytes()
    run = run_cli(["persona", choice])
    assert run.code == 1
    assert cli.PERSONA_UNKNOWN.format(raw=choice) in run.out
    assert f"2. {LABELS[PersonaSpectrum.ZEN_PHILOSOPHER]}" in run.out
    assert (data_home / PROFILE_FILENAME).read_bytes() == before


def test_before_onboarding(run_cli, data_home):
    shown = run_cli(["persona"])
    assert shown.code == 0 and cli.PERSONA_NOT_ONBOARDED in shown.out
    switched = run_cli(["persona", "2"])
    assert switched.code == 1 and cli.PERSONA_NOT_ONBOARDED in switched.out
    assert not (data_home / PROFILE_FILENAME).exists()


def test_refusal_record_has_no_persona(run_cli, data_home):
    ProfileStore(data_home).save(
        PersonaProfile(
            age_confirmed_18_plus=False, created_at=NOW, updated_at=NOW, age_gate_refused_at=NOW
        )
    )
    record = (data_home / PROFILE_FILENAME).read_text(encoding="utf-8")
    run = run_cli(["persona", "2"])
    assert run.code == 1 and cli.PERSONA_ADULTS_ONLY in run.out
    assert (data_home / PROFILE_FILENAME).read_text(encoding="utf-8") == record
    assert run_cli(["persona"]).code == 0


def test_region_is_untouched_by_a_switch(run_cli, data_home):
    save_profile(data_home, region=UserRegion("US", "America/Chicago"))
    assert run_cli(["persona", "2"]).code == 0
    saved = json.loads((data_home / PROFILE_FILENAME).read_text(encoding="utf-8"))
    region = saved["region"]
    assert (region["country_code"], region["timezone"]) == ("US", "America/Chicago")
    assert saved["persona_spectrum"] == "ZEN_PHILOSOPHER"
