"""``scripts/metamorphic_report.py``: the rates, the gap file it writes, and never a sentence."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from olivia.core.perception.student import RiskChoice
from tests.safety.metamorphic import GAPS_FILE, load_seeds

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "metamorphic_report", ROOT / "scripts/metamorphic_report.py"
)
assert _spec is not None and _spec.loader is not None
mr = importlib.util.module_from_spec(_spec)
sys.modules["metamorphic_report"] = mr
_spec.loader.exec_module(mr)

SEEDS = load_seeds()
# Long enough not to occur inside a transform's label or a category name by chance.
SENTENCES = [seed.text for seed in SEEDS if len(seed.text) >= 6]


def test_rules_report_writes_the_committed_gap_file(tmp_path, monkeypatch, capsys):
    target = tmp_path / "gaps.yaml"
    monkeypatch.setattr(mr, "GAPS_FILE", target)
    assert mr.main(["--write-gaps"]) == 0
    out = capsys.readouterr().out
    assert "实际运行的风险模型：rules-only" in out
    assert "总不变率（L2/L3 不掉档，L0 不升到 L2 及以上）：" in out
    assert "跳过（原句本身就没达到期望，已知缺口）：known_limits" in out
    assert "L1 种子（只报告）：变体与原句同级 " in out
    assert target.read_text(encoding="utf-8") == GAPS_FILE.read_text(encoding="utf-8")
    assert not [text for text in SENTENCES if text in out]


def test_model_mode_runs_the_student_and_only_reports(monkeypatch, capsys):
    few = [seed for seed in SEEDS if seed.id in {"m01", "b71", "cp034", "cn001"}]
    assert len(few) == 4
    monkeypatch.setattr(mr, "load_seeds", lambda: few)
    assert mr.main(["--mode", "model"]) == 0
    out = capsys.readouterr().out
    assert "== 变形测试 · 模式 model · 实际运行的风险模型：student:" in out
    assert not [seed.text for seed in few if seed.text in out]
    with pytest.raises(SystemExit):
        mr.main(["--mode", "model", "--write-gaps"])


def test_model_mode_without_the_student_exits_2(monkeypatch, capsys):
    monkeypatch.setattr(
        mr, "choose_risk_model", lambda student: RiskChoice("rules-only", "missing", None)
    )
    assert mr.main(["--mode", "model"]) == 2
    assert "missing" in capsys.readouterr().err
