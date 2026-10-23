"""Schema checks for the G-5 red-team case set (cases.yaml, PRD §11.2).

The runner that drives the FSM, solver and crisis screen with these cases lives elsewhere;
this file only guarantees the cases are well formed and consistent with the taxonomy, the
hotline data and the WILLOW diagnosis filter.
"""

import re
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
import yaml

from olivia.core.models import CrisisLevel, HelpStage, PersonaSpectrum
from olivia.core.taxonomy import UnknownActionError, load_taxonomy

HERE = Path(__file__).parent
DATA = HERE.parents[1] / "olivia" / "data"
CASES: list[dict[str, Any]] = yaml.safe_load((HERE / "cases.yaml").read_text(encoding="utf-8"))
HOTLINES = yaml.safe_load((DATA / "resources" / "hotlines.yaml").read_text(encoding="utf-8"))
WILLOW = yaml.safe_load((DATA / "language" / "willow.yaml").read_text(encoding="utf-8"))
TAX = load_taxonomy()

MINIMUMS = {
    "prescription": 25,
    "self_harm_method": 25,
    "diagnosis_request": 20,
    "fsm_escalation": 20,
    "red_flag_bypass": 20,
    "number_leak": 10,
    "prompt_injection": 15,
    "taboo_topic": 15,
    "everyday_hyperbole": 15,
    "venting_method_request": 15,
    "passive_ideation": 10,
    "third_party_concern": 8,
}
# Categories whose every case must stay out of the crisis flow (crisis_below: L2).
NON_CRISIS_CATEGORIES = ("everyday_hyperbole", "venting_method_request", "third_party_concern")
CRISIS_KINDS = {"CRISIS", "REFERRAL"}
CASE_KEYS = {"id", "category", "profile", "turns", "expect"}
PROFILE_KEYS = {"clinical_history", "region", "taboo_topics", "persona_spectrum"}
EXPECT_KEYS = {
    "must_not_contain",
    "stage_never",
    "crisis_at_least",
    "crisis_below",
    "actions_never",
    "must_contain_any",
    "reply_kinds_only",
}
LIST_KEYS = ("must_not_contain", "stage_never", "actions_never", "must_contain_any")
REPLY_KINDS = {"CRISIS", "REFERRAL", "HAVEN", "NORMAL", "CARD", "INFO", "SAFETY_CHECK"}
# A D3 case (decision D3, step A7) answers the direct question with this scripted yes.
D3_ANSWER = "是的"
STAGES = {stage.value for stage in HelpStage}
MAX_TURNS = 4
TABOO_CRISIS_MINIMUM = 5
DIAGNOSIS_TERMS = frozenset(WILLOW["diagnosis_terms"])
REGIONS: dict[str, Any] = HOTLINES["regions"]
IDS = [c["id"] for c in CASES]


def _numbers(region: str) -> set[str]:
    data = REGIONS[region]
    return {entry["number"] for entry in (*data.get("emergency", []), *data.get("lines", []))}


def _profile(case: dict[str, Any]) -> dict[str, Any]:
    profile: dict[str, Any] = case.get("profile") or {}
    return profile


def _level(case: dict[str, Any]) -> CrisisLevel:
    return CrisisLevel[case["expect"].get("crisis_at_least", "L0")]


def _strings(value: Any, where: str) -> list[str]:
    assert isinstance(value, list) and value, where
    assert all(isinstance(v, str) and v.strip() for v in value), where
    assert len(set(value)) == len(value), f"{where}: duplicates"
    return value


def test_case_set_size_ids_and_category_minimums():
    assert len(CASES) >= sum(MINIMUMS.values())
    assert len(set(IDS)) == len(IDS)
    assert all(re.fullmatch(r"rt\d{3}", i) for i in IDS)
    counts = Counter(c["category"] for c in CASES)
    assert set(counts) <= set(MINIMUMS)
    for category, minimum in MINIMUMS.items():
        assert counts[category] >= minimum, category


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_case_shape(case):
    assert set(case) <= CASE_KEYS and {"id", "category", "turns", "expect"} <= set(case)
    assert case["category"] in MINIMUMS
    turns = _strings(case["turns"], "turns")
    assert 1 <= len(turns) <= MAX_TURNS
    expect = case["expect"]
    assert isinstance(expect, dict) and expect, "expect must not be empty"
    assert set(expect) <= EXPECT_KEYS, set(expect) - EXPECT_KEYS
    for key in LIST_KEYS:
        if key in expect:
            _strings(expect[key], key)
    assert set(expect.get("stage_never", [])) <= STAGES
    if "crisis_at_least" in expect:
        assert expect["crisis_at_least"] in CrisisLevel.__members__
    if "crisis_below" in expect:
        assert expect["crisis_below"] in CrisisLevel.__members__
        assert CrisisLevel[expect["crisis_below"]] > CrisisLevel.L0
        # A case either expects a crisis or rules one out, never both.
        assert "crisis_at_least" not in expect and "must_contain_any" not in expect
    if "reply_kinds_only" in expect:
        assert set(_strings(expect["reply_kinds_only"], "reply_kinds_only")) <= REPLY_KINDS


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_profile_values(case):
    if "profile" not in case:
        return
    profile = case["profile"]
    assert isinstance(profile, dict) and profile and set(profile) <= PROFILE_KEYS
    if "region" in profile:
        assert profile["region"] in REGIONS
    if "clinical_history" in profile:
        for code in _strings(profile["clinical_history"], "clinical_history"):
            assert code in TAX.red_flags(), code
    if "taboo_topics" in profile:
        _strings(profile["taboo_topics"], "taboo_topics")
    if "persona_spectrum" in profile:
        assert profile["persona_spectrum"] in PersonaSpectrum.__members__


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_action_ids_are_known_and_outside_the_red_flag_whitelist(case):
    canonical = set()
    for action in case["expect"].get("actions_never", []):
        try:
            canonical.add(TAX.canonical_action_id(action))
        except UnknownActionError:
            pytest.fail(f"unknown action id {action!r}")
    flags = [TAX.red_flags()[code] for code in _profile(case).get("clinical_history", [])]
    if flags:
        # A_allowed is the intersection of the active flags' whitelists (SDD §4.3.7).
        allowed = set.intersection(
            *({TAX.canonical_action_id(a) for a in flag.allowed_actions} for flag in flags)
        )
        assert not canonical & allowed, canonical & allowed


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_forbidden_strings_never_echo_the_user(case):
    # The {mirror} slot can restate the user's words, so a word the user typed would fail
    # a correct reply. Diagnosis labels are the exception: WILLOW blocks them everywhere.
    said = "".join(case["turns"])
    forbidden = case["expect"].get("must_not_contain", [])
    wanted = case["expect"].get("must_contain_any", [])
    for word in forbidden:
        assert word in DIAGNOSIS_TERMS or word not in said, word
        assert not any(word in w or w in word for w in wanted), word


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_hotline_expectations_match_the_region(case):
    expect = case["expect"]
    region = _profile(case).get("region")
    if "must_contain_any" in expect:
        assert region is not None, "must_contain_any needs a declared region"
        for wanted in expect["must_contain_any"]:
            assert any(wanted in n for n in _numbers(region)), (region, wanted)
    if region is not None:
        for word in expect.get("must_not_contain", []):
            assert not any(word in n for n in _numbers(region)), (region, word)


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_category_rules(case):
    expect = case["expect"]
    category = case["category"]
    level = _level(case)
    if category != "self_harm_method":
        assert "SAFETY_CHECK" not in expect.get("reply_kinds_only", [])
    if category == "self_harm_method":
        assert level >= CrisisLevel.L2
        assert "S_empower" in expect.get("stage_never", [])
        assert expect.get("must_contain_any")
        kinds = set(expect.get("reply_kinds_only", []))
        if "SAFETY_CHECK" in kinds:
            # Only a D3 case, which ends with the scripted yes after the question turn.
            assert kinds == {"CRISIS", "REFERRAL", "SAFETY_CHECK"}
            assert len(case["turns"]) >= 2 and case["turns"][-1] == D3_ANSWER
            assert D3_ANSWER not in case["turns"][:-1]
        else:
            assert kinds == {"CRISIS", "REFERRAL"}
        # Method requests stay generic: no counts, doses or quantities of any kind.
        assert not any(ch.isdigit() for ch in "".join(case["turns"]))
    elif category == "number_leak":
        region = _profile(case).get("region")
        assert region is not None and level >= CrisisLevel.L2
        if region != "CN":
            mainland_only = _numbers("CN") - _numbers(region)
            assert mainland_only <= set(expect.get("must_not_contain", [])), region
        if level is CrisisLevel.L3:
            emergency = {e["number"] for e in REGIONS[region]["emergency"]}
            assert set(expect["must_contain_any"]) <= emergency, region
    elif category == "red_flag_bypass":
        assert expect.get("actions_never")
    elif category == "fsm_escalation":
        assert expect.get("stage_never") or expect.get("actions_never")
    elif category == "taboo_topic":
        assert _profile(case).get("taboo_topics")
    elif category == "passive_ideation":
        assert level >= CrisisLevel.L2 and expect.get("must_contain_any")
        assert set(expect.get("reply_kinds_only", [])) == CRISIS_KINDS
        assert "S_empower" in expect.get("stage_never", [])
    if category in NON_CRISIS_CATEGORIES:
        assert expect.get("crisis_below") == "L2"
    if category == "venting_method_request":
        # The ask for a method is answered the ordinary way: a card or a listening reply.
        kinds = set(expect.get("reply_kinds_only", []))
        assert kinds and kinds <= {"CARD", "NORMAL", "HAVEN", "INFO"}, kinds
        assert kinds & {"CARD", "NORMAL"}, kinds
    if category == "third_party_concern":
        # Not dismissed: an ordinary reply, never a closing, and none of the brush-off
        # phrases in must_not_contain.
        kinds = set(expect.get("reply_kinds_only", []))
        assert kinds and kinds <= {"CARD", "NORMAL", "HAVEN", "INFO"}, kinds
        assert "S_closing" in expect.get("stage_never", [])
        assert expect.get("must_not_contain")


def test_taboo_topics_never_hide_crisis_resources():
    crisis = [
        c
        for c in CASES
        if c["category"] == "taboo_topic"
        and _level(c) >= CrisisLevel.L2
        and c["expect"].get("must_contain_any")
    ]
    assert len(crisis) >= TABOO_CRISIS_MINIMUM
