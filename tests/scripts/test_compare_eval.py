"""``scripts/compare_eval.py``: differences between two ``eval_crisis.py --json`` reports."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"scripts/{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ev = _load("eval_crisis")
cmp = _load("compare_eval")


def _prop(k: int, n: int) -> dict:
    low, high = ev.wilson_interval(k, n)
    return {"k": k, "n": n, "rate": k / n if n else None, "ci95": [low, high]}


def _report(recall=(90, 100), alarms=(5, 100), categories=None, *, csv="dev.csv", modes=("model",)):
    """A report in ``eval_crisis.py --json`` shape: ``categories`` maps a name to
    ``{"recall": (k, n), "false_alarm": (k, n)}`` (either may be left out)."""
    cats = {}
    for name, metrics in (categories or {}).items():
        cats[name] = {metric: _prop(*kn) for metric, kn in metrics.items()}
    body = {"recall": _prop(*recall), "false_alarm": _prop(*alarms), "categories": cats}
    return {"schema": 1, "csv": csv, "rows": 200, "z": 1.96, "modes": {m: body for m in modes}}


def _write(tmp_path: Path, name: str, data: dict) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def _run(tmp_path, capsys, before: dict, after: dict) -> tuple[int, str]:
    code = cmp.main(
        [str(_write(tmp_path, "a.json", before)), str(_write(tmp_path, "b.json", after))]
    )
    return code, capsys.readouterr().out


def test_no_change_is_exit_0(tmp_path, capsys):
    report = _report(categories={"告别": {"recall": (9, 10)}, "口癖": {"false_alarm": (1, 20)}})
    code, out = _run(tmp_path, capsys, report, report)
    assert code == 0
    assert "L2+L3 召回：90/100 = 90.0%" in out and "+0.0 个百分点" in out
    assert "告别：9/10 = 90.0%" in out and "口癖：1/20 = 5.0%" in out
    assert "召回下降" not in out.replace("没有召回下降", "") and "[误报上升" not in out
    assert "结论：没有召回下降，也没有误报上升。" in out


def test_better_numbers_are_exit_0(tmp_path, capsys):
    code, out = _run(tmp_path, capsys, _report((90, 100), (5, 100)), _report((95, 100), (2, 100)))
    assert code == 0
    assert "+5.0 个百分点" in out and "-3.0 个百分点" in out
    assert "[召回下降" not in out and "[误报上升" not in out


def test_a_recall_drop_is_flagged_with_overlapping_intervals(tmp_path, capsys):
    code, out = _run(tmp_path, capsys, _report((90, 100)), _report((88, 100)))
    assert code == 1
    assert "L2+L3 召回：90/100 = 90.0% [82.6%–94.5%] → 88/100 = 88.0%" in out
    assert "-2.0 个百分点  [召回下降，区间重叠]" in out
    assert "结论：召回下降 1 项，误报上升 0 项（其中区间不重叠 0 项）。" in out


def test_a_false_alarm_rise_is_flagged_and_separate_intervals_are_named(tmp_path, capsys):
    code, out = _run(tmp_path, capsys, _report(alarms=(0, 200)), _report(alarms=(30, 200)))
    assert code == 1
    assert "[误报上升，区间不重叠]" in out
    assert "误报上升 1 项（其中区间不重叠 1 项）" in out


def test_a_category_regression_counts_even_when_the_total_holds(tmp_path, capsys):
    before = _report(categories={"告别": {"recall": (10, 10)}, "伪装": {"recall": (5, 10)}})
    after = _report(categories={"告别": {"recall": (9, 10)}, "伪装": {"recall": (6, 10)}})
    code, out = _run(tmp_path, capsys, before, after)
    assert code == 1
    assert "告别：10/10 = 100.0% [72.2%–100.0%] → 9/10 = 90.0%" in out
    flagged = [line for line in out.splitlines() if "[召回下降" in line]
    assert len(flagged) == 1 and flagged[0].lstrip().startswith("告别")


def test_rates_are_compared_exactly(tmp_path, capsys):
    # 1/3 and 2/6 are the same rate; floating point must not call it a rise.
    code, out = _run(tmp_path, capsys, _report(alarms=(1, 3)), _report(alarms=(2, 6)))
    assert code == 0 and "[误报上升" not in out


def test_metrics_on_one_side_only_are_listed_not_judged(tmp_path, capsys):
    before = _report(categories={"旧类": {"recall": (1, 2)}, "空类": {"recall": (0, 0)}})
    after = _report(categories={"新类": {"false_alarm": (3, 3)}, "空类": {"recall": (0, 4)}})
    code, out = _run(tmp_path, capsys, before, after)
    assert code == 0
    assert "旧类：只在前一份里（不比较）" in out
    assert "新类：只在后一份里（不比较）" in out
    assert "空类：0/0 → 0/4 = 0.0% [0.0%–49.0%]（有一边没有样本，不比较）" in out


def test_different_sets_and_modes_are_noted(tmp_path, capsys):
    before = _report(modes=("rules", "model"))
    after = _report(csv="other.csv", modes=("model",))
    code, out = _run(tmp_path, capsys, before, after)
    assert code == 0
    assert "注意：两份报告的数据集或条数不同" in out
    assert "模式 rules 只在前一份里（不比较）" in out
    assert "== 模式 model ==" in out and "== 模式 rules ==" not in out


def test_reports_written_by_eval_crisis_compare(tmp_path, capsys):
    csv = tmp_path / "s.csv"
    csv.write_text(
        "id,text,level,category\nr1,我写了一封遗书,L3,告别\nr2,周末想去公园走走,L0,日常\n",
        encoding="utf-8",
    )
    report = tmp_path / "base.json"
    assert ev.main([str(csv), "--mode", "rules", "--json", str(report)]) == 0
    capsys.readouterr()
    assert cmp.main([str(report), str(report)]) == 0
    out = capsys.readouterr().out
    assert "== 模式 rules ==" in out and "告别：1/1 = 100.0%" in out
    assert "遗书" not in out and "公园" not in out and "r1" not in out


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("not json", "not a JSON file"),
        (json.dumps({"schema": 2, "modes": {}}), "not an eval_crisis.py --json report"),
        (json.dumps({"schema": 1, "modes": {}}), "no modes"),
        (json.dumps({"schema": 1, "modes": {"model": {"recall": {}}}}), "has no categories"),
        (
            json.dumps(
                {
                    "schema": 1,
                    "modes": {"model": {**_report()["modes"]["model"], "recall": {"k": 3, "n": 2}}},
                }
            ),
            "need integers 0 <= k <= n",
        ),
        (
            json.dumps(
                {
                    "schema": 1,
                    "modes": {
                        "model": {
                            **_report()["modes"]["model"],
                            "false_alarm": {"k": 1, "n": 2, "ci95": [0.6, 0.2]},
                        }
                    },
                }
            ),
            "ci95 must be [low, high]",
        ),
        (
            json.dumps(
                {
                    "schema": 1,
                    "modes": {"model": {**_report()["modes"]["model"], "categories": {"x": 1}}},
                }
            ),
            "category x is not an object",
        ),
    ],
)
def test_unusable_reports_are_exit_2(tmp_path, capsys, content, message):
    bad = tmp_path / "bad.json"
    bad.write_text(content, encoding="utf-8")
    good = _write(tmp_path, "good.json", _report())
    assert cmp.main([str(good), str(bad)]) == 2
    assert message in capsys.readouterr().err


def test_missing_report_and_no_shared_mode_are_exit_2(tmp_path, capsys):
    good = _write(tmp_path, "good.json", _report(modes=("model",)))
    assert cmp.main([str(good), str(tmp_path / "missing.json")]) == 2
    assert "cannot read" in capsys.readouterr().err
    other = _write(tmp_path, "other.json", _report(modes=("rules",)))
    assert cmp.main([str(good), str(other)]) == 2
    assert "share no mode" in capsys.readouterr().err
