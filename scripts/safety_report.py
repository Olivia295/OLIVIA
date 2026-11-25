#!/usr/bin/env python3
"""One command for the safety evidence: run every safety check and write one Markdown page.

    python scripts/safety_report.py [--eval-dir DIR] [--out PATH] [--skip-model]

Runs, in this order, each script as its own process from the repository root (with
``PYTHONPATH`` set to it, so this checkout's ``olivia`` is the code measured):

1. Crisis recognition: ``scripts/eval_crisis.py <csv> --mode both --json ...`` on the
   development set (``interim_fresh.csv``, used for choices) and on EVAL-4 (``eval4.csv``,
   reported only), each only when its CSV is under ``--eval-dir`` (default ``build/eval``;
   the sets are never in git). Only the JSON is read: L2+L3 recall and the L0 false-alarm
   rate, each ``k/n`` with its Wilson 95% interval, and the risk model that ran.
2. Metamorphic testing: ``scripts/metamorphic_report.py`` (rules) and ``--mode model``: the
   overall invariance rate and the five transforms with the lowest rate.
3. Red team and multi-turn: the entries of the three ``tests/redteam/known_gaps*.yaml``
   files counted by kind and category, and compared with the counts their header comment
   states (:func:`header_claims`); a difference is a failure.
4. Hazard log: ``scripts/check_hazard_log.py`` and its ``--table``: hazards by status and
   residual risk, and the ids with a residual risk of 3 or more.
5. Mutation testing: the summary table of ``docs/safety/mutation-report.md`` (read, not
   re-run).
6. Hotlines: ``scripts/check_hotline_freshness.py``, and from the packaged data it checks the
   latest ``verified_on`` date and the re-verification deadline (the earliest one plus the
   script's maximum age).
7. ``scripts/privacy_audit.py`` and ``scripts/trace_requirements.py``.

``--skip-model`` runs rules mode only (no packaged student). The page goes to ``--out``
(default ``build/reports/safety-evidence-<short commit>.md``; ``build/`` is git-ignored) and
each evaluation's JSON next to it (``<stem>.dev.json``, ``<stem>.eval4.json``: counts and
category names only), ready for ``scripts/compare_eval.py``.

**No sentence and no id of an evaluation set is ever printed or written.** Of an evaluation
run only the JSON's counts are read, and a failed run is reported by its exit status alone
(its error text can name a row id). Of every other script only counts, dates and fixed check
names are kept.

Exit status: 0 when no check failed (an evaluation set that is not on this machine is
skipped, not failed), 1 otherwise.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

EVAL_SCRIPT = "scripts/eval_crisis.py"
METAMORPHIC_SCRIPT = "scripts/metamorphic_report.py"
HAZARD_SCRIPT = "scripts/check_hazard_log.py"
HOTLINE_SCRIPT = "scripts/check_hotline_freshness.py"
PRIVACY_SCRIPT = "scripts/privacy_audit.py"
TRACE_SCRIPT = "scripts/trace_requirements.py"
MUTATION_REPORT = "docs/safety/mutation-report.md"

# (name, CSV file, JSON suffix, what it is for).
EVAL_SETS = (
    ("开发集", "interim_fresh.csv", "dev", "用于选型"),
    ("EVAL-4", "eval4.csv", "eval4", "只报告"),
)
# (file, what it holds); the cases files give each red-team id its category.
GAP_FILES = (
    ("tests/redteam/known_gaps.yaml", "单句 · 规则模式"),
    ("tests/redteam/known_gaps_model.yaml", "单句 · 模型模式"),
    ("tests/redteam/known_gaps_multiturn.yaml", "多轮"),
)
CASE_FILES = ("tests/redteam/cases.yaml", "tests/redteam/multiturn.yaml")
# The kinds a gap reason may start with (tests/redteam/test_redteam.py, test_multiturn.py).
GAP_KINDS = (
    "crisis recall",
    "rules false alarm",
    "model false alarm",
    "asked first",
    "early exit",
    "hotline",
    "other",
)

PASS, FAIL, SKIP = "通过", "失败", "跳过"
TIMEOUT_S = 3600
TIMED_OUT = -1
NOT_RUN = 127
WORST = 5
STUDENT_PREFIX = "student:"
NO_CATEGORY = "（未知类别）"


# -- running the scripts --------------------------------------------------------------------


@dataclass(frozen=True)
class Proc:
    """A finished command: exit status and captured output (never echoed as is)."""

    code: int
    out: str
    err: str


Runner = Callable[[Sequence[str]], Proc]


def run_command(args: Sequence[str]) -> Proc:
    """``args`` from the repository root, output captured; a timeout or a missing program
    is an exit status (:data:`TIMED_OUT`, :data:`NOT_RUN`), not an exception."""
    env = dict(os.environ)
    paths = [str(ROOT), env.get("PYTHONPATH", "")]
    env["PYTHONPATH"] = os.pathsep.join(p for p in paths if p)
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        done = subprocess.run(
            list(args),
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return Proc(TIMED_OUT, "", "")
    except OSError:
        return Proc(NOT_RUN, "", "")
    return Proc(done.returncode, done.stdout, done.stderr)


def python(script: str, *args: str) -> list[str]:
    return [sys.executable, script, *args]


def _exit(proc: Proc) -> str:
    if proc.code == TIMED_OUT:
        return f"超时（{TIMEOUT_S} 秒）"
    if proc.code == NOT_RUN:
        return "无法启动"
    return f"退出码 {proc.code}"


# -- report structure -----------------------------------------------------------------------


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    """:data:`PASS`, :data:`FAIL` or :data:`SKIP`."""
    note: str


@dataclass
class Section:
    title: str
    body: list[str] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)
    models: set[str] = field(default_factory=set)
    """Risk-model labels a run in this section reported."""

    def check(self, name: str, status: str, note: str) -> None:
        self.checks.append(Check(name, status, note))


def display_path(path: Path, root: Path) -> str:
    """``path`` relative to the repository when inside it, else with the home folder as ``~``."""
    resolved = path.resolve()
    try:
        return resolved.relative_to(root.resolve()).as_posix()
    except ValueError:
        pass
    home = Path.home().resolve()
    try:
        return "~/" + resolved.relative_to(home).as_posix()
    except ValueError:
        return resolved.as_posix()


def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def proportion(value: object) -> str:
    """``{k, n, ci95}`` of an ``eval_crisis.py --json`` report as ``k/n = r%（95% 区间 a–b）``."""
    if not isinstance(value, dict):
        raise ValueError("not a proportion")
    k, n, ci = value.get("k"), value.get("n"), value.get("ci95")
    if not (isinstance(k, int) and isinstance(n, int) and isinstance(ci, list) and len(ci) == 2):
        raise ValueError("not a proportion")
    if n == 0:
        return "0/0（没有这类样本）"
    low, high = float(ci[0]), float(ci[1])
    return f"{k}/{n} = {_pct(k / n)}（95% 区间 {_pct(low)}–{_pct(high)}）"


# -- 1. crisis recognition ------------------------------------------------------------------


def eval_section(
    run: Runner, eval_dir: Path, json_stem: Path, skip_model: bool, root: Path
) -> Section:
    section = Section("危机识别")
    mode = "rules" if skip_model else "both"
    expected = ("rules",) if skip_model else ("rules", "model")
    section.body += [
        f"评估集目录：`{display_path(eval_dir, root)}`。开发集用于选型，EVAL-4 只报告"
        "（不参与任何取舍）。召回：标注 L2/L3 的句子判到 L2 及以上；L0 误报：标注 L0 的句子"
        "判到 L2 及以上。区间为 Wilson 95% 区间。",
        "",
    ]
    rows: list[str] = []
    for name, csv_name, suffix, purpose in EVAL_SETS:
        check = f"危机识别 · {name}"
        csv_path = eval_dir / csv_name
        if not csv_path.is_file():
            section.body.append(f"- {name}（`{csv_name}`）：评估集不在本机，跳过。")
            section.check(check, SKIP, "评估集不在本机，跳过")
            continue
        out = json_stem.with_name(f"{json_stem.name}.{suffix}.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        proc = run(python(EVAL_SCRIPT, str(csv_path), "--mode", mode, "--json", str(out)))
        if proc.code != 0:
            # Its error text can name a row id: only the exit status is reported.
            section.body.append(f"- {name}（`{csv_name}`）：`eval_crisis.py` {_exit(proc)}。")
            section.check(check, FAIL, f"eval_crisis.py {_exit(proc)}")
            continue
        try:
            document = json.loads(out.read_text(encoding="utf-8"))
            modes = document["modes"]
            total = int(document["rows"])
            cells = {
                m: (
                    sorted(modes[m]["risk_models"]),
                    proportion(modes[m]["recall"]),
                    proportion(modes[m]["false_alarm"]),
                )
                for m in expected
            }
        except (OSError, ValueError, KeyError, TypeError):
            section.body.append(f"- {name}（`{csv_name}`）：JSON 读不出预期的字段。")
            section.check(check, FAIL, "JSON 读不出预期的字段")
            continue
        problems = []
        for m, (labels, recall, alarm) in cells.items():
            section.models.update(labels)
            rows.append(f"| {name}（{purpose}） | {m} | {'、'.join(labels)} | {recall} | {alarm} |")
            if m == "model" and not all(label.startswith(STUDENT_PREFIX) for label in labels):
                problems.append("模型模式没有加载学生模型")
        section.body.append(
            f"- {name}（`{csv_name}`）：{total} 条，{'、'.join(expected)} 模式；"
            f"统计 JSON：`{display_path(out, root)}`。"
        )
        if problems:
            section.check(check, FAIL, "；".join(problems))
        else:
            section.check(check, PASS, f"{total} 条，{'、'.join(expected)} 模式")
    if rows:
        section.body += [
            "",
            "| 评估集 | 模式 | 实际运行的风险模型 | L2+L3 召回 | L0 误报 |",
            "| :--- | :--- | :--- | :--- | :--- |",
            *rows,
            "",
            "两次运行的统计 JSON 可以用 `python scripts/compare_eval.py 旧.json 新.json` 比较。",
        ]
    return section


# -- 2. metamorphic testing -----------------------------------------------------------------


@dataclass(frozen=True)
class Transform:
    name: str
    family: str
    held: int
    judged: int
    failed: int


@dataclass(frozen=True)
class Metamorphic:
    label: str
    held: int
    judged: int
    skipped: str
    transforms: tuple[Transform, ...]

    def worst(self, n: int = WORST) -> list[Transform]:
        judged = [t for t in self.transforms if t.judged]
        return sorted(judged, key=lambda t: (t.held / t.judged, -t.failed, t.name))[:n]


_META_LABEL = re.compile(r"^== 变形测试 · 模式 \S+ · 实际运行的风险模型：(.+?) ==$")
_META_TOTAL = re.compile(r"^总不变率[^：]*：(\d+)/(\d+)")
_META_SKIPPED = re.compile(r"^跳过[^：]*：(.*)$")
_META_FAMILY = re.compile(r"^  \[(.+)\]$")
_META_TRANSFORM = re.compile(r"^    (\S+)\s+(\d+)/(\d+)(?: = [\d.]+%)?\s+失败 (\d+)\s*$")


def parse_metamorphic(text: str) -> Metamorphic | None:
    """The counts of a ``metamorphic_report.py`` report; ``None`` when its lines are missing."""
    label = total = skipped = None
    transforms: list[Transform] = []
    family = ""
    in_transforms = False
    for line in text.splitlines():
        if (m := _META_LABEL.match(line)) is not None:
            label = m.group(1)
        elif (m := _META_TOTAL.match(line)) is not None:
            total = (int(m.group(1)), int(m.group(2)))
        elif (m := _META_SKIPPED.match(line)) is not None:
            skipped = m.group(1)
        elif line.startswith("按变换"):
            in_transforms = True
        elif in_transforms and not line.strip():
            in_transforms = False
        elif in_transforms and (m := _META_FAMILY.match(line)) is not None:
            family = m.group(1)
        elif in_transforms and (m := _META_TRANSFORM.match(line)) is not None:
            held, judged, failed = (int(m.group(i)) for i in (2, 3, 4))
            transforms.append(Transform(m.group(1), family, held, judged, failed))
    if label is None or total is None or not transforms:
        return None
    return Metamorphic(label, total[0], total[1], skipped or "无", tuple(transforms))


def _rate(k: int, n: int) -> str:
    return f"{k}/{n} = {100 * k / n:.2f}%" if n else "0/0"


def metamorphic_section(run: Runner, skip_model: bool) -> Section:
    section = Section("变形测试")
    section.body.append(
        "每个种子句与它的每种保留原意的改写都过一遍危机筛查：L3 保持 L3、L2 不掉到 L2 以下、"
        "L0 不升到 L2 及以上才算不变。最差的变换按不变率从低到高排。"
    )
    modes = ("rules",) if skip_model else ("rules", "model")
    results: list[tuple[str, Metamorphic]] = []
    for mode in modes:
        check = f"变形测试 · {mode}"
        proc = run(python(METAMORPHIC_SCRIPT, "--mode", mode))
        parsed = parse_metamorphic(proc.out) if proc.code == 0 else None
        if parsed is None:
            why = _exit(proc) if proc.code != 0 else "输出里没有预期的统计行"
            section.body.append(f"\n- {mode}：`metamorphic_report.py` {why}。")
            section.check(check, FAIL, why)
            continue
        section.models.add(parsed.label)
        if mode == "model" and not parsed.label.startswith(STUDENT_PREFIX):
            section.check(check, FAIL, "模型模式没有加载学生模型")
        else:
            section.check(check, PASS, f"总不变率 {_rate(parsed.held, parsed.judged)}")
        results.append((mode, parsed))
    if results:
        section.body += [
            "",
            "| 模式 | 实际运行的风险模型 | 总不变率 | 变换数 | 跳过的种子（原句本身未达期望） |",
            "| :--- | :--- | :--- | ---: | :--- |",
        ]
        for mode, parsed in results:
            section.body.append(
                f"| {mode} | {parsed.label} | {_rate(parsed.held, parsed.judged)} "
                f"| {len(parsed.transforms)} | {parsed.skipped} |"
            )
    for mode, parsed in results:
        section.body += [
            "",
            f"{mode} 模式最差的 {WORST} 种变换：",
            "",
            "| 变换 | 类别 | 不变率 | 失败 |",
            "| :--- | :--- | :--- | ---: |",
        ]
        for t in parsed.worst():
            section.body.append(
                f"| `{t.name}` | {t.family} | {_rate(t.held, t.judged)} | {t.failed} |"
            )
    return section


# -- 3. red team and multi-turn known gaps ---------------------------------------------------


@dataclass(frozen=True)
class Gap:
    id: str
    kinds: tuple[str, ...]
    category: str


@dataclass
class GapFile:
    path: str
    title: str
    groups: dict[str, list[Gap]]
    """Mode to entries; ``""`` for a file with a single ``gaps`` list."""
    claims: dict[tuple[str, str, str], int]
    """(group, kind or ``""``, category or ``""``) to the count the header states."""

    def actual(self, group: str, kind: str, category: str) -> int:
        return sum(
            1
            for gap in self.groups.get(group, [])
            if (not kind or kind in gap.kinds) and (not category or gap.category == category)
        )

    def mismatches(self) -> list[str]:
        """Every stated count the entries do not bear out, and a group with no stated total."""
        found: list[str] = []
        for group in self.groups:
            if (group, "", "") not in self.claims:
                found.append(f"{self._where(group)}：文件头没有写总数")
        for (group, kind, category), stated in sorted(self.claims.items()):
            actual = self.actual(group, kind, category)
            if actual != stated:
                scope = " · ".join(s for s in (kind, category) if s) or "总数"
                found.append(f"{self._where(group)} {scope}：条目 {actual} 条，文件头写 {stated}")
        return found

    def _where(self, group: str) -> str:
        name = Path(self.path).name
        return f"{name}（{group}）" if group else name


def case_categories(root: Path) -> dict[str, str]:
    """Red-team case and scenario id to its category."""
    found: dict[str, str] = {}
    for path in CASE_FILES:
        file = root / path
        if not file.is_file():
            continue
        for item in yaml.safe_load(file.read_text(encoding="utf-8")) or []:
            if isinstance(item, dict) and "id" in item and "category" in item:
                found[str(item["id"])] = str(item["category"])
    return found


def _kinds(reason: str) -> tuple[str, ...]:
    head = reason.split(":", 1)[0]
    return tuple(k.strip() for k in head.split(" + ") if k.strip())


def _reason_category(reason: str) -> str | None:
    """``crisis recall: passive_ideation, ...`` gives ``passive_ideation``."""
    match = re.match(r"[^:]*:\s*([a-z][a-z_]*)\s*,", reason)
    return match.group(1) if match else None


def header_lines(text: str) -> list[tuple[int, str]]:
    """The comment block before the first YAML line: per line, the indent after ``#`` and
    the text."""
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            break
        body = stripped[1:]
        lines.append((len(body) - len(body.lstrip()), body.strip()))
    return lines


def _alternation(words: Iterable[str]) -> str:
    return "|".join(re.escape(w) for w in sorted(set(words), key=len, reverse=True))


def header_claims(
    header: Sequence[tuple[int, str]], groups: Sequence[str], categories: Iterable[str]
) -> dict[tuple[str, str, str], int]:
    """The counts a gap file's header comment states, by (group, kind, category).

    The header is read the way the gap files write it; a later statement replaces an
    earlier one, and a statement may wrap onto more indented lines:

    * a file with modes (``rules:`` / ``model:`` lists): the last ``<mode>: N of M fail``
      per mode is that mode's total;
    * a file with one ``gaps`` list: the last ``total: N`` is the total. When it goes on
      with ``(N kind, N kind ...)``, those are the counts by kind; otherwise each
      ``<kind>: N`` line is. A kind's categories are ``(category N, ...)`` on its line or
      ``category: N`` on the more indented lines under it (only known red-team categories
      count, so ids and dates in the prose never do).
    """
    claims: dict[tuple[str, str, str], int] = {}
    moded = [g for g in groups if g]
    if moded:
        prose = " ".join(text for _, text in header)
        for mode in moded:
            for found in re.finditer(rf"\b{re.escape(mode)}:\s*(\d+) of \d+\s+fail", prose):
                claims[(mode, "", "")] = int(found.group(1))
        return claims
    kinds_alt, cats_alt = _alternation(GAP_KINDS), _alternation(categories)
    total_re = re.compile(r"^total:\s*(\d+)\b(.*)$")
    kind_re = re.compile(rf"^({kinds_alt}):\s*(\d+)\b(.*)$")
    nested_re = re.compile(rf"^({cats_alt}):\s*(\d+)\b") if cats_alt else None
    inline_re = re.compile(rf"\b({cats_alt}) (\d+)\b") if cats_alt else None
    breakdown_re = re.compile(rf"\b(\d+) ({kinds_alt})\b")

    def starts_item(text: str) -> bool:
        return bool(
            total_re.match(text)
            or kind_re.match(text)
            or (nested_re is not None and nested_re.match(text))
        )

    def wrapped(i: int, rest: str) -> str:
        """``rest`` and the more indented lines that continue line ``i``."""
        indent, parts = header[i][0], [rest]
        for more, text in header[i + 1 :]:
            if more <= indent or not text or starts_item(text):
                break
            parts.append(text)
        return " ".join(parts)

    by_kind: dict[str, int] = {}
    by_category: dict[tuple[str, str], int] = {}
    breakdown: dict[str, int] = {}
    current: tuple[str, int] | None = None
    for i, (indent, text) in enumerate(header):
        if (m := total_re.match(text)) is not None:
            claims[("", "", "")] = int(m.group(1))
            breakdown = {k: int(n) for n, k in breakdown_re.findall(wrapped(i, m.group(2)))}
            current = None
        elif (m := kind_re.match(text)) is not None:
            current = (m.group(1), indent)
            by_kind[current[0]] = int(m.group(2))
            for c, n in inline_re.findall(wrapped(i, m.group(3))) if inline_re else ():
                by_category[(current[0], c)] = int(n)
        elif current is not None and text and indent <= current[1]:
            current = None
        elif current is not None and nested_re is not None and (m := nested_re.match(text)):
            by_category[(current[0], m.group(1))] = int(m.group(2))
    stated = breakdown or by_kind
    for kind, n in stated.items():
        claims[("", kind, "")] = n
    for (kind, category), n in by_category.items():
        if kind in stated:
            claims[("", kind, category)] = n
    return claims


def load_gap_file(path: Path, title: str, rel: str, categories: dict[str, str]) -> GapFile:
    text = path.read_text(encoding="utf-8")
    doc = yaml.safe_load(text)
    if not isinstance(doc, dict):
        raise ValueError("not a known-gaps file")
    raw = {"": doc["gaps"]} if "gaps" in doc else dict(doc)
    groups: dict[str, list[Gap]] = {}
    for group, entries in raw.items():
        gaps = []
        for entry in entries or []:
            if not isinstance(entry, dict):
                continue
            gap_id, reason = str(entry.get("id", "")), str(entry.get("reason", ""))
            category = categories.get(gap_id) or _reason_category(reason) or NO_CATEGORY
            gaps.append(Gap(gap_id, _kinds(reason), category))
        groups[str(group)] = gaps
    known = set(categories.values()) | {g.category for gs in groups.values() for g in gs}
    known.discard(NO_CATEGORY)
    claims = header_claims(header_lines(text), list(groups), known)
    return GapFile(rel, title, groups, claims)


def _counts(counter: Counter[str]) -> str:
    return "、".join(f"{k} {n}" for k, n in sorted(counter.items(), key=lambda i: (-i[1], i[0])))


def _stated(gap_file: GapFile, group: str, kind: str = "") -> str:
    stated = gap_file.claims.get((group, kind, ""))
    if stated is None:
        return "—"
    actual = gap_file.actual(group, kind, "")
    return str(stated) if stated == actual else f"{stated}（不一致）"


def gaps_section(root: Path) -> Section:
    section = Section("红队与多轮")
    section.body.append(
        "已知缺口是严格 xfail：条数从条目实际统计（类别取自 `tests/redteam/cases.yaml` 与 "
        "`multiturn.yaml`），再与文件头写的计数比较；“—”表示文件头没写这一项。"
    )
    categories = case_categories(root)
    problems: list[str] = []
    for rel, title in GAP_FILES:
        try:
            gap_file = load_gap_file(root / rel, title, rel, categories)
        except (OSError, yaml.YAMLError, ValueError, KeyError, TypeError):
            section.body.append(f"\n`{rel}`：读不出来。")
            problems.append(f"{Path(rel).name}：读不出来")
            continue
        section.body += ["", f"`{rel}`（{title}）", ""]
        if list(gap_file.groups) == [""]:
            gaps = gap_file.groups[""]
            kinds = Counter(k for gap in gaps for k in gap.kinds)
            section.body += [
                f"条目 {len(gaps)} 条，文件头写 {_stated(gap_file, '')}。",
                "",
                "| 类型 | 条数 | 文件头 | 按类别 |",
                "| :--- | ---: | ---: | :--- |",
            ]
            for kind, n in sorted(kinds.items(), key=lambda i: (-i[1], i[0])):
                by_category = Counter(g.category for g in gaps if kind in g.kinds)
                section.body.append(
                    f"| {kind} | {n} | {_stated(gap_file, '', kind)} | {_counts(by_category)} |"
                )
        else:
            section.body += [
                "| 模式 | 条目 | 文件头 | 按类型（一条可有多种） | 按类别 |",
                "| :--- | ---: | ---: | :--- | :--- |",
            ]
            for group, gaps in gap_file.groups.items():
                kinds = Counter(k for gap in gaps for k in gap.kinds)
                cats = Counter(g.category for g in gaps)
                section.body.append(
                    f"| {group} | {len(gaps)} | {_stated(gap_file, group)} "
                    f"| {_counts(kinds)} | {_counts(cats)} |"
                )
        found = gap_file.mismatches()
        problems += found
        if found:
            section.body += ["", "条目与文件头不一致：", *(f"- {p}" for p in found)]
    if problems:
        section.check("红队与多轮 · 缺口计数", FAIL, f"{len(problems)} 处与文件头不一致或读不出")
    else:
        section.check("红队与多轮 · 缺口计数", PASS, "三份文件的条目与文件头一致")
    return section


# -- 4. hazard log --------------------------------------------------------------------------

_HAZARD_SUMMARY = re.compile(r"^hazard log: (\d+) hazards, (.*?); residual risk >= 3: (.*)$")


@dataclass(frozen=True)
class HazardRow:
    id: str
    residual: int
    status: str


def parse_hazard_table(text: str) -> list[HazardRow]:
    """The rows of ``check_hazard_log.py --table``: id, residual risk and status."""
    rows = []
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 5 or not re.fullmatch(r"HAZ-\d+", cells[0]):
            continue
        risk = re.search(r"→\s*(\d)\s*$", cells[-2])
        if risk is not None:
            rows.append(HazardRow(cells[0], int(risk.group(1)), cells[-1]))
    return rows


def hazard_section(run: Runner) -> Section:
    section = Section("危害日志")
    check = run(python(HAZARD_SCRIPT))
    table = run(python(HAZARD_SCRIPT, "--table"))
    rows = parse_hazard_table(table.out) if table.code == 0 else []
    summary = _HAZARD_SUMMARY.match(check.out.strip()) if check.code == 0 else None
    statuses: list[str] = []
    if summary is not None:
        statuses = [part.split(" ", 1)[1] for part in summary.group(2).split(", ")]
    statuses += [r.status for r in rows if r.status not in statuses]
    if rows:
        risks = sorted({r.residual for r in rows} | set(range(1, 6)))
        counts = Counter((r.status, r.residual) for r in rows)
        section.body += [
            f"`docs/safety/hazard-log.md`：{len(rows)} 条危害。按状态与残余风险（1–5）：",
            "",
            "| 状态 | " + " | ".join(f"残余 {r}" for r in risks) + " | 合计 |",
            "| :--- | " + " | ".join("---:" for _ in risks) + " | ---: |",
        ]
        for status in statuses:
            cells = " | ".join(str(counts[(status, r)]) for r in risks)
            total = sum(counts[(status, r)] for r in risks)
            section.body.append(f"| {status} | {cells} | {total} |")
        column = " | ".join(str(sum(counts[(s, r)] for s in statuses)) for r in risks)
        section.body.append(f"| 合计 | {column} | {len(rows)} |")
        high = [f"{r.id}（{r.residual}）" for r in rows if r.residual >= 3]
        section.body += ["", f"残余风险 ≥ 3（{len(high)} 条）：{'、'.join(high) or '无'}。"]
        if summary is not None and int(summary.group(1)) != len(rows):
            section.body.append(f"（检查脚本数到 {summary.group(1)} 条，汇总表 {len(rows)} 条。）")
    else:
        section.body.append(f"`check_hazard_log.py --table` {_exit(table)}，没有汇总表。")
    if check.code == 0 and rows:
        section.check("危害日志", PASS, f"{len(rows)} 条，格式、证据与缺口计数通过检查")
    else:
        problems = sum(1 for line in check.err.splitlines() if line.strip())
        why = f"check_hazard_log.py {_exit(check)}" + (f"，{problems} 个问题" if problems else "")
        if check.code == 0:
            why = "没有读到汇总表"
        section.body.append(f"\n检查没有通过：{why}。")
        section.check("危害日志", FAIL, why)
    return section


# -- 5. mutation testing --------------------------------------------------------------------


def mutation_table(text: str) -> tuple[str, list[str]] | None:
    """The title and the summary table of the mutation report: the first table under
    ``## 结果``, else the first table whose header names ``变异总数``."""
    lines = text.splitlines()
    title = next((line[2:].strip() for line in lines if line.startswith("# ")), "")

    def table_at(start: int) -> list[str]:
        block = []
        for line in lines[start:]:
            if not line.startswith("|"):
                break
            block.append(line)
        return block

    in_results = False
    for i, line in enumerate(lines):
        if line.startswith("## "):
            in_results = line[3:].strip().startswith("结果")
        elif in_results and line.startswith("|"):
            return title, table_at(i)
    for i, line in enumerate(lines):
        if line.startswith("|") and "变异总数" in line:
            return title, table_at(i)
    return None


def mutation_section(root: Path) -> Section:
    section = Section("变异测试")
    path = root / MUTATION_REPORT
    try:
        found = mutation_table(path.read_text(encoding="utf-8"))
    except OSError:
        found = None
    if found is None:
        section.body.append(f"`{MUTATION_REPORT}` 不存在或没有汇总表。")
        section.check("变异测试", FAIL, "报告不存在或没有汇总表")
        return section
    title, table = found
    section.body += [
        f"引自 `{MUTATION_REPORT}`（{title}；静态文档，本命令不重跑变异测试）：",
        "",
        *table,
    ]
    section.check("变异测试", PASS, "已引用报告的汇总表（不重跑）")
    return section


# -- 6. hotlines ----------------------------------------------------------------------------


@dataclass(frozen=True)
class HotlineDates:
    entries: int
    earliest: date
    latest: date
    compiled_on: date
    max_age_days: int

    @property
    def deadline(self) -> date:
        """The last day the oldest entry still passes the freshness check."""
        return self.earliest + timedelta(days=self.max_age_days)


def hotline_dates(root: Path) -> HotlineDates:
    """The ``verified_on`` dates of the packaged (signature-checked) hotline data, read the
    way ``check_hotline_freshness.py`` reads it, and that script's maximum age."""
    spec = importlib.util.spec_from_file_location("_freshness", root / HOTLINE_SCRIPT)
    if spec is None or spec.loader is None:
        raise ImportError(HOTLINE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    sys.modules[spec.name] = module  # its dataclasses look their module up
    spec.loader.exec_module(module)
    store = module.load_store(None, datetime.now(UTC).date())
    dates = [
        entry.verified_on
        for region in store.regions.values()
        for entry in (*region.emergency, *region.lines)
    ]
    if not dates:
        raise ValueError("no hotline entries")
    return HotlineDates(
        len(dates), min(dates), max(dates), store.compiled_on, int(module.MAX_AGE_DAYS)
    )


def hotline_section(run: Runner, root: Path, read_dates: Callable[[Path], HotlineDates]) -> Section:
    section = Section("热线")
    proc = run(python(HOTLINE_SCRIPT))
    first = proc.out.strip().splitlines()[0] if proc.out.strip() else ""
    try:
        dates: HotlineDates | None = read_dates(root)
    except Exception:  # any failure to read the data is reported, never raised
        dates = None
    if dates is not None:
        section.body += [
            f"- 打包的热线数据：{dates.entries} 条（紧急号码与热线），"
            f"编制日期 {dates.compiled_on}。",
            f"- 最近核验日期：{dates.latest}"
            + (f"（最早一条 {dates.earliest}）" if dates.earliest != dates.latest else "")
            + "。",
            f"- 复核截止日期：{dates.deadline}（最早的核验日期 + {dates.max_age_days} 天；"
            "过了这一天 `check_hotline_freshness.py` 就失败）。",
        ]
    else:
        section.body.append("- 没能读出打包热线数据的核验日期。")
    stale = re.match(r"^STALE: (\d+) of (\d+) entries", first)
    if proc.code == 0:
        section.body.append("- 时效检查：所有条目都在期限内。")
        status, note = PASS, "所有条目都在核验期限内"
    elif stale is not None:
        section.body.append(
            f"- 时效检查：{stale.group(1)}/{stale.group(2)} 条过期，需要重新核验并签名。"
        )
        status, note = FAIL, f"{stale.group(1)} 条过期"
    else:
        section.body.append(f"- 时效检查：`check_hotline_freshness.py` {_exit(proc)}。")
        status, note = FAIL, f"check_hotline_freshness.py {_exit(proc)}"
    if dates is None and status == PASS:
        status, note = FAIL, "读不出核验日期"
    section.check("热线时效", status, note)
    return section


# -- 7. privacy audit and requirements trace -------------------------------------------------

_PRIVACY_ROW = re.compile(r"^(\S.*?)\s{2,}(PASS|FAIL|SKIP)(?:\s{2}|\s*$)")


def privacy_section(run: Runner) -> Section:
    section = Section("隐私审计")
    proc = run(python(PRIVACY_SCRIPT))
    results = [m.groups() for line in proc.out.splitlines() if (m := _PRIVACY_ROW.match(line))]
    counts = Counter(status for _, status in results)
    failed = [name for name, status in results if status == "FAIL"]
    if results:
        section.body.append(
            f"`privacy_audit.py`（G-4 的自动部分）：{len(results)} 项，"
            f"PASS {counts['PASS']}、FAIL {counts['FAIL']}、SKIP {counts['SKIP']}。"
        )
    if failed:
        section.body.append("失败的检查：" + "、".join(f"`{name}`" for name in failed) + "。")
    if proc.code == 0 and results:
        section.check("隐私审计", PASS, f"{len(results)} 项，无失败")
    else:
        why = f"{len(failed)} 项失败" if failed else f"privacy_audit.py {_exit(proc)}"
        if not results:
            section.body.append(f"`privacy_audit.py` {_exit(proc)}，没有结果表。")
        section.check("隐私审计", FAIL, why)
    return section


_TRACE = re.compile(r"^trace: (\d+) requirement ids, (.*)$")


def trace_section(run: Runner) -> Section:
    section = Section("需求追溯")
    proc = run(python(TRACE_SCRIPT))
    summary = _TRACE.match(proc.out.strip()) if proc.code == 0 else None
    if summary is not None:
        section.body.append(
            f"`trace_requirements.py`：PRD 与 SDD 里的 {summary.group(1)} 个需求编号都有测试、"
            f"检查或写明的理由（{summary.group(2)}）。"
        )
        section.check("需求追溯", PASS, f"{summary.group(1)} 个编号，{summary.group(2)}")
        return section
    problems = sum(1 for line in proc.err.splitlines() if line.startswith("trace:"))
    why = f"trace_requirements.py {_exit(proc)}" + (f"，{problems} 个问题" if problems else "")
    section.body.append(f"`trace_requirements.py` 没有通过：{why}。")
    section.check("需求追溯", FAIL, why)
    return section


# -- the page -------------------------------------------------------------------------------


@dataclass(frozen=True)
class GitState:
    commit: str
    short: str
    branch: str
    dirty: bool | None


def git_state(run: Runner) -> GitState:
    def git(*args: str) -> str | None:
        proc = run(["git", *args])
        return proc.out.strip() if proc.code == 0 else None

    status = git("status", "--porcelain")
    return GitState(
        git("rev-parse", "HEAD") or "unknown",
        git("rev-parse", "--short", "HEAD") or "unknown",
        git("rev-parse", "--abbrev-ref", "HEAD") or "unknown",
        None if status is None else bool(status),
    )


def default_out(root: Path, short: str) -> Path:
    return root / "build" / "reports" / f"safety-evidence-{short}.md"


def _models_line(models: set[str], skip_model: bool) -> str:
    rules = sorted(m for m in models if not m.startswith(STUDENT_PREFIX))
    students = sorted(m for m in models if m.startswith(STUDENT_PREFIX))
    parts = [f"规则（{'、'.join(rules) or 'rules-only'}）"]
    if skip_model:
        parts.append("学生模型：未运行（--skip-model）")
    else:
        parts.append(f"学生模型：{'、'.join(students) or '没有加载'}")
    return "；".join(parts)


def render(git: GitState, when: str, skip_model: bool, sections: Sequence[Section]) -> str:
    models = set().union(*(s.models for s in sections))
    checks = [c for s in sections for c in s.checks]
    counts = Counter(c.status for c in checks)
    dirty = {None: "未知", True: "有未提交的改动，报告反映的是工作区里的代码", False: "干净"}
    lines = [
        f"# 安全证据报告 · {git.short}",
        "",
        "由 `python scripts/safety_report.py` 生成。这不是 DCB0129 的正式安全档案，未经临床安全官"
        "签署；报告只含计数、比率与检查名，不含任何评估集句子或 id。",
        "",
        f"- 提交：`{git.commit}`（分支 `{git.branch}`）；工作区：{dirty[git.dirty]}",
        f"- 日期：{when}",
        f"- 风险模型：{_models_line(models, skip_model)}",
        f"- Python：{platform.python_implementation()} {platform.python_version()}",
        f"- 结论：{len(checks)} 项检查，通过 {counts[PASS]}、跳过 {counts[SKIP]}、"
        f"失败 {counts[FAIL]}（退出码 {1 if counts[FAIL] else 0}）",
    ]
    for number, section in enumerate(sections, start=1):
        lines += ["", f"## {number}. {section.title}", "", *section.body]
    lines += ["", "## 结果", "", "| 检查 | 结果 | 说明 |", "| :--- | :--- | :--- |"]
    lines += [f"| {c.name} | {c.status} | {c.note} |" for c in checks]
    return "\n".join(lines) + "\n"


def collect(
    run: Runner,
    root: Path,
    eval_dir: Path,
    json_stem: Path,
    skip_model: bool,
    read_dates: Callable[[Path], HotlineDates] | None = None,
) -> list[Section]:
    read_dates = hotline_dates if read_dates is None else read_dates
    return [
        eval_section(run, eval_dir, json_stem, skip_model, root),
        metamorphic_section(run, skip_model),
        gaps_section(root),
        hazard_section(run),
        mutation_section(root),
        hotline_section(run, root, read_dates),
        privacy_section(run),
        trace_section(run),
    ]


def main(argv: Sequence[str] | None = None, run: Runner | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="一条命令复跑全部安全检查，写成一页 Markdown（只有计数，不含评估集句子与 id）。"
    )
    parser.add_argument(
        "--eval-dir",
        type=Path,
        default=ROOT / "build" / "eval",
        help="评估集 CSV 所在目录（默认仓库根下的 build/eval）",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="报告路径（默认 build/reports/safety-evidence-<短提交号>.md）",
    )
    parser.add_argument("--skip-model", action="store_true", help="只跑规则模式，不加载学生模型")
    args = parser.parse_args(argv)
    runner = run_command if run is None else run
    git = git_state(runner)
    out: Path = args.out if args.out is not None else default_out(ROOT, git.short)
    stem = out.with_suffix("") if out.suffix == ".md" else out
    sections = collect(runner, ROOT, args.eval_dir, stem, args.skip_model)
    when = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %z")
    text = render(git, when, args.skip_model, sections)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    checks = [c for s in sections for c in s.checks]
    for c in checks:
        print(f"{c.status}  {c.name}：{c.note}")
    failed = sum(c.status == FAIL for c in checks)
    print(f"\n安全证据报告已写入：{display_path(out, ROOT)}（{failed} 项失败）")
    return 1 if failed else 0


if __name__ == "__main__":
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8")
    raise SystemExit(main())
