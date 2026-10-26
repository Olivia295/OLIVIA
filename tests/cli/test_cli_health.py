"""``olivia health`` and the contraindication line of the inspect panel (A1, decision D2)."""

from __future__ import annotations

from datetime import datetime

from cli_support import NOW, ONBOARD_CN, files_under, save_profile

from olivia import cli
from olivia.core.chang.onboarding import load_onboarding_text
from olivia.core.chang.profile import ProfileStore
from olivia.core.crypto.errors import NoKeychainError
from olivia.core.models import PROFILE_CONTRAINDICATIONS, PersonaProfile
from olivia.core.taxonomy import load_taxonomy

TEXT = load_onboarding_text()
HEALTH = TEXT.health
FLAGS = tuple(load_taxonomy().red_flags())
CARDIO, SAFETY, PSYCHOSIS = PROFILE_CONTRAINDICATIONS
# 1-based numbers in the list: the red flags first, then the three disclosures.
CARDIO_NO, SAFETY_NO, PSYCHOSIS_NO = len(FLAGS) + 1, len(FLAGS) + 2, len(FLAGS) + 3
LATER = datetime(2026, 10, 23, 9, 0, tzinfo=NOW.tzinfo)


def _load(home) -> PersonaProfile:
    profile = ProfileStore(home).load()
    assert profile is not None
    return profile


def _raw(home) -> bytes:
    return b"".join(p.read_bytes() for p in files_under(home))


def test_recording_asks_for_consent_and_saves_encrypted(run_cli, data_home):
    save_profile(data_home)
    run = run_cli(["health"], [f"1，{SAFETY_NO}", TEXT.consent_sentence], now=LATER)
    assert run.code == 0
    assert HEALTH["none_recorded"] in run.out
    assert TEXT.consent_sentence in run.out
    assert run.lines[-1] == HEALTH["saved"]
    profile = _load(data_home)
    assert profile.clinical_history == (FLAGS[0],)
    assert profile.contraindications == (SAFETY,)
    assert profile.updated_at == LATER
    raw = _raw(data_home)
    assert FLAGS[0].encode() not in raw and SAFETY.encode() not in raw


def test_the_consent_comes_with_the_onboarding_notice(run_cli, data_home):
    save_profile(data_home)
    run = run_cli(["health"], [str(CARDIO_NO), "跳过"])
    assert run.code == 0 and run.lines[-1] == HEALTH["unchanged"]
    assert TEXT.sensitive_notice in run.out
    assert run.out.index(TEXT.sensitive_notice) < run.out.index(TEXT.consent_sentence)
    assert _load(data_home).contraindications == ()


def test_the_list_shows_labels_and_what_is_recorded(run_cli, data_home):
    save_profile(data_home, clinical_history=(FLAGS[1],), contraindications=(CARDIO,))
    run = run_cli(["health"], [""])
    assert run.code == 0 and run.lines[-1] == HEALTH["unchanged"]
    assert f"· {TEXT.clinical_labels[FLAGS[1]]}" in run.lines
    assert f"· {TEXT.disclosure_labels[CARDIO]}" in run.lines
    assert f"  {CARDIO_NO}. {TEXT.disclosure_labels[CARDIO]}" in run.lines
    assert f"  1. {TEXT.clinical_labels[FLAGS[0]]}" in run.lines
    # Plain Chinese only: no internal codes and no English in the list (ruling: F4 item 4).
    for code in FLAGS:
        assert code not in run.out
    assert "BPD" not in run.out and "PTSD" not in run.out and "SIT-" not in run.out
    assert _load(data_home).contraindications == (CARDIO,)


def test_the_list_offers_the_three_disclosures_last(run_cli, data_home):
    save_profile(data_home)
    run = run_cli(["health"], [""])
    numbers = (CARDIO_NO, SAFETY_NO, PSYCHOSIS_NO)
    for number, cid in zip(numbers, PROFILE_CONTRAINDICATIONS, strict=True):
        assert f"  {number}. {TEXT.disclosure_labels[cid]}" in run.lines
    assert not [line for line in run.lines if line.startswith(f"  {PSYCHOSIS_NO + 1}. ")]


def test_the_psychosis_disclosure_is_saved_encrypted(run_cli, data_home):
    save_profile(data_home, contraindications=(CARDIO,))
    run = run_cli(["health"], [f"{CARDIO_NO}，{PSYCHOSIS_NO}"], now=LATER)
    assert run.code == 0 and run.lines[-1] == HEALTH["saved"]
    assert _load(data_home).contraindications == (CARDIO, PSYCHOSIS)
    raw = _raw(data_home)
    assert PSYCHOSIS.encode() not in raw and CARDIO.encode() not in raw


def test_changing_an_existing_record_needs_no_second_consent(run_cli, data_home):
    save_profile(data_home, contraindications=(CARDIO,))
    run = run_cli(["health"], [f"{CARDIO_NO} {SAFETY_NO}"])
    assert run.code == 0 and run.lines[-1] == HEALTH["saved"]
    assert TEXT.consent_sentence not in run.out
    assert _load(data_home).contraindications == (CARDIO, SAFETY)


def test_zero_deletes_everything(run_cli, data_home):
    save_profile(data_home, clinical_history=(FLAGS[0],), contraindications=(CARDIO,))
    run = run_cli(["health"], ["0"])
    assert run.code == 0 and run.lines[-1] == HEALTH["cleared"]
    profile = _load(data_home)
    assert profile.clinical_history == () and profile.contraindications == ()


def test_zero_shreds_every_older_copy(run_cli, data_home):
    """``0`` is a crypto-shred: the profile key is gone and no snapshot holds ciphertext,
    so a damaged main file can never bring the deleted health information back."""
    save_profile(data_home, clinical_history=(FLAGS[0],), contraindications=(CARDIO,))
    save_profile(data_home, user_name="阿青", clinical_history=(FLAGS[0],))
    run = run_cli(["health"], ["0"])
    assert run.code == 0 and run.lines[-1] == HEALTH["cleared"]
    assert not (data_home / "keys" / "profile.key").exists()
    for path in files_under(data_home):
        assert b"sealed_fields" not in path.read_bytes(), path
    (data_home / "profile.json").write_text("{ damaged", encoding="utf-8")
    run = run_cli(["health"], [""])
    assert FLAGS[0] not in run.out and CARDIO not in run.out


def test_an_unknown_choice_is_asked_again(run_cli, data_home):
    save_profile(data_home, contraindications=(CARDIO,))
    run = run_cli(["health"], ["99", str(SAFETY_NO)])
    assert TEXT.hints["clinical_unknown"].replace("{tokens}", "99") in run.out
    assert run.lines[-1] == HEALTH["saved"]
    assert _load(data_home).contraindications == (SAFETY,)


def test_skipping_the_consent_records_nothing(run_cli, data_home):
    save_profile(data_home)
    before = _raw(data_home)
    run = run_cli(["health"], [str(CARDIO_NO), "跳过"])
    assert run.code == 0 and run.lines[-1] == HEALTH["unchanged"]
    assert _raw(data_home) == before


def test_a_wrong_consent_sentence_is_asked_again(run_cli, data_home):
    save_profile(data_home)
    run = run_cli(["health"], [str(CARDIO_NO), "同意", TEXT.consent_sentence])
    assert TEXT.hints["consent_unrecognized"] in run.out
    assert _load(data_home).contraindications == (CARDIO,)


def test_without_a_keychain_nothing_is_asked_or_saved(run_cli, data_home, keychain):
    save_profile(data_home)
    before = _raw(data_home)
    keychain.broken = NoKeychainError("none")
    run = run_cli(["health"], [str(CARDIO_NO)])
    assert run.code == 1 and run.out.strip() == HEALTH["no_keychain"]
    assert _raw(data_home) == before


def test_before_onboarding_and_for_a_refusal_record(run_cli, data_home):
    run = run_cli(["health"], [])
    assert run.code == 1 and run.out.strip() == HEALTH["not_onboarded"]
    save_profile(data_home, age_confirmed_18_plus=False, region=None, age_gate_refused_at=NOW)
    run = run_cli(["health"], [])
    assert run.code == 1 and run.out.strip() == HEALTH["adults_only"]


def test_end_of_input_changes_nothing(run_cli, data_home):
    save_profile(data_home)
    before = _raw(data_home)
    assert run_cli(["health"], []).code == 0
    assert _raw(data_home) == before


def test_health_is_a_listed_command():
    assert "health" in cli.build_parser().format_help()


# -- onboarding checklist and chat ------------------------------------------------------


def test_onboarding_checklist_is_saved_and_used_by_the_session(run_cli, data_home):
    # Consent, no clinical-history code, then the second checklist item (home safety).
    answers = [*ONBOARD_CN[:-1], TEXT.consent_sentence, "", "2"]
    run = run_cli(["chat", "--rules", "--inspect"], [*answers, "[80%] 给我一个方法"])
    assert run.code == 0
    assert _load(data_home).contraindications == (SAFETY,)
    assert SAFETY in run.results[0].inspect["contraindications"]
    assert f"│ 禁忌 {SAFETY} · 情境 -" in run.panel


def test_the_third_checklist_item_records_psychosis_for_the_session(run_cli, data_home):
    answers = [*ONBOARD_CN[:-1], TEXT.consent_sentence, "", "3"]
    run = run_cli(["chat", "--rules", "--inspect"], [*answers, "[80%] 给我一个方法"])
    assert run.code == 0
    assert _load(data_home).contraindications == (PSYCHOSIS,)
    assert run.results[0].inspect["contraindications"] == [PSYCHOSIS]
    assert "olivia health" not in run.results[0].reply


def test_a_disclosure_in_chat_is_never_written_to_the_profile(run_cli, data_home):
    save_profile(data_home)
    run = run_cli(["chat", "--rules"], ["他又动手打我了", "我有心脏病"])
    assert run.out.count("olivia health") == 2
    profile = _load(data_home)
    assert profile.contraindications == () and profile.clinical_history == ()
