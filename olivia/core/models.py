"""Domain enums and data contracts (SDD section 2)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum, StrEnum
from typing import Final
from uuid import UUID

UNKNOWN_COUNTRY: Final = "ZZ"
PROFILE_SCHEMA_VERSION: Final = 1

_COUNTRY_RE: Final = re.compile(r"[A-Z]{2}")
NAME_MAX_LEN: Final = 12
_MAX_SCHEMAS: Final = 3


class CrisisLevel(IntEnum):
    L0 = 0
    L1 = 1
    L2 = 2
    L3 = 3


class HelpStage(StrEnum):
    S_READY = "S_ready"
    S_EXPLORE = "S_explore"
    S_CLARIFY = "S_clarify"
    S_EMPOWER = "S_empower"
    S_HAVEN = "S_haven"
    S_CLOSING = "S_closing"
    S_CRISIS = "S_crisis"


class PersonaSpectrum(StrEnum):
    GENTLE_HOLDING = "GENTLE_HOLDING"
    ZEN_PHILOSOPHER = "ZEN_PHILOSOPHER"
    RATIONAL_PEER = "RATIONAL_PEER"
    SILENT_ANCHOR = "SILENT_ANCHOR"


class SafetyGrade(StrEnum):
    GRADE_A = "GRADE_A"
    GRADE_B = "GRADE_B"
    GRADE_C = "GRADE_C"


class ActionType(StrEnum):
    MICRO_EXERCISE = "MICRO_EXERCISE"
    STABILIZATION = "STABILIZATION"
    COMPANIONSHIP = "COMPANIONSHIP"
    PSYCHOEDUCATION = "PSYCHOEDUCATION"
    REFERRAL = "REFERRAL"


def _check_range(name: str, value: float, low: float = 0.0) -> None:
    if not low <= value <= 1.0:
        raise ValueError(f"{name} must be within [{low}, 1.0], got {value}")


@dataclass(frozen=True)
class UserRegion:
    country_code: str
    timezone: str
    province_code: str | None = None
    city_code: str | None = None
    city_display_name: str | None = None

    def __post_init__(self) -> None:
        if not _COUNTRY_RE.fullmatch(self.country_code):
            raise ValueError(f"country_code must be two uppercase letters: {self.country_code!r}")
        if not self.timezone:
            raise ValueError("timezone must not be empty")

    def to_dict(self) -> dict[str, object]:
        return {
            "country_code": self.country_code,
            "timezone": self.timezone,
            "province_code": self.province_code,
            "city_code": self.city_code,
            "city_display_name": self.city_display_name,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> UserRegion:
        return cls(
            country_code=_req_str(data, "country_code"),
            timezone=_req_str(data, "timezone"),
            province_code=_opt_str(data, "province_code"),
            city_code=_opt_str(data, "city_code"),
            city_display_name=_opt_str(data, "city_display_name"),
        )


@dataclass(frozen=True)
class PersonaProfile:
    age_confirmed_18_plus: bool
    created_at: datetime
    updated_at: datetime
    user_name: str = "朋友"
    agent_name: str = "Olivia"
    persona_spectrum: PersonaSpectrum = PersonaSpectrum.GENTLE_HOLDING
    directiveness_preference: float = 0.5
    taboo_topics: tuple[str, ...] = ()
    region: UserRegion | None = None
    clinical_history: tuple[str, ...] = ()
    enable_at_rest_encryption: bool = False
    age_gate_refused_at: datetime | None = None
    """Set only on the refusal record a declared minor leaves behind (NG-3, ruling 22).

    Such a record has ``age_confirmed_18_plus=False`` and holds nothing collected from
    the user: no region, taboo topics or clinical history. Every other profile is an
    adult's and has ``age_confirmed_18_plus=True``.
    """

    def __post_init__(self) -> None:
        for label, name in (("user_name", self.user_name), ("agent_name", self.agent_name)):
            if not 1 <= len(name.strip()) <= NAME_MAX_LEN:
                raise ValueError(f"{label} must be 1-{NAME_MAX_LEN} characters after trimming")
        stamps = [("created_at", self.created_at), ("updated_at", self.updated_at)]
        if self.age_gate_refused_at is None:
            if self.age_confirmed_18_plus is not True:
                raise ValueError("age_confirmed_18_plus must be True")
        else:
            if self.age_confirmed_18_plus is not False:
                raise ValueError("an age-gate refusal record cannot confirm 18+")
            if self.region is not None or self.taboo_topics or self.clinical_history:
                raise ValueError("an age-gate refusal record must not hold user data")
            stamps.append(("age_gate_refused_at", self.age_gate_refused_at))
        for label, ts in stamps:
            if ts.tzinfo is None:
                raise ValueError(f"{label} must be timezone-aware")
        _check_range("directiveness_preference", self.directiveness_preference)

    @property
    def is_age_gate_refusal(self) -> bool:
        """True for a minor's refusal record, which must block onboarding and any session."""
        return self.age_gate_refused_at is not None

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": PROFILE_SCHEMA_VERSION,
            "age_confirmed_18_plus": self.age_confirmed_18_plus,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "user_name": self.user_name,
            "agent_name": self.agent_name,
            "persona_spectrum": self.persona_spectrum.value,
            "directiveness_preference": self.directiveness_preference,
            "taboo_topics": list(self.taboo_topics),
            "region": self.region.to_dict() if self.region is not None else None,
            "clinical_history": list(self.clinical_history),
            "enable_at_rest_encryption": self.enable_at_rest_encryption,
            "age_gate_refused_at": (
                self.age_gate_refused_at.isoformat() if self.age_gate_refused_at else None
            ),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> PersonaProfile:
        """Rebuild a profile; every malformed or invalid input raises ``ValueError``."""
        version = _require(data, "schema_version")
        if isinstance(version, bool) or version != PROFILE_SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version: {version!r}")
        adult = _require(data, "age_confirmed_18_plus")
        if not isinstance(adult, bool):
            raise ValueError("age_confirmed_18_plus must be a bool")
        region_raw = data.get("region")
        if region_raw is not None and not isinstance(region_raw, Mapping):
            raise ValueError("region must be a mapping or null")
        spectrum_raw = data.get("persona_spectrum", PersonaSpectrum.GENTLE_HOLDING.value)
        if not isinstance(spectrum_raw, str):
            raise ValueError("persona_spectrum must be a string")
        try:
            spectrum = PersonaSpectrum(spectrum_raw)
        except ValueError as exc:
            raise ValueError(f"unknown persona_spectrum: {spectrum_raw!r}") from exc
        return cls(
            age_confirmed_18_plus=adult,
            created_at=_aware_datetime(data, "created_at"),
            updated_at=_aware_datetime(data, "updated_at"),
            user_name=_str_or(data, "user_name", "朋友"),
            agent_name=_str_or(data, "agent_name", "Olivia"),
            persona_spectrum=spectrum,
            directiveness_preference=_number_or(data, "directiveness_preference", 0.5),
            taboo_topics=_str_tuple(data, "taboo_topics"),
            region=UserRegion.from_dict(region_raw) if region_raw is not None else None,
            clinical_history=_str_tuple(data, "clinical_history"),
            enable_at_rest_encryption=_bool_or(data, "enable_at_rest_encryption", False),
            age_gate_refused_at=(
                _aware_datetime(data, "age_gate_refused_at")
                if data.get("age_gate_refused_at") is not None
                else None
            ),
        )


@dataclass
class SessionState:
    session_id: UUID
    current_stage: HelpStage = HelpStage.S_READY
    global_turn_count: int = 0
    stage_turn_count: int = 0
    pure_listening_locked: bool = False
    social_battery: float = 0.6
    current_risk_level: CrisisLevel = CrisisLevel.L0
    consecutive_l1_count: int = 0
    """Mirror of ``CrisisTracker.consecutive_l1_count``, copied in by ``fsm.step`` each turn."""
    user_shelved_actions: list[str] = field(default_factory=list)
    stage_entry_arousal: float | None = None
    """Arousal on the turn that entered the current stage: the ΔArousal baseline (SDD 4.2)."""


@dataclass(frozen=True)
class PerceptionContext:
    valence: float
    arousal: float
    fine_grained_emotion: str
    empathy_intent: str
    risk_level: CrisisLevel
    crisis_confidence: float
    communication_stance: str
    readiness_to_change: float
    distress_vector: Mapping[str, float]
    detected_distortions: tuple[str, ...]
    detected_schemas: tuple[str, ...]
    deep_yearning: str
    somatic_stabilization_eligible: bool

    def __post_init__(self) -> None:
        _check_range("valence", self.valence, low=-1.0)
        _check_range("arousal", self.arousal)
        _check_range("crisis_confidence", self.crisis_confidence)
        _check_range("readiness_to_change", self.readiness_to_change)
        if len(self.detected_schemas) > _MAX_SCHEMAS:
            raise ValueError(f"detected_schemas holds at most {_MAX_SCHEMAS} items")


@dataclass(frozen=True)
class ActionSkeleton:
    method_id: str
    action_type: ActionType
    safety_grade: SafetyGrade | None
    clinical_rationale: str
    core_action_steps: tuple[str, ...]
    duration_minutes: int
    stealth_workplace_compatible: bool
    contraindications: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.method_id:
            raise ValueError("method_id must not be empty")
        if self.duration_minutes < 0:
            raise ValueError("duration_minutes must not be negative")


def _require(data: Mapping[str, object], key: str) -> object:
    if key not in data:
        raise ValueError(f"missing required key: {key}")
    return data[key]


def _req_str(data: Mapping[str, object], key: str) -> str:
    value = _require(data, key)
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value


def _opt_str(data: Mapping[str, object], key: str) -> str | None:
    value = data.get(key)
    if value is not None and not isinstance(value, str):
        raise ValueError(f"{key} must be a string or null")
    return value


def _str_or(data: Mapping[str, object], key: str, default: str) -> str:
    return _req_str(data, key) if key in data else default


def _bool_or(data: Mapping[str, object], key: str, default: bool) -> bool:
    if key not in data:
        return default
    value = data[key]
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a bool")
    return value


def _number_or(data: Mapping[str, object], key: str, default: float) -> float:
    if key not in data:
        return default
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{key} must be a number")
    try:
        return float(value)
    except OverflowError as exc:  # an int too large for a float
        raise ValueError(f"{key} is out of range") from exc


def _str_tuple(data: Mapping[str, object], key: str) -> tuple[str, ...]:
    value = data.get(key, [])
    if not isinstance(value, list | tuple) or not all(isinstance(v, str) for v in value):
        raise ValueError(f"{key} must be a list of strings")
    return tuple(value)


def _aware_datetime(data: Mapping[str, object], key: str) -> datetime:
    raw = _require(data, key)
    if not isinstance(raw, str):
        raise ValueError(f"{key} must be an ISO-8601 string")
    parsed = datetime.fromisoformat(raw)  # raises ValueError when unparseable
    if parsed.tzinfo is None:
        raise ValueError(f"{key} must be timezone-aware")
    return parsed
