"""``training/colab/export_olivia_data.py``: red-team turns are exclude-only rows (step C5)."""

from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "export_olivia_data", ROOT / "training" / "colab" / "export_olivia_data.py"
)
assert _spec is not None and _spec.loader is not None
export = importlib.util.module_from_spec(_spec)
sys.modules["export_olivia_data"] = export
_spec.loader.exec_module(export)


def _turns(name: str) -> set[str]:
    cases = yaml.safe_load((ROOT / "tests" / "redteam" / name).read_text("utf-8"))
    return {turn for case in cases for turn in case["turns"] if turn.strip()}


def test_every_red_team_turn_is_an_exclude_row() -> None:
    single, multi = _turns("cases.yaml"), _turns("multiturn.yaml")
    rows = export.collect_exclusions([])
    assert {r["text"] for r in rows} == single | multi
    assert len(rows) == len(single | multi)
    assert {r["role"] for r in rows} == {"exclude"}
    assert {r["source"] for r in rows} == {"redteam", "redteam_multiturn"}
    # A turn in both sets is exported once, under the single-turn set.
    multi_rows = {r["text"] for r in rows if r["source"] == "redteam_multiturn"}
    assert multi_rows == multi - single


def test_exclude_csv_rows_are_added_once(tmp_path: Path) -> None:
    path = tmp_path / "extra.csv"
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "text", "role"])
        writer.writeheader()
        writer.writerows([
            {"id": "x1", "text": "一句只用来排除的话", "role": "fresh"},
            {"id": "x2", "text": "一句只用来排除的话", "role": "fresh"},
            {"id": "", "text": "另一句", "role": "fresh"},
        ])
    extra = [r for r in export.collect_exclusions([path]) if r["source"] == "exclude:extra"]
    assert [(r["id"], r["text"]) for r in extra] == [("x1", "一句只用来排除的话"), ("extra_3", "另一句")]


def test_train_rows_near_an_exclude_row_are_dropped() -> None:
    rows = [
        {"id": "e1", "text": "今天下班以后想去江边走走散散心", "role": "exclude"},
        {"id": "t1", "text": "今天下班以后想去江边走走散散心。", "role": "train"},
        {"id": "t2", "text": "周末打算在家看书", "role": "train"},
    ]
    kept, dropped = export.drop_test_overlap(rows)
    assert [r["id"] for r in kept] == ["e1", "t2"]
    assert [r["id"] for r in dropped] == ["t1"]
