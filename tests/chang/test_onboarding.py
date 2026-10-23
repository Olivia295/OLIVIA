"""First-visit onboarding flow (ONB-01..08; rulings 22-24, 28)."""

from __future__ import annotations

import json
import shutil
import zoneinfo
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from olivia.core.chang import onboarding as onb
from olivia.core.chang.onboarding import (
    SUPPORTED_REGIONS,
    TIMEZONE_CHOICES,
    Completed,
    OnboardingFinishedError,
    OnboardingFlow,
    OnboardingTextError,
    Prompt,
    RefusalReason,
    Refused,
    Step,
    canonical_timezone,
    load_onboarding_text,
)
from olivia.core.chang.profile import ProfileStore
from olivia.core.crypto.errors import KeychainUnavailableError, NoKeychainError
from olivia.core.models import PersonaProfile, PersonaSpectrum, UserRegion
from olivia.core.taxonomy import load_taxonomy

ROOT = Path(__file__).resolve().parents[2]
TEXT_FILE = ROOT / "olivia/data/templates/onboarding.yaml"
HOTLINES = ROOT / "olivia/data/resources/hotlines.yaml"
WILLOW = ROOT / "olivia/data/language/willow.yaml"
NOW = datetime(2026, 10, 22, 9, 30, tzinfo=UTC)
TAX = load_taxonomy()
TEXT = load_onboarding_text()
HAS_TZDB = bool(zoneinfo.available_timezones())

# Banned in every onboarding sentence (WILLOW-01/04): preaching, diagnosis, exclamation.
FORBIDDEN = ["你应该", "应该", "必须", "一定要", "症状", "病", "诊断", "患者", "治疗", "！", "!"]


def _flow(tmp_path: Path) -> OnboardingFlow:
    return OnboardingFlow(TAX, ProfileStore(tmp_path), NOW)


def _files(tmp_path: Path) -> list[Path]:
    return [p for p in tmp_path.rglob("*") if p.is_file()]


def _walk(flow: OnboardingFlow, answers: list[str]) -> Prompt | Completed | Refused:
    result: Prompt | Completed | Refused = flow.prompt()
    for reply in answers:
        result = flow.answer(reply)
    return result


def _to_region(flow: OnboardingFlow) -> None:
    _walk(flow, ["1", "1", "", "", "", "", ""])
    assert flow.step is Step.REGION


# -- happy paths ---------------------------------------------------------------------


def test_full_happy_path_mainland(tmp_path):
    flow = _flow(tmp_path)
    first = flow.prompt()
    assert first.step is Step.DISCLAIMER
    assert first.options == ("我已阅读并同意", "我不同意")

    steps = []
    for reply in ["1", "1", "", " 小林 ", "阿柳", "", "考试、前任，体重", "1", "跳过"]:
        steps.append(flow.step)
        result = flow.answer(reply)

    assert steps == [
        Step.DISCLAIMER,
        Step.AGE_GATE,
        Step.ENCRYPTION,
        Step.USER_NAME,
        Step.AGENT_NAME,
        Step.PERSONA,
        Step.TABOO,
        Step.REGION,
        Step.CLINICAL_CONSENT,
    ]
    assert isinstance(result, Completed)
    assert flow.outcome == result
    p = result.profile
    assert p.age_confirmed_18_plus is True and p.age_gate_refused_at is None
    assert (p.user_name, p.agent_name) == ("小林", "阿柳")
    assert p.persona_spectrum is PersonaSpectrum.GENTLE_HOLDING
    assert p.taboo_topics == ("考试", "前任", "体重")
    assert p.region == UserRegion(country_code="CN", timezone="Asia/Shanghai")
    assert p.clinical_history == ()
    assert p.enable_at_rest_encryption is False
    assert p.created_at == p.updated_at == NOW
    assert "小林" in result.text and "阿柳" in result.text
    assert ProfileStore(tmp_path).load() == p


def test_happy_path_with_timezone_choice_and_clinical_consent(tmp_path):
    flow = _flow(tmp_path)
    _to_region(flow)
    tz_prompt = flow.answer("美国")
    assert isinstance(tz_prompt, Prompt) and tz_prompt.step is Step.TIMEZONE
    assert len(tz_prompt.options) == len(TIMEZONE_CHOICES["US"])
    assert tz_prompt.options[0].endswith("America/New_York")
    consent = flow.answer("5")
    assert isinstance(consent, Prompt) and consent.step is Step.CLINICAL_CONSENT
    assert TEXT.consent_sentence in consent.text
    history = flow.answer(TEXT.consent_sentence + "。")
    assert isinstance(history, Prompt) and history.step is Step.CLINICAL_HISTORY
    flags = list(TAX.red_flags().values())
    assert history.options == tuple(f"{f.code} {f.name_zh}" for f in flags)
    result = flow.answer(f"{flags[2].code.lower()}，1  {flags[2].code}")
    assert isinstance(result, Completed)
    assert result.profile.region == UserRegion(country_code="US", timezone="America/Los_Angeles")
    # Taxonomy order, de-duplicated, canonical case.
    assert result.profile.clinical_history == (flags[0].code, flags[2].code)
    assert ProfileStore(tmp_path).load() == result.profile


def test_defaults_on_empty_answers(tmp_path):
    flow = _flow(tmp_path)
    result = _walk(flow, ["同意", "是", "", "", "", "", "", "1", ""])
    assert isinstance(result, Completed)
    p = result.profile
    assert (p.user_name, p.agent_name, p.taboo_topics) == ("朋友", "Olivia", ())
    assert p.region == UserRegion(country_code="CN", timezone="Asia/Shanghai")
    assert p.clinical_history == ()


def test_full_width_digits_are_accepted(tmp_path):
    flow = _flow(tmp_path)
    flow.answer("１")
    assert flow.step is Step.AGE_GATE


def test_no_file_written_before_completion(tmp_path):
    flow = _flow(tmp_path)
    answers = ["1", "1", "2", "小林", "阿柳", "1", "前任", "9", "Europe/Paris"]
    answers.append(TEXT.consent_sentence)
    for reply in answers:
        flow.answer(reply)
        assert flow.outcome is None
        assert _files(tmp_path) == []
    assert flow.step is Step.CLINICAL_HISTORY
    result = flow.answer("1")
    assert isinstance(result, Completed)
    assert sorted(p.name for p in _files(tmp_path)) == ["profile.json", "profile.key"]


# -- ONB-01 disclaimer ---------------------------------------------------------------


@pytest.mark.parametrize("reply", ["2", "我不同意", "不同意", "拒绝"])
def test_disclaimer_refusal_stops_and_saves_nothing(tmp_path, reply):
    flow = _flow(tmp_path)
    result = flow.answer(reply)
    assert isinstance(result, Refused)
    assert result.reason is RefusalReason.DISCLAIMER_DECLINED
    assert result.text == TEXT.outcomes["disclaimer_declined"]
    assert _files(tmp_path) == []
    with pytest.raises(OnboardingFinishedError):
        flow.prompt()
    with pytest.raises(OnboardingFinishedError):
        flow.answer("1")
    # Nothing was persisted, so the next launch starts over at the disclaimer.
    assert _flow(tmp_path).prompt().step is Step.DISCLAIMER


@pytest.mark.parametrize("reply", ["", "嗯", "3", "ok"])
def test_disclaimer_needs_explicit_acceptance(tmp_path, reply):
    flow = _flow(tmp_path)
    again = flow.answer(reply)
    assert isinstance(again, Prompt) and again.step is Step.DISCLAIMER
    assert again.text.startswith(TEXT.hints["unrecognized"])
    assert flow.outcome is None
    # The hint is shown once, not carried into the next step.
    assert not flow.answer("1").text.startswith(TEXT.hints["unrecognized"])


# -- ONB-05 age gate (NG-3, ruling 22) -----------------------------------------------


def test_minor_refusal_persists_and_blocks_restart(tmp_path):
    flow = _flow(tmp_path)
    flow.answer("1")
    result = flow.answer("2")
    assert isinstance(result, Refused) and result.reason is RefusalReason.UNDER_18
    assert "12355" in result.text and "中国大陆" in result.text
    assert "findahelpline.com" in result.text and "befrienders.org" in result.text

    saved = ProfileStore(tmp_path).load()
    assert saved is not None and saved.is_age_gate_refusal
    assert saved.age_confirmed_18_plus is False and saved.age_gate_refused_at == NOW
    assert saved.region is None and saved.taboo_topics == () and saved.clinical_history == ()
    assert (saved.user_name, saved.agent_name) == ("朋友", "Olivia")

    later = OnboardingFlow(TAX, ProfileStore(tmp_path), NOW + timedelta(days=30))
    assert later.outcome == result
    with pytest.raises(OnboardingFinishedError):
        later.prompt()
    with pytest.raises(OnboardingFinishedError):
        later.answer("1")
    assert ProfileStore(tmp_path).load() == saved  # the later launch wrote nothing


def test_minor_message_numbers_match_the_hotline_data():
    regions = yaml.safe_load(HOTLINES.read_text(encoding="utf-8"))["regions"]
    message = TEXT.outcomes["under_18"]
    cn_youth = [line for line in regions["CN"]["lines"] if line.get("minors_only")]
    assert [line["number"] for line in cn_youth] == ["12355"]
    for line in regions["ZZ"]["lines"]:
        assert line["number"] in message
    for code, region in regions.items():  # R8: no other region's youth lines are claimed
        if code not in ("CN", "ZZ"):
            assert all(line["number"] not in message for line in region.get("lines", []))


def test_adult_profile_already_saved_finishes_immediately(tmp_path):
    store = ProfileStore(tmp_path)
    existing = PersonaProfile(age_confirmed_18_plus=True, created_at=NOW, updated_at=NOW)
    store.save(existing)
    flow = OnboardingFlow(TAX, store, NOW)
    assert flow.outcome == Completed(existing, "")


# -- ONB-02 names --------------------------------------------------------------------


def test_name_length_validation(tmp_path):
    flow = _flow(tmp_path)
    _walk(flow, ["1", "1", ""])
    too_long = flow.answer("一二三四五六七八九十一二三")
    assert isinstance(too_long, Prompt) and too_long.step is Step.USER_NAME
    assert "12" in too_long.text.split("\n\n")[0]
    agent = flow.answer("一二三四五六七八九十一二")
    assert isinstance(agent, Prompt) and agent.step is Step.AGENT_NAME
    assert "一二三四五六七八九十一二" in agent.text
    assert flow.answer("x" * 13).step is Step.AGENT_NAME
    assert flow.answer("tab\tname").step is Step.AGENT_NAME
    assert flow.answer("  Willow  ").step is Step.PERSONA
    result = _walk(flow, ["", "", "1", ""])
    assert isinstance(result, Completed)
    assert result.profile.agent_name == "Willow"


# -- ONB-03 persona, ONB-04 taboo ----------------------------------------------------


def test_persona_offers_only_gentle_holding(tmp_path):
    flow = _flow(tmp_path)
    prompt = _walk(flow, ["1", "1", "", "", ""])
    assert isinstance(prompt, Prompt) and prompt.step is Step.PERSONA
    assert prompt.options == (TEXT.persona_label,)
    assert flow.answer("2").step is Step.PERSONA
    assert flow.answer("gentle_holding").step is Step.TABOO


def test_taboo_parsing_and_limits(tmp_path):
    flow = _flow(tmp_path)
    _walk(flow, ["1", "1", "", "", "", ""])
    assert flow.answer("、".join(f"话题{i}" for i in range(21))).step is Step.TABOO
    assert flow.answer("一" * 21).step is Step.TABOO
    flow.answer("前夫 体重,体重；高考")
    result = _walk(flow, ["1", ""])
    assert isinstance(result, Completed)
    assert result.profile.taboo_topics == ("前夫", "体重", "高考")


@pytest.mark.parametrize("reply", ["", "无", "没有", " 跳过 "])
def test_taboo_may_be_empty(tmp_path, reply):
    flow = _flow(tmp_path)
    result = _walk(flow, ["1", "1", "", "", "", "", reply, "1", ""])
    assert isinstance(result, Completed) and result.profile.taboo_topics == ()


# -- ONB-07 region and timezone (ruling 24) ------------------------------------------


def test_supported_regions_match_the_hotline_data():
    regions = yaml.safe_load(HOTLINES.read_text(encoding="utf-8"))["regions"]
    assert set(SUPPORTED_REGIONS) == set(regions)
    assert SUPPORTED_REGIONS[-1] == "ZZ"


@pytest.mark.parametrize(
    ("reply", "code", "zone"),
    [
        ("1", "CN", "Asia/Shanghai"),
        ("香港", "HK", "Asia/Hong_Kong"),
        ("mo", "MO", "Asia/Macau"),
        ("中国台湾", "TW", "Asia/Taipei"),
        ("GB", "GB", "Europe/London"),
    ],
)
def test_region_default_timezone_skips_the_question(tmp_path, reply, code, zone):
    flow = _flow(tmp_path)
    _to_region(flow)
    assert flow.answer(reply).step is Step.CLINICAL_CONSENT
    result = flow.answer("")
    assert isinstance(result, Completed)
    assert result.profile.region == UserRegion(country_code=code, timezone=zone)


@pytest.mark.parametrize("code", ["US", "CA", "AU"])
def test_region_with_several_zones_asks(tmp_path, code):
    flow = _flow(tmp_path)
    _to_region(flow)
    prompt = flow.answer(code)
    assert isinstance(prompt, Prompt) and prompt.step is Step.TIMEZONE
    assert prompt.options == tuple(f"{TEXT.timezone_labels[z]} {z}" for z in TIMEZONE_CHOICES[code])
    assert flow.answer("").step is Step.TIMEZONE  # no silent default here
    assert flow.answer(str(len(prompt.options) + 1)).step is Step.TIMEZONE
    assert flow.answer("1").step is Step.CLINICAL_CONSENT
    result = flow.answer("")
    assert isinstance(result, Completed)
    assert result.profile.region == UserRegion(
        country_code=code, timezone=TIMEZONE_CHOICES[code][0]
    )


@pytest.mark.parametrize("reply", ["9", "ZZ", "其他", "不想说"])
def test_unknown_region_is_zz_and_defaults_to_utc(tmp_path, reply):
    flow = _flow(tmp_path)
    _to_region(flow)
    prompt = flow.answer(reply)
    assert isinstance(prompt, Prompt) and prompt.step is Step.TIMEZONE
    assert prompt.options == () and "UTC" in prompt.text
    result = _walk(flow, ["", ""])
    assert isinstance(result, Completed)
    assert result.profile.region == UserRegion(country_code="ZZ", timezone="UTC")


def test_unknown_region_accepts_a_typed_timezone(tmp_path):
    flow = _flow(tmp_path)
    _to_region(flow)
    result = _walk(flow, ["9", "Mars/Olympus", "Asia/Singapore", ""])
    assert isinstance(result, Completed)
    assert result.profile.region == UserRegion(country_code="ZZ", timezone="Asia/Singapore")


def test_unrecognized_region_reprompts(tmp_path):
    flow = _flow(tmp_path)
    _to_region(flow)
    again = flow.answer("火星")
    assert again.step is Step.REGION and again.text.startswith(TEXT.hints["unrecognized"])
    assert flow.answer("0").step is Step.REGION
    assert flow.answer(str(len(SUPPORTED_REGIONS) + 1)).step is Step.REGION


@pytest.mark.skipif(not HAS_TZDB, reason="no tz database on this platform")
def test_timezone_validation_with_tz_database():
    assert canonical_timezone("Asia/Singapore") == "Asia/Singapore"
    assert canonical_timezone(" asia/singapore ") == "Asia/Singapore"
    assert canonical_timezone("utc") == "UTC"
    for bad in ("Mars/Olympus", "Asia/", "Singapore", "PRC", "US/Eastern", "", "../etc/passwd"):
        assert canonical_timezone(bad) is None
    for zones in TIMEZONE_CHOICES.values():
        assert all(canonical_timezone(zone) == zone for zone in zones)


def test_timezone_validation_without_tz_database(monkeypatch):
    monkeypatch.setattr(onb.zoneinfo, "available_timezones", set)
    assert canonical_timezone("Asia/Singapore") == "Asia/Singapore"
    assert canonical_timezone("America/Argentina/Buenos_Aires") == "America/Argentina/Buenos_Aires"
    assert canonical_timezone("America/Port-au-Prince") == "America/Port-au-Prince"
    assert canonical_timezone("UTC") == "UTC"
    for bad in ("asia/singapore", "Asia/", "Mars/Olympus", "Etc/GMT+8", "Asia/Singapore/", ""):
        assert canonical_timezone(bad) is None
    for zones in TIMEZONE_CHOICES.values():
        assert all(canonical_timezone(zone) == zone for zone in zones)


# -- clinical history consent (ruling 23) --------------------------------------------


@pytest.mark.parametrize("reply", ["", "跳过", "没有"])
def test_clinical_consent_can_be_skipped(tmp_path, reply):
    flow = _flow(tmp_path)
    _to_region(flow)
    flow.answer("1")
    result = flow.answer(reply)
    assert isinstance(result, Completed) and result.profile.clinical_history == ()


@pytest.mark.parametrize("reply", ["1", "同意", "我同意", "好"])
def test_clinical_consent_needs_the_full_sentence(tmp_path, reply):
    flow = _flow(tmp_path)
    _to_region(flow)
    flow.answer("1")
    again = flow.answer(reply)
    assert isinstance(again, Prompt) and again.step is Step.CLINICAL_CONSENT
    assert again.text.startswith(TEXT.hints["consent_unrecognized"])


def test_clinical_consent_then_nothing_selected(tmp_path):
    flow = _flow(tmp_path)
    _to_region(flow)
    result = _walk(flow, ["1", f"  {TEXT.consent_sentence} ", ""])
    assert isinstance(result, Completed) and result.profile.clinical_history == ()


@pytest.mark.parametrize("bad", ["SIT-99-99", "99", "0", "1, SIT-XX"])
def test_invalid_red_flag_code_rejected(tmp_path, bad):
    flow = _flow(tmp_path)
    _to_region(flow)
    _walk(flow, ["1", TEXT.consent_sentence])
    again = flow.answer(bad)
    assert isinstance(again, Prompt) and again.step is Step.CLINICAL_HISTORY
    unknown = [t for t in bad.replace(",", " ").split() if t != "1"]
    assert all(token.casefold() in again.text.casefold() for token in unknown)
    assert _files(tmp_path) == []
    result = flow.answer("1")
    assert isinstance(result, Completed)
    assert result.profile.clinical_history == (next(iter(TAX.red_flags())),)


# -- ONB-06 at-rest encryption switch (ruling 28) ------------------------------------


def _profile_bytes(tmp_path: Path) -> list[bytes]:
    return [p.read_bytes() for p in _files(tmp_path)]


def test_encryption_question_comes_right_after_the_age_gate(tmp_path):
    flow = _flow(tmp_path)
    prompt = _walk(flow, ["1", "1"])
    assert isinstance(prompt, Prompt) and prompt.step is Step.ENCRYPTION
    keep_off, encrypt_all = TEXT.choices["encryption"]
    assert prompt.options == (keep_off.label, encrypt_all.label)
    again = flow.answer("也许")
    assert again.step is Step.ENCRYPTION and again.text.startswith(TEXT.hints["unrecognized"])
    assert flow.answer("").step is Step.USER_NAME


@pytest.mark.parametrize(
    ("reply", "whole"), [("", False), ("1", False), ("2", True), ("全部加密", True)]
)
def test_encryption_switch_choice_is_saved(tmp_path, reply, whole):
    flow = _flow(tmp_path)
    result = _walk(flow, ["1", "1", reply, "小林", "", "", "", "1", ""])
    assert isinstance(result, Completed)
    assert result.profile.enable_at_rest_encryption is whole
    assert TEXT.outcomes["health_not_saved"] not in result.text
    raw = b"".join(_profile_bytes(tmp_path))
    assert ("小林".encode() in raw) is not whole
    assert ProfileStore(tmp_path).load() == result.profile


@pytest.mark.parametrize("encryption", ["", "2"])
def test_clinical_history_is_encrypted_whatever_the_switch(tmp_path, encryption):
    flow = _flow(tmp_path)
    code = next(iter(TAX.red_flags()))
    result = _walk(flow, ["1", "1", encryption, "", "", "", "", "1", TEXT.consent_sentence, "1"])
    assert isinstance(result, Completed) and result.profile.clinical_history == (code,)
    for raw in _profile_bytes(tmp_path):
        assert code.encode() not in raw and b"clinical_history" not in raw
    assert ProfileStore(tmp_path).load() == result.profile


@pytest.mark.parametrize("error", [NoKeychainError("none"), KeychainUnavailableError("locked")])
def test_without_keychain_health_questions_are_skipped_and_the_user_told(tmp_path, keychain, error):
    keychain.broken = error
    flow = _flow(tmp_path)
    steps = []
    result: Prompt | Completed | Refused = flow.prompt()
    for reply in ["1", "1", "小林", "", "", "", "1"]:
        steps.append(flow.step)
        result = flow.answer(reply)
    assert Step.ENCRYPTION not in steps and steps[-1] is Step.REGION
    assert isinstance(result, Completed)
    assert result.text.startswith(TEXT.outcomes["health_not_saved"])
    assert "小林" in result.text
    p = result.profile
    assert p.clinical_history == () and p.enable_at_rest_encryption is False
    assert [f.name for f in _files(tmp_path)] == ["profile.json"]
    keychain.broken = None
    assert ProfileStore(tmp_path).load() == p


def test_keychain_failing_at_the_final_save_drops_health_information(tmp_path, keychain):
    flow = _flow(tmp_path)
    _walk(flow, ["1", "1", "2", "", "", "", "", "1", TEXT.consent_sentence])
    keychain.broken = KeychainUnavailableError("locked")
    result = flow.answer("1")
    assert isinstance(result, Completed)
    assert result.text.startswith(TEXT.outcomes["health_not_saved"])
    assert result.profile.clinical_history == ()
    assert result.profile.enable_at_rest_encryption is False
    code = next(iter(TAX.red_flags()))
    for raw in _profile_bytes(tmp_path):
        assert code.encode() not in raw
    keychain.broken = None
    assert ProfileStore(tmp_path).load() == result.profile


# -- construction and text file ------------------------------------------------------


def test_now_must_be_timezone_aware(tmp_path):
    with pytest.raises(ValueError):
        OnboardingFlow(TAX, ProfileStore(tmp_path), datetime(2026, 10, 22))
    aware = datetime(2026, 10, 22, tzinfo=timezone(timedelta(hours=8)))
    assert OnboardingFlow(TAX, ProfileStore(tmp_path), aware).outcome is None


def test_text_file_has_draft_header_and_no_banned_wording():
    first = TEXT_FILE.read_text(encoding="utf-8").splitlines()[0]
    assert first == (
        "# 草稿：待 G-0 两名注册心理师审核"
        "（docs/superpowers/plans/2026-10-22-remaining-roadmap.md R1-4）"
    )
    diagnosis = yaml.safe_load(WILLOW.read_text(encoding="utf-8"))["diagnosis_terms"]
    texts = [
        TEXT.consent_sentence,
        TEXT.persona_label,
        *TEXT.prompts.values(),
        *TEXT.hints.values(),
        *TEXT.outcomes.values(),
        *TEXT.region_labels.values(),
        *(c.label for pair in TEXT.choices.values() for c in pair),
    ]
    for text in texts:
        lowered = text.casefold()
        assert not [w for w in [*FORBIDDEN, *diagnosis] if w in lowered], text


def test_text_loader_rejects_missing_and_unknown_slots(tmp_path):
    data = yaml.safe_load(TEXT_FILE.read_text(encoding="utf-8"))
    broken = json.loads(json.dumps(data))
    del broken["prompts"]["taboo"]
    (tmp_path / "onboarding.yaml").write_text(yaml.safe_dump(broken), encoding="utf-8")
    with pytest.raises(OnboardingTextError, match="taboo"):
        load_onboarding_text(tmp_path)

    broken = json.loads(json.dumps(data))
    broken["hints"]["unrecognized"] = "{city}"
    (tmp_path / "onboarding.yaml").write_text(yaml.safe_dump(broken), encoding="utf-8")
    with pytest.raises(OnboardingTextError, match="city"):
        load_onboarding_text(tmp_path)

    broken = json.loads(json.dumps(data))
    broken["region_aliases"]["XX"] = ["x"]
    (tmp_path / "onboarding.yaml").write_text(yaml.safe_dump(broken), encoding="utf-8")
    with pytest.raises(OnboardingTextError, match="XX"):
        load_onboarding_text(tmp_path)

    (tmp_path / "onboarding.yaml").write_text("- not a mapping", encoding="utf-8")
    with pytest.raises(OnboardingTextError):
        load_onboarding_text(tmp_path)
    shutil.rmtree(tmp_path)
    with pytest.raises(OnboardingTextError):
        load_onboarding_text(tmp_path)
