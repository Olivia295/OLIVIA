"""``scripts/safety_report.py``: one command, counts only, exit 1 when any check fails.

Every script it runs is replaced by canned output, except the evaluation script, which runs
in this process on made-up CSVs of everyday placeholder sentences (rules mode only). The
known-gap files, the red-team categories and the mutation report are synthetic files in a
temporary folder, so nothing here reads build/eval, runs the privacy audit or loads the
student.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import sys
from collections.abc import Sequence
from datetime import date, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str) -> ModuleType:
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, ROOT / f"scripts/{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


sr = _load("safety_report")
ev = _load("eval_crisis")

GIT = {
    ("rev-parse", "HEAD"): "0123456789abcdef0123456789abcdef01234567",
    ("rev-parse", "--short", "HEAD"): "0123456",
    ("rev-parse", "--abbrev-ref", "HEAD"): "feat/test",
    ("status", "--porcelain"): "",
}
STUDENT = "student:feedc0de"

_TRANSFORMS = """
按变换（不变率；失败的 种子id/变换）：
  [句首语气词]
    prefix_a             4/4 = 100.00%  失败 0
    prefix_b             3/4 = 75.00%  失败 1
      s1/prefix_b
  [句末语气]
    suffix_a             2/4 = 50.00%  失败 2
      s1/suffix_a, s2/suffix_a
    suffix_b             4/4 = 100.00%  失败 0
    suffix_c             3/4 = 75.00%  失败 1
      s3/suffix_c
    a_very_long_transform_name 4/4 = 100.00%  失败 0
    nothing_judged       0/0  失败 0

按种子类别（不变率；失败数）：
  BENIGN                       20/24 = 83.33%  失败 4
"""


def _meta(mode: str, label: str) -> str:
    return (
        f"== 变形测试 · 模式 {mode} · 实际运行的风险模型：{label} ==\n"
        "种子：4 个；变换：7 种\n"
        "跳过（原句本身就没达到期望，已知缺口）：无\n"
        "总不变率（L2/L3 不掉档，L0 不升到 L2 及以上）：20/24 = 83.33%\n" + _TRANSFORMS
    )


HAZARD_LINE = (
    "hazard log: 4 hazards, 1 已控制, 2 部分控制, 0 开放, 1 待 G-0; "
    "residual risk >= 3: HAZ-01, HAZ-03"
)
HAZARD_TABLE = """| 编号 | 危害 | 初始风险 | 残余风险 | 状态 |
| :--- | :--- | :--- | :--- | :--- |
| HAZ-01 | 甲 | 灾难性 / 高 → 5 | 灾难性 / 中 → 4 | 部分控制 |
| HAZ-02 | 乙 | 重大 / 中 → 3 | 重大 / 极低 → 2 | 已控制 |
| HAZ-03 | 丙 | 重大 / 中 → 3 | 重大 / 低 → 3 | 待 G-0 |
| HAZ-04 | 丁 | 较大 / 中 → 3 | 较大 / 极低 → 2 | 部分控制 |
"""
PRIVACY_PASS = """check                     result  detail
------------------------  ------  ------
network-imports           PASS    9 modules scanned
permissions [switch-off]  SKIP    Windows: POSIX modes do not apply
forget-all-clean [on]     PASS    no file, no keychain item

privacy audit: all checks passed (1.0 s)
"""
PRIVACY_FAIL = PRIVACY_PASS.replace(
    "forget-all-clean [on]     PASS", "forget-all-clean [on]     FAIL"
).replace("all checks passed", "1 check(s) failed")
TRACE = "trace: 3 requirement ids, 2 covered, 1 partial, 0 exempt\n"
HOTLINE = "OK: all 2 entries verified within 90 days of 2026-11-25 (data compiled 2026-10-25).\n"
HOTLINE_STALE = (
    "STALE: 1 of 2 entries were last verified more than 90 days before 2027-02-01:\n"
    "  CN x: verified 2026-10-25 (99 days)\n"
)
DATES = sr.HotlineDates(2, date(2026, 10, 25), date(2026, 11, 20), date(2026, 10, 25), 90)


class Fake:
    """Stands in for :func:`safety_report.run_command`."""

    def __init__(
        self,
        codes: dict[str, int] | None = None,
        *,
        eval_document: dict[str, Any] | None = None,
        model_label: str = STUDENT,
    ) -> None:
        self.codes = codes or {}
        self.eval_document = eval_document
        self.model_label = model_label
        self.calls: list[list[str]] = []

    def scripts(self) -> list[str]:
        return [Path(c[1]).name for c in self.calls if c[0] != "git"]

    def __call__(self, args: Sequence[str]) -> Any:
        args = list(args)
        self.calls.append(args)
        if args[0] == "git":
            return sr.Proc(0, GIT[tuple(args[1:])] + "\n", "")
        script, rest = Path(args[1]).name, args[2:]
        code = self.codes.get(script, 0)
        if script == "eval_crisis.py":
            return self._eval(rest)
        if script == "metamorphic_report.py":
            mode = rest[rest.index("--mode") + 1]
            label = "rules-only" if mode == "rules" else self.model_label
            return sr.Proc(code, _meta(mode, label) if code == 0 else "", "")
        if script == "check_hazard_log.py":
            if "--table" in rest:
                return sr.Proc(0, HAZARD_TABLE, "")
            err = "hazard log: HAZ-01: a problem\nhazard log: HAZ-02: another\n"
            return sr.Proc(code, "" if code else HAZARD_LINE + "\n", err if code else "")
        if script == "check_hotline_freshness.py":
            return sr.Proc(code, HOTLINE_STALE if code else HOTLINE, "")
        if script == "privacy_audit.py":
            return sr.Proc(code, PRIVACY_FAIL if code else PRIVACY_PASS, "")
        if script == "trace_requirements.py":
            return sr.Proc(code, "" if code else TRACE, "trace: Q-1: missing\n" if code else "")
        raise AssertionError(f"unexpected command {args}")

    def _eval(self, rest: list[str]) -> Any:
        if self.eval_document is not None:
            out = Path(rest[rest.index("--json") + 1])
            out.write_text(json.dumps(self.eval_document, ensure_ascii=False), encoding="utf-8")
            return sr.Proc(0, "", "")
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
            code = ev.main(rest)
        return sr.Proc(code, buffer.getvalue(), buffer.getvalue())


# -- synthetic inputs -----------------------------------------------------------------------

CASES = """- id: c1
  category: passive_ideation
- id: c2
  category: number_leak
- id: c3
  category: everyday_hyperbole
- id: c4
  category: prescription
"""
SCENARIOS = """- id: m1
  category: gradual_disclosure
- id: m2
  category: retraction
"""
# The three header shapes the real files use: counts by kind with categories in brackets;
# nested categories, a stale kind line and a wrapped breakdown on the total; per mode.
RULES_GAPS = """# Synthetic gaps.
#
# Count by kind and category:
#   crisis recall: 2 (passive_ideation 1, number_leak 1)
#   rules false alarm: 1 (everyday_hyperbole 1)
#   total: 3

gaps:
  - id: c1
    reason: "crisis recall: passive_ideation, rules mode highest level L1 < L2"
  - id: c2
    reason: "crisis recall: number_leak, rules mode highest level L2 < L3"
  - id: c3
    reason: "rules false alarm: everyday_hyperbole, rules mode highest level L2, crisis_below L2"
"""
MODEL_GAPS = """# Synthetic gaps.
#
# What is left:
#   crisis recall: 1
#     number_leak: 1 (c2 needs L3; closed 2026-11-25 for the
#                  others)
#     passive_ideation: 0 (c1 closed)
#   model false alarm: 1 (the student raises one everyday case)
#   asked first: 4 (an older count; all four closed since (0))
#   total: 2 (1 crisis recall, 1 model
#          false alarm)
# A later note mentions passive_ideation 7 times without being a count.

gaps:
  - id: c2
    reason: "crisis recall: number_leak, model mode highest level L2 < L3"
  - id: c4
    reason: "model false alarm: prescription, model mode highest level L2, crisis_below L2"
"""
MULTITURN_GAPS = """# Synthetic scenarios.
#   rules: 3 of 5 fail (crisis recall 2, other 1); 2 pass
# A later change: rules: 1 of 5 fail; model: 2 of 5
# fail.

rules:
  - id: m1
    reason: "crisis recall: 第3轮没有到期望的等级。"
model:
  - id: m1
    reason: "crisis recall + model false alarm: 第2轮先进了危机流程。"
  - id: m2
    reason: "model false alarm: 第1轮进了危机流程。"
"""
MUTATION = """# 变异测试（测试用）

## 工具

| 不是 | 这张 |
| --- | --- |

## 结果

说明文字。

| 文件 | 变异总数 | 存活 |
| --- | ---: | ---: |
| a.py | 10 | 1 |

## 其他

| x | y |
"""


@pytest.fixture
def inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Synthetic gap, case and mutation files; fixed hotline dates."""
    folder = tmp_path / "inputs"
    folder.mkdir()
    files = {
        "cases.yaml": CASES,
        "multiturn.yaml": SCENARIOS,
        "known_gaps.yaml": RULES_GAPS,
        "known_gaps_model.yaml": MODEL_GAPS,
        "known_gaps_multiturn.yaml": MULTITURN_GAPS,
        "mutation-report.md": MUTATION,
    }
    for name, text in files.items():
        (folder / name).write_text(text, encoding="utf-8")
    monkeypatch.setattr(
        sr, "CASE_FILES", (str(folder / "cases.yaml"), str(folder / "multiturn.yaml"))
    )
    monkeypatch.setattr(
        sr,
        "GAP_FILES",
        (
            (str(folder / "known_gaps.yaml"), "单句 · 规则模式"),
            (str(folder / "known_gaps_model.yaml"), "单句 · 模型模式"),
            (str(folder / "known_gaps_multiturn.yaml"), "多轮"),
        ),
    )
    monkeypatch.setattr(sr, "MUTATION_REPORT", str(folder / "mutation-report.md"))
    monkeypatch.setattr(sr, "hotline_dates", lambda root: DATES)
    return folder


def _report(
    tmp_path: Path, fake: Fake, *extra: str, eval_dir: Path | None = None
) -> tuple[int, str]:
    out = tmp_path / "reports" / "evidence.md"
    folder = eval_dir if eval_dir is not None else tmp_path / "not-here"
    code = sr.main(["--eval-dir", str(folder), "--out", str(out), *extra], run=fake)
    return code, out.read_text(encoding="utf-8")


# Everyday placeholder sentences, nothing about risk; some carry an L2 label only so the
# recall has rows to count.
ROWS = [
    ("ph-dev-01", "今天下午去图书馆还了两本书", "L0"),
    ("ph-dev-02", "周末想把阳台上的绿萝换个大盆", "L0"),
    ("ph-dev-03", "晚饭打算做番茄炒蛋和紫菜汤", "L2"),
    ("ph-dev-04", "明天早上八点半有一个组会要开", "L1"),
    ("ph-dev-05", "新买的耳机降噪效果还挺不错", "L2"),
]


def _csvs(folder: Path, rows: Sequence[tuple[str, str, str]] = ROWS) -> list[tuple[str, str]]:
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for prefix, name in (("dev", "interim_fresh.csv"), ("e4", "eval4.csv")):
        lines = ["id,text,level,category"]
        for row_id, text, level in rows:
            new_id = row_id.replace("dev", prefix)
            lines.append(f"{new_id},{text},{level},占位类别")
            written.append((new_id, text))
        (folder / name).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return written


# -- the four cases the task names ------------------------------------------------------------


def test_missing_evaluation_sets_are_skipped(tmp_path, inputs, capsys):
    fake = Fake()
    code, page = _report(tmp_path, fake)
    assert code == 0
    assert "- 开发集（`interim_fresh.csv`）：评估集不在本机，跳过。" in page
    assert "- EVAL-4（`eval4.csv`）：评估集不在本机，跳过。" in page
    assert "| 危机识别 · 开发集 | 跳过 |" in page and "| 危机识别 · EVAL-4 | 跳过 |" in page
    assert "eval_crisis.py" not in fake.scripts()
    assert fake.scripts().count("metamorphic_report.py") == 2
    assert "开发集用于选型，EVAL-4 只报告" in page
    # The header: commit, date, the risk models that ran, Python.
    assert "`0123456789abcdef0123456789abcdef01234567`" in page
    assert "规则（rules-only）；学生模型：student:feedc0de" in page
    assert "- Python：CPython " in page and "- 日期：" in page
    assert "（退出码 0）" in page
    out = capsys.readouterr().out
    assert "跳过  危机识别 · 开发集" in out and "0 项失败" in out


@pytest.mark.parametrize(
    ("script", "check"),
    [
        ("check_hazard_log.py", "危害日志"),
        ("privacy_audit.py", "隐私审计"),
        ("trace_requirements.py", "需求追溯"),
        ("check_hotline_freshness.py", "热线时效"),
        ("metamorphic_report.py", "变形测试 · rules"),
    ],
)
def test_any_failed_check_makes_the_exit_status_1(tmp_path, inputs, script, check):
    code, page = _report(tmp_path, Fake({script: 1}))
    assert code == 1
    assert f"| {check} | 失败 |" in page
    assert "（退出码 1）" in page


def test_the_report_never_holds_the_csv_text_or_ids(tmp_path, inputs, capsys):
    folder = tmp_path / "eval"
    written = _csvs(folder)
    fake = Fake()
    code, page = _report(tmp_path, fake, "--skip-model", eval_dir=folder)
    assert code == 0
    assert fake.scripts().count("eval_crisis.py") == 2
    assert "| 开发集（用于选型） | rules | rules-only | 0/2 = 0.0%（95% 区间 0.0%–65.8%）" in page
    assert "| EVAL-4（只报告） | rules | rules-only |" in page
    assert "| 0/2 = 0.0%（95% 区间 0.0%–65.8%） |" in page  # the two L0 rows
    assert "学生模型：未运行（--skip-model）" in page
    jsons = sorted((tmp_path / "reports").glob("evidence.*.json"))
    assert [p.name for p in jsons] == ["evidence.dev.json", "evidence.eval4.json"]
    shown = page + capsys.readouterr().out + "".join(p.read_text(encoding="utf-8") for p in jsons)
    assert written and not [t for pair in written for t in pair if t in shown]


def test_a_gap_count_that_differs_from_the_header_is_reported(tmp_path, inputs):
    gaps = inputs / "known_gaps.yaml"
    text = gaps.read_text(encoding="utf-8")
    text = text.replace("total: 3", "total: 4")
    gaps.write_text(
        text.replace("(everyday_hyperbole 1)", "(everyday_hyperbole 2)"), encoding="utf-8"
    )
    multiturn = inputs / "known_gaps_multiturn.yaml"
    text = multiturn.read_text(encoding="utf-8").replace("model: 2 of 5", "model: 3 of 5")
    multiturn.write_text(text, encoding="utf-8")
    code, page = _report(tmp_path, Fake())
    assert code == 1
    assert "条目与文件头不一致：" in page
    assert "- known_gaps.yaml 总数：条目 3 条，文件头写 4" in page
    assert "- known_gaps.yaml rules false alarm · everyday_hyperbole：条目 1 条，文件头写 2" in (
        page
    )
    assert "- known_gaps_multiturn.yaml（model） 总数：条目 2 条，文件头写 3" in page
    assert "条目 3 条，文件头写 4（不一致）。" in page
    assert "| 红队与多轮 · 缺口计数 | 失败 | 3 处与文件头不一致或读不出 |" in page


# -- the other parts --------------------------------------------------------------------------


def test_gap_counts_agree_with_each_header_shape(tmp_path, inputs):
    code, page = _report(tmp_path, Fake())
    assert code == 0
    assert "| crisis recall | 2 | 2 | number_leak 1、passive_ideation 1 |" in page
    assert "| rules false alarm | 1 | 1 | everyday_hyperbole 1 |" in page
    assert "| model false alarm | 1 | 1 | prescription 1 |" in page
    assert "| rules | 1 | 1 | crisis recall 1 | gradual_disclosure 1 |" in page
    assert (
        "| model | 2 | 2 | model false alarm 2、crisis recall 1 "
        "| gradual_disclosure 1、retraction 1 |"
    ) in page
    assert "| 红队与多轮 · 缺口计数 | 通过 |" in page


def test_header_claims_read_the_latest_and_wrapped_statements(inputs):
    categories = sr.case_categories(Path("/"))
    gap_file = sr.load_gap_file(inputs / "known_gaps_model.yaml", "t", "x.yaml", categories)
    assert gap_file.claims == {
        ("", "", ""): 2,
        ("", "crisis recall", ""): 1,
        ("", "model false alarm", ""): 1,
        ("", "crisis recall", "number_leak"): 1,
        ("", "crisis recall", "passive_ideation"): 0,
    }
    assert gap_file.mismatches() == []


def test_a_header_without_a_total_or_an_unreadable_file_fails(tmp_path, inputs):
    gaps = inputs / "known_gaps.yaml"
    text = gaps.read_text(encoding="utf-8").replace("#   total: 3\n", "")
    gaps.write_text(text, encoding="utf-8")
    (inputs / "known_gaps_multiturn.yaml").write_text("- just a list\n", encoding="utf-8")
    code, page = _report(tmp_path, Fake())
    assert code == 1
    assert "- known_gaps.yaml：文件头没有写总数" in page
    assert "known_gaps_multiturn.yaml`：读不出来。" in page


def test_evaluation_that_fails_reports_only_its_exit_status(tmp_path, inputs):
    folder = tmp_path / "eval"
    _csvs(folder, [("ph-bad-01", "今天天气不错", "L0"), ("ph-bad-02", "", "L0")])
    code, page = _report(tmp_path, Fake(), "--skip-model", eval_dir=folder)
    assert code == 1
    assert "`eval_crisis.py` 退出码 2。" in page
    assert "ph-bad" not in page


def test_model_mode_that_fell_back_to_rules_fails(tmp_path, inputs):
    folder = tmp_path / "eval"
    _csvs(folder)
    proportion = {"k": 1, "n": 2, "rate": 0.5, "ci95": [0.094, 0.906]}
    mode = {"risk_models": {}, "recall": proportion, "false_alarm": proportion}
    document = {
        "rows": 5,
        "modes": {
            "rules": {**mode, "risk_models": {"rules-only": 5}},
            "model": {**mode, "risk_models": {"rules-only（missing）": 5}},
        },
    }
    fake = Fake(eval_document=document, model_label="rules-only")
    code, page = _report(tmp_path, fake, eval_dir=folder)
    assert code == 1
    assert "| 危机识别 · 开发集 | 失败 | 模型模式没有加载学生模型 |" in page
    assert "| 变形测试 · model | 失败 | 模型模式没有加载学生模型 |" in page
    assert "1/2 = 50.0%（95% 区间 9.4%–90.6%）" in page
    assert "学生模型：没有加载" in page


def test_metamorphic_rates_and_the_worst_five(tmp_path, inputs):
    parsed = sr.parse_metamorphic(_meta("rules", "rules-only"))
    assert parsed is not None and (parsed.held, parsed.judged) == (20, 24)
    assert [t.name for t in parsed.worst()] == [
        "suffix_a",
        "prefix_b",
        "suffix_c",
        "a_very_long_transform_name",
        "prefix_a",
    ]
    assert len(parsed.transforms) == 7 and parsed.transforms[0].family == "句首语气词"
    assert sr.parse_metamorphic("no report here") is None
    _, page = _report(tmp_path, Fake())
    assert "| rules | rules-only | 20/24 = 83.33% | 7 | 无 |" in page
    assert "| `suffix_a` | 句末语气 | 2/4 = 50.00% | 2 |" in page


def test_hazards_by_status_and_residual_risk(tmp_path, inputs):
    _, page = _report(tmp_path, Fake())
    assert "| 状态 | 残余 1 | 残余 2 | 残余 3 | 残余 4 | 残余 5 | 合计 |" in page
    assert "| 部分控制 | 0 | 1 | 0 | 1 | 0 | 2 |" in page
    assert "| 开放 | 0 | 0 | 0 | 0 | 0 | 0 |" in page  # a status with no hazard still shows
    assert "| 合计 | 0 | 2 | 1 | 1 | 0 | 4 |" in page
    assert "残余风险 ≥ 3（2 条）：HAZ-01（4）、HAZ-03（3）。" in page
    code, page = _report(tmp_path, Fake({"check_hazard_log.py": 1}))
    assert code == 1 and "check_hazard_log.py 退出码 1，2 个问题" in page


def test_mutation_table_is_quoted_and_a_missing_report_fails(tmp_path, inputs):
    _, page = _report(tmp_path, Fake())
    assert "| a.py | 10 | 1 |" in page and "| x | y |" not in page and "| 不是 |" not in page
    assert "变异测试（测试用）" in page
    (inputs / "mutation-report.md").unlink()
    code, page = _report(tmp_path, Fake())
    assert code == 1 and "| 变异测试 | 失败 |" in page
    found = sr.mutation_table("# t\n\n| 文件 | 变异总数 |\n| --- | --- |\n")
    assert found is not None and found[1][0].startswith("| 文件")


def test_hotline_dates_and_deadline(tmp_path, inputs, monkeypatch):
    _, page = _report(tmp_path, Fake())
    assert "- 最近核验日期：2026-11-20（最早一条 2026-10-25）。" in page
    assert "- 复核截止日期：2027-01-23（最早的核验日期 + 90 天" in page
    code, page = _report(tmp_path, Fake({"check_hotline_freshness.py": 1}))
    assert code == 1 and "1/2 条过期" in page

    def broken(root: Path) -> Any:
        raise OSError("unreadable")

    monkeypatch.setattr(sr, "hotline_dates", broken)
    code, page = _report(tmp_path, Fake())
    assert code == 1 and "没能读出打包热线数据的核验日期" in page


def test_privacy_audit_counts_and_failed_names(tmp_path, inputs):
    _, page = _report(tmp_path, Fake())
    assert "3 项，PASS 2、FAIL 0、SKIP 1。" in page
    _, page = _report(tmp_path, Fake({"privacy_audit.py": 1}))
    assert "失败的检查：`forget-all-clean [on]`。" in page
    assert "Windows: POSIX" not in page  # details are never copied


def test_packaged_hotline_dates():
    dates = sr.hotline_dates(ROOT)
    assert dates.entries > 0 and dates.earliest <= dates.latest
    assert dates.deadline == dates.earliest + timedelta(days=dates.max_age_days)


def test_run_command(monkeypatch):
    done = sr.run_command([sys.executable, "-c", "import os; print(os.environ['PYTHONPATH'])"])
    assert done.code == 0 and done.out.strip().split(os.pathsep)[0] == str(sr.ROOT)
    assert sr.run_command([str(ROOT / "no-such-program")]).code == sr.NOT_RUN
    monkeypatch.setattr(sr, "TIMEOUT_S", 0.2)
    assert sr.run_command([sys.executable, "-c", "import time; time.sleep(5)"]).code == sr.TIMED_OUT


def test_default_output_is_under_the_ignored_build_folder():
    assert sr.default_out(ROOT, "abc1234") == ROOT / "build/reports/safety-evidence-abc1234.md"
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "build/" in ignored


def test_display_path():
    assert sr.display_path(ROOT / "build" / "eval", ROOT) == "build/eval"
    assert sr.display_path(Path.home() / "x" / "y", ROOT) == "~/x/y"
