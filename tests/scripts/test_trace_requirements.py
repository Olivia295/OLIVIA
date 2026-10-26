"""``scripts/trace_requirements.py`` on a synthetic tree and on the repository itself."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "trace_requirements", ROOT / "scripts/trace_requirements.py"
)
assert _spec is not None and _spec.loader is not None
trace = importlib.util.module_from_spec(_spec)
sys.modules["trace_requirements"] = trace
_spec.loader.exec_module(trace)


def _tree(tmp_path: Path, trace_yaml: str, prd: str = "ONB-01 与 G-1。") -> Path:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/PRODUCT_DOCUMENT.md").write_text(prd, encoding="utf-8")
    (tmp_path / "docs/SYSTEM_DESIGN.md").write_text("SAFE-1 是步骤名。", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_x.py").write_text(
        "class TestAge:\n    def test_gate(self):\n        pass\n\ndef test_plain():\n    pass\n",
        encoding="utf-8",
    )
    (tmp_path / "tests/requirements_trace.yaml").write_text(trace_yaml, encoding="utf-8")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/audit.py").write_text("", encoding="utf-8")
    (tmp_path / "scripts/idle.py").write_text("", encoding="utf-8")
    (tmp_path / "scripts/check.sh").write_text('"$PY" scripts/audit.py\n', encoding="utf-8")
    return tmp_path


_GOOD = """
ONB-01:
  status: covered
  summary: 年龄门禁
  tests: [tests/test_x.py::TestAge::test_gate, tests/test_x.py::test_plain]
G-1:
  status: covered
  summary: 断网
  checks: [scripts/audit.py]
"""


def test_document_ids_skip_plan_step_names(tmp_path: Path) -> None:
    root = _tree(tmp_path, _GOOD, prd="ONB-04b、COLBO-07、SAFE-09、NG-10、Q-8、G-5、XONB-1")
    assert trace.document_ids(root) == {"ONB-04b", "COLBO-07", "SAFE-09", "NG-10", "Q-8", "G-5"}


def test_complete_trace_has_no_problems(tmp_path: Path) -> None:
    entries, problems = trace.validate(_tree(tmp_path, _GOOD))
    assert problems == []
    assert set(entries) == {"ONB-01", "G-1"}


@pytest.mark.parametrize(
    ("trace_yaml", "expected"),
    [
        (
            "ONB-01: {status: covered, summary: x, tests: [tests/test_x.py::test_plain]}\n",
            "G-1: named in the documents but missing",
        ),
        (
            _GOOD + "ONB-99: {status: exempt, summary: x, reason: y}\n",
            "ONB-99: in tests/requirements_trace.yaml but no longer named",
        ),
        (_GOOD.replace("test_plain", "test_gone"), "defines no test_gone"),
        (
            _GOOD.replace("tests/test_x.py::TestAge", "tests/test_y.py::TestAge"),
            "test file tests/test_y.py does not exist",
        ),
        (_GOOD.replace("scripts/audit.py", "scripts/idle.py"), "is not run by"),
        (
            _GOOD.replace("status: covered\n  summary: 断网", "status: exempt\n  summary: 断网"),
            "G-1: exempt needs a reason",
        ),
        (
            _GOOD.replace("status: covered\n  summary: 断网", "status: done\n  summary: 断网"),
            "G-1: status must be one of",
        ),
        (
            "ONB-01: {status: partial, summary: x, reason: y}\n"
            "G-1: {status: exempt, summary: z, reason: w}\n",
            "ONB-01: partial needs at least one test or check",
        ),
        (_GOOD.replace("summary: 年龄门禁", "summary: ''"), "ONB-01: summary is empty"),
    ],
)
def test_each_gap_is_reported(tmp_path: Path, trace_yaml: str, expected: str) -> None:
    _, problems = trace.validate(_tree(tmp_path, trace_yaml))
    assert any(expected in p for p in problems), problems


def test_markdown_lists_evidence(tmp_path: Path) -> None:
    entries, _ = trace.validate(_tree(tmp_path, _GOOD))
    table = trace.markdown(entries)
    assert "| ONB-01 | covered | 年龄门禁 | `tests/test_x.py::TestAge::test_gate`" in table
    assert table.index("ONB-01") < table.index("G-1")


def test_repository_trace_is_complete() -> None:
    _, problems = trace.validate(ROOT)
    assert problems == []
