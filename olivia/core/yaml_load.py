"""YAML loading through libyaml when PyYAML has it (F5d).

``yaml.safe_load`` runs PyYAML's pure-Python parser. libyaml's ``CSafeLoader`` builds
the same objects (``tests/core/test_yaml_load.py`` checks every packaged data file) in
less than half the time and with a lower memory peak; without libyaml the pure-Python
``SafeLoader`` is used. Either way it is the safe loader: plain YAML types only.
"""

from __future__ import annotations

from typing import Any, Final

import yaml

LOADER: Final[type[yaml.SafeLoader] | type[yaml.CSafeLoader]] = (
    yaml.CSafeLoader if yaml.__with_libyaml__ else yaml.SafeLoader
)


def safe_load(stream: str | bytes) -> Any:
    """``yaml.safe_load`` with :data:`LOADER`."""
    return yaml.load(stream, Loader=LOADER)  # noqa: S506 - LOADER is a safe loader
