"""First-visit onboarding (PRD ONB-01..08; SOP 1; roadmap rulings 22-24, 28).

The flow is pure logic over a :class:`ProfileStore`: the caller shows ``prompt()``,
passes the user's reply to ``answer()``, and repeats until it gets :class:`Completed`
or :class:`Refused`. All wording lives in ``olivia/data/templates/onboarding.yaml``.

Order: disclaimer (explicit acceptance) -> 18+ gate (a "no" is confirmed once, so a
mis-click can be undone before the permanent refusal is recorded) -> at-rest encryption
switch (ONB-06, default off: only health information is encrypted, ruling 28) -> both
names -> persona (the four of ONB-03, ``GENTLE_HOLDING`` by default; plan D-1) -> taboo
topics -> region -> timezone (Enter for "other" takes this computer's zone) -> optional
clinical-history consent (last, ruling 23; its prompt shows the standalone
``sensitive_notice`` before the consent sentence, PIPL Art. 28-30, B8) -> after consent,
the clinical history (plain Chinese labels, codes kept internal) and the D2 checklist of
the profile's contraindication disclosures (heart or breathing, safety at home; step A1)
-> one atomic save (ONB-08). The age
gate comes before anything personal is asked, so nothing is ever collected from a minor
(ruling 22). Nothing touches disk until the end: an adult's answers are saved once, as
a complete profile; a declared minor leaves a refusal record (no user data) so a later
launch shows the refusal again instead of restarting; a declined disclaimer saves nothing.

Without a usable OS keychain nothing sensitive can be encrypted, so the encryption
switch and the health questions (consent, clinical history, checklist) are skipped, no
health information is stored, and the closing text starts with
``outcomes.health_not_saved``. Skipping the consent skips the checklist too.
"""

from __future__ import annotations

import contextlib
import os
import re
import unicodedata
import zoneinfo
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

import yaml

from olivia.core.chang.profile import ProfileLockedError, ProfileStore
from olivia.core.models import (
    NAME_MAX_LEN,
    PROFILE_CONTRAINDICATIONS,
    UNKNOWN_COUNTRY,
    PersonaProfile,
    PersonaSpectrum,
    UserRegion,
)
from olivia.core.taxonomy import RedFlag, Taxonomy

DEFAULT_USER_NAME: Final = "朋友"
DEFAULT_AGENT_NAME: Final = "Olivia"
FALLBACK_TIMEZONE: Final = "UTC"
# ONB-03: the personas in display order (numbered from 1); the first is the default.
PERSONA_CHOICES: Final = (
    PersonaSpectrum.GENTLE_HOLDING,
    PersonaSpectrum.ZEN_PHILOSOPHER,
    PersonaSpectrum.RATIONAL_PEER,
    PersonaSpectrum.SILENT_ANCHOR,
)
DEFAULT_PERSONA: Final = PERSONA_CHOICES[0]

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
# Where ``system_timezone`` looks after ``TZ`` (module-level so tests can point elsewhere).
_LOCALTIME = "/etc/localtime"
_TIMEZONE_FILE = Path("/etc/timezone")
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
    "age_confirm",
    "encryption",
    "user_name",
    "agent_name",
    "persona",
    "taboo",
    "region",
    "timezone_choice",
    "timezone_free",
    "clinical_consent",
    "clinical_history",
    "contraindications",
)
_HINT_KEYS: Final = (
    "unrecognized",
    "name_length",
    "name_unprintable",
    "persona_choice",
    "taboo_limits",
    "timezone_invalid",
    "consent_unrecognized",
    "clinical_unknown",
)
_OUTCOME_KEYS: Final = ("completed", "health_not_saved", "disclaimer_declined", "under_18")
# ``olivia health`` (chang/health.py), kept here so every health wording is in one file.
_HEALTH_KEYS: Final = (
    "current",
    "none_recorded",
    "select",
    "consent",
    "saved",
    "cleared",
    "unchanged",
    "no_keychain",
    "not_onboarded",
    "adults_only",
)
_SLOTS: Final = frozenset(
    {
        "user_name",
        "agent_name",
        "max_len",
        "max_count",
        "consent_sentence",
        "sensitive_notice",
        "tokens",
        "system_timezone",
    }
)
_SLOT: Final = re.compile(r"\{([^{}]*)\}")


class OnboardingTextError(Exception):
    """``onboarding.yaml`` is missing, malformed, or incomplete."""


class OnboardingFinishedError(RuntimeError):
    """``prompt`` or ``answer`` was called after the flow reached its outcome."""


class Step(StrEnum):
    DISCLAIMER = "disclaimer"
    AGE_GATE = "age_gate"
    AGE_CONFIRM = "age_confirm"
    ENCRYPTION = "encryption"
    USER_NAME = "user_name"
    AGENT_NAME = "agent_name"
    PERSONA = "persona"
    TABOO = "taboo"
    REGION = "region"
    TIMEZONE = "timezone"
    CLINICAL_CONSENT = "clinical_consent"
    CLINICAL_HISTORY = "clinical_history"
    CONTRAINDICATIONS = "contraindications"


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
    sensitive_notice: str
    """The standalone notice shown before the consent sentence (PIPL Art. 28-30, B8):
    what is recorded, why, where it stays, what declining changes and how to withdraw."""
    prompts: Mapping[str, str]
    choices: Mapping[str, tuple[Choice, Choice]]
    """``disclaimer`` and ``age_gate`` as ``(accept, decline)``; ``age_confirm`` as
    ``(confirm_minor, mistaken)``; ``encryption`` as ``(keep_off, encrypt_all)``, the
    first being the default."""
    persona_labels: Mapping[PersonaSpectrum, str]
    """One line per persona, ``简称：description`` (ONB-03)."""
    persona_aliases: Mapping[PersonaSpectrum, tuple[str, ...]]
    """Short names also accepted for a persona (``olivia persona 树洞``)."""
    clinical_labels: Mapping[str, str]
    """Red-flag code -> the plain Chinese label shown in the lists; codes stay internal."""
    region_labels: Mapping[str, str]
    region_aliases: Mapping[str, tuple[str, ...]]
    timezone_labels: Mapping[str, str]
    skip_words: frozenset[str]
    hints: Mapping[str, str]
    outcomes: Mapping[str, str]
    disclosure_labels: Mapping[str, str]
    """``PROFILE_CONTRAINDICATIONS`` id -> checklist label, in that order (D2)."""
    health: Mapping[str, str]
    """The ``olivia health`` wording (``health_command``)."""


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
    labels = _str_map(doc, "persona_labels", tuple(p.value for p in PERSONA_CHOICES))
    persona_aliases_raw = _section(doc, "persona_aliases")
    persona_aliases = {
        p: _str_list(persona_aliases_raw.get(p.value, []), f"persona_aliases.{p.value}")
        for p in PERSONA_CHOICES
    }
    unknown_personas = sorted(
        str(k) for k in persona_aliases_raw if k not in {p.value for p in PERSONA_CHOICES}
    )
    if unknown_personas:
        raise OnboardingTextError(
            f"{_TEXT_FILE}: persona_aliases has unknown keys {unknown_personas}"
        )
    clinical_raw = _section(doc, "clinical_labels")
    clinical_labels = {
        str(code): _nonempty_str(label, f"clinical_labels.{code}")
        for code, label in clinical_raw.items()
    }
    hints = _str_map(doc, "hints", _HINT_KEYS)
    outcomes = _str_map(doc, "outcomes", _OUTCOME_KEYS)
    disclosure_labels = _str_map(doc, "disclosure_labels", PROFILE_CONTRAINDICATIONS)
    health = _str_map(doc, "health_command", _HEALTH_KEYS)
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
            _choice(_section(choices_raw, step), first, f"choices.{step}"),
            _choice(_section(choices_raw, step), second, f"choices.{step}"),
        )
        for step, first, second in (
            ("disclaimer", "accept", "decline"),
            ("age_gate", "accept", "decline"),
            ("age_confirm", "confirm", "mistaken"),
            ("encryption", "keep_off", "encrypt_all"),
        )
    }
    notice = _nonempty_str(doc.get("sensitive_notice"), "sensitive_notice")
    if _SLOT.search(notice):
        raise OnboardingTextError(f"{_TEXT_FILE}: sensitive_notice takes no slots")
    for where, texts in (
        ("prompts", prompts),
        ("hints", hints),
        ("outcomes", outcomes),
        ("health_command", health),
    ):
        for key, value in texts.items():
            bad = sorted(set(_SLOT.findall(value)) - _SLOTS)
            if bad:
                raise OnboardingTextError(f"{_TEXT_FILE}: {where}.{key} uses unknown slots {bad}")
    return OnboardingText(
        consent_sentence=_nonempty_str(doc.get("consent_sentence"), "consent_sentence"),
        sensitive_notice=notice,
        prompts=MappingProxyType(prompts),
        choices=MappingProxyType(choices),
        persona_labels=MappingProxyType({p: labels[p.value] for p in PERSONA_CHOICES}),
        persona_aliases=MappingProxyType(persona_aliases),
        clinical_labels=MappingProxyType(clinical_labels),
        region_labels=MappingProxyType(region_labels),
        region_aliases=MappingProxyType(region_aliases),
        timezone_labels=MappingProxyType(timezone_labels),
        skip_words=frozenset(_str_list(doc.get("skip_words"), "skip_words")),
        hints=MappingProxyType(hints),
        outcomes=MappingProxyType(outcomes),
        disclosure_labels=MappingProxyType(disclosure_labels),
        health=MappingProxyType(health),
    )


def parse_choices(reply: str, keys: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(chosen keys in ``keys`` order, unrecognized tokens) for a list-selection reply.

    A token is a 1-based position in ``keys`` or a key itself (case-insensitive);
    tokens are split on commas, enumeration commas, semicolons, slashes and spaces.
    """
    by_token: dict[str, str] = {}
    for index, key in enumerate(keys, start=1):
        by_token[str(index)] = key
        by_token[_fold(key)] = key
    tokens = [t for t in _LIST_SPLIT.split(_fold(reply)) if t]
    unknown = tuple(t for t in tokens if t not in by_token)
    chosen = {by_token[t] for t in tokens if t in by_token}
    return tuple(key for key in keys if key in chosen), unknown


def persona_from_reply(
    reply: str,
    labels: Mapping[PersonaSpectrum, str],
    aliases: Mapping[PersonaSpectrum, tuple[str, ...]] | None = None,
) -> PersonaSpectrum | None:
    """The persona ``reply`` names, else None (an empty reply names none).

    Accepted, after NFKC folding and case-folding: the number in ``PERSONA_CHOICES``
    (from 1), the enum value, the whole label, its short name before ``：``, or one of
    ``aliases`` (``树洞``, ``理性`` ...).
    """
    folded = _fold(reply)
    for number, persona in enumerate(PERSONA_CHOICES, start=1):
        label = labels[persona]
        extra = aliases.get(persona, ()) if aliases is not None else ()
        names = (str(number), persona.value, label, label.split("：", 1)[0], *extra)
        if folded and folded in {_fold(name) for name in names}:
            return persona
    return None


def region_from_reply(reply: str, text: OnboardingText, *, numbers: bool = True) -> str | None:
    """The ``SUPPORTED_REGIONS`` code ``reply`` names, else None.

    Accepted, after NFKC folding, case-folding and dropping spaces: the two-letter code,
    the label, an alias from ``region_aliases`` (``china``, ``中国``, ``香港`` ...) and, with
    ``numbers``, the 1-based position in the onboarding list.
    """
    folded = _squash_spaces(reply)
    if not folded:
        return None
    for index, code in enumerate(SUPPORTED_REGIONS, start=1):
        names = [code, text.region_labels[code], *text.region_aliases[code]]
        if numbers:
            names.append(str(index))
        if folded in {_squash_spaces(name) for name in names}:
            return code
    return None


def system_timezone() -> str:
    """This computer's IANA timezone name, else ``UTC``.

    Read from ``TZ``, then the ``/etc/localtime`` link (macOS, most Linux), then
    ``/etc/timezone``; only a name ``canonical_timezone`` accepts is returned.
    """
    candidates: list[str] = []
    env = os.environ.get("TZ", "").strip().lstrip(":")
    if env:
        candidates.append(env.split("zoneinfo/", 1)[-1])
    target = os.path.realpath(_LOCALTIME)
    if "zoneinfo/" in target:
        candidates.append(target.split("zoneinfo/", 1)[1])
    with contextlib.suppress(OSError, UnicodeDecodeError):
        candidates.append(_TIMEZONE_FILE.read_text(encoding="utf-8").strip())
    for name in candidates:
        zone = canonical_timezone(name) if name else None
        if zone is not None:
            return zone
    return FALLBACK_TIMEZONE


def clinical_options(tax: Taxonomy, text: OnboardingText) -> tuple[str, ...]:
    """The plain Chinese label of every red flag, in taxonomy order (codes stay internal).

    Raises :class:`OnboardingTextError` when ``clinical_labels`` misses a red flag.
    """
    codes = tuple(tax.red_flags())
    missing = sorted(set(codes) - set(text.clinical_labels))
    extra = sorted(set(text.clinical_labels) - set(codes))
    if missing or extra:
        raise OnboardingTextError(
            f"{_TEXT_FILE}: clinical_labels missing {missing}, unexpected {extra}"
        )
    return tuple(text.clinical_labels[code] for code in codes)


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
        self._clinical_options = clinical_options(tax, self._text)
        self._step = Step.DISCLAIMER
        self._hint = ""
        self._user_name = DEFAULT_USER_NAME
        self._agent_name = DEFAULT_AGENT_NAME
        self._persona = DEFAULT_PERSONA
        self._taboo: tuple[str, ...] = ()
        self._country = UNKNOWN_COUNTRY
        self._timezone = FALLBACK_TIMEZONE
        self._protected = False
        """Whether sensitive data can be encrypted here (checked once the user is an adult)."""
        self._encrypt_all = False
        self._clinical: tuple[str, ...] = ()
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
            Step.AGE_CONFIRM: self._on_age_confirm,
            Step.ENCRYPTION: self._on_encryption,
            Step.USER_NAME: self._on_user_name,
            Step.AGENT_NAME: self._on_agent_name,
            Step.PERSONA: self._on_persona,
            Step.TABOO: self._on_taboo,
            Step.REGION: self._on_region,
            Step.TIMEZONE: self._on_timezone,
            Step.CLINICAL_CONSENT: self._on_clinical_consent,
            Step.CLINICAL_HISTORY: self._on_clinical_history,
            Step.CONTRAINDICATIONS: self._on_contraindications,
        }[self._step]
        handler(text)
        return self._outcome if self._outcome is not None else self.prompt()

    # -- questions -------------------------------------------------------------------

    def _question(self) -> tuple[str, tuple[str, ...]]:
        prompts = self._text.prompts
        match self._step:
            case Step.DISCLAIMER | Step.AGE_GATE | Step.AGE_CONFIRM | Step.ENCRYPTION:
                accept, decline = self._text.choices[self._step.value]
                return prompts[self._step.value], (accept.label, decline.label)
            case Step.AGENT_NAME:
                return self._render(prompts["agent_name"]), ()
            case Step.PERSONA:
                personas = self._text.persona_labels
                return prompts["persona"], tuple(personas[p] for p in PERSONA_CHOICES)
            case Step.REGION:
                labels = self._text.region_labels
                return prompts["region"], tuple(labels[code] for code in SUPPORTED_REGIONS)
            case Step.TIMEZONE:
                if self._country == UNKNOWN_COUNTRY:
                    return self._render(
                        prompts["timezone_free"], system_timezone=system_timezone()
                    ), ()
                return prompts["timezone_choice"], tuple(
                    f"{self._text.timezone_labels[zone]} {zone}"
                    for zone in TIMEZONE_CHOICES[self._country]
                )
            case Step.CLINICAL_CONSENT:
                return self._render(prompts["clinical_consent"]), ()
            case Step.CLINICAL_HISTORY:
                return prompts["clinical_history"], self._clinical_options
            case Step.CONTRAINDICATIONS:
                labels = self._text.disclosure_labels
                return prompts["contraindications"], tuple(
                    labels[cid] for cid in PROFILE_CONTRAINDICATIONS
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
            self._protected = self._store.can_protect_sensitive()
            self._step = Step.ENCRYPTION if self._protected else Step.USER_NAME
        elif adult is False:
            self._step = Step.AGE_CONFIRM

    def _on_age_confirm(self, text: str) -> None:
        minor = self._binary_choice(text)
        if minor is False:  # "我选错了": ask the age question again
            self._step = Step.AGE_GATE
        elif minor is True:
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

    def _on_encryption(self, text: str) -> None:
        keep_off, encrypt_all = self._text.choices[Step.ENCRYPTION.value]
        reply = _fold(text)
        if reply in {"", "1", *(_fold(n) for n in (keep_off.label, *keep_off.aliases))}:
            self._encrypt_all = False
        elif reply in {"2", *(_fold(n) for n in (encrypt_all.label, *encrypt_all.aliases))}:
            self._encrypt_all = True
        else:
            self._hint = self._text.hints["unrecognized"]
            return
        self._step = Step.USER_NAME

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
        chosen = (
            DEFAULT_PERSONA
            if _fold(text) == ""
            else persona_from_reply(text, self._text.persona_labels, self._text.persona_aliases)
        )
        if chosen is None:
            self._hint = self._text.hints["persona_choice"]
            return
        self._persona = chosen
        self._step = Step.TABOO

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
        code = region_from_reply(text, self._text)
        if code is None:
            self._hint = self._text.hints["unrecognized"]
            return
        self._country = code
        default = DEFAULT_TIMEZONES.get(code)
        if default is None:
            self._step = Step.TIMEZONE
        else:
            self._timezone = default
            self._after_location()

    def _on_timezone(self, text: str) -> None:
        reply = _fold(text)
        choices = TIMEZONE_CHOICES[self._country]
        zone: str | None
        if self._country == UNKNOWN_COUNTRY and reply == "":
            zone = system_timezone()
        elif reply.isdigit() and 1 <= int(reply) <= len(choices):
            zone = choices[int(reply) - 1]
        else:
            zone = canonical_timezone(text)
        if zone is None:
            self._hint = self._text.hints["timezone_invalid"]
            return
        self._timezone = zone
        self._after_location()

    def _on_clinical_consent(self, text: str) -> None:
        if _fold(text) in self._skip_words():
            self._finish(())
        elif _SQUASH.sub("", _fold(text)) == _SQUASH.sub("", _fold(self._text.consent_sentence)):
            self._step = Step.CLINICAL_HISTORY
        else:
            self._hint = self._text.hints["consent_unrecognized"]

    def _on_clinical_history(self, text: str) -> None:
        chosen = self._choose(text, tuple(flag.code for flag in self._red_flags))
        if chosen is not None:
            self._clinical = chosen
            self._step = Step.CONTRAINDICATIONS

    def _on_contraindications(self, text: str) -> None:
        chosen = self._choose(text, PROFILE_CONTRAINDICATIONS)
        if chosen is not None:
            self._finish(self._clinical, chosen)

    # -- helpers ---------------------------------------------------------------------

    def _after_location(self) -> None:
        """The optional clinical-history consent, or the end when it cannot be protected."""
        if self._protected:
            self._step = Step.CLINICAL_CONSENT
        else:
            self._finish(())

    def _choose(self, text: str, keys: tuple[str, ...]) -> tuple[str, ...] | None:
        """The chosen keys, or None (with a hint) when a token is not in the list."""
        chosen, unknown = parse_choices(text, keys)
        if unknown:
            self._hint = self._render(
                self._text.hints["clinical_unknown"], tokens="、".join(unknown)
            )
            return None
        return chosen

    def _finish(
        self, clinical_history: tuple[str, ...], contraindications: tuple[str, ...] = ()
    ) -> None:
        """ONB-08: the one write of an adult's onboarding, atomic via the store.

        Health information is never stored unencrypted (ruling 28): if the keychain
        fails at this last moment, the profile is saved without it and the switch off.
        """
        profile = PersonaProfile(
            age_confirmed_18_plus=True,
            created_at=self._now,
            updated_at=self._now,
            user_name=self._user_name,
            agent_name=self._agent_name,
            persona_spectrum=self._persona,
            taboo_topics=self._taboo,
            region=UserRegion(country_code=self._country, timezone=self._timezone),
            clinical_history=clinical_history,
            contraindications=contraindications,
            enable_at_rest_encryption=self._encrypt_all,
        )
        protected = self._protected
        try:
            self._store.save(profile)
        except ProfileLockedError:
            profile = replace(
                profile,
                clinical_history=(),
                contraindications=(),
                enable_at_rest_encryption=False,
            )
            self._store.save(profile)
            protected = False
        text = self._render(self._text.outcomes["completed"])
        if not protected:
            text = f"{self._text.outcomes['health_not_saved']}\n\n{text}"
        self._outcome = Completed(profile, text)

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
            "sensitive_notice": self._text.sensitive_notice,
            **extra,
        }
        return _SLOT.sub(lambda m: values[m.group(1)], template)

    def _ensure_running(self) -> None:
        if self._outcome is not None:
            raise OnboardingFinishedError("onboarding has already finished")


def _fold(text: str) -> str:
    """Normalize a reply for matching: NFKC (full-width digits), trimmed, case-folded."""
    return unicodedata.normalize("NFKC", text).strip().casefold()


def _squash_spaces(text: str) -> str:
    """``_fold`` without any whitespace, so ``Hong Kong`` matches ``hongkong``."""
    return re.sub(r"\s+", "", _fold(text))


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
