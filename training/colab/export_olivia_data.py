#!/usr/bin/env python3
"""Export the project's safety cases as one CSV for the crisis feasibility notebook.

Rows have one of five roles:

- ``train``: cases.yaml, the ho* reviewer probes, and the known limitations other than
  kl_fr*, all written or tuned by the same author;
- ``probe``: the 52-sentence fresh-author probe (fr* in tuned_probe.yaml plus kl_fr* in
  known_false_positives.yaml). Its model results were seen on 2026-10-22, so it is no
  longer an independent test: report it, but never choose thresholds or settings by it;
- ``dev``: an optional development set (``--dev-eval``, same columns as ``--fresh-eval``),
  e.g. build/eval/interim_fresh.csv. Never trained on, but its results may be looked at
  repeatedly to choose between models, settings or thresholds; it is not a final test;
- ``fresh``: an optional independent evaluation set (``--fresh-eval``), a CSV with columns
  id, text, level (L0-L3) written by someone who has not seen the cases or the lexicon.
  It is the final test: never choose anything by it. A sentence may not be in both the
  dev and the fresh set;
- ``exclude``: sentences that are never trained on and never scored by the notebook, only
  used to drop near-duplicates from training (level and rule_level -1). Always every user
  turn of the G-5 red-team cases (tests/redteam/cases.yaml: the red-team runner is the
  release gate for step C5, so its inputs must not leak into training), plus any CSV with
  a ``text`` column given with ``--exclude-csv`` (e.g. build/eval/redteam_texts.csv).

Test sentences must never be trained on, so train rows that duplicate or nearly duplicate
a probe, dev, fresh or exclude sentence are dropped and reported.

Each row also carries ``rule_level``, what today's rules-mode SafetyScreen returns for it,
and ``category``, the cases.yaml category (empty for other sources).

Run from the repository root with the project's venv:

    .venv/bin/python training/colab/export_olivia_data.py \
        [--dev-eval build/eval/interim_fresh.csv] \
        [--fresh-eval path/to/fresh.csv] [--exclude-csv build/eval/redteam_texts.csv]
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
REDTEAM_CASES = ROOT / "tests" / "redteam" / "cases.yaml"
PROBE_SIZE = 52
NEAR_DUPLICATE_JACCARD = 0.8
LEVELS = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}
ROLES = ("train", "probe", "dev", "fresh", "exclude")
TEST_ROLES = ("probe", "dev", "fresh")
EVAL_SOURCES = {"dev": "dev_eval", "fresh": "fresh_eval"}
EXCLUDE_ROLE = "exclude"
HELD_OUT_ROLES = (*TEST_ROLES, EXCLUDE_ROLE)


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


def load_fresh(path: Path, role: str = "fresh") -> list[dict]:
    """An evaluation set (``role`` fresh or dev): CSV with id, text, level (L0-L3)."""
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        missing = {"id", "text", "level"} - set(reader.fieldnames or [])
        if missing:
            raise SystemExit(f"{path}: missing columns {sorted(missing)}")
        rows = [{"id": r["id"], "text": r["text"], "level": r["level"].strip(), "role": role,
                 "source": EVAL_SOURCES[role], "category": ""} for r in reader]
    bad = [r["id"] for r in rows if r["level"] not in LEVELS]
    if bad:
        raise SystemExit(f"{path}: level must be L0-L3, bad rows: {bad[:10]}")
    empty = [r["id"] for r in rows if not r["text"].strip()]
    if empty:
        raise SystemExit(f"{path}: {len(empty)} rows have no text, e.g. {empty[:10]}")
    return rows


def collect_eval_rows(fresh: Path | None, dev: Path | None) -> list[dict]:
    """The dev rows, then the fresh rows; a sentence may not be in both sets."""
    dev_rows = load_fresh(dev, "dev") if dev is not None else []
    fresh_rows = load_fresh(fresh, "fresh") if fresh is not None else []
    shared = {normalize(r["text"]) for r in dev_rows} & {normalize(r["text"]) for r in fresh_rows}
    if shared:
        raise SystemExit(f"{len(shared)} sentences are in both the dev and the fresh set; "
                         "the final test must stay separate from the dev set")
    return dev_rows + fresh_rows


def collect_exclusions(extra: list[Path]) -> list[dict]:
    """Exclude-only rows: every distinct red-team user turn, then each ``--exclude-csv`` row."""
    rows, seen = [], set()

    def add(row_id: str, text: str, source: str, category: str) -> None:
        if text.strip() and text not in seen:
            seen.add(text)
            rows.append({"id": row_id, "text": text, "level": None, "role": EXCLUDE_ROLE,
                         "source": source, "category": category})

    with open(REDTEAM_CASES, encoding="utf-8") as f:
        cases = yaml.safe_load(f)
    for case in cases:
        for turn_no, turn in enumerate(case["turns"], 1):
            add(f"{case['id']}_t{turn_no}", turn, "redteam", case["category"])
    for path in extra:
        with open(path, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if "text" not in (reader.fieldnames or []):
                raise SystemExit(f"{path}: an exclude CSV needs a text column")
            for n, r in enumerate(reader, 1):
                add(r.get("id") or f"{path.stem}_{n}", r["text"], f"exclude:{path.stem}", "")
    return rows


def _bigrams(text: str) -> set[str]:
    return {text[i:i + 2] for i in range(len(text) - 1)} or {text}


def _jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b)


def drop_test_overlap(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Remove train rows that equal or nearly equal a test or exclude sentence after normalization."""
    test_grams = [_bigrams(normalize(r["text"])) for r in rows if r["role"] in HELD_OUT_ROLES]
    kept, dropped = [], []
    seen_train: set[str] = set()
    for row in rows:
        if row["role"] in HELD_OUT_ROLES:
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
                        help="optional independent evaluation CSV (id, text, level): "
                             "the final test")
    parser.add_argument("--dev-eval", type=Path, default=None,
                        help="optional development CSV (id, text, level): never trained on, "
                             "used to choose between models")
    parser.add_argument("--exclude-csv", type=Path, action="append", default=[],
                        help="CSV with a text column: never trained on, never scored "
                             "(the red-team turns are always excluded)")
    args = parser.parse_args()

    rows = collect_rows()
    probe_count = sum(r["role"] == "probe" for r in rows)
    if probe_count != PROBE_SIZE:
        raise SystemExit(f"expected {PROBE_SIZE} fresh-author probe sentences, found {probe_count}")
    rows += collect_eval_rows(args.fresh_eval, args.dev_eval)
    rows += collect_exclusions(args.exclude_csv)
    rows, dropped = drop_test_overlap(rows)

    tax = load_taxonomy()
    screen = SafetyScreen(tax, load_safety_lexicons(tax))
    for row in rows:
        if row["role"] == EXCLUDE_ROLE:
            row["level"] = row["rule_level"] = -1
            continue
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
            for role in TEST_ROLES + ("train",)
        },
        "exclude_rows": {source: sum(r["role"] == EXCLUDE_ROLE and r["source"] == source
                                     for r in rows)
                         for source in sorted({r["source"] for r in rows
                                               if r["role"] == EXCLUDE_ROLE})},
        "dropped_train_rows": [{"id": r["id"], "text": r["text"]} for r in dropped],
    }
    with open(args.out / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"wrote {csv_path} ({len(rows)} rows, git {commit})")
    print(json.dumps(manifest["by_role_and_level"], ensure_ascii=False))
    print("exclude-only rows:", json.dumps(manifest["exclude_rows"], ensure_ascii=False))
    print(f"dropped {len(dropped)} train rows that duplicate a test or train sentence")
    for r in dropped:
        print(f"  - {r['id']}: {r['text']}")


if __name__ == "__main__":
    main()
