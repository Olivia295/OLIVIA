"""``scripts/eval_crisis.py`` on a synthetic CSV: the numbers, and never the sentences."""

from __future__ import annotations

import importlib.util
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
