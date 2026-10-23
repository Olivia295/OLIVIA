"""``training/colab/export_olivia_data.py``: the ``dev`` role (``--dev-eval``, step C5)."""

from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "export_olivia_data_dev", ROOT / "training" / "colab" / "export_olivia_data.py"
)
assert _spec is not None and _spec.loader is not None
export = importlib.util.module_from_spec(_spec)
sys.modules["export_olivia_data_dev"] = export
_spec.loader.exec_module(export)


def _write(path: Path, rows: list[dict]) -> Path:
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "text", "level"])
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_dev_rows_have_their_own_role_and_source(tmp_path: Path) -> None:
    dev = _write(
        tmp_path / "dev.csv",
        [
            {"id": "d1", "text": "今天在公园里散步", "level": "L0"},
            {"id": "d2", "text": "最近总是睡不好", "level": " L1 "},
        ],
    )
    rows = export.collect_eval_rows(None, dev)
    assert [(r["id"], r["role"], r["source"], r["level"]) for r in rows] == [
        ("d1", "dev", "dev_eval", "L0"),
        ("d2", "dev", "dev_eval", "L1"),
    ]


def test_dev_rows_come_before_fresh_rows(tmp_path: Path) -> None:
    dev = _write(tmp_path / "dev.csv", [{"id": "d1", "text": "今天在公园里散步", "level": "L0"}])
    fresh = _write(tmp_path / "fresh.csv", [{"id": "f1", "text": "周末想去看电影", "level": "L0"}])
    rows = export.collect_eval_rows(fresh, dev)
    assert [(r["id"], r["role"], r["source"]) for r in rows] == [
        ("d1", "dev", "dev_eval"),
        ("f1", "fresh", "fresh_eval"),
    ]


def test_a_sentence_in_both_dev_and_fresh_is_rejected(tmp_path: Path) -> None:
    dev = _write(tmp_path / "dev.csv", [{"id": "d1", "text": "今天在公园里散步", "level": "L0"}])
    fresh = _write(
        tmp_path / "fresh.csv", [{"id": "f1", "text": "今天在公园里散步", "level": "L0"}]
    )
    with pytest.raises(SystemExit, match="both the dev and the fresh set"):
        export.collect_eval_rows(fresh, dev)


def test_dev_levels_are_checked(tmp_path: Path) -> None:
    dev = _write(tmp_path / "dev.csv", [{"id": "d1", "text": "今天在公园里散步", "level": "high"}])
    with pytest.raises(SystemExit, match="level must be L0-L3"):
        export.collect_eval_rows(None, dev)


def test_train_rows_near_a_dev_row_are_dropped_and_dev_rows_kept() -> None:
    rows = [
        {"id": "d1", "text": "今天下班以后想去江边走走散散心", "role": "dev"},
        {"id": "t1", "text": "今天下班以后想去江边走走散散心。", "role": "train"},
        {"id": "t2", "text": "周末打算在家看书", "role": "train"},
    ]
    kept, dropped = export.drop_test_overlap(rows)
    assert [r["id"] for r in kept] == ["d1", "t2"]
    assert [r["id"] for r in dropped] == ["t1"]


def test_dev_is_a_held_out_role() -> None:
    assert "dev" in export.ROLES
    assert "dev" in export.HELD_OUT_ROLES
    assert "dev" in export.TEST_ROLES
