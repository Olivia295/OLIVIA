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
from olivia.core.models import (
    PROFILE_CONTRAINDICATIONS,
    PersonaProfile,
    PersonaSpectrum,
    UserRegion,
)
from olivia.core.resources.fallback import EMERGENCY, emergency_lines
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


_real_system_timezone = onb.system_timezone  # bound at import, before any test patches it


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
    assert history.options == tuple(TEXT.clinical_labels[f.code] for f in flags)
    checklist = flow.answer(f"{flags[2].code.lower()}，1  {flags[2].code}")
    assert isinstance(checklist, Prompt) and checklist.step is Step.CONTRAINDICATIONS
    assert checklist.options == tuple(TEXT.disclosure_labels[c] for c in PROFILE_CONTRAINDICATIONS)
    assert PROFILE_CONTRAINDICATIONS == (
        "CARDIORESPIRATORY_INSTABILITY",
        "INTERPERSONAL_SAFETY_HAZARD",
        "RED_FLAG_PSYCHOSIS",
    )
    result = flow.answer("２")
    assert isinstance(result, Completed)
    assert result.profile.region == UserRegion(country_code="US", timezone="America/Los_Angeles")
    # Taxonomy order, de-duplicated, canonical case.
    assert result.profile.clinical_history == (flags[0].code, flags[2].code)
    assert result.profile.contraindications == ("INTERPERSONAL_SAFETY_HAZARD",)
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
    flow.answer("1")
    assert flow.outcome is None and _files(tmp_path) == []
    assert flow.step is Step.CONTRAINDICATIONS
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
    assert result.text == TEXT.outcomes["disclaimer_declined"] + "\n" + "\n".join(emergency_lines())
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
    confirm = flow.answer("2")
    assert isinstance(confirm, Prompt) and confirm.step is Step.AGE_CONFIRM
    assert _files(tmp_path) == []  # nothing is recorded before the confirmation
    result = flow.answer("1")
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


def test_age_confirmation_asks_once_with_two_choices(tmp_path):
    flow = _flow(tmp_path)
    _walk(flow, ["1", "2"])
    prompt = flow.prompt()
    assert prompt.step is Step.AGE_CONFIRM
    assert prompt.text.startswith("你确认自己未满 18 岁吗？")
    assert prompt.options == ("是", "我选错了")


@pytest.mark.parametrize("reply", ["2", "我选错了", "选错了"])
def test_a_mistaken_under_18_answer_can_be_undone(tmp_path, reply):
    flow = _flow(tmp_path)
    _walk(flow, ["1", "2"])
    back = flow.answer(reply)
    assert isinstance(back, Prompt) and back.step is Step.AGE_GATE
    assert _files(tmp_path) == []
    result = _walk(flow, ["1", "", "", "", "", "", "1", ""])
    assert isinstance(result, Completed) and result.profile.age_confirmed_18_plus is True
    assert not result.profile.is_age_gate_refusal


@pytest.mark.parametrize("reply", ["", "嗯", "3"])
def test_age_confirmation_needs_a_clear_answer(tmp_path, reply):
    flow = _flow(tmp_path)
    _walk(flow, ["1", "2"])
    again = flow.answer(reply)
    assert isinstance(again, Prompt) and again.step is Step.AGE_CONFIRM
    assert again.text.startswith(TEXT.hints["unrecognized"])
    assert _files(tmp_path) == []


@pytest.mark.parametrize("answers", [["1", "2", "1"], ["2"]])
def test_refusal_pages_list_the_emergency_numbers_they_ask_for(tmp_path, answers):
    """QA r3: both pages say "请…拨打当地的紧急电话"; no region is known yet, so every
    supported region's numbers follow (the fixed list, checked against hotlines.yaml)."""
    result = _walk(_flow(tmp_path), answers)
    assert isinstance(result, Refused)
    asked = result.text.index("紧急电话")
    for _code, label, numbers in EMERGENCY:
        assert f"· {label}：" in result.text[asked:]
        assert all(number in result.text[asked:] for number, _ in numbers)
    assert result.text.endswith("\n".join(emergency_lines()))
    for number in ("110", "120", "999", "911", "000", "112"):
        assert number in result.text
    if result.reason is RefusalReason.UNDER_18:
        assert "12355" in result.text


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


def test_persona_offers_the_four_personas_gentle_first(tmp_path):
    flow = _flow(tmp_path)
    prompt = _walk(flow, ["1", "1", "", "", ""])
    assert isinstance(prompt, Prompt) and prompt.step is Step.PERSONA
    assert tuple(PersonaSpectrum) == onb.PERSONA_CHOICES
    assert onb.PERSONA_CHOICES[0] is onb.DEFAULT_PERSONA is PersonaSpectrum.GENTLE_HOLDING
    assert prompt.options == tuple(TEXT.persona_labels[p] for p in onb.PERSONA_CHOICES)
    assert "olivia persona" in prompt.text
    for label in prompt.options:
        name, _, description = label.partition("：")
        assert 2 <= len(name) <= 4 and description, label
    # Enter keeps the default.
    result = _walk(flow, ["", "", "1", ""])
    assert isinstance(result, Completed)
    assert result.profile.persona_spectrum is PersonaSpectrum.GENTLE_HOLDING


@pytest.mark.parametrize(
    ("reply", "persona"),
    [
        ("2", PersonaSpectrum.ZEN_PHILOSOPHER),
        ("４", PersonaSpectrum.SILENT_ANCHOR),
        ("平视战友", PersonaSpectrum.RATIONAL_PEER),
        (" rational_peer ", PersonaSpectrum.RATIONAL_PEER),
        ("SILENT_ANCHOR", PersonaSpectrum.SILENT_ANCHOR),
        ("1", PersonaSpectrum.GENTLE_HOLDING),
    ],
)
def test_persona_choice_is_saved(tmp_path, reply, persona):
    flow = _flow(tmp_path)
    _walk(flow, ["1", "1", "", "", ""])
    assert flow.answer(reply).step is Step.TABOO
    result = _walk(flow, ["", "1", ""])
    assert isinstance(result, Completed) and result.profile.persona_spectrum is persona
    assert ProfileStore(tmp_path).load() == result.profile


def test_persona_full_label_is_accepted(tmp_path):
    flow = _flow(tmp_path)
    _walk(flow, ["1", "1", "", "", ""])
    assert flow.answer(TEXT.persona_labels[PersonaSpectrum.ZEN_PHILOSOPHER]).step is Step.TABOO


@pytest.mark.parametrize("reply", ["5", "0", "随便", "树洞型"])
def test_unrecognized_persona_asks_again(tmp_path, reply):
    flow = _flow(tmp_path)
    _walk(flow, ["1", "1", "", "", ""])
    again = flow.answer(reply)
    assert isinstance(again, Prompt) and again.step is Step.PERSONA
    assert again.text.startswith(TEXT.hints["persona_choice"])


@pytest.mark.parametrize(
    ("reply", "persona"),
    [
        ("3", PersonaSpectrum.RATIONAL_PEER),
        ("沉静哲思", PersonaSpectrum.ZEN_PHILOSOPHER),
        ("", None),
        ("五", None),
    ],
)
def test_persona_from_reply(reply, persona):
    assert onb.persona_from_reply(reply, TEXT.persona_labels) is persona


@pytest.mark.parametrize(
    ("reply", "persona"),
    [
        ("树洞", PersonaSpectrum.SILENT_ANCHOR),
        ("静默", PersonaSpectrum.SILENT_ANCHOR),
        ("哲思", PersonaSpectrum.ZEN_PHILOSOPHER),
        ("禅", PersonaSpectrum.ZEN_PHILOSOPHER),
        ("战友", PersonaSpectrum.RATIONAL_PEER),
        ("理性", PersonaSpectrum.RATIONAL_PEER),
        ("温和", PersonaSpectrum.GENTLE_HOLDING),
        ("随便", None),
    ],
)
def test_persona_short_aliases(tmp_path, reply, persona):
    assert onb.persona_from_reply(reply, TEXT.persona_labels, TEXT.persona_aliases) is persona
    # Without the aliases only numbers, enum values and labels are accepted.
    assert onb.persona_from_reply(reply, TEXT.persona_labels) is None
    if persona is not None:
        flow = _flow(tmp_path)
        _walk(flow, ["1", "1", "", "", ""])
        assert flow.answer(reply).step is Step.TABOO


def test_persona_aliases_are_unambiguous():
    seen: dict[str, PersonaSpectrum] = {}
    for persona, aliases in TEXT.persona_aliases.items():
        for alias in aliases:
            assert seen.setdefault(alias, persona) is persona, alias


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


@pytest.mark.parametrize("reply", ["9", "ZZ", "其他", "不想说", "", "  ", "跳过"])
def test_unknown_region_is_zz_and_defaults_to_the_system_timezone(tmp_path, reply, monkeypatch):
    monkeypatch.setattr(onb, "system_timezone", lambda: "Asia/Tokyo")
    flow = _flow(tmp_path)
    _to_region(flow)
    prompt = flow.answer(reply)
    assert isinstance(prompt, Prompt) and prompt.step is Step.TIMEZONE
    assert prompt.options == () and "Asia/Tokyo" in prompt.text and "UTC" not in prompt.text
    result = _walk(flow, ["", ""])
    assert isinstance(result, Completed)
    assert result.profile.region == UserRegion(country_code="ZZ", timezone="Asia/Tokyo")


@pytest.mark.parametrize(
    ("reply", "code"),
    [
        ("china", "CN"),
        ("中国", "CN"),
        ("大陆", "CN"),
        ("内地", "CN"),
        ("cn", "CN"),
        ("Hong Kong", "HK"),
        ("hongkong", "HK"),
        ("香港", "HK"),
        ("台湾", "TW"),
        ("澳门", "MO"),
        ("us", "US"),
        ("美国", "US"),
        ("USA", "US"),
        ("uk", "GB"),
        ("australia", "AU"),
        ("其他", "ZZ"),
        ("JP", None),
        ("火星", None),
        ("", None),
    ],
)
def test_region_from_reply_accepts_common_names(reply, code):
    assert onb.region_from_reply(reply, TEXT) == code


def test_region_from_reply_numbers_are_optional():
    assert onb.region_from_reply("1", TEXT) == "CN"
    assert onb.region_from_reply("1", TEXT, numbers=False) is None


def test_region_aliases_are_unambiguous():
    seen: dict[str, str] = {}
    for code in SUPPORTED_REGIONS:
        for name in (code, TEXT.region_labels[code], *TEXT.region_aliases[code]):
            key = "".join(name.casefold().split())
            assert seen.setdefault(key, code) == code, name


def test_system_timezone_reads_tz_then_the_system_files(tmp_path, monkeypatch):
    zone_file = tmp_path / "timezone"
    monkeypatch.setattr(onb, "_LOCALTIME", str(tmp_path / "missing"))
    monkeypatch.setattr(onb, "_TIMEZONE_FILE", zone_file)
    monkeypatch.setenv("TZ", ":Europe/Paris")
    assert _real_system_timezone() == "Europe/Paris" or not HAS_TZDB
    monkeypatch.setenv("TZ", "Not/A_Zone")
    assert _real_system_timezone() == "UTC"
    zone_file.write_text("Asia/Singapore\n", encoding="utf-8")
    assert _real_system_timezone() == "Asia/Singapore"
    monkeypatch.delenv("TZ")
    link = tmp_path / "localtime"
    link.symlink_to(tmp_path / "zoneinfo" / "America" / "Chicago")
    monkeypatch.setattr(onb, "_LOCALTIME", str(link))
    assert _real_system_timezone() == "America/Chicago"


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
    result = _walk(flow, ["1", f"  {TEXT.consent_sentence} ", "", ""])
    assert isinstance(result, Completed) and result.profile.clinical_history == ()
    assert result.profile.contraindications == ()


# PIPL Art. 28-30: the notice before the separate consent states what is collected, why,
# where it stays, what declining changes and how to withdraw (next-phase B8).
NOTICE_POINTS = (
    "敏感的个人信息",  # what kind of information this is
    "以往被专业人士评估过",  # what: the clinical-history list
    "心脏或呼吸",  # what: the three checklist items
    "身边有人可能伤害你",
    "幻觉、妄想",
    "只用来",  # purpose
    "加密保存在这台电脑上",  # where and how
    "不会上传",
    "没有任何影响",  # declining changes nothing
    "olivia health",  # withdrawal
    "olivia forget",
)


def test_consent_comes_after_a_standalone_notice(tmp_path):
    notice = TEXT.sensitive_notice
    for point in NOTICE_POINTS:
        assert point in notice, point
    assert TEXT.consent_sentence not in notice and "{" not in notice
    flow = _flow(tmp_path)
    _to_region(flow)
    consent = flow.answer("1")
    assert isinstance(consent, Prompt) and consent.step is Step.CLINICAL_CONSENT
    assert notice in consent.text
    assert consent.text.index(notice) < consent.text.index(TEXT.consent_sentence)
    # A reply that is not the sentence: the hint and the sentence again, not the whole
    # notice (dogfood P1); it was shown just above, before the first ask.
    again = flow.answer("好")
    assert isinstance(again, Prompt) and again.step is Step.CLINICAL_CONSENT
    assert notice not in again.text and TEXT.consent_sentence in again.text


def test_notice_wording_is_marked_for_legal_review():
    assert "待 G-4 法务审核" in TEXT_FILE.read_text(encoding="utf-8")


def test_checklist_rejects_unknown_numbers_and_keeps_the_clinical_answer(tmp_path):
    flow = _flow(tmp_path)
    _to_region(flow)
    _walk(flow, ["1", TEXT.consent_sentence, "2"])
    again = flow.answer("4")
    assert isinstance(again, Prompt) and again.step is Step.CONTRAINDICATIONS
    assert TEXT.hints["clinical_unknown"] in again.text and _files(tmp_path) == []
    assert "「4」" not in again.text  # never read back (QA 2026-10-26 #4)
    result = flow.answer("1、2、3")
    assert isinstance(result, Completed)
    assert result.profile.clinical_history == (tuple(TAX.red_flags())[1],)
    assert result.profile.contraindications == PROFILE_CONTRAINDICATIONS


def test_skipping_the_consent_skips_the_checklist(tmp_path):
    flow = _flow(tmp_path)
    _to_region(flow)
    result = _walk(flow, ["1", "跳过"])
    assert isinstance(result, Completed) and result.profile.contraindications == ()


@pytest.mark.parametrize("bad", ["SIT-99-99", "99", "0", "1, SIT-XX"])
def test_invalid_red_flag_code_rejected(tmp_path, bad):
    flow = _flow(tmp_path)
    _to_region(flow)
    _walk(flow, ["1", TEXT.consent_sentence])
    again = flow.answer(bad)
    assert isinstance(again, Prompt) and again.step is Step.CLINICAL_HISTORY
    assert again.text.startswith(TEXT.hints["clinical_unknown"])
    unknown = [t for t in bad.replace(",", " ").split() if t != "1"]
    assert not any(f"「{token}」" in again.text for token in unknown)  # QA 2026-10-26 #4
    assert "SIT" not in again.text
    assert _files(tmp_path) == []
    assert flow.answer("1").step is Step.CONTRAINDICATIONS
    result = flow.answer("")
    assert isinstance(result, Completed)
    assert result.profile.clinical_history == (next(iter(TAX.red_flags())),)


def test_clinical_options_are_plain_chinese_labels_without_codes():
    options = onb.clinical_options(TAX, TEXT)
    assert len(options) == len(TAX.red_flags())
    for option, code in zip(options, TAX.red_flags(), strict=True):
        assert option == TEXT.clinical_labels[code]
        assert code not in option and "SIT" not in option
        assert not any("a" <= ch.casefold() <= "z" for ch in option), option
        assert "(" not in option


def test_clinical_labels_must_cover_every_red_flag():
    broken = onb.OnboardingText(
        **{
            **TEXT.__dict__,
            "clinical_labels": {k: v for k, v in TEXT.clinical_labels.items() if k != "SIT-02-04"},
        }
    )
    with pytest.raises(OnboardingTextError, match="SIT-02-04"):
        onb.clinical_options(TAX, broken)
    with pytest.raises(OnboardingTextError, match="SIT-02-04"):
        OnboardingFlow(TAX, ProfileStore(Path("/nonexistent-olivia-test")), NOW, broken)


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
    answers = ["1", "1", encryption, "", "", "", "", "1", TEXT.consent_sentence, "1", "1，3"]
    result = _walk(flow, answers)
    assert isinstance(result, Completed) and result.profile.clinical_history == (code,)
    disclosed = (PROFILE_CONTRAINDICATIONS[0], "RED_FLAG_PSYCHOSIS")
    assert result.profile.contraindications == disclosed
    for raw in _profile_bytes(tmp_path):
        assert code.encode() not in raw and b"clinical_history" not in raw
        assert b"contraindications" not in raw and b"PSYCHOSIS" not in raw
        assert disclosed[0].encode() not in raw
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
    _walk(flow, ["1", "1", "2", "", "", "", "", "1", TEXT.consent_sentence, "1"])
    keychain.broken = KeychainUnavailableError("locked")
    result = flow.answer("1，2")
    assert isinstance(result, Completed)
    assert result.text.startswith(TEXT.outcomes["health_not_saved"])
    assert result.profile.clinical_history == ()
    assert result.profile.contraindications == ()
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
        TEXT.sensitive_notice,
        *TEXT.persona_labels.values(),
        *TEXT.prompts.values(),
        *TEXT.hints.values(),
        *TEXT.outcomes.values(),
        *TEXT.region_labels.values(),
        *(c.label for pair in TEXT.choices.values() for c in pair),
        *TEXT.disclosure_labels.values(),
        *TEXT.health.values(),
        *TEXT.profile.values(),
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
    del broken["persona_labels"]["SILENT_ANCHOR"]
    (tmp_path / "onboarding.yaml").write_text(yaml.safe_dump(broken), encoding="utf-8")
    with pytest.raises(OnboardingTextError, match="SILENT_ANCHOR"):
        load_onboarding_text(tmp_path)

    broken = json.loads(json.dumps(data))
    broken["persona_aliases"]["CHEERFUL"] = ["x"]
    (tmp_path / "onboarding.yaml").write_text(yaml.safe_dump(broken), encoding="utf-8")
    with pytest.raises(OnboardingTextError, match="CHEERFUL"):
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


# -- a wrong answer repeats only the question (dogfood P1, P2) ---------------------------------


def _reach(flow: OnboardingFlow, step: Step) -> Prompt:
    """Answer with the defaults until ``step`` is asked."""
    defaults = {
        Step.DISCLAIMER: "1",
        Step.AGE_GATE: "1",
        Step.REGION: "1",
        Step.CLINICAL_CONSENT: TEXT.consent_sentence,
        Step.CLINICAL_HISTORY: "",
    }
    prompt = flow.prompt()
    while flow.step is not step:
        result = flow.answer(defaults.get(flow.step, ""))
        assert isinstance(result, Prompt)
        prompt = result
    return prompt


@pytest.mark.parametrize(
    ("step", "wrong", "hint"),
    [
        (Step.DISCLAIMER, "嗯", "unrecognized"),
        (Step.AGE_GATE, "也许", "unrecognized"),
        (Step.ENCRYPTION, "随便", "unrecognized"),
        (Step.USER_NAME, "名" * 13, None),
        (Step.PERSONA, "开心果", "persona_choice"),
        (Step.REGION, "火星", "unrecognized"),
        (Step.CLINICAL_CONSENT, "好", "consent_unrecognized"),
        (Step.CLINICAL_HISTORY, "99", None),
        (Step.CONTRAINDICATIONS, "99", None),
    ],
)
def test_a_wrong_answer_repeats_only_the_question(tmp_path, step, wrong, hint):
    flow = _flow(tmp_path)
    first = _reach(flow, step)
    again = flow.answer(wrong)
    assert isinstance(again, Prompt) and again.step is step
    if hint is not None:
        assert again.text.startswith(TEXT.hints[hint])
    reprompt = onb.fill_slots(
        TEXT.reprompts[step.value], user_name="朋友", consent_sentence=TEXT.consent_sentence
    )
    assert again.text.endswith(reprompt)
    assert again.options == first.options  # the choices are still there to pick from
    # The long paragraphs are not printed again (probe.txt: the health notice, every time).
    assert TEXT.sensitive_notice not in again.text
    assert first.text.split("\n\n")[0] not in again.text


def test_the_consent_retry_still_shows_the_sentence_to_type(tmp_path):
    flow = _flow(tmp_path)
    _reach(flow, Step.CLINICAL_CONSENT)
    again = flow.answer("好")
    assert TEXT.consent_sentence in again.text
    assert isinstance(flow.answer(TEXT.consent_sentence), Prompt)
    assert flow.step is Step.CLINICAL_HISTORY


@pytest.mark.parametrize("reply", ["跳过", "不想说", ""])
def test_other_region_can_skip_the_timezone(tmp_path, monkeypatch, reply):
    """Dogfood P2: 「跳过」 was refused with a hint about numbers that were not shown."""
    monkeypatch.setattr(onb, "system_timezone", lambda: "Asia/Tokyo")
    flow = _flow(tmp_path)
    _to_region(flow)
    prompt = flow.answer("9")
    assert "跳过" in prompt.text
    result = _walk(flow, [reply, ""])
    assert isinstance(result, Completed)
    assert result.profile.region == UserRegion(country_code="ZZ", timezone="Asia/Tokyo")


def test_other_region_timezone_hint_matches_what_is_on_screen(tmp_path, monkeypatch):
    monkeypatch.setattr(onb, "system_timezone", lambda: "Asia/Tokyo")
    flow = _flow(tmp_path)
    _to_region(flow)
    flow.answer("9")
    again = flow.answer("Mars/Olympus")
    assert again.step is Step.TIMEZONE and again.options == ()
    hint = onb.fill_slots(TEXT.hints["timezone_free_invalid"], system_timezone="Asia/Tokyo")
    assert again.text.startswith(hint)
    assert "序号" not in again.text  # there are no numbers to pick here
    # Where numbers are shown, the hint may name them.
    us = _flow(tmp_path / "us")
    _to_region(us)
    us.answer("5")
    assert us.answer("Mars/Olympus").text.startswith(TEXT.hints["timezone_invalid"])


def test_an_unknown_health_reply_is_never_read_back(tmp_path):
    """QA 2026-10-26 #4: "真想睡过去不醒了" typed into the health list was echoed in the
    hint; whatever is not on the list is only said to be missing."""
    flow = _flow(tmp_path)
    _to_region(flow)
    _walk(flow, ["1", TEXT.consent_sentence])
    again = flow.answer("真想睡过去不醒了")
    assert isinstance(again, Prompt) and again.step is Step.CLINICAL_HISTORY
    assert "睡过去" not in again.text
    assert "没有在列表里找到你写的那一项" in again.text


def test_the_region_is_known_once_it_is_chosen(tmp_path):
    flow = _flow(tmp_path)
    assert flow.region is None
    _walk(flow, ["1", "1", "", "", "", "", ""])
    assert flow.step is Step.REGION and flow.region is None
    flow.answer("2")
    assert flow.region is not None and flow.region.country_code == "HK"
