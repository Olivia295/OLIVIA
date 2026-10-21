from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_package_copy_matches_root_ssot() -> None:
    assert (ROOT / "olivia/data/taxonomy.yaml").read_bytes() == (
        ROOT / "taxonomy.yaml"
    ).read_bytes()
