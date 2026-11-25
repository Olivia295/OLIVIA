"""``scripts/eval_crisis.py`` on a synthetic CSV: the numbers, and never the sentences."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from olivia.core.models import CrisisLevel

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("eval_crisis", ROOT / "scripts/eval_crisis.py")
assert _spec is not None and _spec.loader is not None
ev = importlib.util.module_from_spec(_spec)
sys.modules["eval_crisis"] = ev
_spec.loader.exec_module(ev)

# Labels chosen so the outcome is certain: a farewell letter is caught by the rules (L3);
# a plain remark about lunch is not. "fa1" and "miss1" are deliberately mislabelled.
ROWS = [
    ("hit1", "我写了一封遗书", "L3", "告别"),
    ("miss1", "今天中午吃了一碗面条", "L3", "伪装"),
    ("ok1", "今天中午吃了一碗面条，还挺好吃", "L0", "日常"),
    ("fa1", "我写了一封遗书", "L0", "口癖"),
    ("ok2", "周末想去公园走走", "L0", ""),
]
SENTENCES = {text for _, text, _, _ in ROWS}


def _csv(tmp_path: Path, rows=ROWS, header="id,text,level,category") -> Path:
    path = tmp_path / "synthetic.csv"
    lines = [header, *(",".join(row) for row in rows)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_rules_mode_counts(tmp_path):
    report = ev.evaluate(ev.load_rows(_csv(tmp_path)), "rules")
    assert report.matrix[(CrisisLevel.L3, CrisisLevel.L3)] == 1
    assert [row.id for row in report.misses] == ["miss1"]
    assert [row.id for row in report.false_alarms] == ["fa1"]
    assert report.crisis_total == 2 and report.count(CrisisLevel.L0) == 3
    assert sum(report.matrix.values()) == len(ROWS)
    assert set(report.risk_models) == {"rules-only"}


def test_report_never_prints_sentences_and_ids_only_on_request(tmp_path, capsys):
    assert ev.main([str(_csv(tmp_path)), "--mode", "rules"]) == 0
    out = capsys.readouterr().out
    assert not [s for s in SENTENCES if s in out]
    assert "遗书" not in out and "面条" not in out
    assert "miss1" not in out and "fa1" not in out
    assert "L2+L3 召回（判到 L2 及以上）：1/2 = 50.0%" in out
    assert "L0 误报率（判到 L2 及以上）：1/3 = 33.3%" in out
    assert "伪装：1" in out and "口癖：1" in out

    assert ev.main([str(_csv(tmp_path)), "--mode", "rules", "--show-ids"]) == 0
    shown = capsys.readouterr().out
    assert "伪装：1  [miss1]" in shown and "口癖：1  [fa1]" in shown
    assert "hit1" not in shown and "ok1" not in shown
    assert not [s for s in SENTENCES if s in shown]


Z2 = 1.96**2


def test_wilson_interval_bounds():
    assert ev.wilson_interval(0, 0) == (0.0, 1.0)  # no rows: no information
    low, high = ev.wilson_interval(0, 10)
    assert low == 0.0 and high == pytest.approx(Z2 / (10 + Z2))
    low, high = ev.wilson_interval(10, 10)
    assert high == 1.0 and low == pytest.approx(10 / (10 + Z2))
    assert ev.wilson_interval(1, 2) == pytest.approx((0.094529, 0.905471), abs=1e-6)
    assert ev.wilson_interval(8, 100) == pytest.approx((0.041093, 0.149983), abs=1e-6)
    assert ev.wilson_interval(1, 1) == pytest.approx((1 / (1 + Z2), 1.0))
    for k, n in [(0, 1), (3, 7), (124, 138), (2, 98), (138, 138)]:
        low, high = ev.wilson_interval(k, n)
        assert 0.0 <= low <= k / n <= high <= 1.0


@pytest.mark.parametrize(("k", "n"), [(-1, 5), (6, 5), (0, -1)])
def test_wilson_interval_refuses_impossible_counts(k, n):
    with pytest.raises(ValueError):
        ev.wilson_interval(k, n)


def test_report_gives_intervals_and_category_tables(tmp_path, capsys):
    assert ev.main([str(_csv(tmp_path)), "--mode", "rules"]) == 0
    out = capsys.readouterr().out
    assert "L2+L3 召回（判到 L2 及以上）：1/2 = 50.0%（95% 区间 9.5%–90.5%）" in out
    assert "L0 误报率（判到 L2 及以上）：1/3 = 33.3%（95% 区间 6.1%–79.2%）" in out
    lines = out.splitlines()
    recall = lines.index(next(line for line in lines if line.startswith("按类别的召回表")))
    alarms = lines.index(next(line for line in lines if line.startswith("按类别的 L0 误报表")))
    recall_rows = [line.split() for line in lines[recall + 2 : alarms]]
    # n, hits, recall, interval, category; the lowest recall first.
    assert recall_rows == [
        ["1", "0", "0.0%", "0.0%–79.3%", "伪装"],
        ["1", "1", "100.0%", "20.7%–100.0%", "告别"],
    ]
    alarm_rows = [line.split() for line in lines[alarms + 2 :]]
    assert alarm_rows[0] == ["1", "1", "100.0%", "20.7%–100.0%", "口癖"]  # the highest first
    assert {row[-1] for row in alarm_rows} == {"口癖", "日常", ev.NO_CATEGORY}
    assert not [s for s in SENTENCES if s in out]


def test_category_rates_split_by_label(tmp_path):
    rows = [*ROWS, ("hit2", "我写了一封遗书", "L2", "口癖"), ("l1", "我写了一封遗书", "L1", "口癖")]
    report = ev.evaluate(ev.load_rows(_csv(tmp_path, rows)), "rules")
    # 口癖 has an L0, an L1 and an L2 row: recall counts the L2, false alarms the L0.
    assert report.category_recall() == {"伪装": (0, 1), "口癖": (1, 1), "告别": (1, 1)}
    assert report.category_false_alarms() == {
        "口癖": (1, 1),
        "日常": (0, 1),
        ev.NO_CATEGORY: (0, 1),
    }


def test_json_has_the_numbers_and_neither_sentences_nor_ids(tmp_path, capsys):
    target = tmp_path / "reports" / "base.json"  # the folder is created
    assert ev.main([str(_csv(tmp_path)), "--json", str(target)]) == 0
    assert str(target) in capsys.readouterr().out
    raw = target.read_text(encoding="utf-8")
    assert not [s for s in SENTENCES if s in raw]
    assert "遗书" not in raw and "面条" not in raw
    assert not [row_id for row_id, *_ in ROWS if row_id in raw]
    data = json.loads(raw)
    assert data["schema"] == ev.JSON_SCHEMA and data["csv"] == "synthetic.csv"
    assert data["rows"] == len(ROWS) and data["z"] == 1.96
    assert set(data["modes"]) == {"rules", "model"}
    rules = data["modes"]["rules"]
    assert rules["risk_models"] == {"rules-only": len(ROWS)}
    assert rules["confusion"]["L3"] == {"L0": 1, "L1": 0, "L2": 0, "L3": 1}
    assert rules["confusion"]["L0"] == {"L0": 2, "L1": 0, "L2": 0, "L3": 1}
    assert rules["flow"]["L0"]["crisis"] == 1
    assert rules["recall"] == {"k": 1, "n": 2, "rate": 0.5, "ci95": [0.094529, 0.905471]}
    assert rules["false_alarm"]["k"] == 1 and rules["false_alarm"]["n"] == 3
    categories = rules["categories"]
    assert set(categories) == {"告别", "伪装", "日常", "口癖", ev.NO_CATEGORY}
    assert categories["伪装"]["recall"] == {"k": 0, "n": 1, "rate": 0.0, "ci95": [0.0, 0.793457]}
    assert "false_alarm" not in categories["伪装"]
    assert categories["口癖"]["false_alarm"]["k"] == 1 and "recall" not in categories["口癖"]
    assert categories["口癖"]["rows"] == {"L0": 1, "L1": 0, "L2": 0, "L3": 0}


def test_json_with_no_crisis_rows_has_an_empty_recall(tmp_path):
    rows = [row for row in ROWS if row[2] == "L0"]
    data = ev.reports_to_json(
        "x.csv", len(rows), [ev.evaluate(ev.load_rows(_csv(tmp_path, rows)), "rules")]
    )
    assert data["modes"]["rules"]["recall"] == {"k": 0, "n": 0, "rate": None, "ci95": [0.0, 1.0]}


def test_unwritable_json_is_exit_2(tmp_path, capsys):
    assert ev.main([str(_csv(tmp_path)), "--mode", "rules", "--json", str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert "cannot write" in err
    assert not [s for s in SENTENCES if s in err]


def test_model_mode_runs_through_the_student_switch(tmp_path, capsys):
    rows = ev.load_rows(_csv(tmp_path))
    rules = ev.evaluate(rows, "rules")
    model = ev.evaluate(rows, "model")
    assert sum(model.risk_models.values()) == len(rows)
    # The student can only raise the rule level, so it never misses what the rules caught.
    assert {r.id for r in model.misses} <= {r.id for r in rules.misses}
    assert ev.main([str(_csv(tmp_path))]) == 0  # both modes by default
    out = capsys.readouterr().out
    assert "== 模式 rules" in out and "== 模式 model" in out
    assert not [s for s in SENTENCES if s in out]


def test_category_is_optional(tmp_path):
    rows = [(i, t, lv) for i, t, lv, _ in ROWS]
    loaded = ev.load_rows(_csv(tmp_path, rows, header="id,text,level"))
    assert {row.category for row in loaded} == {ev.NO_CATEGORY}


@pytest.mark.parametrize(
    ("header", "rows", "message"),
    [
        ("id,level", [("a", "L0")], "missing column(s) text"),
        ("id,text,level", [("a", "秘密句子一", "L4")], "level must be L0-L3"),
        ("id,text,level", [("a", "", "L0")], "empty text"),
        ("id,text,level", [("a", "秘密句子一", "L0"), ("a", "秘密句子二", "L1")], "repeated id"),
        ("id,text,level", [], "no rows"),
    ],
)
def test_bad_csv_is_exit_2_without_the_text(tmp_path, capsys, header, rows, message):
    path = _csv(tmp_path, rows, header=header)
    assert ev.main([str(path)]) == 2
    err = capsys.readouterr().err
    assert message in err
    assert "秘密句子" not in err


def test_unreadable_csv_is_exit_2(tmp_path, capsys):
    assert ev.main([str(tmp_path / "missing.csv")]) == 2
    assert "cannot read" in capsys.readouterr().err


def test_unknown_mode_is_refused():
    with pytest.raises(ValueError):
        ev.evaluate([], "magic")
