"""``olivia health``: view and change the recorded health information (D2, step A1).

Like onboarding, this is pure logic over a :class:`ProfileStore`: the caller shows
``prompt()``, passes the reply to ``answer()`` and repeats until it gets
:class:`HealthDone`. All wording is in ``olivia/data/templates/onboarding.yaml``
(``health_command``); the list is the onboarding one, the clinical-history codes with
their taxonomy names followed by the ``disclosure_labels``, and only labels are shown.

The list shows what is recorded now; the reply chooses the new set by number or code,
``0`` deletes everything and an empty reply changes nothing. Recording something on a
profile that holds no health information yet shows the onboarding's standalone
``sensitive_notice`` and asks for the consent sentence first (ruling 23, B8). The change
is saved through the store, so it is always encrypted; without a usable keychain
nothing is asked and nothing is saved. A store error
(``ProfileCorruptError``, ``ProfileLockedError``) propagates to the caller.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
from typing import Final

from olivia.core.chang.onboarding import OnboardingText, load_onboarding_text, parse_choices
from olivia.core.chang.profile import ProfileStore
from olivia.core.models import PROFILE_CONTRAINDICATIONS, PersonaProfile
from olivia.core.taxonomy import Taxonomy

_SQUASH: Final = re.compile(r"[\s。.]+")
CLEAR_WORDS: Final = ("0", "清空", "全部删除")
"""Replies that delete every recorded item."""


@dataclass(frozen=True)
class HealthPrompt:
    """What to show next; ``options`` are numbered from 1 by the caller."""

    text: str
    options: tuple[str, ...] = ()


@dataclass(frozen=True)
class HealthDone:
    text: str
    ok: bool
    """False when nothing could be shown or changed (no profile, no keychain)."""


class _Step(Enum):
    SELECT = 0
    CONSENT = 1


class HealthEditor:
    """One ``olivia health`` exchange; see the module docstring."""

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
        flags = tax.red_flags()
        self._keys: tuple[str, ...] = (*flags, *PROFILE_CONTRAINDICATIONS)
        self._labels: tuple[str, ...] = (
            *(f"{code} {flag.name_zh}" for code, flag in flags.items()),
            *(self._text.disclosure_labels[cid] for cid in PROFILE_CONTRAINDICATIONS),
        )
        self._step = _Step.SELECT
        self._hint = ""
        self._chosen: tuple[str, ...] = ()
        self._outcome: HealthDone | None = None
        health = self._text.health
        profile = store.load()
        self._profile = profile
        if profile is None:
            self._outcome = HealthDone(health["not_onboarded"], ok=False)
        elif profile.is_age_gate_refusal:
            self._outcome = HealthDone(health["adults_only"], ok=False)
        elif not store.can_protect_sensitive():
            self._outcome = HealthDone(health["no_keychain"], ok=False)

    @property
    def outcome(self) -> HealthDone | None:
        """None while the exchange is still going."""
        return self._outcome

    def prompt(self) -> HealthPrompt:
        if self._outcome is not None:
            raise RuntimeError("the exchange has already finished")
        health = self._text.health
        if self._step is _Step.CONSENT:
            body = (
                health["consent"]
                .replace("{sensitive_notice}", self._text.sensitive_notice)
                .replace("{consent_sentence}", self._text.consent_sentence)
            )
            options: tuple[str, ...] = ()
        else:
            recorded = self._recorded()
            labels = [self._labels[self._keys.index(key)] for key in recorded]
            current = (
                "\n".join([health["current"], *(f"· {label}" for label in labels)])
                if labels
                else health["none_recorded"]
            )
            body, options = f"{current}\n\n{health['select']}", self._labels
        return HealthPrompt(f"{self._hint}\n\n{body}" if self._hint else body, options)

    def answer(self, text: str) -> HealthPrompt | HealthDone:
        if self._outcome is not None:
            raise RuntimeError("the exchange has already finished")
        self._hint = ""
        if self._step is _Step.CONSENT:
            self._on_consent(text)
        else:
            self._on_select(text)
        return self._outcome if self._outcome is not None else self.prompt()

    # -- steps -------------------------------------------------------------------------

    def _on_select(self, text: str) -> None:
        reply = text.strip()
        if not reply:
            self._outcome = HealthDone(self._text.health["unchanged"], ok=True)
            return
        if _fold(reply) in CLEAR_WORDS:
            chosen: tuple[str, ...] = ()
        else:
            picked, unknown = parse_choices(reply, self._keys)
            if unknown:
                self._hint = self._text.hints["clinical_unknown"].replace(
                    "{tokens}", "、".join(unknown)
                )
                return
            chosen = picked
        if chosen == self._recorded():
            self._outcome = HealthDone(self._text.health["unchanged"], ok=True)
        elif chosen and not self._recorded():
            self._chosen = chosen
            self._step = _Step.CONSENT
        else:
            self._save(chosen)

    def _on_consent(self, text: str) -> None:
        skip = {"", *(_fold(word) for word in self._text.skip_words)}
        if _fold(text) in skip:
            self._outcome = HealthDone(self._text.health["unchanged"], ok=True)
        elif _squash(text) == _squash(self._text.consent_sentence):
            self._save(self._chosen)
        else:
            self._hint = self._text.hints["consent_unrecognized"]

    # -- helpers -----------------------------------------------------------------------

    def _recorded(self) -> tuple[str, ...]:
        profile = self._profile
        if profile is None:
            return ()
        held = {*profile.clinical_history, *profile.contraindications}
        return tuple(key for key in self._keys if key in held)

    def _save(self, chosen: tuple[str, ...]) -> None:
        profile = self._profile
        if profile is None:  # pragma: no cover - the constructor ends the exchange first
            raise RuntimeError("no profile to change")
        updated: PersonaProfile = replace(
            profile,
            clinical_history=tuple(k for k in chosen if k not in PROFILE_CONTRAINDICATIONS),
            contraindications=tuple(k for k in chosen if k in PROFILE_CONTRAINDICATIONS),
            updated_at=self._now,
        )
        self._store.save(updated)
        self._profile = updated
        key = "saved" if chosen else "cleared"
        self._outcome = HealthDone(self._text.health[key], ok=True)


def _fold(text: str) -> str:
    """NFKC (full-width digits), trimmed, case-folded: the onboarding reply folding."""
    return unicodedata.normalize("NFKC", text).strip().casefold()


def _squash(text: str) -> str:
    return _SQUASH.sub("", _fold(text))
