"""The wording of the reminders and of ``olivia settings`` (``data/templates/notify.yaml``)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Final

import yaml

from olivia.core.yaml_load import safe_load

_FILE: Final = "notify.yaml"
_SLOT: Final = re.compile(r"\{([^{}]*)\}")
_ALLOWED_SLOTS: Final = frozenset({"state", "job", "where"})
NOTIFICATION_KEYS: Final = ("title", "journal", "absence")
SETTINGS_KEYS: Final = (
    "heading",
    "notifications_item",
    "state_on",
    "state_off",
    "unknown_choice",
    "about_on",
    "confirm",
    "confirm_yes",
    "confirm_no",
    "cancelled",
    "turned_on",
    "turned_off",
    "off_incomplete",
    "install_failed",
    "unsupported_system",
    "unsupported_notifier",
    "unsupported_scheduler",
    "encryption_item",
    "encryption_state_all",
    "encryption_state_health",
    "about_encrypt_all",
    "confirm_encrypt_all",
    "encrypt_all_yes",
    "about_encrypt_health",
    "confirm_encrypt_health",
    "encrypt_health_yes",
    "encryption_no",
    "encrypted_all",
    "encrypted_health",
    "encryption_needs_keychain",
    "needs_keychain",
    "not_onboarded",
    "adults_only",
)
PLACE_KEYS: Final = ("launchd", "schtasks", "systemd", "cron")


class NotifyTextError(Exception):
    """``notify.yaml`` is missing, malformed or incomplete."""


@dataclass(frozen=True)
class NotifyText:
    notifications: Mapping[str, str]
    settings: Mapping[str, str]
    places: Mapping[str, str]

    def all_texts(self) -> tuple[str, ...]:
        """Every sentence shown on its own, for the WILLOW and gate checks in the tests."""
        fragments = {
            "state_on",
            "state_off",
            "confirm_yes",
            "confirm_no",
            "encryption_state_all",
            "encryption_state_health",
            "encrypt_all_yes",
            "encrypt_health_yes",
            "encryption_no",
        }
        return (
            *self.notifications.values(),
            *(v for k, v in self.settings.items() if k not in fragments),
        )


def load_notify_text(directory: Path | None = None) -> NotifyText:
    """Load and validate ``notify.yaml``; ``None`` reads the packaged copy (cached)."""
    if directory is None:
        return _packaged_text()
    return _load_text(directory)


@cache
def _packaged_text() -> NotifyText:
    return _load_text(resources.files("olivia").joinpath("data/templates"))


def _section(doc: Mapping[str, object], name: str, keys: tuple[str, ...]) -> dict[str, str]:
    raw = doc.get(name)
    if not isinstance(raw, dict) or set(raw) != set(keys):
        raise NotifyTextError(f"{_FILE}: {name} must hold exactly {list(keys)}")
    out: dict[str, str] = {}
    for key in keys:
        value = raw[key]
        if not isinstance(value, str) or not value.strip():
            raise NotifyTextError(f"{_FILE}: {name}.{key} must be a non-empty string")
        unknown = set(_SLOT.findall(value)) - _ALLOWED_SLOTS
        if unknown:
            raise NotifyTextError(f"{_FILE}: {name}.{key} uses unknown slots {sorted(unknown)}")
        out[key] = value
    return out


def _load_text(base: Traversable | Path) -> NotifyText:
    try:
        doc = safe_load(base.joinpath(_FILE).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise NotifyTextError(f"{_FILE}: cannot read: {exc}") from exc
    sections = {"version", "notifications", "settings", "places"}
    if not isinstance(doc, dict) or doc.get("version") != 1 or set(doc) != sections:
        raise NotifyTextError(f"{_FILE}: must be version 1 with sections {sorted(sections)}")
    notifications = _section(doc, "notifications", NOTIFICATION_KEYS)
    if any(_SLOT.search(v) for v in notifications.values()):
        raise NotifyTextError(f"{_FILE}: a notification holds no slots (it is content-free)")
    return NotifyText(
        notifications=notifications,
        settings=_section(doc, "settings", SETTINGS_KEYS),
        places=_section(doc, "places", PLACE_KEYS),
    )


def fill(template: str, **values: object) -> str:
    text = template
    for name, value in values.items():
        text = text.replace("{" + name + "}", str(value))
    return text
