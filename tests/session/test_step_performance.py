"""G-3 per-step guards: each step of the control loop, peak memory and installed size.

The scripted run and the budgets are those of ``scripts/bench_loop.py`` (its docstring
cites the PRD and SDD section of each); this is its fast form for ``scripts/check.sh``.
Each step's P99 is its exclusive time per turn in an instrumented run, in rules mode and in
model mode. The whole turn's P99 (55 ms) is guarded by ``test_session_performance.py``.

Two budgets are not met yet and are marked ``xfail(strict=True)``, so the suite records
the gap and turns red once it closes (then drop the marker):

* generation + gate (SDD §10.1 Step 6, P99 2 ms): about 10 ms here, nearly all of it the
  WILLOW filter's ``replace_longest`` (``language/filters.py``), which tries every phrase
  at every position of the reply;
* peak RSS (SDD §0, < 50 MB): about 63 MB after importing ``olivia.cli`` alone (the
  interpreter, NumPy, cryptography, PyYAML) and 74-80 MB after a scripted run.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
TURNS = 105  # seven sessions of the bench script
ROUNDS = 3


def _bench() -> ModuleType:
    spec = importlib.util.spec_from_file_location("bench_loop", ROOT / "scripts" / "bench_loop.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up while it loads
    spec.loader.exec_module(module)
    return module


BENCH = _bench()


def _coverage_is_tracing() -> bool:
    try:
        import coverage
    except ImportError:
        return False
    return coverage.Coverage.current() is not None


untraced = pytest.mark.skipif(
    _coverage_is_tracing(), reason="latency and memory are not measurable under coverage"
)


@pytest.fixture(scope="module")
def step_p99s(tmp_path_factory: pytest.TempPathFactory) -> dict[tuple[str, str], list[float]]:
    """(mode, step) -> the P99 of each round, in seconds."""
    p99s: dict[tuple[str, str], list[float]] = {}
    for mode in ("rules", "model"):
        student = mode == "model"
        home = tmp_path_factory.mktemp(f"bench-{mode}")
        warm = len(BENCH.SCRIPT)
        BENCH.run_mode(student=student, turns=warm, home=home / "warm", instrument=False)
        for round_no in range(ROUNDS):
            samples = BENCH.run_mode(
                student=student, turns=TURNS, home=home / f"r{round_no}", instrument=True
            )
            for step in BENCH.STEPS:
                p99s.setdefault((mode, step), []).append(BENCH.percentile(samples[step], 99))
    return p99s


GENERATION_GAP = pytest.mark.xfail(
    strict=True, reason="WILLOW replace_longest: generation P99 about 10 ms (budget 2 ms)"
)


@untraced
@pytest.mark.parametrize("mode", ["rules", "model"])
@pytest.mark.parametrize(
    "step",
    [
        "perception",
        "safety",
        "fsm",
        "solver",
        pytest.param("generation", marks=GENERATION_GAP),
    ],
)
def test_step_p99_within_its_budget(step_p99s, mode: str, step: str):
    budget = BENCH.budget_for(step)
    # Scheduler jitter on shared runners has nothing to do with this code, so the budget
    # applies to the best of the rounds: a real slowdown fails every round.
    rounds = step_p99s[(mode, step)]
    assert min(rounds) <= budget, f"{mode} {step} P99 per round (s): {rounds}, budget {budget}"


def test_the_instrumented_run_times_every_step(tmp_path):
    samples = BENCH.run_mode(student=False, turns=len(BENCH.SCRIPT), home=tmp_path, instrument=True)
    for step in ("perception", "safety", "fsm", "solver", "generation"):
        assert max(samples[step]) > 0.0, step  # every step was reached and timed
    assert len(samples["turn"]) == len(BENCH.SCRIPT)


@untraced
@pytest.mark.skipif(sys.platform == "win32", reason="no resource module on Windows")
@pytest.mark.xfail(strict=True, reason="peak RSS about 74 MB in rules mode (budget < 50 MB)")
def test_peak_rss_of_a_rules_mode_run_is_within_the_envelope():
    env = {**os.environ, "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"}
    done = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "bench_loop.py"), "--worker", "rules"]
        + ["--turns", str(3 * len(BENCH.SCRIPT))],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    rss = json.loads(done.stdout.splitlines()[-1])["rss"]
    assert rss < BENCH.budget_for("rss"), f"peak RSS {rss / BENCH.MB:.1f} MB"


def test_installed_package_and_its_data_are_within_the_size_envelope():
    files = BENCH.package_files()
    installed = sum(p.stat().st_size for p in files)
    data = sum(p.stat().st_size for p in files if p.is_relative_to(ROOT / "olivia" / "data"))
    assert any(p.suffix == ".npz" for p in files)  # the student's weights are counted
    # SDD §0 bounds the weights and knowledge data; the whole package must fit as well.
    assert data < installed < BENCH.budget_for("installed"), (data, installed)
