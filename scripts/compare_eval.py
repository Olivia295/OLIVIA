#!/usr/bin/env python3
"""Compare two ``eval_crisis.py --json`` reports: before a change and after it.

    python scripts/compare_eval.py before.json after.json

For every mode both files have, prints each metric before and after with its Wilson 95%
interval and the difference in percentage points: L2+L3 recall and the L0 false-alarm
rate overall, then per category (recall over the category's L2/L3 rows, the false-alarm
rate over its L0 rows). A lower recall is marked ``召回下降`` and a higher false-alarm
rate ``误报上升``, each with whether the two intervals overlap (overlapping intervals
mean the change may be noise; a regression is flagged either way). A metric only one
file has, or with no rows on one side, is listed but not judged.

The reports hold counts and category names only (``eval_crisis.py`` never writes a
sentence or an id), so neither does this output. Exit status: 0 when nothing regressed,
1 when any recall fell or any false-alarm rate rose, 2 when a file cannot be used.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA = 1
RECALL = "recall"
FALSE_ALARM = "false_alarm"
METRIC_NAMES = {RECALL: "L2+L3 召回", FALSE_ALARM: "L0 误报率"}
REGRESSION = {RECALL: "召回下降", FALSE_ALARM: "误报上升"}


class ReportError(ValueError):
    """The file is missing, is not JSON, or is not an ``eval_crisis.py --json`` report."""


@dataclass(frozen=True)
class Proportion:
    k: int
    n: int
    low: float
    high: float

    @property
    def rate(self) -> float:
        return self.k / self.n

    def show(self) -> str:
        if self.n == 0:
            return "0/0"
        return (
            f"{self.k}/{self.n} = {100 * self.rate:.1f}%"
            f" [{100 * self.low:.1f}%–{100 * self.high:.1f}%]"
        )


@dataclass(frozen=True)
class Change:
    mode: str
    metric: str
    """``recall`` or ``false_alarm``."""
    scope: str
    """``总体`` or a category name."""
    before: Proportion
    after: Proportion

    @property
    def comparable(self) -> bool:
        return self.before.n > 0 and self.after.n > 0

    @property
    def regressed(self) -> bool:
        """Recall fell or the false-alarm rate rose (compared exactly, as fractions)."""
        if not self.comparable:
            return False
        before = self.before.k * self.after.n
        after = self.after.k * self.before.n
        return after < before if self.metric == RECALL else after > before

    @property
    def overlap(self) -> bool:
        return max(self.before.low, self.after.low) <= min(self.before.high, self.after.high)


def _proportion(raw: object, where: str) -> Proportion:
    if not isinstance(raw, dict):
        raise ReportError(f"{where}: not a proportion")
    k, n, ci = raw.get("k"), raw.get("n"), raw.get("ci95")
    if not (isinstance(k, int) and isinstance(n, int) and 0 <= k <= n):
        raise ReportError(f"{where}: need integers 0 <= k <= n")
    if not (
        isinstance(ci, list)
        and len(ci) == 2
        and all(isinstance(x, int | float) for x in ci)
        and 0 <= ci[0] <= ci[1] <= 1
    ):
        raise ReportError(f"{where}: ci95 must be [low, high] within [0, 1]")
    return Proportion(k, n, float(ci[0]), float(ci[1]))


def load_report(path: Path) -> dict[str, Any]:
    """The parsed report; :class:`ReportError` says what is wrong with it."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ReportError(f"{path.name}: cannot read ({type(exc).__name__})") from None
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ReportError(f"{path.name}: not a JSON file") from None
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise ReportError(f"{path.name}: not an eval_crisis.py --json report (schema {SCHEMA})")
    modes = data.get("modes")
    if not isinstance(modes, dict) or not modes:
        raise ReportError(f"{path.name}: no modes")
    for mode, body in modes.items():
        if not isinstance(body, dict) or not isinstance(body.get("categories"), dict):
            raise ReportError(f"{path.name}: mode {mode} has no categories")
        for metric in (RECALL, FALSE_ALARM):
            _proportion(body.get(metric), f"{path.name}: {mode} {metric}")
        for name, entry in body["categories"].items():
            if not isinstance(entry, dict):
                raise ReportError(f"{path.name}: {mode} category {name} is not an object")
            for metric in (RECALL, FALSE_ALARM):
                if metric in entry:
                    _proportion(entry[metric], f"{path.name}: {mode} {name} {metric}")
    return data


def _metrics(body: dict[str, Any]) -> dict[tuple[str, str], Proportion]:
    """(metric, scope) -> proportion: the two overall metrics, then each category's."""
    found = {
        (metric, "总体"): _proportion(body[metric], metric) for metric in (RECALL, FALSE_ALARM)
    }
    for name, entry in sorted(body["categories"].items()):
        for metric in (RECALL, FALSE_ALARM):
            if metric in entry:
                found[(metric, name)] = _proportion(entry[metric], name)
    return found


@dataclass
class Comparison:
    changes: list[Change]
    only_before: list[tuple[str, str, str]]
    """(mode, metric, scope) found only in the first file."""
    only_after: list[tuple[str, str, str]]
    modes_only_before: list[str]
    modes_only_after: list[str]

    @property
    def regressions(self) -> list[Change]:
        return [change for change in self.changes if change.regressed]


def compare(before: dict[str, Any], after: dict[str, Any]) -> Comparison:
    """Every metric both reports have, mode by mode."""
    changes: list[Change] = []
    only_before: list[tuple[str, str, str]] = []
    only_after: list[tuple[str, str, str]] = []
    modes_before, modes_after = before["modes"], after["modes"]
    for mode in sorted(set(modes_before) & set(modes_after)):
        old, new = _metrics(modes_before[mode]), _metrics(modes_after[mode])
        for key in old:
            if key in new:
                changes.append(Change(mode, key[0], key[1], old[key], new[key]))
            else:
                only_before.append((mode, *key))
        only_after.extend((mode, *key) for key in new if key not in old)
    return Comparison(
        changes,
        only_before,
        only_after,
        sorted(set(modes_before) - set(modes_after)),
        sorted(set(modes_after) - set(modes_before)),
    )


def _line(change: Change) -> str:
    label = METRIC_NAMES[change.metric] if change.scope == "总体" else change.scope
    text = f"  {label}：{change.before.show()} → {change.after.show()}"
    if not change.comparable:
        return text + "（有一边没有样本，不比较）"
    diff = 100 * (change.after.rate - change.before.rate)
    text += f"，{diff:+.1f} 个百分点"
    if change.regressed:
        text += f"  [{REGRESSION[change.metric]}，区间{'重叠' if change.overlap else '不重叠'}]"
    return text


def _section(comparison: Comparison, mode: str) -> Iterator[str]:
    changes = [change for change in comparison.changes if change.mode == mode]
    yield f"== 模式 {mode} =="
    for change in changes:
        if change.scope == "总体":
            yield _line(change)
    for metric, title in ((RECALL, "按类别的召回"), (FALSE_ALARM, "按类别的 L0 误报率")):
        rows = [c for c in changes if c.metric == metric and c.scope != "总体"]
        gone = [scope for m, k, scope in comparison.only_before if m == mode and k == metric]
        new = [scope for m, k, scope in comparison.only_after if m == mode and k == metric]
        if not (rows or gone or new):
            continue
        yield f"{title}："
        yield from (_line(change) for change in rows)
        yield from (f"  {scope}：只在前一份里（不比较）" for scope in gone)
        yield from (f"  {scope}：只在后一份里（不比较）" for scope in new)


def format_comparison(
    comparison: Comparison, before: dict[str, Any], after: dict[str, Any], names: Sequence[str]
) -> str:
    lines = [
        f"前：{names[0]}（{before.get('csv', '?')}，{before.get('rows', '?')} 条）",
        f"后：{names[1]}（{after.get('csv', '?')}，{after.get('rows', '?')} 条）",
    ]
    if (before.get("csv"), before.get("rows")) != (after.get("csv"), after.get("rows")):
        lines.append("注意：两份报告的数据集或条数不同，差值可能不只来自改动。")
    lines.extend(f"模式 {mode} 只在前一份里（不比较）" for mode in comparison.modes_only_before)
    lines.extend(f"模式 {mode} 只在后一份里（不比较）" for mode in comparison.modes_only_after)
    modes = sorted({change.mode for change in comparison.changes})
    for mode in modes:
        lines.append("")
        lines.extend(_section(comparison, mode))
    regressions = comparison.regressions
    drops = sum(1 for c in regressions if c.metric == RECALL)
    rises = sum(1 for c in regressions if c.metric == FALSE_ALARM)
    lines.append("")
    if regressions:
        apart = sum(1 for c in regressions if not c.overlap)
        lines.append(
            f"结论：召回下降 {drops} 项，误报上升 {rises} 项（其中区间不重叠 {apart} 项）。"
        )
    else:
        lines.append("结论：没有召回下降，也没有误报上升。")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="比较两份 eval_crisis.py --json 报告：打印每个指标的差值，"
        "标出召回下降与误报上升（并说明区间是否重叠）。"
    )
    parser.add_argument("before", type=Path, help="改动前的 JSON")
    parser.add_argument("after", type=Path, help="改动后的 JSON")
    args = parser.parse_args(argv)
    try:
        before, after = load_report(args.before), load_report(args.after)
    except ReportError as exc:
        print(f"compare_eval: {exc}", file=sys.stderr)
        return 2
    comparison = compare(before, after)
    if not comparison.changes:
        print("compare_eval: the two reports share no mode", file=sys.stderr)
        return 2
    print(format_comparison(comparison, before, after, (args.before.name, args.after.name)))
    return 1 if comparison.regressions else 0


if __name__ == "__main__":
    raise SystemExit(main())
