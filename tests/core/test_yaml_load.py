"""F5d: libyaml's safe loader reads every packaged data file exactly as PyYAML's does."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from olivia.core import yaml_load

DATA = Path(__file__).resolve().parents[2] / "olivia" / "data"
FILES = sorted(DATA.rglob("*.yaml"))


def _typed(value: Any) -> Any:
    """``value`` with every scalar's type kept, so 1, 1.0 and True stay apart."""
    if isinstance(value, dict):
        return {_typed(k): _typed(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_typed(v) for v in value]
    return (type(value).__name__, value)


def test_the_data_files_are_found() -> None:
    assert len(FILES) >= 20


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(DATA)))
def test_both_loaders_read_the_same_objects(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    pure = yaml.load(text, Loader=yaml.SafeLoader)  # noqa: S506 - the safe loader
    fast = yaml_load.safe_load(text)
    assert _typed(fast) == _typed(pure)
    assert yaml_load.safe_load(path.read_bytes()) == fast


def test_libyaml_is_used_when_present() -> None:
    expected = yaml.CSafeLoader if yaml.__with_libyaml__ else yaml.SafeLoader
    assert yaml_load.LOADER is expected


def test_the_loader_is_safe() -> None:
    with pytest.raises(yaml.YAMLError):
        yaml_load.safe_load("!!python/object/apply:os.system ['true']")
