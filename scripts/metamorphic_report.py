#!/usr/bin/env python3
"""Metamorphic report of the crisis screen: does a rewrite that keeps the meaning keep the level?

    python scripts/metamorphic_report.py [--mode rules|model] [--write-gaps]

Every seed of tests/safety/metamorphic.py (cases.yaml, composition_cases.yaml,
tuned_probe.yaml, known_false_positives.yaml; never tests/redteam/cases.yaml) is screened
as written and after each meaning-preserving rewrite (``TRANSFORMS``), through
``SafetyScreen.assess`` as tests/safety/test_case_suite.py does. ``rules`` (the default) is
the rule screen alone; ``model`` adds the packaged perception student the way
``Session.open(student=True)`` does (``choose_risk_model``, as scripts/eval_crisis.py), and
only reports.

Printed: the overall invariance rate (expected L3 stays L3, L2 stays at L2 or above, L0
stays below L2), the rate and failures by transform and by seed category, how often an L1
seed stays L1, and the seeds skipped because the original sentence already misses its
expectation. Failures are printed as ``<seed id>/<transform>``; **sentences never are**.

``--write-gaps`` (rules mode only) rewrites tests/safety/known_metamorphic_gaps.yaml from the
failures, which test_metamorphic.py then holds strictly. Exit status 0 after a report, 2 when
the student was asked for and could not be loaded.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from olivia.core.models import CrisisLevel  # noqa: E402
from olivia.core.perception.student import choose_risk_model  # noqa: E402
from olivia.core.safety.crisis import SafetyScreen  # noqa: E402
from olivia.core.safety.lexicon import load_safety_lexicons  # noqa: E402
from olivia.core.taxonomy import load_taxonomy  # noqa: E402
from tests.safety.metamorphic import (  # noqa: E402
    FAMILIES,
    GAPS_FILE,
    TRANSFORMS,
    Outcome,
    Seed,
    load_seeds,
    render_gaps,
    run,
)

MODES = ("rules", "model")


def _rate(part: int, whole: int) -> str:
    if whole == 0:
        return "0/0"
    return f"{part}/{whole} = {100 * part / whole:.2f}%"


def _ids(outcomes: Sequence[Outcome]) -> str:
    return ", ".join(o.key for o in outcomes)


def screen_for(mode: str) -> tuple[Callable[[str], CrisisLevel], str]:
    """The level function of ``mode`` and the risk model that actually runs."""
    tax = load_taxonomy()
    screen = SafetyScreen(tax, load_safety_lexicons(tax))
    if mode == "rules":
        return (lambda text: screen.assess(text).level), "rules-only"
    risk = choose_risk_model(student=True)
    if risk.model is None:
        raise RuntimeError(f"the packaged student did not load ({risk.reason})")
    model_screen = screen.with_model(risk.model, model_plan_evidence=False)
    return (lambda text: model_screen.assess(text).level), risk.label


def format_report(
    mode: str, label: str, outcomes: Sequence[Outcome], skips: Sequence[Seed]
) -> str:
    judged = [o for o in outcomes if o.held is not None]
    failed = [o for o in judged if not o.held]
    lines = [
        f"== 变形测试 · 模式 {mode} · 实际运行的风险模型：{label} ==",
        f"种子：{len({o.seed.id for o in outcomes}) + len(skips)} 个；变换：{len(TRANSFORMS)} 种",
        "跳过（原句本身就没达到期望，已知缺口）："
        + (
            "、".join(f"{src} {n}" for src, n in sorted(Counter(s.source for s in skips).items()))
            or "无"
        ),
        "总不变率（L2/L3 不掉档，L0 不升到 L2 及以上）："
        + _rate(len(judged) - len(failed), len(judged)),
        "",
        "按变换（不变率；失败的 种子id/变换）：",
    ]
    for family, title in FAMILIES.items():
        members = [t for t in TRANSFORMS if t.family == family]
        if not members:
            continue
        lines.append(f"  [{title}]")
        for t in members:
            mine = [o for o in judged if o.transform.name == t.name]
            bad = [o for o in mine if not o.held]
            line = f"    {t.name:<20} {_rate(len(mine) - len(bad), len(mine))}  失败 {len(bad)}"
            lines.append(line)
            if bad:
                lines.append(f"      {_ids(bad)}")
    lines += ["", "按种子类别（不变率；失败数）："]
    by_category: dict[str, list[Outcome]] = defaultdict(list)
    for o in judged:
        by_category[o.seed.category].append(o)
    for category in sorted(by_category):
        mine = by_category[category]
        bad = [o for o in mine if not o.held]
        lines.append(f"  {category:<28} {_rate(len(mine) - len(bad), len(mine))}  失败 {len(bad)}")
    lines += ["", "失败按方式："]
    kinds = Counter((o.transform.family, o.kind) for o in failed)
    for (family, kind), n in sorted(kinds.items()):
        lines.append(f"  {FAMILIES[family]}：{kind} {n} 条")
    if not kinds:
        lines.append("  （无）")
    l1 = [o for o in outcomes if o.held is None]
    up = sum(o.level > o.original for o in l1)
    down = sum(o.level < o.original for o in l1)
    kept = sum(o.level is CrisisLevel.L1 for o in l1)
    lines += [
        "",
        "L1 种子（只报告）：变体与原句同级 "
        + _rate(len(l1) - up - down, len(l1))
        + f"（升 {up}，降 {down}）；变体仍是 L1 "
        + _rate(kept, len(l1)),
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="危机筛查的变形测试报告：只打印统计和 种子id/变换，从不打印句子。"
    )
    parser.add_argument("--mode", choices=MODES, default="rules", help="rules（默认）或 model")
    parser.add_argument(
        "--write-gaps",
        action="store_true",
        help="按失败项重写 tests/safety/known_metamorphic_gaps.yaml（只限 rules 模式）",
    )
    args = parser.parse_args(argv)
    if args.write_gaps and args.mode != "rules":
        parser.error("--write-gaps 只用于 rules 模式")
    try:
        level, label = screen_for(args.mode)
    except RuntimeError as exc:
        print(f"metamorphic_report: {exc}", file=sys.stderr)
        return 2
    outcomes, skips = run(level, load_seeds())
    print(format_report(args.mode, label, outcomes, skips))
    if args.write_gaps:
        failed = [o for o in outcomes if o.held is False]
        GAPS_FILE.write_text(render_gaps(failed), encoding="utf-8")
        print(f"\n已写入 {GAPS_FILE.name}：{len(failed)} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
