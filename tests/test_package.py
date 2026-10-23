import tomllib
from pathlib import Path

import olivia

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "olivia"


def test_version_is_semver_string():
    parts = olivia.__version__.split(".")
    assert len(parts) == 3 and all(p.isdigit() for p in parts)


def test_every_data_file_ships_in_the_wheel():
    # setuptools only packages the files the package-data globs match; a new data file
    # (or a new data directory) that no glob covers would be missing from installs.
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    patterns = config["tool"]["setuptools"]["package-data"]["olivia"]
    shipped = {path for pattern in patterns for path in PACKAGE.glob(pattern)}
    data = {
        path
        for path in (PACKAGE / "data").rglob("*")
        if path.is_file() and not path.name.startswith(".") and "__pycache__" not in path.parts
    }
    assert data, "no data files found"
    assert sorted(data - shipped) == []
