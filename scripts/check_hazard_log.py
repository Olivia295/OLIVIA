#!/usr/bin/env python3
"""check_hazard_log.py - the clinical safety hazard log is well formed and its evidence is real.

Reads ``docs/safety/hazard-log.md`` (a draft laid out after DCB0129). Every fenced ``yaml``
block in it is one hazard, a mapping with these fields:

  id          ``HAZ-NN``, unique
  title       a short name, used in the summary table
  hazard      what can go wrong
  cause       list of causes
  effect      what it does to the user
  initial     ``{severity, likelihood, risk}`` before the controls
  controls    list of code or data locations, or PRD / SDD / plan references; a control
              that starts with a path (``olivia/core/safety/compose.py ...``) needs that
              path to exist
  evidence    list of pytest node ids (``tests/...py::name`` or ``tests/...py::Class::name``,
              found by an AST scan of the file, the last name a test) or scripts under
              ``scripts/`` that exist
  residual    ``{severity, likelihood, risk}`` with the controls in place
  status      已控制 | 部分控制 | 开放 | 待 G-0
  known_gaps  list (may be empty) of ``{file, kind, count}`` with optional ``mode``,
              ``category`` and ``ids``: how many strict-xfail entries of a
              ``tests/redteam/known_gaps*.yaml`` file have that kind (and category, mode,
              ids). The count is checked against the file, so the log cannot drift from it.

Severity is one of 轻微 显著 较大 重大 灾难性, likelihood one of 极低 低 中 高 极高; the risk
(1-5) must be the one :data:`RISK_MATRIX` gives for the pair. The residual risk may not
exceed the initial risk, and 已控制 may not carry known gaps. Every hazard needs at least one
control and one piece of evidence. The summary table between the two summary markers must
be exactly what ``--table`` prints.

Exit status 0 when the log is valid (a one-line summary on stdout), 1 otherwise (each
problem on its own line on stderr).

Usage: python scripts/check_hazard_log.py [--table]
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
LOG = "docs/safety/hazard-log.md"
CASES = ("tests/redteam/cases.yaml", "tests/redteam/multiturn.yaml")

SEVERITIES = ("轻微", "显著", "较大", "重大", "灾难性")
LIKELIHOODS = ("极低", "低", "中", "高", "极高")
STATUSES = ("已控制", "部分控制", "开放", "待 G-0")
# Rows by likelihood (极低 .. 极高), columns by severity (轻微 .. 灾难性).
RISK_MATRIX = (
    (1, 1, 2, 2, 3),
    (1, 2, 2, 3, 4),
    (2, 2, 3, 3, 4),
    (2, 3, 3, 4, 5),
    (3, 4, 4, 5, 5),
)
FIELDS = (
    "id",
    "title",
    "hazard",
    "cause",
    "effect",
    "initial",
    "controls",
    "evidence",
    "residual",
    "status",
    "known_gaps",
)
SUMMARY_START = "<!-- hazard-summary:start -->"
SUMMARY_END = "<!-- hazard-summary:end -->"

_ID = re.compile(r"HAZ-\d{2}")
_BLOCK = re.compile(r"^```yaml[ \t]*\n(.*?)^```", re.M | re.S)
_LEADING_PATH = re.compile(r"[A-Za-z0-9_.\-]+(?:/[A-Za-z0-9_.\-]+)+")
_GAP_FILE = re.compile(r"tests/redteam/known_gaps[A-Za-z0-9_]*\.yaml")


@dataclass(frozen=True)
class Rating:
    severity: str
    likelihood: str
    risk: int

    def label(self) -> str:
        return f"{self.severity} / {self.likelihood} → {self.risk}"


@dataclass(frozen=True)
class Hazard:
    hazard_id: str
    title: str
    initial: Rating
    residual: Rating
    status: str
    gap_count: int


def matrix_risk(severity: str, likelihood: str) -> int:
    return RISK_MATRIX[LIKELIHOODS.index(likelihood)][SEVERITIES.index(severity)]


def blocks(text: str) -> list[tuple[int, str]]:
    """Every fenced yaml block with the line its body starts on."""
    return [(text.count("\n", 0, m.start(1)) + 1, m.group(1)) for m in _BLOCK.finditer(text)]


def _strings(value: object, where: str, problems: list[str]) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        problems.append(f"{where}: must be a list of non-empty strings")
        return []
    return list(value)


def _rating(value: object, where: str, problems: list[str]) -> Rating | None:
    if not isinstance(value, dict):
        problems.append(f"{where}: must be a mapping of severity, likelihood and risk")
        return None
    severity, likelihood, risk = value.get("severity"), value.get("likelihood"), value.get("risk")
    ok = True
    if severity not in SEVERITIES:
        problems.append(f"{where}.severity must be one of {' '.join(SEVERITIES)}")
        ok = False
    if likelihood not in LIKELIHOODS:
        problems.append(f"{where}.likelihood must be one of {' '.join(LIKELIHOODS)}")
        ok = False
    if isinstance(risk, bool) or not isinstance(risk, int) or not 1 <= risk <= 5:
        problems.append(f"{where}.risk must be a whole number from 1 to 5")
        ok = False
    if not ok:
        return None
    assert isinstance(severity, str) and isinstance(likelihood, str) and isinstance(risk, int)
    expected = matrix_risk(severity, likelihood)
    if risk != expected:
        problems.append(f"{where}.risk is {risk} but {severity} / {likelihood} is {expected}")
        return None
    return Rating(severity, likelihood, risk)


class Sources:
    """The files the log points at, each read and parsed once."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._defs: dict[str, dict[str, set[str] | None]] = {}
        self._yaml: dict[str, Any] = {}
        self._categories: dict[str, str] | None = None

    def definitions(self, path: str) -> dict[str, set[str] | None]:
        """Top-level functions (``None``) and classes (their method names) of a file."""
        if path not in self._defs:
            tree = ast.parse((self.root / path).read_text(encoding="utf-8"), filename=path)
            found: dict[str, set[str] | None] = {}
            for node in tree.body:
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                    found[node.name] = None
                elif isinstance(node, ast.ClassDef):
                    found[node.name] = {
                        n.name
                        for n in node.body
                        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
                    }
            self._defs[path] = found
        return self._defs[path]

    def load(self, path: str) -> Any:
        if path not in self._yaml:
            self._yaml[path] = yaml.safe_load((self.root / path).read_text(encoding="utf-8"))
        return self._yaml[path]

    def categories(self) -> dict[str, str]:
        """Case and scenario id to category, from the red-team sets."""
        if self._categories is None:
            found: dict[str, str] = {}
            for path in CASES:
                if (self.root / path).is_file():
                    for item in self.load(path) or []:
                        if isinstance(item, dict) and "id" in item and "category" in item:
                            found[str(item["id"])] = str(item["category"])
            self._categories = found
        return self._categories


def evidence_problems(sources: Sources, ref: str) -> list[str]:
    if "::" not in ref:
        if ref.startswith("scripts/") and (sources.root / ref).is_file():
            return []
        return [f"evidence {ref!r} is neither a pytest node id nor a script under scripts/"]
    path, _, rest = ref.partition("::")
    if not (path.startswith("tests/") and path.endswith(".py")):
        return [f"evidence {ref!r}: a test reference must name a tests/...py file"]
    if not (sources.root / path).is_file():
        return [f"test file {path} does not exist"]
    names = rest.split("::")
    names[-1] = names[-1].split("[", 1)[0]
    defs = sources.definitions(path)
    if len(names) == 1:
        name = names[0]
        if name not in defs:
            return [f"{path} defines no {name}"]
        is_class = defs[name] is not None
        if not name.startswith("Test" if is_class else "test"):
            return [f"{path}::{name} is not a test"]
        return []
    if len(names) == 2:
        cls, name = names
        methods = defs.get(cls)
        if methods is None:
            return [f"{path} defines no class {cls}"]
        if name not in methods:
            return [f"{path}::{cls} defines no {name}"]
        if not (cls.startswith("Test") and name.startswith("test")):
            return [f"{path}::{cls}::{name} is not a test"]
        return []
    return [f"evidence {ref!r}: use path::name or path::Class::name"]


def control_problems(root: Path, control: str) -> list[str]:
    match = _LEADING_PATH.match(control)
    if match and not (root / match.group()).exists():
        return [f"control {control!r} names {match.group()}, which does not exist"]
    return []


def _gap_entries(sources: Sources, spec: dict[str, Any], where: str) -> list[dict[str, Any]]:
    """The entries of the gap file (and mode) a known_gaps item points at."""
    path = spec.get("file")
    if not isinstance(path, str) or not _GAP_FILE.fullmatch(path):
        raise ValueError(f"{where}.file must be a tests/redteam/known_gaps*.yaml file")
    if not (sources.root / path).is_file():
        raise ValueError(f"{where}.file {path} does not exist")
    doc = sources.load(path)
    mode = spec.get("mode")
    if isinstance(doc, dict) and "gaps" in doc:
        if mode is not None:
            raise ValueError(f"{where}.mode: {path} has no modes")
        entries = doc["gaps"]
    elif isinstance(doc, dict):
        if mode not in doc:
            raise ValueError(f"{where}.mode must be one of {', '.join(map(str, doc))}")
        entries = doc[mode]
    else:
        raise ValueError(f"{where}.file {path} is not a known-gaps file")
    return [e for e in entries or [] if isinstance(e, dict)]


def gap_problems(sources: Sources, spec: object, where: str) -> tuple[int, list[str]]:
    """The count a known_gaps item states, and what is wrong with it."""
    if not isinstance(spec, dict):
        return 0, [f"{where}: must be a mapping with file, kind and count"]
    count, kind = spec.get("count"), spec.get("kind")
    category, ids = spec.get("category"), spec.get("ids")
    problems: list[str] = []
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        problems.append(f"{where}.count must be a whole number of at least 1")
    if not isinstance(kind, str) or not kind.strip():
        problems.append(f"{where}.kind must name a gap kind, e.g. crisis recall")
    if category is not None and not isinstance(category, str):
        problems.append(f"{where}.category must be a string")
    if ids is not None and (not isinstance(ids, list) or not all(isinstance(i, str) for i in ids)):
        problems.append(f"{where}.ids must be a list of ids")
    unknown = set(spec) - {"file", "mode", "kind", "category", "ids", "count"}
    if unknown:
        problems.append(f"{where}: unknown keys {', '.join(sorted(map(str, unknown)))}")
    try:
        entries = _gap_entries(sources, spec, where)
    except ValueError as error:
        problems.append(str(error))
    if problems:
        return 0, problems
    assert isinstance(count, int) and isinstance(kind, str)
    categories = sources.categories()
    matched: list[str] = []
    for entry in entries:
        gap_id = str(entry.get("id", ""))
        kinds = {k.strip() for k in str(entry.get("reason", "")).split(":", 1)[0].split(" + ")}
        if kind not in kinds:
            continue
        if category is not None and categories.get(gap_id) != category:
            continue
        if ids is not None and gap_id not in ids:
            continue
        matched.append(gap_id)
    if ids is not None:
        missing = sorted(set(ids) - set(matched))
        if missing:
            problems.append(f"{where}: {', '.join(missing)} not in {spec['file']} as {kind}")
    if len(matched) != count:
        problems.append(
            f"{where}.count is {count} but {spec['file']} holds {len(matched)}; "
            "update the count (or remove the item) to match the gap file"
        )
    return count, problems


def hazard_problems(
    sources: Sources, body: object, where: str
) -> tuple[Hazard | None, list[str]]:
    if not isinstance(body, dict):
        return None, [f"{where}: a hazard block must be a mapping"]
    problems: list[str] = []
    missing = [f for f in FIELDS if f not in body]
    if missing:
        problems.append(f"{where}: missing {', '.join(missing)}")
    unknown = set(body) - set(FIELDS)
    if unknown:
        problems.append(f"{where}: unknown fields {', '.join(sorted(map(str, unknown)))}")
    if missing:
        return None, problems
    hazard_id = body["id"]
    if not isinstance(hazard_id, str) or not _ID.fullmatch(hazard_id):
        problems.append(f"{where}: id must look like HAZ-01")
        hazard_id = str(hazard_id)
    where = hazard_id if _ID.fullmatch(hazard_id) else where
    for field in ("title", "hazard", "effect"):
        if not isinstance(body[field], str) or not body[field].strip():
            problems.append(f"{where}: {field} must be non-empty text")
    _strings(body["cause"], f"{where}.cause", problems)
    controls = _strings(body["controls"], f"{where}.controls", problems)
    evidence = _strings(body["evidence"], f"{where}.evidence", problems)
    if not controls:
        problems.append(f"{where}: needs at least one control")
    if not evidence:
        problems.append(f"{where}: needs at least one piece of evidence")
    for control in controls:
        problems.extend(f"{where}: {p}" for p in control_problems(sources.root, control))
    for ref in evidence:
        problems.extend(f"{where}: {p}" for p in evidence_problems(sources, ref))
    initial = _rating(body["initial"], f"{where}.initial", problems)
    residual = _rating(body["residual"], f"{where}.residual", problems)
    if initial and residual and residual.risk > initial.risk:
        problems.append(
            f"{where}: residual risk {residual.risk} exceeds initial risk {initial.risk}"
        )
    status = body["status"]
    if status not in STATUSES:
        problems.append(f"{where}: status must be one of {' / '.join(STATUSES)}")
    gaps = body["known_gaps"]
    gap_total = 0
    if not isinstance(gaps, list):
        problems.append(f"{where}.known_gaps must be a list (empty when there are none)")
    else:
        for i, spec in enumerate(gaps):
            count, found = gap_problems(sources, spec, f"{where}.known_gaps[{i}]")
            gap_total += count
            problems.extend(found)
    if status == "已控制" and gap_total:
        problems.append(f"{where}: 已控制 cannot carry known gaps ({gap_total})")
    if problems or initial is None or residual is None or not isinstance(status, str):
        return None, problems
    title = str(body["title"]).strip()
    return Hazard(hazard_id, title, initial, residual, status, gap_total), problems


def table(hazards: list[Hazard]) -> str:
    lines = ["| 编号 | 危害 | 初始风险 | 残余风险 | 状态 |", "| :--- | :--- | :--- | :--- | :--- |"]
    for h in sorted(hazards, key=lambda h: h.hazard_id):
        lines.append(
            f"| {h.hazard_id} | {h.title} | {h.initial.label()} | {h.residual.label()} "
            f"| {h.status} |"
        )
    return "\n".join(lines)


def _summary_block(text: str) -> str | None:
    start, end = text.find(SUMMARY_START), text.find(SUMMARY_END)
    if start < 0 or end < start:
        return None
    return text[start + len(SUMMARY_START) : end].strip()


def validate(root: Path) -> tuple[list[Hazard], list[str]]:
    path = root / LOG
    if not path.is_file():
        return [], [f"{LOG} does not exist"]
    text = path.read_text(encoding="utf-8")
    sources = Sources(root)
    problems: list[str] = []
    hazards: list[Hazard] = []
    seen: set[str] = set()
    found = blocks(text)
    if not found:
        problems.append(f"{LOG}: no yaml hazard blocks")
    for line, raw in found:
        where = f"{LOG}:{line}"
        try:
            body = yaml.safe_load(raw)
        except yaml.YAMLError as error:
            problems.append(f"{where}: not valid YAML ({error.__class__.__name__})")
            continue
        if isinstance(body, dict) and isinstance(body.get("id"), str):
            if body["id"] in seen:
                problems.append(f"{body['id']}: duplicate id ({where})")
            seen.add(body["id"])
        hazard, found_problems = hazard_problems(sources, body, where)
        problems.extend(found_problems)
        if hazard is not None:
            hazards.append(hazard)
    summary = _summary_block(text)
    if summary is None:
        problems.append(f"{LOG}: no summary table between {SUMMARY_START} and {SUMMARY_END}")
    elif not problems and summary != table(hazards):
        problems.append(
            f"{LOG}: the summary table is out of date; paste the output of "
            "`python scripts/check_hazard_log.py --table` between the markers"
        )
    return hazards, problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--table", action="store_true", help="print the summary table")
    args = parser.parse_args(argv)
    hazards, problems = validate(ROOT)
    if args.table:
        # Printing the table is how a stale one gets fixed, so only other problems stop it.
        problems = [p for p in problems if "summary table" not in p]
        if not problems:
            print(table(hazards))
            return 0
    if problems:
        for problem in problems:
            print(f"hazard log: {problem}", file=sys.stderr)
        return 1
    counts = Counter(h.status for h in hazards)
    high = [h.hazard_id for h in sorted(hazards, key=lambda h: h.hazard_id) if h.residual.risk >= 3]
    print(
        f"hazard log: {len(hazards)} hazards, "
        + ", ".join(f"{counts.get(s, 0)} {s}" for s in STATUSES)
        + f"; residual risk >= 3: {', '.join(high) or '-'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
