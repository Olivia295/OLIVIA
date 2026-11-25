"""``scripts/check_hazard_log.py`` on a synthetic tree and on the repository itself."""

from __future__ import annotations

import copy
import importlib.util
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "check_hazard_log", ROOT / "scripts/check_hazard_log.py"
)
assert _spec is not None and _spec.loader is not None
hazard = importlib.util.module_from_spec(_spec)
sys.modules["check_hazard_log"] = hazard
_spec.loader.exec_module(hazard)

Body = dict[str, Any]

_GOOD: Body = {
    "id": "HAZ-01",
    "title": "漏判",
    "hazard": "危机句没有进入危机流程",
    "cause": ["词表不全"],
    "effect": "没有热线",
    "initial": {"severity": "灾难性", "likelihood": "高", "risk": 5},
    "controls": ["olivia/core/x.py 筛查", "PRD §9.1"],
    "evidence": [
        "tests/test_x.py::test_plain",
        "tests/test_x.py::TestAge::test_gate",
        "tests/test_x.py::TestAge",
        "scripts/audit.py",
    ],
    "residual": {"severity": "灾难性", "likelihood": "中", "risk": 4},
    "status": "部分控制",
    "known_gaps": [
        {
            "file": "tests/redteam/known_gaps.yaml",
            "kind": "crisis recall",
            "category": "passive_ideation",
            "count": 1,
        },
        {
            "file": "tests/redteam/known_gaps_multiturn.yaml",
            "mode": "rules",
            "kind": "model false alarm",
            "ids": ["mt001"],
            "count": 1,
        },
    ],
}

_TEST_FILE = """\
class TestAge:
    def test_gate(self):
        pass


def test_plain():
    pass


def helper():
    pass
"""


def _block(body: Body) -> str:
    return "```yaml\n" + yaml.safe_dump(body, allow_unicode=True, sort_keys=False) + "```\n"


def _tree(tmp_path: Path, bodies: list[Body], *, table: bool = True) -> Path:
    for folder in ("docs/safety", "tests/redteam", "scripts", "olivia/core"):
        (tmp_path / folder).mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests/test_x.py").write_text(_TEST_FILE, encoding="utf-8")
    (tmp_path / "scripts/audit.py").write_text("", encoding="utf-8")
    (tmp_path / "olivia/core/x.py").write_text("", encoding="utf-8")
    redteam = tmp_path / "tests/redteam"
    (redteam / "cases.yaml").write_text(
        "- {id: rt001, category: passive_ideation}\n- {id: rt002, category: everyday_hyperbole}\n",
        encoding="utf-8",
    )
    (redteam / "multiturn.yaml").write_text(
        "- {id: mt001, category: gradual_disclosure}\n", encoding="utf-8"
    )
    (redteam / "known_gaps.yaml").write_text(
        "gaps:\n"
        "  - {id: rt001, reason: 'crisis recall: passive_ideation, rules mode L0 < L2'}\n"
        "  - {id: rt002, reason: 'rules false alarm: everyday_hyperbole, L2'}\n",
        encoding="utf-8",
    )
    (redteam / "known_gaps_multiturn.yaml").write_text(
        "rules:\n  - {id: mt001, reason: 'crisis recall + model false alarm: 第3轮'}\nmodel: []\n",
        encoding="utf-8",
    )
    blocks = "\n".join(_block(b) for b in bodies)
    log = tmp_path / hazard.LOG
    log.write_text(
        f"# 危害日志\n\n{hazard.SUMMARY_START}\n{hazard.SUMMARY_END}\n\n{blocks}", encoding="utf-8"
    )
    if table:
        hazards, _ = hazard.validate(tmp_path)
        text = log.read_text(encoding="utf-8").replace(
            hazard.SUMMARY_END, hazard.table(hazards) + "\n" + hazard.SUMMARY_END
        )
        log.write_text(text, encoding="utf-8")
    return tmp_path


def _changed(change: Callable[[Body], None]) -> Body:
    body = copy.deepcopy(_GOOD)
    change(body)
    return body


def _set(path: str, value: object) -> Callable[[Body], None]:
    def apply(body: Body) -> None:
        *keys, last = path.split(".")
        target: Any = body
        for key in keys:
            target = target[int(key)] if isinstance(target, list) else target[key]
        if isinstance(target, list):
            target[int(last)] = value
        else:
            target[last] = value

    return apply


def test_complete_log_has_no_problems(tmp_path: Path) -> None:
    hazards, problems = hazard.validate(_tree(tmp_path, [_GOOD]))
    assert problems == []
    assert [h.hazard_id for h in hazards] == ["HAZ-01"]
    assert hazards[0].gap_count == 2


def test_the_matrix_rises_with_severity_and_likelihood() -> None:
    for row in hazard.RISK_MATRIX:
        assert list(row) == sorted(row)
    for column in zip(*hazard.RISK_MATRIX, strict=True):
        assert list(column) == sorted(column)
    assert hazard.matrix_risk("轻微", "极低") == 1
    assert hazard.matrix_risk("灾难性", "极低") == 3
    assert hazard.matrix_risk("灾难性", "极高") == 5


def test_a_parametrized_test_id_names_its_function(tmp_path: Path) -> None:
    body = _changed(_set("evidence", ["tests/test_x.py::test_plain[case-1]"]))
    _, problems = hazard.validate(_tree(tmp_path, [body]))
    assert problems == []


_NO_GAPS = _set("known_gaps", [])


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (_set("id", "HAZ-1"), "id must look like HAZ-01"),
        (lambda b: b.pop("effect"), "missing effect"),
        (lambda b: b.update(extra=1), "unknown fields extra"),
        (_set("title", ""), "title must be non-empty text"),
        (_set("cause", "词表不全"), "cause: must be a list of non-empty strings"),
        (_set("initial.risk", 6), "risk must be a whole number from 1 to 5"),
        (_set("initial.risk", 4), "initial.risk is 4 but 灾难性 / 高 is 5"),
        (_set("residual.severity", "严重"), "residual.severity must be one of"),
        (_set("residual.likelihood", "偶尔"), "residual.likelihood must be one of"),
        (_set("controls", []), "needs at least one control"),
        (_set("controls", ["olivia/core/gone.py 筛查"]), "names olivia/core/gone.py"),
        (_set("evidence", []), "needs at least one piece of evidence"),
        (_set("evidence.0", "tests/test_x.py::test_gone"), "defines no test_gone"),
        (_set("evidence.0", "tests/test_y.py::test_plain"), "test file tests/test_y.py"),
        (_set("evidence.0", "tests/test_x.py::helper"), "tests/test_x.py::helper is not a test"),
        (_set("evidence.0", "tests/test_x.py::TestAge::test_other"), "defines no test_other"),
        (_set("evidence.0", "tests/test_x.py::TestGone::test_gate"), "no class TestGone"),
        (_set("evidence.0", "scripts/gone.py"), "neither a pytest node id nor a script"),
        (_set("evidence.0", "docs/x.md::test_plain"), "must name a tests/...py file"),
        (
            lambda b: b.update(
                initial={"severity": "重大", "likelihood": "低", "risk": 3},
            ),
            "residual risk 4 exceeds initial risk 3",
        ),
        (_set("status", "完成"), "status must be one of"),
        (_set("status", "已控制"), "已控制 cannot carry known gaps (2)"),
        (_set("known_gaps", {}), "known_gaps must be a list"),
        (_set("known_gaps.0.count", 2), "count is 2 but tests/redteam/known_gaps.yaml holds 1"),
        (_set("known_gaps.0.count", 0), "count must be a whole number of at least 1"),
        (_set("known_gaps.0.category", "number_leak"), "holds 0"),
        (_set("known_gaps.0.kind", "model false alarm"), "holds 0"),
        (_set("known_gaps.0.file", "tests/other.yaml"), "must be a tests/redteam/known_gaps"),
        (_set("known_gaps.0.file", "tests/redteam/known_gaps_x.yaml"), "does not exist"),
        (_set("known_gaps.0.mode", "rules"), "has no modes"),
        (_set("known_gaps.0.note", "x"), "unknown keys note"),
        (_set("known_gaps.1.ids", ["mt009"]), "mt009 not in"),
        (lambda b: b["known_gaps"][1].pop("mode"), "mode must be one of rules, model"),
    ],
)
def test_each_problem_is_reported(
    tmp_path: Path, change: Callable[[Body], None], expected: str
) -> None:
    _, problems = hazard.validate(_tree(tmp_path, [_changed(change)]))
    assert any(expected in p for p in problems), problems


def test_duplicate_ids_are_reported(tmp_path: Path) -> None:
    _, problems = hazard.validate(_tree(tmp_path, [_GOOD, _GOOD]))
    assert any("HAZ-01: duplicate id" in p for p in problems), problems


def test_a_block_that_is_not_yaml_is_reported(tmp_path: Path) -> None:
    root = _tree(tmp_path, [_GOOD])
    log = root / hazard.LOG
    log.write_text(log.read_text(encoding="utf-8") + "```yaml\nid: [HAZ-02\n```\n", "utf-8")
    _, problems = hazard.validate(root)
    assert any("not valid YAML" in p for p in problems), problems


def test_a_stale_summary_table_is_reported(tmp_path: Path) -> None:
    root = _tree(tmp_path, [_GOOD])
    log = root / hazard.LOG
    log.write_text(log.read_text(encoding="utf-8").replace("部分控制 |", "已控制 |"), "utf-8")
    _, problems = hazard.validate(root)
    assert any("summary table is out of date" in p for p in problems), problems


def test_a_missing_summary_table_is_reported(tmp_path: Path) -> None:
    root = _tree(tmp_path, [_GOOD])
    log = root / hazard.LOG
    log.write_text(log.read_text(encoding="utf-8").replace(hazard.SUMMARY_END, ""), "utf-8")
    _, problems = hazard.validate(root)
    assert any("no summary table" in p for p in problems), problems


def test_a_log_without_hazards_or_without_a_file_is_reported(tmp_path: Path) -> None:
    _, problems = hazard.validate(tmp_path)
    assert problems == [f"{hazard.LOG} does not exist"]
    _, problems = hazard.validate(_tree(tmp_path, []))
    assert any("no yaml hazard blocks" in p for p in problems), problems


def test_main_prints_the_summary_and_fails_on_problems(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(hazard, "ROOT", _tree(tmp_path, [_GOOD]))
    assert hazard.main([]) == 0
    out = capsys.readouterr().out
    assert "1 hazards" in out and "1 部分控制" in out and "residual risk >= 3: HAZ-01" in out
    assert hazard.main(["--table"]) == 0
    assert (
        "| HAZ-01 | 漏判 | 灾难性 / 高 → 5 | 灾难性 / 中 → 4 | 部分控制 |"
        in capsys.readouterr().out
    )

    bad = tmp_path / "bad"
    monkeypatch.setattr(hazard, "ROOT", _tree(bad, [_changed(_set("status", "完成"))]))
    assert hazard.main([]) == 1
    assert "status must be one of" in capsys.readouterr().err


def test_table_prints_even_when_only_the_table_is_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(hazard, "ROOT", _tree(tmp_path, [_GOOD], table=False))
    assert hazard.main([]) == 1
    assert "out of date" in capsys.readouterr().err
    assert hazard.main(["--table"]) == 0
    assert "| HAZ-01 |" in capsys.readouterr().out


def test_repository_hazard_log_is_valid() -> None:
    hazards, problems = hazard.validate(ROOT)
    assert problems == []
    assert len(hazards) >= 30


def test_the_quality_gate_runs_the_check() -> None:
    gate = (ROOT / "scripts/check.sh").read_text(encoding="utf-8")
    assert '"$PY" scripts/check_hazard_log.py' in gate
