#!/usr/bin/env python3
"""trace_requirements.py - every PRD/SDD requirement id has evidence or a stated reason.

Reads the requirement ids that ``docs/PRODUCT_DOCUMENT.md`` and ``docs/SYSTEM_DESIGN.md``
name (ONB, MIYI, COLBO, WILLOW, CHANG, GEO, SAFE, NG, RSK, Q and the G-0..G-5 gates) and
the trace in ``tests/requirements_trace.yaml``. Each id needs one entry:

  status   covered (the behaviour is asserted), partial (asserted in part; ``reason`` says
           what is not) or exempt (not testable here; ``reason`` says why, e.g. P7 or an
           external gate).
  tests    ``path::name`` (or ``path::Class::name``); the file must define each name.
  checks   a script under ``scripts/`` that ``scripts/check.sh`` or the CI workflow runs.

covered and partial need at least one test or check. An entry for an id the documents no
longer name is an error too, so the trace cannot drift from the documents.

Exit status 0 when the trace is complete, 1 otherwise (each problem on its own line).
``--markdown`` prints the whole matrix instead of the summary.

Usage: python scripts/trace_requirements.py [--markdown]
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = ("docs/PRODUCT_DOCUMENT.md", "docs/SYSTEM_DESIGN.md")
TRACE = "tests/requirements_trace.yaml"
# What runs a check script; a script nothing runs is not evidence.
RUNNERS = ("scripts/check.sh", ".github/workflows/ci.yml")
STATUSES = ("covered", "partial", "exempt")

# SAFE takes two digits: SAFE-1 / SAFE-2 in the SDD are plan step names, not requirements.
_ID = re.compile(
    r"(?<![A-Za-z0-9-])"
    r"((?:ONB|MIYI|COLBO|WILLOW|CHANG|GEO|NG|RSK|Q)-\d+[a-z]?|SAFE-\d{2}[a-z]?|G-[0-5])"
    r"(?![A-Za-z0-9-])"
)
_FAMILY_ORDER = ("ONB", "MIYI", "COLBO", "WILLOW", "CHANG", "GEO", "SAFE", "NG", "RSK", "Q", "G")


@dataclass(frozen=True)
class Entry:
    req_id: str
    status: str
    summary: str
    reason: str
    tests: tuple[str, ...]
    checks: tuple[str, ...]


def document_ids(root: Path) -> set[str]:
    found: set[str] = set()
    for name in DOCUMENTS:
        found.update(_ID.findall((root / name).read_text(encoding="utf-8")))
    return found


def sort_key(req_id: str) -> tuple[int, int, str]:
    family, _, rest = req_id.partition("-")
    digits = re.match(r"\d+", rest)
    return (_FAMILY_ORDER.index(family), int(digits.group()) if digits else 0, rest)


def _strings(value: object, where: str, problems: list[str]) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        problems.append(f"{where}: must be a list of strings")
        return ()
    return tuple(value)


def load_trace(root: Path, problems: list[str]) -> dict[str, Entry]:
    doc = yaml.safe_load((root / TRACE).read_text(encoding="utf-8")) or {}
    if not isinstance(doc, dict):
        problems.append(f"{TRACE}: top level must be a mapping of requirement ids")
        return {}
    entries: dict[str, Entry] = {}
    for req_id, body in doc.items():
        if not isinstance(body, dict):
            problems.append(f"{req_id}: entry must be a mapping")
            continue
        entries[str(req_id)] = Entry(
            req_id=str(req_id),
            status=str(body.get("status", "")),
            summary=str(body.get("summary", "")),
            reason=str(body.get("reason", "") or ""),
            tests=_strings(body.get("tests"), f"{req_id}.tests", problems),
            checks=_strings(body.get("checks"), f"{req_id}.checks", problems),
        )
    return entries


def _defines(source: str, name: str) -> bool:
    return re.search(rf"^\s*(?:async\s+)?(?:def|class)\s+{re.escape(name)}\b", source, re.M) is not None


def test_problems(root: Path, ref: str) -> list[str]:
    path, sep, names = ref.partition("::")
    if not sep or not names:
        return [f"test reference {ref!r} is not path::name"]
    file = root / path
    if not path.startswith("tests/") or not file.is_file():
        return [f"test file {path} does not exist"]
    source = file.read_text(encoding="utf-8")
    return [f"{path} defines no {name}" for name in names.split("::") if not _defines(source, name)]


def check_problems(root: Path, ref: str) -> list[str]:
    if not ref.startswith("scripts/") or not (root / ref).is_file():
        return [f"check script {ref} does not exist"]
    runners = "".join((root / r).read_text(encoding="utf-8") for r in RUNNERS if (root / r).is_file())
    if ref not in runners:
        return [f"check script {ref} is not run by {' or '.join(RUNNERS)}"]
    return []


def validate(root: Path) -> tuple[dict[str, Entry], list[str]]:
    problems: list[str] = []
    ids = document_ids(root)
    entries = load_trace(root, problems)
    for req_id in sorted(ids - entries.keys(), key=sort_key):
        problems.append(f"{req_id}: named in the documents but missing from {TRACE}")
    for req_id in sorted(entries.keys() - ids, key=str):
        problems.append(f"{req_id}: in {TRACE} but no longer named in the documents")
    for entry in entries.values():
        where = entry.req_id
        if entry.status not in STATUSES:
            problems.append(f"{where}: status must be one of {', '.join(STATUSES)}")
            continue
        if not entry.summary.strip():
            problems.append(f"{where}: summary is empty")
        if entry.status in ("partial", "exempt") and not entry.reason.strip():
            problems.append(f"{where}: {entry.status} needs a reason")
        if entry.status in ("covered", "partial") and not (entry.tests or entry.checks):
            problems.append(f"{where}: {entry.status} needs at least one test or check")
        for ref in entry.tests:
            problems.extend(f"{where}: {p}" for p in test_problems(root, ref))
        for ref in entry.checks:
            problems.extend(f"{where}: {p}" for p in check_problems(root, ref))
    return entries, problems


def markdown(entries: dict[str, Entry]) -> str:
    lines = ["| 编号 | 状态 | 要求 | 证据 | 说明 |", "| :--- | :--- | :--- | :--- | :--- |"]
    for req_id in sorted(entries, key=sort_key):
        e = entries[req_id]
        evidence = "<br>".join(f"`{ref}`" for ref in (*e.tests, *e.checks)) or "-"
        lines.append(f"| {req_id} | {e.status} | {e.summary} | {evidence} | {e.reason or '-'} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--markdown", action="store_true", help="print the whole matrix")
    args = parser.parse_args(argv)
    entries, problems = validate(ROOT)
    if problems:
        for problem in problems:
            print(f"trace: {problem}", file=sys.stderr)
        return 1
    if args.markdown:
        print(markdown(entries))
        return 0
    counts = Counter(e.status for e in entries.values())
    print(
        f"trace: {len(entries)} requirement ids, "
        + ", ".join(f"{counts.get(s, 0)} {s}" for s in STATUSES)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
