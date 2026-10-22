#!/usr/bin/env python3
"""Export the project's safety cases as one CSV for the crisis feasibility notebook.

Rows have one of three roles:

- ``train``: cases.yaml, the ho* reviewer probes, and the known limitations other than
  kl_fr*, all written or tuned by the same author;
- ``probe``: the 52-sentence fresh-author probe (fr* in tuned_probe.yaml plus kl_fr* in
  known_false_positives.yaml). Its model results were seen on 2026-10-22, so it is no
  longer an independent test: report it, but never choose thresholds or settings by it;
- ``fresh``: an optional independent evaluation set (``--fresh-eval``), a CSV with columns
  id, text, level (L0-L3) written by someone who has not seen the cases or the lexicon.

Test sentences must never be trained on, so train rows that duplicate or nearly duplicate
a probe or fresh sentence are dropped and reported.

Each row also carries ``rule_level``, what today's rules-mode SafetyScreen returns for it,
and ``category``, the cases.yaml category (empty for other sources).

Run from the repository root with the project's venv:

    .venv/bin/python training/colab/export_olivia_data.py [--fresh-eval path/to/fresh.csv]
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
from pathlib import Path

import yaml

from olivia.core.safety.crisis import SafetyScreen
from olivia.core.safety.lexicon import load_safety_lexicons
from olivia.core.safety.normalize import normalize
from olivia.core.taxonomy import load_taxonomy

ROOT = Path(__file__).resolve().parents[2]
SAFETY_TESTS = ROOT / "tests" / "safety"
PROBE_SIZE = 52
NEAR_DUPLICATE_JACCARD = 0.8
LEVELS = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}
ROLES = ("train", "probe", "fresh")
TEST_ROLES = ("probe", "fresh")


def _load(name: str) -> list[dict]:
    with open(SAFETY_TESTS / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


def collect_rows() -> list[dict]:
    """All labelled sentences from the test suite with their role, before de-duplication."""
    rows = []
    for case in _load("cases.yaml"):
        rows.append({"id": case["id"], "text": case["text"], "level": case["expect"],
                     "role": "train", "source": "cases", "category": case["category"]})
    for case in _load("tuned_probe.yaml"):
        probe = case["id"].startswith("fr")
        rows.append({"id": case["id"], "text": case["text"], "level": case["expect"],
                     "role": "probe" if probe else "train",
                     "source": "fresh_probe" if probe else "tuned_probe", "category": ""})
    for case in _load("known_false_positives.yaml"):
        # `ideal` is the human reading; `current` is only what the rules say today.
        probe = case["id"].startswith("kl_fr")
        rows.append({"id": case["id"].removeprefix("kl_") if probe else case["id"],
                     "text": case["text"], "level": case["ideal"],
                     "role": "probe" if probe else "train",
                     "source": "fresh_probe" if probe else "known_limitations", "category": ""})
    return rows


def load_fresh(path: Path) -> list[dict]:
    """An independent evaluation set: CSV with id, text, level (L0-L3)."""
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        missing = {"id", "text", "level"} - set(reader.fieldnames or [])
        if missing:
            raise SystemExit(f"{path}: missing columns {sorted(missing)}")
        rows = [{"id": r["id"], "text": r["text"], "level": r["level"].strip(), "role": "fresh",
                 "source": "fresh_eval", "category": ""} for r in reader]
    bad = [r["id"] for r in rows if r["level"] not in LEVELS]
    if bad:
        raise SystemExit(f"{path}: level must be L0-L3, bad rows: {bad[:10]}")
    return rows


def _bigrams(text: str) -> set[str]:
    return {text[i:i + 2] for i in range(len(text) - 1)} or {text}


def _jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b)


def drop_test_overlap(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Remove train rows that equal or nearly equal a test sentence after normalization."""
    test_grams = [_bigrams(normalize(r["text"])) for r in rows if r["role"] in TEST_ROLES]
    kept, dropped = [], []
    seen_train: set[str] = set()
    for row in rows:
        if row["role"] in TEST_ROLES:
            kept.append(row)
            continue
        norm = normalize(row["text"])
        grams = _bigrams(norm)
        if norm in seen_train or any(_jaccard(grams, t) >= NEAR_DUPLICATE_JACCARD
                                     for t in test_grams):
            dropped.append(row)
            continue
        seen_train.add(norm)
        kept.append(row)
    return kept, dropped


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "build" / "colab_data",
                        help="output directory (default: build/colab_data, git-ignored)")
    parser.add_argument("--fresh-eval", type=Path, default=None,
                        help="optional independent evaluation CSV (id, text, level)")
    args = parser.parse_args()

    rows = collect_rows()
    probe_count = sum(r["role"] == "probe" for r in rows)
    if probe_count != PROBE_SIZE:
        raise SystemExit(f"expected {PROBE_SIZE} fresh-author probe sentences, found {probe_count}")
    if args.fresh_eval is not None:
        rows += load_fresh(args.fresh_eval)
    rows, dropped = drop_test_overlap(rows)

    tax = load_taxonomy()
    screen = SafetyScreen(tax, load_safety_lexicons(tax))
    for row in rows:
        row["level"] = LEVELS[row["level"]]
        row["rule_level"] = int(screen.assess(row["text"]).level)

    args.out.mkdir(parents=True, exist_ok=True)
    csv_path = args.out / "olivia_cases.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "text", "level", "role", "source",
                                               "category", "rule_level"])
        writer.writeheader()
        writer.writerows(rows)

    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                            capture_output=True, text=True, check=False).stdout.strip()
    manifest = {
        "git_commit": commit,
        "rows": len(rows),
        "by_role_and_level": {
            role: {lvl: sum(r["role"] == role and r["level"] == n for r in rows)
                   for lvl, n in LEVELS.items()}
            for role in ROLES
        },
        "dropped_train_rows": [{"id": r["id"], "text": r["text"]} for r in dropped],
    }
    with open(args.out / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"wrote {csv_path} ({len(rows)} rows, git {commit})")
    print(json.dumps(manifest["by_role_and_level"], ensure_ascii=False))
    print(f"dropped {len(dropped)} train rows that duplicate a test or train sentence")
    for r in dropped:
        print(f"  - {r['id']}: {r['text']}")


if __name__ == "__main__":
    main()
