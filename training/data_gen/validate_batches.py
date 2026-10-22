#!/usr/bin/env python3
"""Validate and merge synthetic batches for the perception model (roadmap P6-2).

Each batch is a JSONL file of records matching label_schema.json, plus a `meta` object
{"batch", "slot"} naming the quota slot it fills (e.g. "L0_hyperbole"). The script:

1. validates every record against the schema (cross-head constraints included);
2. checks the batch's slot counts against quota.yaml;
3. drops exact and near duplicates (character-bigram Jaccard >= 0.8) within the round;
4. drops any record that equals or nearly equals a test sentence, so the evaluation sets
   (the fresh-author probe, the interim set and, once written, the owner's set) are never
   trained on;
5. writes the merged, de-duplicated records to the output file and prints a report.

Run with an interpreter that has PyYAML and jsonschema (the training venv, not the
project's runtime):

    python training/data_gen/validate_batches.py BATCH_DIR --out merged.jsonl \
        --test-csv build/colab_data/olivia_cases.csv --test-csv build/eval/interim_fresh.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

HERE = Path(__file__).resolve().parent
NEAR_DUPLICATE_JACCARD = 0.8


def bigrams(text: str) -> frozenset[str]:
    t = re.sub(r"\s+", "", text)
    return frozenset(t[i:i + 2] for i in range(len(t) - 1)) or frozenset({t})


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    return len(a & b) / len(a | b)


def load_test_texts(paths: list[Path]) -> list[str]:
    """Texts of test rows: role probe/fresh in an export CSV, or every row of a plain eval CSV."""
    texts = []
    for path in paths:
        with open(path, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                if row.get("role", "fresh") in ("probe", "fresh") and row.get("text", "").strip():
                    texts.append(row["text"])
    return texts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("batch_dir", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--test-csv", type=Path, action="append", default=[])
    args = parser.parse_args()

    schema = json.loads((HERE / "label_schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    quota = yaml.safe_load((HERE / "quota.yaml").read_text(encoding="utf-8"))
    test_grams = [bigrams(t) for t in load_test_texts(args.test_csv)]

    kept: list[dict] = []
    kept_grams: list[frozenset[str]] = []
    report: Counter[str] = Counter()
    slot_counts: dict[str, Counter[str]] = {}
    for path in sorted(args.batch_dir.glob("*.jsonl")):
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            record = json.loads(line)
            meta = record.pop("meta", {})
            errors = sorted(validator.iter_errors(record), key=lambda e: list(e.path))
            if errors:
                report["schema_error"] += 1
                print(f"{path.name}:{line_no}: {errors[0].message}")
                continue
            slot_counts.setdefault(meta.get("batch", path.stem), Counter())[meta.get("slot", "?")] += 1
            grams = bigrams(record["text"])
            if any(jaccard(grams, t) >= NEAR_DUPLICATE_JACCARD for t in test_grams):
                report["dropped_test_overlap"] += 1
                continue
            if any(jaccard(grams, k) >= NEAR_DUPLICATE_JACCARD for k in kept_grams):
                report["dropped_duplicate"] += 1
                continue
            record["source"] = f"synthetic:{meta.get('batch', path.stem)}"
            kept.append(record)
            kept_grams.append(grams)
            report["kept"] += 1

    for batch, counts in sorted(slot_counts.items()):
        off = {s: (counts.get(s, 0), n) for s, n in quota["risk_mix"].items() if counts.get(s, 0) != n}
        if off:
            print(f"{batch}: slot counts differ from quota (got, want): {off}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        for record in kept:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(json.dumps(dict(report), ensure_ascii=False))
    print("risk:", dict(Counter(r["risk"] for r in kept)))
    print("emotion:", dict(Counter(r["emotion"] for r in kept)))


if __name__ == "__main__":
    main()
