from datetime import UTC, datetime
from uuid import uuid4

import pytest

from olivia.core.models import (
    PROFILE_CONTRAINDICATIONS,
    UNKNOWN_COUNTRY,
    ActionSkeleton,
    ActionType,
    CrisisLevel,
    HelpStage,
    PerceptionContext,
    PersonaProfile,
    PersonaSpectrum,
    SafetyGrade,
    SessionState,
    UserRegion,
)

NOW = datetime(2026, 10, 22, tzinfo=UTC)


def _profile(**kw):
    return PersonaProfile(age_confirmed_18_plus=True, created_at=NOW, updated_at=NOW, **kw)


def test_help_stage_has_seven_states():
    assert [s.value for s in HelpStage] == [
        "S_ready",
        "S_explore",
        "S_clarify",
        "S_empower",
        "S_haven",
        "S_closing",
        "S_crisis",
    ]


def test_crisis_level_is_ordered_for_max_arbitration():
    assert max(CrisisLevel.L1, CrisisLevel.L3, CrisisLevel.L2) is CrisisLevel.L3


def test_action_type_values():
    assert {a.value for a in ActionType} == {
        "MICRO_EXERCISE",
        "STABILIZATION",
        "COMPANIONSHIP",
        "PSYCHOEDUCATION",
        "REFERRAL",
    }


def test_safety_grade_and_persona_values():
    assert [g.value for g in SafetyGrade] == ["GRADE_A", "GRADE_B", "GRADE_C"]
    assert [p.value for p in PersonaSpectrum] == [
        "GENTLE_HOLDING",
        "ZEN_PHILOSOPHER",
        "RATIONAL_PEER",
        "SILENT_ANCHOR",
    ]


def test_profile_defaults():
    p = _profile()
    assert (p.user_name, p.agent_name, p.persona_spectrum) == (
        "朋友",
        "Olivia",
        PersonaSpectrum.GENTLE_HOLDING,
    )
    assert p.directiveness_preference == 0.5 and p.region is None


@pytest.mark.parametrize("name", ["", "一二三四五六七八九十一二三"])  # 0 字与 13 字
def test_profile_rejects_name_length_outside_1_to_12(name):
    with pytest.raises(ValueError):
        _profile(user_name=name)


def test_profile_rejects_blank_agent_name():
    with pytest.raises(ValueError):
        _profile(agent_name="   ")


def test_profile_requires_adult_confirmation():
    with pytest.raises(ValueError):
        PersonaProfile(age_confirmed_18_plus=False, created_at=NOW, updated_at=NOW)


def _refusal(**kw):
    return PersonaProfile(
        age_confirmed_18_plus=False, created_at=NOW, updated_at=NOW, age_gate_refused_at=NOW, **kw
    )


def test_age_gate_refusal_record_round_trips():
    import json

    p = _refusal()
    assert p.is_age_gate_refusal and not _profile().is_age_gate_refusal
    data = json.loads(json.dumps(p.to_dict()))
    assert data["age_gate_refused_at"] == NOW.isoformat()
    assert data["age_confirmed_18_plus"] is False
    assert PersonaProfile.from_dict(data) == p
    assert _profile().to_dict()["age_gate_refused_at"] is None


def test_profile_without_refusal_key_still_loads():
    data = dict(_profile().to_dict())
    del data["age_gate_refused_at"]
    assert PersonaProfile.from_dict(data) == _profile()


@pytest.mark.parametrize(
    "kw",
    [
        {"region": UserRegion(country_code="CN", timezone="Asia/Shanghai")},
        {"taboo_topics": ("考试",)},
        {"clinical_history": ("SIT-02-04",)},
        {"contraindications": ("CARDIORESPIRATORY_INSTABILITY",)},
    ],
)
def test_age_gate_refusal_record_holds_no_user_data(kw):
    with pytest.raises(ValueError):
        _refusal(**kw)


def test_age_gate_refusal_record_cannot_confirm_adult_and_must_be_aware():
    with pytest.raises(ValueError):
        PersonaProfile(
            age_confirmed_18_plus=True, created_at=NOW, updated_at=NOW, age_gate_refused_at=NOW
        )
    with pytest.raises(ValueError):
        PersonaProfile(
            age_confirmed_18_plus=False,
            created_at=NOW,
            updated_at=NOW,
            age_gate_refused_at=datetime(2026, 10, 22),
        )
    data = _refusal().to_dict() | {"age_gate_refused_at": "2026-10-22T00:00:00"}
    with pytest.raises(ValueError):
        PersonaProfile.from_dict(data)
    with pytest.raises(ValueError):
        PersonaProfile.from_dict(_refusal().to_dict() | {"age_gate_refused_at": 5})


def test_profile_rejects_naive_datetime():
    with pytest.raises(ValueError):
        PersonaProfile(age_confirmed_18_plus=True, created_at=datetime(2026, 1, 1), updated_at=NOW)


@pytest.mark.parametrize("value", [-0.01, 1.01])
def test_profile_rejects_directiveness_out_of_range(value):
    with pytest.raises(ValueError):
        _profile(directiveness_preference=value)


def test_profile_round_trip_with_region_and_chinese_text():
    p = _profile(
        user_name="小林",
        taboo_topics=("前夫", "体重"),
        clinical_history=("SIT-08-04",),
        region=UserRegion(
            country_code="CN",
            timezone="Asia/Shanghai",
            city_code="440300",
            city_display_name="深圳市",
        ),
    )
    data = p.to_dict()
    assert data["schema_version"] == 1
    assert PersonaProfile.from_dict(data) == p


def test_profile_to_dict_is_json_friendly():
    import json

    p = _profile(taboo_topics=("a",), region=UserRegion(country_code="CN", timezone="UTC"))
    data = p.to_dict()
    assert data["persona_spectrum"] == "GENTLE_HOLDING"
    assert data["taboo_topics"] == ["a"]
    assert data["created_at"] == NOW.isoformat()
    assert PersonaProfile.from_dict(json.loads(json.dumps(data))) == p


def test_profile_from_dict_rejects_unknown_schema_version():
    data = _profile().to_dict() | {"schema_version": 99}
    with pytest.raises(ValueError):
        PersonaProfile.from_dict(data)


def test_profile_from_dict_rejects_adult_flag_false():
    data = _profile().to_dict() | {"age_confirmed_18_plus": False}
    with pytest.raises(ValueError):
        PersonaProfile.from_dict(data)


@pytest.mark.parametrize(
    "key", ["age_confirmed_18_plus", "created_at", "updated_at", "schema_version"]
)
def test_profile_from_dict_rejects_missing_required_key(key):
    data = dict(_profile().to_dict())
    del data[key]
    with pytest.raises(ValueError):
        PersonaProfile.from_dict(data)


def test_profile_from_dict_rejects_unknown_persona():
    data = _profile().to_dict() | {"persona_spectrum": "NOPE"}
    with pytest.raises(ValueError):
        PersonaProfile.from_dict(data)


def test_profile_from_dict_rejects_naive_datetime_string():
    data = _profile().to_dict() | {"created_at": "2026-10-22T00:00:00"}
    with pytest.raises(ValueError):
        PersonaProfile.from_dict(data)


def test_profile_from_dict_rejects_unparseable_datetime_and_bad_types():
    base = _profile().to_dict()
    for override in (
        {"created_at": "not-a-date"},
        {"created_at": 123},
        {"user_name": 5},
        {"persona_spectrum": 7},
        {"taboo_topics": "abc"},
        {"directiveness_preference": "high"},
        {"region": "CN"},
        {"region": {"timezone": "UTC"}},
    ):
        with pytest.raises(ValueError):
            PersonaProfile.from_dict(base | override)


def test_region_validation():
    assert UserRegion(country_code=UNKNOWN_COUNTRY, timezone="UTC").country_code == "ZZ"
    for bad in ("cn", "CHN", ""):
        with pytest.raises(ValueError):
            UserRegion(country_code=bad, timezone="UTC")
    with pytest.raises(ValueError):
        UserRegion(country_code="CN", timezone="")


def test_session_state_defaults():
    s = SessionState(session_id=uuid4())
    assert s.current_stage is HelpStage.S_READY and s.social_battery == 0.6
    assert s.current_risk_level is CrisisLevel.L0 and s.user_shelved_actions == []
    assert s.stage_entry_arousal is None


def test_session_state_shelved_list_not_shared():
    a, b = SessionState(session_id=uuid4()), SessionState(session_id=uuid4())
    a.user_shelved_actions.append("x")
    assert b.user_shelved_actions == []


def _perception(**kw):
    base = dict(
        valence=0.0,
        arousal=0.5,
        fine_grained_emotion="anxiety",
        empathy_intent="EXPLORATION",
        risk_level=CrisisLevel.L0,
        crisis_confidence=0.0,
        communication_stance="CONGRUENT",
        readiness_to_change=0.5,
        distress_vector={},
        detected_distortions=(),
        detected_schemas=(),
        deep_yearning="SAFETY",
        somatic_stabilization_eligible=False,
    )
    return PerceptionContext(**(base | kw))


def test_perception_valid_baseline():
    assert _perception().risk_level is CrisisLevel.L0


@pytest.mark.parametrize(
    "field,value",
    [
        ("valence", -1.1),
        ("arousal", 1.2),
        ("crisis_confidence", -0.1),
        ("readiness_to_change", 2.0),
    ],
)
def test_perception_rejects_out_of_range(field, value):
    with pytest.raises(ValueError):
        _perception(**{field: value})


def test_perception_caps_schemas_at_three():
    with pytest.raises(ValueError):
        _perception(detected_schemas=("FAILURE", "DEFECTIVENESS", "PUNITIVENESS", "REST_GUILT"))


def _skeleton(**kw):
    base = dict(
        method_id="M-01",
        action_type=ActionType.MICRO_EXERCISE,
        safety_grade=SafetyGrade.GRADE_A,
        clinical_rationale="r",
        core_action_steps=("a", "b"),
        duration_minutes=3,
        stealth_workplace_compatible=True,
        contraindications=(),
    )
    return ActionSkeleton(**(base | kw))


def test_action_skeleton_allows_none_grade_for_redline_actions():
    assert _skeleton(safety_grade=None).safety_grade is None


def test_action_skeleton_rejects_bad_values():
    for bad in ({"method_id": ""}, {"duration_minutes": -1}):
        with pytest.raises(ValueError):
            _skeleton(**bad)


def test_profile_from_dict_huge_integer_is_a_value_error():
    data = _profile().to_dict()
    data["directiveness_preference"] = 10**400
    with pytest.raises(ValueError):
        PersonaProfile.from_dict(data)


def test_profile_contraindications_round_trip_and_default_to_none():
    p = _profile(contraindications=PROFILE_CONTRAINDICATIONS)
    assert PersonaProfile.from_dict(p.to_dict()) == p
    legacy = dict(_profile().to_dict())
    del legacy["contraindications"]
    assert PersonaProfile.from_dict(legacy).contraindications == ()


@pytest.mark.parametrize("bad", [("ACUTE_AROUSAL_OVERLOAD",), ("RED_FLAG_MANIA",), ("x",)])
def test_profile_records_only_the_disclosure_contraindications(bad):
    with pytest.raises(ValueError, match="contraindications"):
        _profile(contraindications=bad)
    with pytest.raises(ValueError, match="contraindications"):
        PersonaProfile.from_dict(_profile().to_dict() | {"contraindications": list(bad)})
