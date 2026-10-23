"""scripts/dossier_coverage.py runs and reports the cue coverage plan D-2 asks for."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/dossier_coverage.py"


def _run() -> str:
    done = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout


def test_the_report_has_one_row_per_dossier_and_the_totals() -> None:
    out = _run()
    rows = [line for line in out.splitlines() if re.match(r"SIT-\d{2}-\d{2} ", line)]
    assert len(rows) == 60
    assert "dossiers: 60" in out
    for label in ("situation cues:", "dossier imagery used:", "Grade B lenses used:"):
        assert label in out
    assert "contraindications reaching the solver:" in out
    assert "not wired" in out


def test_situation_cues_cover_at_least_80_percent_of_the_dossiers() -> None:
    match = re.search(r"situation cues: (\d+)/60", _run())
    assert match is not None
    assert int(match.group(1)) / 60 >= 0.80
