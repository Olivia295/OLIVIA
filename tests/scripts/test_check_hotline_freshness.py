"""``scripts/check_hotline_freshness.py`` on a synthetic store and on the packaged data."""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "check_hotline_freshness", ROOT / "scripts/check_hotline_freshness.py"
)
assert _spec is not None and _spec.loader is not None
fresh = importlib.util.module_from_spec(_spec)
sys.modules["check_hotline_freshness"] = fresh
_spec.loader.exec_module(fresh)

TODAY = date(2026, 10, 24)


def _line(line_id: str, verified: str) -> dict[str, object]:
    return {
        "id": line_id,
        "name_zh": "测试热线",
        "number": "123",
        "kind": "crisis_hotline",
        "levels": ["L2", "L3"],
        "hours": "24/7",
        "scope": "national",
        "adcode": None,
        "minors_only": False,
        "source_url": "https://example.org/",
        "verified_on": verified,
        "notes": "",
    }


def _store(tmp_path: Path, *, line_date: str, emergency_date: str) -> Path:
    doc = {
        "version": 1,
        "compiled_on": "2026-01-01",
        "regions": {
            "ZZ": {
                "emergency": [
                    {
                        "number": "112",
                        "purpose": "generic_gsm_emergency",
                        "source_url": "https://example.org/",
                        "verified_on": emergency_date,
                        "notes": "",
                    }
                ],
                "lines": [_line("zz_fresh", "2026-10-01"), _line("zz_test", line_date)],
            }
        },
    }
    path = tmp_path / "hotlines.yaml"
    path.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    return path


def _run(*argv: str) -> int:
    return fresh.main(["--today", TODAY.isoformat(), *argv])


def test_fresh_store_passes(tmp_path, capsys):
    path = _store(tmp_path, line_date="2026-08-01", emergency_date="2026-07-26")  # 84, 90 days
    assert _run("--store", str(path)) == 0
    assert capsys.readouterr().out.startswith("OK: all 3 entries")


def test_an_entry_older_than_90_days_fails(tmp_path, capsys):
    path = _store(tmp_path, line_date="2026-07-25", emergency_date="2026-01-01")  # 91, 296 days
    assert _run("--store", str(path)) == 1
    out = capsys.readouterr().out
    assert "STALE: 2 of 3 entries" in out
    assert "ZZ zz_test: verified 2026-07-25 (91 days)" in out
    assert "ZZ zz_emergency_112: verified 2026-01-01 (296 days)" in out
    assert "zz_fresh" not in out


def test_the_limit_can_be_changed(tmp_path):
    path = _store(tmp_path, line_date="2026-07-25", emergency_date="2026-07-25")
    assert _run("--store", str(path), "--max-age-days", "120") == 0
    assert _run("--store", str(path), "--max-age-days", "30") == 1


def test_unreadable_or_invalid_data_is_exit_2(tmp_path, capsys):
    assert _run("--store", str(tmp_path / "missing.yaml")) == 2
    bad = tmp_path / "bad.yaml"
    bad.write_text("version: 1\nregions: {}\n", encoding="utf-8")
    assert _run("--store", str(bad)) == 2
    assert "cannot read" in capsys.readouterr().err


def test_the_packaged_data_is_read_through_the_signed_bundle(capsys):
    store = fresh.load_store(None, TODAY)
    assert store.has_region("CN") and store.has_region("ZZ")
    oldest = min(e.verified_on for r in store.regions.values() for e in (*r.emergency, *r.lines))
    far_future = date.fromordinal(oldest.toordinal() + 365)
    assert fresh.main(["--today", far_future.isoformat()]) == 1
    assert fresh.main(["--today", oldest.isoformat()]) == 0


def test_the_workflow_runs_it_quarterly_and_on_demand():
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/hotline-freshness.yml").read_text(encoding="utf-8")
    )
    triggers = workflow[True]  # YAML 1.1 reads the bare key "on" as a boolean
    assert "workflow_dispatch" in triggers
    (cron,) = [entry["cron"] for entry in triggers["schedule"]]
    minute, hour, day, months, weekday = cron.split()
    assert months == "1,4,7,10" and day.isdigit() and weekday == "*"
    steps = [step.get("run", "") for job in workflow["jobs"].values() for step in job["steps"]]
    assert any("scripts/check_hotline_freshness.py" in run for run in steps)


def test_the_sources_document_names_an_owner():
    doc = (ROOT / "docs/resources/hotline-sources.md").read_text(encoding="utf-8")
    assert "维护负责人" in doc and "check_hotline_freshness.py" in doc
