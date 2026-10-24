"""``olivia privacy``: the short privacy notice (next-phase step B8; PIPL, gate G-4).

The notice says what is stored where (the data directory, filled into the ``{data_dir}``
slot), that OLIVIA never goes online, what is always encrypted, what is never stored,
and how to see (``olivia memory``) and delete (``olivia health``, ``olivia forget``) it.
All wording is in ``olivia/data/templates/privacy.yaml`` (a G-0 / G-4 legal draft).
Showing it reads and writes nothing: not the profile, not the keychain, not even the
data directory, which is only located (``storage.data_dir_location``), never created.
``scripts/privacy_audit.py`` checks the claims automatically.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Final

import yaml

from olivia.core.yaml_load import safe_load

_TEXT_FILE: Final = "privacy.yaml"
_DATA_DIR_SLOT: Final = "data_dir"
_SLOT: Final = re.compile(r"\{([^{}]*)\}")


class PrivacyTextError(Exception):
    """``privacy.yaml`` is missing, malformed, or incomplete."""


@dataclass(frozen=True)
class PrivacyText:
    notice: str
    """The notice, with one ``{data_dir}`` slot."""


def load_privacy_text(directory: Path | None = None) -> PrivacyText:
    """Load and validate ``privacy.yaml``; ``None`` reads the packaged copy."""
    base: Traversable | Path = (
        resources.files("olivia").joinpath("data/templates") if directory is None else directory
    )
    try:
        doc = safe_load(base.joinpath(_TEXT_FILE).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise PrivacyTextError(f"{_TEXT_FILE}: cannot read: {exc}") from exc
    if not isinstance(doc, dict) or doc.get("version") != 1:
        raise PrivacyTextError(f"{_TEXT_FILE}: must be a mapping with version 1")
    notice = doc.get("notice")
    if not isinstance(notice, str) or not notice.strip():
        raise PrivacyTextError(f"{_TEXT_FILE}: notice must be a non-empty string")
    slots = _SLOT.findall(notice)
    if slots != [_DATA_DIR_SLOT]:
        raise PrivacyTextError(f"{_TEXT_FILE}: notice needs exactly one {{data_dir}}, has {slots}")
    return PrivacyText(notice=notice)


def privacy_notice(data_dir: Path, text: PrivacyText | None = None) -> str:
    """The notice for a data directory at ``data_dir``."""
    wording = load_privacy_text() if text is None else text
    return wording.notice.replace(f"{{{_DATA_DIR_SLOT}}}", str(data_dir))
