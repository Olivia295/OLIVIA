"""First-visit onboarding (PRD ONB-01..05, 07, 08; SOP 1; roadmap rulings 22-24).

The flow is pure logic over a :class:`ProfileStore`: the caller shows ``prompt()``,
passes the user's reply to ``answer()``, and repeats until it gets :class:`Completed`
or :class:`Refused`. All wording lives in ``olivia/data/templates/onboarding.yaml``.

Order: disclaimer (explicit acceptance) -> 18+ gate -> both names -> persona (R1 offers
only ``GENTLE_HOLDING``, decision Q8) -> taboo topics -> region -> timezone -> optional
clinical-history consent (last, ruling 23) -> one atomic save (ONB-08). The age gate
comes before anything personal is asked, so nothing is ever collected from a minor
(ruling 22). Nothing touches disk until the end: an adult's answers are saved once, as
a complete profile; a declared minor leaves a refusal record (no user data) so a later
launch shows the refusal again instead of restarting; a declined disclaimer saves nothing.
ONB-06 (at-rest encryption) is P5 and is not asked here.
"""

from __future__ import annotations

import re
import unicodedata
import zoneinfo
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

import yaml

from olivia.core.chang.profile import ProfileStore
from olivia.core.models import (
    NAME_MAX_LEN,
    UNKNOWN_COUNTRY,
    PersonaProfile,
    PersonaSpectrum,
    UserRegion,
)
from olivia.core.taxonomy import RedFlag, Taxonomy

DEFAULT_USER_NAME: Final = "朋友"
DEFAULT_AGENT_NAME: Final = "Olivia"
FALLBACK_TIMEZONE: Final = "UTC"
R1_PERSONA: Final = PersonaSpectrum.GENTLE_HOLDING

# The region codes with a section in olivia/data/resources/hotlines.yaml, in display order.
SUPPORTED_REGIONS: Final = ("CN", "HK", "MO", "TW", "US", "CA", "GB", "AU", UNKNOWN_COUNTRY)
DEFAULT_TIMEZONES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "CN": "Asia/Shanghai",
        "HK": "Asia/Hong_Kong",
        "MO": "Asia/Macau",
        "TW": "Asia/Taipei",
        "GB": "Europe/London",
    }
)
TIMEZONE_CHOICES: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        "US": (
            "America/New_York",
            "America/Chicago",
            "America/Denver",
            "America/Phoenix",
            "America/Los_Angeles",
            "America/Anchorage",
            "Pacific/Honolulu",
        ),
        "CA": (
            "America/St_Johns",
            "America/Halifax",
            "America/Toronto",
            "America/Winnipeg",
            "America/Regina",
            "America/Edmonton",
            "America/Vancouver",
        ),
        "AU": (
            "Australia/Sydney",
            "Australia/Melbourne",
            "Australia/Brisbane",
            "Australia/Adelaide",
            "Australia/Darwin",
            "Australia/Perth",
            "Australia/Hobart",
        ),
        UNKNOWN_COUNTRY: (FALLBACK_TIMEZONE,),
    }
)
TABOO_MAX_TOPICS: Final = 20
TABOO_MAX_LEN: Final = 20

_TEXT_FILE: Final = "onboarding.yaml"
_LIST_SPLIT: Final = re.compile(r"[,，、;；/\s]+")
_SQUASH: Final = re.compile(r"[\s。.]+")
# Strict "Area/City[/Sub]" names, used only where the platform ships no tz database.
_IANA_AREAS: Final = (
    "Africa",
    "America",
    "Antarctica",
    "Arctic",
    "Asia",
    "Atlantic",
    "Australia",
    "Europe",
    "Indian",
    "Pacific",
)
_IANA_NAME: Final = re.compile(
    rf"(?:{'|'.join(_IANA_AREAS)})/[A-Z][A-Za-z_\-]*[a-z](?:/[A-Z][A-Za-z_\-]*[a-z])?"
)

_PROMPT_KEYS: Final = (
    "disclaimer",
    "age_gate",
    "user_name",
    "agent_name",
    "persona",
    "taboo",
    "region",
    "timezone_choice",
    "timezone_free",
    "clinical_consent",
    "clinical_history",
)
_HINT_KEYS: Final = (
    "unrecognized",
    "name_length",
    "name_unprintable",
    "persona_only",
    "taboo_limits",
    "timezone_invalid",
    "consent_unrecognized",
    "clinical_unknown",
)
_OUTCOME_KEYS: Final = ("completed", "disclaimer_declined", "under_18")
_SLOTS: Final = frozenset(
    {"user_name", "agent_name", "max_len", "max_count", "consent_sentence", "tokens"}
)
_SLOT: Final = re.compile(r"\{([^{}]*)\}")


class OnboardingTextError(Exception):
    """``onboarding.yaml`` is missing, malformed, or incomplete."""


class OnboardingFinishedError(RuntimeError):
    """``prompt`` or ``answer`` was called after the flow reached its outcome."""


class Step(StrEnum):
    DISCLAIMER = "disclaimer"
    AGE_GATE = "age_gate"
    USER_NAME = "user_name"
    AGENT_NAME = "agent_name"
    PERSONA = "persona"
    TABOO = "taboo"
    REGION = "region"
    TIMEZONE = "timezone"
    CLINICAL_CONSENT = "clinical_consent"
    CLINICAL_HISTORY = "clinical_history"


class RefusalReason(StrEnum):
    DISCLAIMER_DECLINED = "disclaimer_declined"
    UNDER_18 = "under_18"


@dataclass(frozen=True)
class Prompt:
    """What to show next; ``options`` are numbered from 1 by the caller."""

    step: Step
    text: str
    options: tuple[str, ...] = ()


@dataclass(frozen=True)
class Completed:
    """Onboarding is done; ``text`` is empty when the profile already existed."""

    profile: PersonaProfile
    text: str


@dataclass(frozen=True)
class Refused:
    reason: RefusalReason
    text: str


@dataclass(frozen=True)
class Choice:
    label: str
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class OnboardingText:
    consent_sentence: str
    prompts: Mapping[str, str]
    choices: Mapping[str, tuple[Choice, Choice]]
    """``disclaimer`` and ``age_gate`` as ``(accept, decline)``."""
    persona_label: str
    region_labels: Mapping[str, str]
    region_aliases: Mapping[str, tuple[str, ...]]
    timezone_labels: Mapping[str, str]
    skip_words: frozenset[str]
    hints: Mapping[str, str]
    outcomes: Mapping[str, str]


def load_onboarding_text(directory: Path | None = None) -> OnboardingText:
    """Load and validate ``onboarding.yaml``; ``None`` reads the packaged copy."""
    base: Traversable | Path = (
        resources.files("olivia").joinpath("data/templates") if directory is None else directory
    )
    try:
        doc = yaml.safe_load(base.joinpath(_TEXT_FILE).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise OnboardingTextError(f"{_TEXT_FILE}: cannot read: {exc}") from exc
    if not isinstance(doc, dict) or doc.get("version") != 1:
        raise OnboardingTextError(f"{_TEXT_FILE}: must be a mapping with version 1")

    prompts = _str_map(doc, "prompts", _PROMPT_KEYS)
    hints = _str_map(doc, "hints", _HINT_KEYS)
    outcomes = _str_map(doc, "outcomes", _OUTCOME_KEYS)
    region_labels = _str_map(doc, "region_labels", SUPPORTED_REGIONS)
    zones = {zone for zones in TIMEZONE_CHOICES.values() for zone in zones}
    timezone_labels = _str_map(doc, "timezone_labels", tuple(sorted(zones)))
    aliases_raw = _section(doc, "region_aliases")
    unknown = sorted(str(code) for code in aliases_raw if code not in SUPPORTED_REGIONS)
    if unknown:
        raise OnboardingTextError(f"{_TEXT_FILE}: region_aliases has unknown codes {unknown}")
    region_aliases = {
        code: _str_list(aliases_raw.get(code, []), f"region_aliases.{code}")
        for code in SUPPORTED_REGIONS
    }
    choices_raw = _section(doc, "choices")
    choices = {
        step: (
            _choice(_section(choices_raw, step), "accept", f"choices.{step}"),
            _choice(_section(choices_raw, step), "decline", f"choices.{step}"),
        )
        for step in ("disclaimer", "age_gate")
    }
    for where, texts in (("prompts", prompts), ("hints", hints), ("outcomes", outcomes)):
        for key, value in texts.items():
            bad = sorted(set(_SLOT.findall(value)) - _SLOTS)
            if bad:
                raise OnboardingTextError(f"{_TEXT_FILE}: {where}.{key} uses unknown slots {bad}")
    return OnboardingText(
        consent_sentence=_nonempty_str(doc.get("consent_sentence"), "consent_sentence"),
        prompts=MappingProxyType(prompts),
        choices=MappingProxyType(choices),
        persona_label=_nonempty_str(doc.get("persona_label"), "persona_label"),
        region_labels=MappingProxyType(region_labels),
        region_aliases=MappingProxyType(region_aliases),
        timezone_labels=MappingProxyType(timezone_labels),
        skip_words=frozenset(_str_list(doc.get("skip_words"), "skip_words")),
        hints=MappingProxyType(hints),
        outcomes=MappingProxyType(outcomes),
    )


def canonical_timezone(raw: str) -> str | None:
    """The ``Area/City`` IANA name ``raw`` denotes (or ``UTC``), else None.

    Checked against the platform's tz database, case-insensitively; legacy aliases
    such as ``PRC`` or ``US/Eastern`` are refused. Where no database is installed
    (some Windows machines without ``tzdata``) only exact, strict ``Area/City`` names pass.
    """
    name = raw.strip()
    if name.upper() == FALLBACK_TIMEZONE:
        return FALLBACK_TIMEZONE
    available = zoneinfo.available_timezones()
    if not available:
        return name if _IANA_NAME.fullmatch(name) else None
    folded = {zone.casefold(): zone for zone in available}
    canonical = folded.get(name.casefold())
    if canonical is None or canonical.split("/", 1)[0] not in _IANA_AREAS:
        return None
    return canonical


class OnboardingFlow:
    """One first-visit conversation; see the module docstring for the order and rules.

    Construction reads the store: if a profile already exists the flow starts finished
    (:class:`Completed` for an adult, :class:`Refused` for a minor's refusal record), so
    onboarding never restarts over saved data. ``ProfileCorruptError`` propagates.
    """

    def __init__(
        self,
        tax: Taxonomy,
        store: ProfileStore,
        now: datetime,
        text: OnboardingText | None = None,
    ) -> None:
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        self._store = store
        self._now = now
        self._text = load_onboarding_text() if text is None else text
        self._red_flags: tuple[RedFlag, ...] = tuple(tax.red_flags().values())
        self._step = Step.DISCLAIMER
        self._hint = ""
        self._user_name = DEFAULT_USER_NAME
        self._agent_name = DEFAULT_AGENT_NAME
        self._taboo: tuple[str, ...] = ()
        self._country = UNKNOWN_COUNTRY
        self._timezone = FALLBACK_TIMEZONE
        self._outcome: Completed | Refused | None = None
        existing = store.load()
        if existing is not None:
            self._outcome = (
                self._refusal(RefusalReason.UNDER_18)
                if existing.is_age_gate_refusal
                else Completed(existing, "")
            )

    @property
    def outcome(self) -> Completed | Refused | None:
        """None while the conversation is still going."""
        return self._outcome

    @property
    def step(self) -> Step:
        return self._step

    def prompt(self) -> Prompt:
        self._ensure_running()
        body, options = self._question()
        text = f"{self._hint}\n\n{body}" if self._hint else body
        return Prompt(self._step, text, options)

    def answer(self, text: str) -> Prompt | Completed | Refused:
        self._ensure_running()
        self._hint = ""
        handler = {
            Step.DISCLAIMER: self._on_disclaimer,
            Step.AGE_GATE: self._on_age_gate,
            Step.USER_NAME: self._on_user_name,
            Step.AGENT_NAME: self._on_agent_name,
            Step.PERSONA: self._on_persona,
            Step.TABOO: self._on_taboo,
            Step.REGION: self._on_region,
            Step.TIMEZONE: self._on_timezone,
            Step.CLINICAL_CONSENT: self._on_clinical_consent,
            Step.CLINICAL_HISTORY: self._on_clinical_history,
        }[self._step]
        handler(text)
        return self._outcome if self._outcome is not None else self.prompt()

    # -- questions -------------------------------------------------------------------

    def _question(self) -> tuple[str, tuple[str, ...]]:
        prompts = self._text.prompts
        match self._step:
            case Step.DISCLAIMER | Step.AGE_GATE:
                accept, decline = self._text.choices[self._step.value]
                return prompts[self._step.value], (accept.label, decline.label)
            case Step.AGENT_NAME:
                return self._render(prompts["agent_name"]), ()
            case Step.PERSONA:
                return prompts["persona"], (self._text.persona_label,)
            case Step.REGION:
                labels = self._text.region_labels
                return prompts["region"], tuple(labels[code] for code in SUPPORTED_REGIONS)
            case Step.TIMEZONE:
                if self._country == UNKNOWN_COUNTRY:
                    return prompts["timezone_free"], ()
                return prompts["timezone_choice"], tuple(
                    f"{self._text.timezone_labels[zone]} {zone}"
                    for zone in TIMEZONE_CHOICES[self._country]
                )
            case Step.CLINICAL_CONSENT:
                return self._render(prompts["clinical_consent"]), ()
            case Step.CLINICAL_HISTORY:
                return prompts["clinical_history"], tuple(
                    f"{flag.code} {flag.name_zh}" for flag in self._red_flags
                )
            case _:
                return prompts[self._step.value], ()

    # -- answers ---------------------------------------------------------------------

    def _on_disclaimer(self, text: str) -> None:
        accepted = self._binary_choice(text)
        if accepted is True:
            self._step = Step.AGE_GATE
        elif accepted is False:
            self._outcome = self._refusal(RefusalReason.DISCLAIMER_DECLINED)

    def _on_age_gate(self, text: str) -> None:
        adult = self._binary_choice(text)
        if adult is True:
            self._step = Step.USER_NAME
        elif adult is False:
            # Ruling 22: keep a refusal record (no user data) so a later launch stays refused.
            self._store.save(
                PersonaProfile(
                    age_confirmed_18_plus=False,
                    created_at=self._now,
                    updated_at=self._now,
                    age_gate_refused_at=self._now,
                )
            )
            self._outcome = self._refusal(RefusalReason.UNDER_18)

    def _on_user_name(self, text: str) -> None:
        name = self._name(text, DEFAULT_USER_NAME)
        if name is not None:
            self._user_name = name
            self._step = Step.AGENT_NAME

    def _on_agent_name(self, text: str) -> None:
        name = self._name(text, DEFAULT_AGENT_NAME)
        if name is not None:
            self._agent_name = name
            self._step = Step.PERSONA

    def _on_persona(self, text: str) -> None:
        reply = _fold(text)
        accepted = {"", "1", _fold(self._text.persona_label), _fold(R1_PERSONA.value)}
        if reply in accepted:
            self._step = Step.TABOO
        else:
            self._hint = self._text.hints["persona_only"]

    def _on_taboo(self, text: str) -> None:
        if _fold(text) in self._skip_words():
            topics: list[str] = []
        else:
            topics = list(dict.fromkeys(t for t in _LIST_SPLIT.split(text.strip()) if t))
        if len(topics) > TABOO_MAX_TOPICS or any(len(t) > TABOO_MAX_LEN for t in topics):
            self._hint = self._render(
                self._text.hints["taboo_limits"],
                max_len=str(TABOO_MAX_LEN),
                max_count=str(TABOO_MAX_TOPICS),
            )
            return
        self._taboo = tuple(topics)
        self._step = Step.REGION

    def _on_region(self, text: str) -> None:
        reply = _fold(text)
        for index, code in enumerate(SUPPORTED_REGIONS, start=1):
            names = (str(index), code, self._text.region_labels[code])
            if reply in {_fold(n) for n in (*names, *self._text.region_aliases[code])}:
                self._country = code
                default = DEFAULT_TIMEZONES.get(code)
                if default is None:
                    self._step = Step.TIMEZONE
                else:
                    self._timezone = default
                    self._step = Step.CLINICAL_CONSENT
                return
        self._hint = self._text.hints["unrecognized"]

    def _on_timezone(self, text: str) -> None:
        reply = _fold(text)
        choices = TIMEZONE_CHOICES[self._country]
        zone: str | None
        if self._country == UNKNOWN_COUNTRY and reply == "":
            zone = FALLBACK_TIMEZONE
        elif reply.isdigit() and 1 <= int(reply) <= len(choices):
            zone = choices[int(reply) - 1]
        else:
            zone = canonical_timezone(text)
        if zone is None:
            self._hint = self._text.hints["timezone_invalid"]
            return
        self._timezone = zone
        self._step = Step.CLINICAL_CONSENT

    def _on_clinical_consent(self, text: str) -> None:
        if _fold(text) in self._skip_words():
            self._finish(())
        elif _SQUASH.sub("", _fold(text)) == _SQUASH.sub("", _fold(self._text.consent_sentence)):
            self._step = Step.CLINICAL_HISTORY
        else:
            self._hint = self._text.hints["consent_unrecognized"]

    def _on_clinical_history(self, text: str) -> None:
        by_key: dict[str, str] = {}
        for index, flag in enumerate(self._red_flags, start=1):
            by_key[str(index)] = flag.code
            by_key[_fold(flag.code)] = flag.code
        tokens = [t for t in _LIST_SPLIT.split(_fold(text)) if t]
        unknown = [t for t in tokens if t not in by_key]
        if unknown:
            self._hint = self._render(
                self._text.hints["clinical_unknown"], tokens="、".join(unknown)
            )
            return
        chosen = {by_key[t] for t in tokens}
        self._finish(tuple(flag.code for flag in self._red_flags if flag.code in chosen))

    # -- helpers ---------------------------------------------------------------------

    def _finish(self, clinical_history: tuple[str, ...]) -> None:
        """ONB-08: the one write of an adult's onboarding, atomic via the store."""
        profile = PersonaProfile(
            age_confirmed_18_plus=True,
            created_at=self._now,
            updated_at=self._now,
            user_name=self._user_name,
            agent_name=self._agent_name,
            persona_spectrum=R1_PERSONA,
            taboo_topics=self._taboo,
            region=UserRegion(country_code=self._country, timezone=self._timezone),
            clinical_history=clinical_history,
        )
        self._store.save(profile)
        self._outcome = Completed(profile, self._render(self._text.outcomes["completed"]))

    def _refusal(self, reason: RefusalReason) -> Refused:
        return Refused(reason, self._text.outcomes[reason.value])

    def _binary_choice(self, text: str) -> bool | None:
        """True for accept, False for decline, None (with a hint) if unrecognized."""
        accept, decline = self._text.choices[self._step.value]
        reply = _fold(text)
        for number, choice, verdict in (("1", accept, True), ("2", decline, False)):
            if reply in {_fold(n) for n in (number, choice.label, *choice.aliases)}:
                return verdict
        self._hint = self._text.hints["unrecognized"]
        return None

    def _name(self, text: str, default: str) -> str | None:
        name = text.strip()
        if not name:
            return default
        if not name.isprintable():
            self._hint = self._text.hints["name_unprintable"]
            return None
        if len(name) > NAME_MAX_LEN:
            self._hint = self._render(self._text.hints["name_length"], max_len=str(NAME_MAX_LEN))
            return None
        return name

    def _skip_words(self) -> set[str]:
        return {"", *(_fold(word) for word in self._text.skip_words)}

    def _render(self, template: str, **extra: str) -> str:
        """Fill slots; a slot this call does not supply raises ``KeyError``."""
        values = {
            "user_name": self._user_name,
            "agent_name": self._agent_name,
            "consent_sentence": self._text.consent_sentence,
            **extra,
        }
        return _SLOT.sub(lambda m: values[m.group(1)], template)

    def _ensure_running(self) -> None:
        if self._outcome is not None:
            raise OnboardingFinishedError("onboarding has already finished")


def _fold(text: str) -> str:
    """Normalize a reply for matching: NFKC (full-width digits), trimmed, case-folded."""
    return unicodedata.normalize("NFKC", text).strip().casefold()


def _section(node: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = node.get(key)
    if not isinstance(value, dict):
        raise OnboardingTextError(f"{_TEXT_FILE}: {key} must be a mapping")
    return value


def _nonempty_str(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OnboardingTextError(f"{_TEXT_FILE}: {where} must be a non-empty string")
    return value


def _str_list(value: Any, where: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise OnboardingTextError(f"{_TEXT_FILE}: {where} must be a list")
    return tuple(_nonempty_str(item, where) for item in value)


def _str_map(doc: Mapping[str, Any], key: str, required: tuple[str, ...]) -> dict[str, str]:
    section = _section(doc, key)
    keys = {str(k) for k in section}
    if keys != set(required):
        missing, extra = sorted(set(required) - keys), sorted(keys - set(required))
        raise OnboardingTextError(f"{_TEXT_FILE}: {key} missing {missing}, unexpected {extra}")
    return {name: _nonempty_str(section[name], f"{key}.{name}") for name in required}


def _choice(node: Mapping[str, Any], key: str, where: str) -> Choice:
    item = _section(node, key)
    return Choice(
        label=_nonempty_str(item.get("label"), f"{where}.{key}.label"),
        aliases=_str_list(item.get("aliases", []), f"{where}.{key}.aliases"),
    )
