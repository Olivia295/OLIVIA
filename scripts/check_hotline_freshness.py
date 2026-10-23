#!/usr/bin/env python3
"""Fail when any hotline entry was last verified too long ago.

    python scripts/check_hotline_freshness.py [--max-age-days 90] [--today YYYY-MM-DD]
                                               [--store PATH]

Reads the hotline data the product uses (``olivia/data/resources/hotlines.yaml``, loaded
and signature-checked through ``core/resources/bundle.py``) and checks the ``verified_on``
date of every emergency number and every line in every region. Prints one line per entry
older than ``--max-age-days`` (90 by default) and exits 1 when there is any, else 0; 2 when
the data cannot be read. ``--store`` checks another YAML file of the same shape instead
(an unsigned draft, or a test fixture); its signature is not checked.

The quarterly GitHub Actions workflow ``.github/workflows/hotline-freshness.yml`` runs
this; the owner and the re-verification steps are in ``docs/resources/hotline-sources.md``.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import yaml

from olivia.core.resources.bundle import BundleIntegrityError, load_hotlines_bytes
from olivia.core.resources.store import ResourceDataError, ResourceStore, parse_store

MAX_AGE_DAYS = 90


@dataclass(frozen=True)
class Stale:
    region: str
    id: str
    verified_on: date
    age_days: int


def load_store(path: Path | None, today: date) -> ResourceStore:
    """The packaged (signature-checked) store, or the YAML file at ``path``."""
    data = path.read_bytes() if path is not None else load_hotlines_bytes(None, today=today).data
    return parse_store(yaml.safe_load(data))


def stale_entries(store: ResourceStore, today: date, max_age_days: int) -> list[Stale]:
    """Every emergency number and line verified more than ``max_age_days`` before ``today``."""
    found: list[Stale] = []
    for code, region in sorted(store.regions.items()):
        for entry in (*region.emergency, *region.lines):
            age = (today - entry.verified_on).days
            if age > max_age_days:
                found.append(Stale(code, entry.id, entry.verified_on, age))
    return found


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="检查热线数据的核验日期是否过期")
    parser.add_argument("--max-age-days", type=int, default=MAX_AGE_DAYS)
    parser.add_argument("--today", type=date.fromisoformat, default=None, help="YYYY-MM-DD")
    parser.add_argument("--store", type=Path, default=None, help="另一份同格式的 YAML")
    args = parser.parse_args(argv)
    today: date = args.today or datetime.now(UTC).date()
    try:
        store = load_store(args.store, today)
    except (OSError, yaml.YAMLError, ResourceDataError, BundleIntegrityError) as exc:
        print(f"check_hotline_freshness: cannot read the hotline data: {exc}", file=sys.stderr)
        return 2
    stale = stale_entries(store, today, args.max_age_days)
    total = sum(len(r.emergency) + len(r.lines) for r in store.regions.values())
    if not stale:
        print(
            f"OK: all {total} entries verified within {args.max_age_days} days "
            f"of {today.isoformat()} (data compiled {store.compiled_on.isoformat()})."
        )
        return 0
    print(
        f"STALE: {len(stale)} of {total} entries were last verified more than "
        f"{args.max_age_days} days before {today.isoformat()}:"
    )
    for item in stale:
        print(f"  {item.region} {item.id}: verified {item.verified_on} ({item.age_days} days)")
    print("Re-verify them as described in docs/resources/hotline-sources.md, then re-sign.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
