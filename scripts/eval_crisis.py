#!/usr/bin/env python3
"""Run a labelled CSV through the product's crisis screen and report how it did.

    python scripts/eval_crisis.py sentences.csv [--mode rules|model|both] [--show-ids]
                                  [--json PATH]

The CSV has a header row with ``id,text,level`` and an optional ``category`` column
(``docs/eval/volunteer-template.csv`` has this shape); ``level`` is ``L0`` to ``L3``.
Every row goes through a fresh :class:`~olivia.core.session.Session` as a single turn,
the way the product and the internal evaluation (``tests/redteam``) do: ``rules`` opens it
with the rule screen alone (``olivia chat --rules``), ``model`` with the packaged
perception student as well (``olivia chat``'s default since F7; it can only raise the rule
level).
The level is the turn's ``crisis_level``; a turn that enters the crisis flow counts as
L2 or above. A question turn (``SAFETY_CHECK``: decision D3, or since 2026-10-26 a crisis
alarm only the model raises, which asks once before the crisis flow) reports the
screen's level, so a model-only L2 still counts as L2 there; the report also says how
the L2+L3 rows and the L0 rows split between entering the crisis flow and being asked.

Printed per mode: which risk model actually ran, a confusion matrix (rows: the label,
columns: the screen's level), L2+L3 recall (labelled L2/L3 rows the screen put at L2 or
above), the L0 false-alarm rate (labelled L0 rows put at L2 or above) and, per category,
the misses and false alarms. Recall and the false-alarm rate carry a Wilson 95% interval
(:func:`wilson_interval`), overall and in two per-category tables: recall over each
category's L2/L3 rows, and the false-alarm rate over its L0 rows. **The sentences are
never printed**; ``--show-ids`` adds the ids of the missed and falsely alarmed rows.

``--json PATH`` also writes, per mode, the confusion matrix, recall, the false-alarm rate,
their intervals and the per-category results (:func:`report_to_dict`): counts and
category names only, never a sentence or an id. ``scripts/compare_eval.py`` compares two
such files. Exit status: 0 after a report, 2 when the CSV cannot be used or the JSON
cannot be written.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sys
import unicodedata
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from olivia.core.models import CrisisLevel, PersonaProfile, UserRegion
from olivia.core.session import ReplyKind, Session
from olivia.core.taxonomy import Taxonomy, load_taxonomy

MODES = ("rules", "model")
LEVELS = (CrisisLevel.L0, CrisisLevel.L1, CrisisLevel.L2, CrisisLevel.L3)
NOW = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)  # mid-afternoon: no late-night wording
NO_CATEGORY = "（无类别）"
REQUIRED = ("id", "text", "level")
Z95 = 1.96
JSON_SCHEMA = 1
HIGH = (CrisisLevel.L2, CrisisLevel.L3)


class CsvError(ValueError):
    """The CSV is missing a column, has a bad level, an empty text or a repeated id."""


def wilson_interval(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    """The Wilson score interval for ``k`` successes in ``n`` trials (95% at the default z).

    ``n == 0`` says nothing, so the interval is the whole of [0, 1]; ``k == 0`` has a lower
    bound of exactly 0 and ``k == n`` an upper bound of exactly 1.
    """
    if n < 0 or not 0 <= k <= n:
        raise ValueError(f"need 0 <= k <= n, got k={k}, n={n}")
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    z2 = z * z
    denom = 1 + z2 / n
    centre = (p + z2 / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / denom
    low = 0.0 if k == 0 else max(0.0, centre - half)
    high = 1.0 if k == n else min(1.0, centre + half)
    return (low, high)


@dataclass(frozen=True)
class Row:
    id: str
    text: str
    level: CrisisLevel
    category: str


@dataclass
class Report:
    mode: str
    risk_models: Counter[str] = field(default_factory=Counter)
    matrix: Counter[tuple[CrisisLevel, CrisisLevel]] = field(default_factory=Counter)
    misses: list[Row] = field(default_factory=list)
    """Labelled L2/L3, screened below L2."""
    false_alarms: list[Row] = field(default_factory=list)
    """Labelled L0, screened at L2 or above."""
    flow: Counter[tuple[CrisisLevel, str]] = field(default_factory=Counter)
    """(label, ``crisis`` / ``asked`` / ``none``): entered the crisis flow, got the direct
    question (``SAFETY_CHECK``) or neither."""
    categories: Counter[tuple[str, CrisisLevel]] = field(default_factory=Counter)
    """(category, label): how many rows."""

    def count(self, label: CrisisLevel) -> int:
        return sum(n for (gold, _), n in self.matrix.items() if gold is label)

    @property
    def crisis_total(self) -> int:
        return self.count(CrisisLevel.L2) + self.count(CrisisLevel.L3)

    @property
    def caught(self) -> int:
        """Labelled L2/L3 rows screened at L2 or above."""
        return self.crisis_total - len(self.misses)

    def category_recall(self) -> dict[str, tuple[int, int]]:
        """Per category with L2/L3 rows: (caught, L2/L3 rows), by category name."""
        totals: Counter[str] = Counter()
        for (category, gold), n in self.categories.items():
            if gold in HIGH:
                totals[category] += n
        missed = Counter(row.category for row in self.misses)
        return {c: (n - missed[c], n) for c, n in sorted(totals.items())}

    def category_false_alarms(self) -> dict[str, tuple[int, int]]:
        """Per category with L0 rows: (false alarms, L0 rows), by category name."""
        totals: Counter[str] = Counter()
        for (category, gold), n in self.categories.items():
            if gold is CrisisLevel.L0:
                totals[category] += n
        alarms = Counter(row.category for row in self.false_alarms)
        return {c: (alarms[c], n) for c, n in sorted(totals.items())}


def load_rows(path: Path) -> list[Row]:
    """The CSV's rows; :class:`CsvError` names the line (never the text) on a problem."""
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            missing = [c for c in REQUIRED if c not in (reader.fieldnames or ())]
            if missing:
                raise CsvError(f"{path.name}: missing column(s) {', '.join(missing)}")
            rows: list[Row] = []
            seen: set[str] = set()
            for line, raw in enumerate(reader, start=2):
                row_id = (raw.get("id") or "").strip()
                text = (raw.get("text") or "").strip()
                level = (raw.get("level") or "").strip().upper()
                if not row_id or row_id in seen:
                    raise CsvError(f"{path.name} line {line}: empty or repeated id")
                if not text:
                    raise CsvError(f"{path.name} line {line} ({row_id}): empty text")
                if level not in CrisisLevel.__members__:
                    raise CsvError(f"{path.name} line {line} ({row_id}): level must be L0-L3")
                seen.add(row_id)
                category = (raw.get("category") or "").strip() or NO_CATEGORY
                rows.append(Row(row_id, text, CrisisLevel[level], category))
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise CsvError(f"{path.name}: cannot read ({type(exc).__name__})") from None
    if not rows:
        raise CsvError(f"{path.name}: no rows")
    return rows


def _profile() -> PersonaProfile:
    return PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        region=UserRegion("CN", "Asia/Shanghai"),
    )


def evaluate(rows: Sequence[Row], mode: str, tax: Taxonomy | None = None) -> Report:
    """Each row as the single turn of a fresh session in ``mode``."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    taxonomy = load_taxonomy() if tax is None else tax
    profile = _profile()
    report = Report(mode)
    for row in rows:
        session = Session.open(
            taxonomy,
            profile,
            rng=random.Random(f"{row.id}/{mode}"),
            now=lambda: NOW,
            student=mode == "model",
        )
        result = session.turn(row.text)
        level = result.crisis_level
        if result.in_crisis and level < CrisisLevel.L2:
            level = CrisisLevel.L2
        label = str(result.inspect.get("risk_model", "?"))
        reason = result.inspect.get("risk_model_reason")
        report.risk_models[f"{label}（{reason}）" if reason else label] += 1
        report.matrix[(row.level, level)] += 1
        report.categories[(row.category, row.level)] += 1
        if result.in_crisis or result.reply_kind is ReplyKind.CRISIS:
            report.flow[(row.level, "crisis")] += 1
        elif result.reply_kind is ReplyKind.SAFETY_CHECK:
            report.flow[(row.level, "asked")] += 1
        else:
            report.flow[(row.level, "none")] += 1
        if row.level >= CrisisLevel.L2 and level < CrisisLevel.L2:
            report.misses.append(row)
        elif row.level is CrisisLevel.L0 and level >= CrisisLevel.L2:
            report.false_alarms.append(row)
    return report


def _rate(part: int, whole: int) -> str:
    if whole == 0:
        return "0/0（没有这类样本）"
    return f"{part}/{whole} = {100 * part / whole:.1f}%"


def _interval(part: int, whole: int) -> str:
    low, high = wilson_interval(part, whole)
    return f"{100 * low:.1f}%–{100 * high:.1f}%"


def _rate_ci(part: int, whole: int) -> str:
    """:func:`_rate` with the Wilson 95% interval after it (none for an empty group)."""
    if whole == 0:
        return _rate(part, whole)
    return f"{_rate(part, whole)}（95% 区间 {_interval(part, whole)}）"


def _cell(text: str, width: int) -> str:
    """``text`` right-aligned in ``width`` terminal columns (a CJK character takes two)."""
    shown = sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)
    return " " * max(0, width - shown) + text


def _table(rates: dict[str, tuple[int, int]], hit: str, rate: str, *, worst_low: bool) -> list[str]:
    """One line per category, the worst first (then the larger, then by name); the name
    goes last so the number columns line up."""
    if not rates:
        return ["  （无）"]
    sign = 1 if worst_low else -1

    def worst(item: tuple[str, tuple[int, int]]) -> tuple[float, int, str]:
        name, (k, n) = item
        return (sign * k / n, -n, name)

    lines = [_cell("n", 7) + _cell(hit, 7) + _cell(rate, 10) + "  95% 区间       类别"]
    for category, (k, n) in sorted(rates.items(), key=worst):
        cells = _cell(str(n), 7) + _cell(str(k), 7) + _cell(f"{100 * k / n:.1f}%", 10)
        lines.append(f"{cells}  {_interval(k, n):<13}  {category}")
    return lines


def _by_category(rows: Sequence[Row], show_ids: bool) -> list[str]:
    if not rows:
        return ["  （无）"]
    counts = Counter(row.category for row in rows)
    lines = []
    for category, n in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        line = f"  {category}：{n}"
        if show_ids:
            ids = ", ".join(row.id for row in rows if row.category == category)
            line += f"  [{ids}]"
        lines.append(line)
    return lines


def format_report(report: Report, *, show_ids: bool = False) -> str:
    """The printed report: numbers, ids (only with ``show_ids``), categories; no text."""
    models = "、".join(f"{name} ×{n}" for name, n in sorted(report.risk_models.items()))
    head = "        " + "".join(f"{lv.name:>6}" for lv in LEVELS) + "    合计"
    matrix = [head]
    for gold in LEVELS:
        cells = "".join(f"{report.matrix[(gold, got)]:>6}" for got in LEVELS)
        matrix.append(f"  {gold.name:<6}{cells}{report.count(gold):>8}")
    crisis_hi = sum(report.flow[(lv, "crisis")] for lv in HIGH)
    asked_hi = sum(report.flow[(lv, "asked")] for lv in HIGH)
    l0_total = report.count(CrisisLevel.L0)
    lines = [
        f"== 模式 {report.mode} · 实际运行的风险模型：{models or '-'} ==",
        "混淆矩阵（行：标注等级，列：筛查判定）",
        *matrix,
        f"L2+L3 召回（判到 L2 及以上）：{_rate_ci(report.caught, report.crisis_total)}",
        "L0 误报率（判到 L2 及以上）：" + _rate_ci(len(report.false_alarms), l0_total),
        "L2+L3 进入危机流程或被直接询问："
        + _rate(crisis_hi + asked_hi, report.crisis_total)
        + f"（进入危机流程 {crisis_hi}，被询问一次 {asked_hi}）",
        "L0 直接进危机流程：" + _rate(report.flow[(CrisisLevel.L0, "crisis")], l0_total),
        "L0 被询问一次：" + _rate(report.flow[(CrisisLevel.L0, "asked")], l0_total),
        "按类别的漏报（标注 L2/L3，判定低于 L2）：",
        *_by_category(report.misses, show_ids),
        "按类别的误报（标注 L0，判定 L2 及以上）：",
        *_by_category(report.false_alarms, show_ids),
        "按类别的召回表（标注 L2/L3 的行，判到 L2 及以上算命中；召回低的在前）：",
        *_table(report.category_recall(), "命中", "召回", worst_low=True),
        "按类别的 L0 误报表（标注 L0 的行，判到 L2 及以上算误报；误报率高的在前）：",
        *_table(report.category_false_alarms(), "误报", "误报率", worst_low=False),
    ]
    return "\n".join(lines)


def _proportion(k: int, n: int) -> dict[str, Any]:
    low, high = wilson_interval(k, n)
    return {
        "k": k,
        "n": n,
        "rate": round(k / n, 6) if n else None,
        "ci95": [round(low, 6), round(high, 6)],
    }


def report_to_dict(report: Report) -> dict[str, Any]:
    """One mode's numbers for ``--json``: counts and category names, no sentence, no id."""
    categories: dict[str, dict[str, Any]] = {}
    names = sorted({category for category, _ in report.categories})
    recall = report.category_recall()
    alarms = report.category_false_alarms()
    for name in names:
        entry: dict[str, Any] = {
            "rows": {lv.name: report.categories[(name, lv)] for lv in LEVELS},
        }
        if name in recall:
            entry["recall"] = _proportion(*recall[name])
        if name in alarms:
            entry["false_alarm"] = _proportion(*alarms[name])
        categories[name] = entry
    return {
        "risk_models": dict(sorted(report.risk_models.items())),
        "confusion": {
            gold.name: {got.name: report.matrix[(gold, got)] for got in LEVELS} for gold in LEVELS
        },
        "flow": {
            gold.name: {kind: report.flow[(gold, kind)] for kind in ("crisis", "asked", "none")}
            for gold in LEVELS
        },
        "recall": _proportion(report.caught, report.crisis_total),
        "false_alarm": _proportion(len(report.false_alarms), report.count(CrisisLevel.L0)),
        "categories": categories,
    }


def reports_to_json(csv_name: str, rows: int, reports: Sequence[Report]) -> dict[str, Any]:
    """The whole ``--json`` document: the CSV's file name, its row count and every mode."""
    return {
        "schema": JSON_SCHEMA,
        "csv": csv_name,
        "rows": rows,
        "z": Z95,
        "modes": {report.mode: report_to_dict(report) for report in reports},
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="用产品的危机筛查跑一份标注好的 CSV（id,text,level[,category]），只打印统计。"
    )
    parser.add_argument("csv", type=Path, help="CSV 文件：id,text,level[,category]")
    parser.add_argument(
        "--mode", choices=(*MODES, "both"), default="both", help="rules、model 或 both（默认）"
    )
    parser.add_argument(
        "--show-ids", action="store_true", help="同时列出漏报和误报样本的 id（从不打印原句）"
    )
    parser.add_argument(
        "--json",
        type=Path,
        metavar="PATH",
        help="另把每个模式的统计写成 JSON（只有计数与类别名，不含原句和 id）",
    )
    args = parser.parse_args(argv)
    try:
        rows = load_rows(args.csv)
    except CsvError as exc:
        print(f"eval_crisis: {exc}", file=sys.stderr)
        return 2
    tax = load_taxonomy()
    modes = MODES if args.mode == "both" else (args.mode,)
    print(f"{args.csv.name}：{len(rows)} 条")
    reports = []
    for mode in modes:
        report = evaluate(rows, mode, tax)
        reports.append(report)
        print()
        print(format_report(report, show_ids=args.show_ids))
    if args.json is not None:
        document = reports_to_json(args.csv.name, len(rows), reports)
        try:
            args.json.parent.mkdir(parents=True, exist_ok=True)
            args.json.write_text(
                json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        except OSError as exc:
            print(f"eval_crisis: cannot write {args.json} ({type(exc).__name__})", file=sys.stderr)
            return 2
        print()
        print(f"JSON 已写入：{args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
