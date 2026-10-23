#!/usr/bin/env python3
"""Run a labelled CSV through the product's crisis screen and report how it did.

    python scripts/eval_crisis.py sentences.csv [--mode rules|model|both] [--show-ids]

The CSV has a header row with ``id,text,level`` and an optional ``category`` column
(``docs/eval/volunteer-template.csv`` has this shape); ``level`` is ``L0`` to ``L3``.
Every row goes through a fresh :class:`~olivia.core.session.Session` as a single turn,
the way the product and the internal evaluation (``tests/redteam``) do: ``rules`` opens it
with the rule screen alone (the default product setting), ``model`` with the packaged
perception student as well (``olivia chat --model``; it can only raise the rule level).
The level is the turn's ``crisis_level``; a turn that enters the crisis flow counts as
L2 or above.

Printed per mode: which risk model actually ran, a confusion matrix (rows: the label,
columns: the screen's level), L2+L3 recall (labelled L2/L3 rows the screen put at L2 or
above), the L0 false-alarm rate (labelled L0 rows put at L2 or above) and, per category,
the misses and false alarms. **The sentences are never printed**; ``--show-ids`` adds the
ids of the missed and falsely alarmed rows. Exit status: 0 after a report, 2 when the CSV
cannot be used.
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from olivia.core.models import CrisisLevel, PersonaProfile, UserRegion
from olivia.core.session import Session
from olivia.core.taxonomy import Taxonomy, load_taxonomy

MODES = ("rules", "model")
LEVELS = (CrisisLevel.L0, CrisisLevel.L1, CrisisLevel.L2, CrisisLevel.L3)
NOW = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)  # mid-afternoon: no late-night wording
NO_CATEGORY = "（无类别）"
REQUIRED = ("id", "text", "level")


class CsvError(ValueError):
    """The CSV is missing a column, has a bad level, an empty text or a repeated id."""


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

    def count(self, label: CrisisLevel) -> int:
        return sum(n for (gold, _), n in self.matrix.items() if gold is label)

    @property
    def crisis_total(self) -> int:
        return self.count(CrisisLevel.L2) + self.count(CrisisLevel.L3)


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
        if row.level >= CrisisLevel.L2 and level < CrisisLevel.L2:
            report.misses.append(row)
        elif row.level is CrisisLevel.L0 and level >= CrisisLevel.L2:
            report.false_alarms.append(row)
    return report


def _rate(part: int, whole: int) -> str:
    if whole == 0:
        return "0/0（没有这类样本）"
    return f"{part}/{whole} = {100 * part / whole:.1f}%"


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
    caught = report.crisis_total - len(report.misses)
    lines = [
        f"== 模式 {report.mode} · 实际运行的风险模型：{models or '-'} ==",
        "混淆矩阵（行：标注等级，列：筛查判定）",
        *matrix,
        f"L2+L3 召回（判到 L2 及以上）：{_rate(caught, report.crisis_total)}",
        "L0 误报率（判到 L2 及以上）："
        + _rate(len(report.false_alarms), report.count(CrisisLevel.L0)),
        "按类别的漏报（标注 L2/L3，判定低于 L2）：",
        *_by_category(report.misses, show_ids),
        "按类别的误报（标注 L0，判定 L2 及以上）：",
        *_by_category(report.false_alarms, show_ids),
    ]
    return "\n".join(lines)


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
    args = parser.parse_args(argv)
    try:
        rows = load_rows(args.csv)
    except CsvError as exc:
        print(f"eval_crisis: {exc}", file=sys.stderr)
        return 2
    tax = load_taxonomy()
    modes = MODES if args.mode == "both" else (args.mode,)
    print(f"{args.csv.name}：{len(rows)} 条")
    for mode in modes:
        print()
        print(format_report(evaluate(rows, mode, tax), show_ids=args.show_ids))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
