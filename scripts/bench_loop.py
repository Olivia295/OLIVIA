"""G-3 benchmark: per-step latency of the offline control loop, peak memory and size.

    python scripts/bench_loop.py [--turns N] [--modes rules,model] [--wheel PATH] [--json]

Runs N scripted turns through ``Session.turn`` in rules mode and in ``--model`` mode (the
packaged perception student), each mode in its own child process with numerical
libraries held to one thread (the single-core reference of ruling 32), and prints:

* per turn: P50/P95/P99 of ``Session.turn`` (an uninstrumented pass);
* per step (an instrumented pass; each step's exclusive time per turn): perception (rule
  stub, introspector, model heads, the student's forward pass), safety screen (both
  stages, crisis tracker, red flags, the D3 answer, the resource card), FSM step, solver
  (contraindication masks, allowed set, Thompson sampling, skeleton), language generation
  and the output gate (templates, WILLOW, gate checks, wellbeing line), and the rest;
* memory writes: the ledger and carried-state writes after each turn, and the ledger
  write when a session closes (the summary, sealed with the in-memory test keychain);
* peak RSS of each child (``resource``; not available on Windows, where it is skipped);
* size: the wheel, the installed ``olivia/`` package and its ``data/`` (weights + data).

Budgets (exit status 1 when one is exceeded; ``n/a`` rows are reported only):

=====================  ===========  ===============================================
what                   P99 / limit  source
=====================  ===========  ===============================================
turn (control loop)    55 ms        PRD §11.2 Gate G-3; SDD §0 SLO and §10.1 total
perception             45 ms        PRD MIYI-01; SDD §10.1 Step 2
safety screen          1.5 ms       SDD §10.1 Step 1 (0.5 ms) + SDD §8 Stage 2 (1 ms)
memory retrieval       2 ms         SDD §10.1 Step 3 (not in the loop; see note)
FSM step               1.5 ms       SDD §0 SLO; SDD §10.1 Step 4
solver                 3 ms         SDD §10.1 Step 5
generation + gate      2 ms         SDD §10.1 Step 6
peak RSS               < 50 MB      SDD §0 Resource Envelope (the PRD sets none)
installed size         < 4 MB       SDD §0 Resource Envelope: weights and knowledge
                                    data; applied to the whole installed package
=====================  ===========  ===============================================

The PRD itself only fixes the control loop (G-3: P99 <= 55 ms on one core) and the
perception pass (MIYI-01: P99 <= 45 ms); the plan's RSS and size numbers come from the
SDD's resource envelope. Memory retrieval (SDD §3.3) is not wired into the rules-mode
loop, so it has no row here; ``tests/memory/test_retrieval_performance.py`` guards it.
With the environment variable ``CI`` set, latency budgets are relaxed three times, as in
the pytest guards: shared runners are not the reference machine.

Nothing here touches the network, the real keychain or the user's data directory: the
ledger lives in a temporary directory, sealed with an in-memory keychain backend.
"""

from __future__ import annotations

import argparse
import functools
import json
import math
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # this checkout's olivia, not an installed copy
    sys.path.insert(0, str(ROOT))

NOW = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)
MB = 1024 * 1024
CI_FACTOR = 3.0
# One cycle (one session) walks explore, a card and its feedback, closing, a note, the
# haven, a relationship talk, somatic stabilization, a long message, a red flag, a crisis
# and its first turns: the same mix as tests/session/test_session_performance.py, plus a
# note so the ledger writes one.
SCRIPT: tuple[str, ...] = (
    "最近工作压力很大，有点焦虑，晚上总睡不着",
    "被领导催进度，心慌得要命",
    "给我一个方法",
    "/done",
    "记住：周五下午要交季度报告",
    "[5%] 好累，今天不想动脑，只想躺着",
    "[60%] 好一点了，想聊聊我和室友的事情，我觉得她根本不在乎我",
    "心慌得要命，喘不上气，直接给我一个方法",
    "/not-now",
    ("今天加班到很晚，领导又催进度，感觉活着好累，" * 20)[:500],
    "我是边缘型人格，确诊两年了，给我一个练习",
    "我不想活了",
    "我现在安全了",
    "嗯",
    "嗯",
)
STEPS: tuple[str, ...] = ("perception", "safety", "fsm", "solver", "generation", "other")
STEP_LABELS = {
    "turn": "turn (Session.turn)",
    "perception": "perception",
    "safety": "safety screen",
    "fsm": "FSM step",
    "solver": "solver",
    "generation": "generation + gate",
    "other": "other (bookkeeping)",
    "memory_turn": "memory write / turn",
    "memory_close": "ledger write at close",
}


@dataclass(frozen=True)
class Budget:
    key: str
    limit: float
    unit: str
    source: str
    latency: bool = True


BUDGETS: tuple[Budget, ...] = (
    Budget("turn", 0.055, "s", "PRD §11.2 G-3"),
    Budget("perception", 0.045, "s", "PRD MIYI-01; SDD §10.1 Step 2"),
    Budget("safety", 0.0015, "s", "SDD §10.1 Step 1 + §8 Stage 2"),
    Budget("fsm", 0.0015, "s", "SDD §10.1 Step 4"),
    Budget("solver", 0.003, "s", "SDD §10.1 Step 5"),
    Budget("generation", 0.002, "s", "SDD §10.1 Step 6"),
    Budget("rss", 50 * MB, "B", "SDD §0 Resource Envelope", latency=False),
    Budget("installed", 4 * MB, "B", "SDD §0 Resource Envelope", latency=False),
)


def budget_for(key: str, *, ci: bool | None = None) -> float:
    """The budget's limit; latency budgets are relaxed on CI (``CI`` set)."""
    on_ci = bool(os.environ.get("CI")) if ci is None else ci
    budget = next(b for b in BUDGETS if b.key == key)
    return budget.limit * (CI_FACTOR if on_ci and budget.latency else 1.0)


def percentile(samples: Sequence[float], p: float) -> float:
    """Nearest-rank percentile (``p`` in 0..100) of ``samples``."""
    ordered = sorted(samples)
    if not ordered:
        return math.nan
    rank = max(1, math.ceil(p / 100 * len(ordered)))
    return ordered[rank - 1]


# -- instrumentation ----------------------------------------------------------------------------


class StepTimer:
    """Exclusive time per step: a wrapped call's time minus the wrapped calls inside it."""

    def __init__(self) -> None:
        self.turn: dict[str, float] = {}
        self._stack: list[float] = []

    def reset(self) -> None:
        self.turn = {}
        self._stack = []

    def wrap(self, step: str, fn: Callable[..., Any]) -> Callable[..., Any]:
        def timed(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            self._stack.append(0.0)
            try:
                return fn(*args, **kwargs)
            finally:
                inner = self._stack.pop()
                spent = time.perf_counter() - start
                self.turn[step] = self.turn.get(step, 0.0) + spent - inner
                if self._stack:
                    self._stack[-1] += spent

        timed.__wrapped__ = fn  # type: ignore[attr-defined]
        return timed


def _targets() -> list[tuple[Any, str, str]]:
    """(owner, attribute, step) for every call the instrumented pass times."""
    from olivia.core import session as session_module
    from olivia.core.chang.wellbeing import Wellbeing
    from olivia.core.language.engine import LanguageEngine
    from olivia.core.language.gate import OutputGate
    from olivia.core.methods.bandit import ThompsonSampler
    from olivia.core.methods.contraindications import SessionContraindications
    from olivia.core.perception.introspector import Introspector, SchemaMirror
    from olivia.core.perception.model_heads import ModelHeads
    from olivia.core.perception.rule_stub import RuleStub
    from olivia.core.perception.student import StudentRiskModel
    from olivia.core.safety.crisis import SafetyScreen
    from olivia.core.safety.red_flags import SessionRedFlags
    from olivia.core.safety.tracker import CrisisTracker

    targets: list[tuple[Any, str, str]] = [
        (RuleStub, "perceive", "perception"),
        (Introspector, "apply", "perception"),
        (ModelHeads, "refine", "perception"),
        (StudentRiskModel, "predict", "perception"),
        (SchemaMirror, "answer", "perception"),
        (SchemaMirror, "observe", "perception"),
        (SchemaMirror, "choose", "perception"),
        (SafetyScreen, "assess", "safety"),
        (CrisisTracker, "observe", "safety"),
        (SessionRedFlags, "observe", "safety"),
        (session_module, "read_intent_answer", "safety"),
        (session_module, "resolve", "safety"),
        (session_module, "step", "fsm"),
        (SessionContraindications, "observe", "solver"),
        (session_module, "allowed_actions", "solver"),
        (session_module, "active_contraindications", "solver"),
        (session_module, "build_plan", "solver"),
        (session_module, "info_cards", "solver"),
        (ThompsonSampler, "choose", "solver"),
        (ThompsonSampler, "update", "solver"),
        (OutputGate, "check", "generation"),
        (session_module, "apply_willow", "generation"),
        (Wellbeing, "prompt", "generation"),
    ]
    for name in (
        "build_slots",
        "compose",
        "safe_mirror",
        "card_for",
        "render_card",
        "render_info_reply",
        "render_referral",
        "render_crisis",
        "render_safety_check",
    ):
        targets.append((LanguageEngine, name, "generation"))
    return targets


@contextmanager
def instrumented(timer: StepTimer) -> Iterator[None]:
    saved = []
    try:
        for owner, attr, step in _targets():
            original = owner.__dict__[attr] if isinstance(owner, type) else getattr(owner, attr)
            saved.append((owner, attr, original))
            setattr(owner, attr, timer.wrap(step, original))
        yield
    finally:
        for owner, attr, original in reversed(saved):
            setattr(owner, attr, original)


# -- the scripted run ---------------------------------------------------------------------------


class MemoryKeychain:
    """An in-memory key backend: the benchmark never reaches the OS keychain."""

    def __init__(self) -> None:
        self.items: dict[str, str] = {}

    def get(self, name: str) -> str | None:
        return self.items.get(name)

    def set(self, name: str, value: str) -> None:
        self.items[name] = value

    def delete(self, name: str) -> None:
        self.items.pop(name, None)


def _guard_keychain() -> MemoryKeychain:
    """Route every default key backend to memory and make ``keyring`` fail if reached."""
    os.environ["PYTHON_KEYRING_BACKEND"] = "keyring.backends.fail.Keyring"
    import keyring
    import keyring.backends.fail

    from olivia.core.crypto import keychain as keychain_module

    keyring.set_keyring(keyring.backends.fail.Keyring())  # type: ignore[no-untyped-call]
    backend = MemoryKeychain()
    keychain_module.default_backend = lambda: backend
    return backend


@functools.cache
def _taxonomy() -> Any:
    """One taxonomy per process, as in the CLI.

    The session caches its shared data (lexicons, matchers, templates, hotlines) per
    taxonomy object, so a fresh taxonomy per run would keep one more copy of all of it for
    each run and count the copies in the peak RSS.
    """
    from olivia.core.taxonomy import load_taxonomy

    return load_taxonomy()


def run_mode(
    *, student: bool, turns: int, home: Path, instrument: bool, backend: Any = None
) -> dict[str, list[float]]:
    """Run ``turns`` scripted turns; seconds per sample, keyed by step.

    Uninstrumented, the samples are ``turn`` (``Session.turn``), ``memory_turn`` (the
    ledger and carried-state writes after a turn) and ``memory_close`` (one per session).
    Instrumented, they are each step's exclusive time per turn plus ``turn``. The ledger
    and the carried state are sealed with ``backend`` (a fresh in-memory one by default).
    """
    backend = MemoryKeychain() if backend is None else backend
    from olivia.core.crypto.vault import Vault
    from olivia.core.memory.ledger import Ledger
    from olivia.core.memory.recorder import SessionRecorder
    from olivia.core.memory.state import StateRecorder, StateStore
    from olivia.core.models import PersonaProfile, UserRegion
    from olivia.core.session import Session

    tax = _taxonomy()
    profile = PersonaProfile(
        age_confirmed_18_plus=True,
        created_at=NOW,
        updated_at=NOW,
        user_name="小林",
        region=UserRegion("CN", "Asia/Shanghai"),
    )
    home.mkdir(parents=True, exist_ok=True)
    vault = Vault(home, backend=backend)
    ledger = Ledger(home, vault)
    states = StateStore(home, vault)
    samples: dict[str, list[float]] = {}
    timer = StepTimer()

    def add(key: str, value: float) -> None:
        samples.setdefault(key, []).append(value)

    def clock() -> datetime:
        return NOW

    session: Session | None = None
    recorder: SessionRecorder | None = None
    state_recorder: StateRecorder | None = None

    def close() -> None:
        if recorder is not None:
            t0 = time.perf_counter()
            recorder.close()
            if not instrument:
                add("memory_close", time.perf_counter() - t0)

    with instrumented(timer) if instrument else _nothing():
        for i in range(turns):
            if i % len(SCRIPT) == 0:
                close()
                session = Session.open(
                    tax,
                    profile,
                    rng=random.Random(i),
                    now=clock,
                    student=student,
                    carried=states.load(),
                )
                recorder = SessionRecorder(ledger, session.state.session_id, clock)
                state_recorder = StateRecorder(states, session.carried_state())
            assert session is not None and recorder is not None and state_recorder is not None
            text = SCRIPT[i % len(SCRIPT)]
            timer.reset()
            t0 = time.perf_counter()
            result = session.turn(text)
            spent = time.perf_counter() - t0
            add("turn", spent)
            if instrument:
                for step in STEPS[:-1]:
                    add(step, timer.turn.get(step, 0.0))
                add("other", max(0.0, spent - sum(timer.turn.values())))
            t0 = time.perf_counter()
            recorder.observe(text, result)
            state_recorder.observe(session.carried_state())
            if not instrument:
                add("memory_turn", time.perf_counter() - t0)
        close()
    if session is not None and student:
        label = session.turn("嗯").inspect["risk_model"]
        if not str(label).startswith("student:"):
            raise SystemExit(f"model mode did not load the student: {label}")
    return samples


@contextmanager
def _nothing() -> Iterator[None]:
    yield


def peak_rss() -> int | None:
    """This process's peak resident set size in bytes; None where unmeasurable."""
    try:
        import resource
    except ImportError:  # Windows
        return None
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak if sys.platform == "darwin" else peak * 1024)


def _worker(mode: str, turns: int) -> dict[str, Any]:
    if mode == "baseline":  # what importing the CLI alone costs
        import olivia.cli  # noqa: F401

        return {"rss": peak_rss()}
    _guard_keychain()
    student = mode == "model"
    with tempfile.TemporaryDirectory(prefix="olivia-bench-") as tmp:
        # Warm-up: loads and caches the shared data, as the first turn of a process does.
        run_mode(student=student, turns=len(SCRIPT), home=Path(tmp) / "warm", instrument=False)
        timed = run_mode(student=student, turns=turns, home=Path(tmp) / "timed", instrument=False)
        steps = run_mode(student=student, turns=turns, home=Path(tmp) / "steps", instrument=True)
    return {
        "samples": {
            "turn": timed["turn"],
            **{step: steps[step] for step in STEPS},
            "instrumented_turn": steps["turn"],
            "memory_turn": timed["memory_turn"],
            "memory_close": timed["memory_close"],
        },
        "rss": peak_rss(),
    }


# -- size -----------------------------------------------------------------------------------------


def _build_wheel(out: Path) -> tuple[Path | None, str]:
    """Build a wheel from a copy of the sources (offline); (path, note)."""
    src = out / "src"
    src.mkdir()
    for name in ("pyproject.toml", "README.md"):
        if (ROOT / name).exists():
            shutil.copy2(ROOT / name, src / name)
    shutil.copytree(
        ROOT / "olivia", src / "olivia", ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
    )
    command = [sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation"]
    command += ["--no-index", "-q", "-w", str(out / "dist"), str(src)]
    done = subprocess.run(command, capture_output=True, text=True, check=False)
    wheels = sorted((out / "dist").glob("olivia-*.whl"))
    if done.returncode != 0 or len(wheels) != 1:
        output = (done.stderr + done.stdout).splitlines()
        generic = ("subprocess-exited-with-error", "metadata-generation-failed")
        errors = [ln.strip() for ln in output if "error:" in ln and not ln.endswith(generic)]
        errors = errors or ["no wheel"]
        return None, f"no wheel built here ({errors[0][:80]})"
    return wheels[0], "built offline from this checkout"


def package_files() -> list[Path]:
    """The files a wheel installs under ``olivia/`` (sources and package data)."""
    return sorted(
        p
        for p in (ROOT / "olivia").rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and not p.name.startswith(".")
    )


def measure_size(wheel: Path | None) -> dict[str, Any]:
    """Wheel bytes, and the installed ``olivia/`` and ``olivia/data/`` bytes it unpacks to."""
    with tempfile.TemporaryDirectory(prefix="olivia-size-") as tmp:
        note = "given with --wheel"
        if wheel is None:
            wheel, note = _build_wheel(Path(tmp))
        if wheel is None:
            # No wheel tooling here (the ``wheel`` package, say): estimate it as a deflated
            # zip of the package files, which is what a wheel is apart from its metadata.
            wheel = Path(tmp) / "estimate.zip"
            with zipfile.ZipFile(wheel, "w", zipfile.ZIP_DEFLATED) as archive:
                for path in package_files():
                    archive.write(path, path.relative_to(ROOT).as_posix())
            note = f"estimated (zip of the package files); {note}"
        with zipfile.ZipFile(wheel) as archive:
            infos = [i for i in archive.infolist() if i.filename.startswith("olivia/")]
            installed = sum(i.file_size for i in infos)
            data = sum(i.file_size for i in infos if i.filename.startswith("olivia/data/"))
        return {"wheel": wheel.stat().st_size, "installed": installed, "data": data, "note": note}


# -- report ---------------------------------------------------------------------------------------


def _ms(seconds: float) -> str:
    return f"{seconds * 1000:8.3f}"


def _child(mode: str, turns: int) -> dict[str, Any]:
    env = dict(os.environ)
    for var in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ):
        env[var] = "1"  # one core, as the reference machine (ruling 32)
    env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.fail.Keyring"
    command = [sys.executable, str(Path(__file__).resolve()), "--worker", mode]
    command += ["--turns", str(turns)]
    done = subprocess.run(command, capture_output=True, text=True, env=env, check=False)
    if done.returncode != 0:
        raise SystemExit(f"{mode} worker failed:\n{done.stderr}")
    result: dict[str, Any] = json.loads(done.stdout.splitlines()[-1])
    return result


def report(results: dict[str, dict[str, Any]], size: dict[str, Any], turns: int) -> list[str]:
    """Print the table; the failed budgets."""
    failures: list[str] = []
    ci = bool(os.environ.get("CI"))
    print(f"OLIVIA G-3 benchmark · {turns} turns per mode · python {sys.version.split()[0]}")
    print(f"platform {sys.platform} · budgets {'relaxed x3 (CI)' if ci else 'reference machine'}")
    for mode, result in results.items():
        if mode == "baseline":
            continue
        samples = result["samples"]
        print()
        print(f"[{mode} mode]")
        print(f"{'step':<24}{'P50 ms':>10}{'P95 ms':>10}{'P99 ms':>10}{'budget':>10}  result")
        for key in ("turn", *STEPS, "memory_turn", "memory_close"):
            values = samples[key]
            p99 = percentile(values, 99)
            budget = next((b for b in BUDGETS if b.key == key), None)
            verdict, limit = "", "n/a"
            if budget is not None:
                allowed = budget_for(key, ci=ci)
                limit = _ms(allowed).strip()
                verdict = "pass" if p99 <= allowed else "FAIL"
                if verdict == "FAIL":
                    failures.append(f"{mode} {key} P99 {p99 * 1000:.3f} ms > {limit} ms")
            row = f"{STEP_LABELS[key]:<24}{_ms(percentile(values, 50)):>10}"
            row += f"{_ms(percentile(values, 95)):>10}{_ms(p99):>10}{limit:>10}  {verdict}"
            print(row)
        extra = percentile(samples["instrumented_turn"], 99) - percentile(samples["turn"], 99)
        print(f"(steps from an instrumented pass; its turn P99 is {extra * 1000:+.3f} ms off)")
    print()
    print(f"{'memory':<24}{'peak RSS MB':>12}{'budget':>10}  result")
    rss_limit = budget_for("rss")
    for mode, result in results.items():
        rss = result["rss"]
        if rss is None:
            print(f"{mode:<24}{'n/a':>12}{rss_limit / MB:>10.1f}  skipped (no resource module)")
            continue
        gated = mode != "baseline"
        verdict = ("pass" if rss < rss_limit else "FAIL") if gated else "(import olivia.cli only)"
        if gated and rss >= rss_limit:
            failures.append(f"{mode} peak RSS {rss / MB:.1f} MB >= {rss_limit / MB:.0f} MB")
        print(f"{mode:<24}{rss / MB:>12.1f}{rss_limit / MB:>10.1f}  {verdict}")
    print()
    print(f"{'size':<24}{'MB':>12}{'budget':>10}  result")
    wheel = size["wheel"]
    print(f"{'wheel':<24}{(wheel / MB if wheel else math.nan):>12.3f}{'n/a':>10}  {size['note']}")
    allowed = budget_for("installed")
    verdict = "pass" if size["installed"] < allowed else "FAIL"
    if verdict == "FAIL":
        failures.append(f"installed size {size['installed'] / MB:.3f} MB >= 4 MB")
    installed = size["installed"] / MB
    print(f"{'installed olivia/':<24}{installed:>12.3f}{allowed / MB:>10.1f}  {verdict}")
    print(f"{'  of which data/':<24}{size['data'] / MB:>12.3f}{'':>10}  weights + data files")
    return failures


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--turns", type=int, default=1050, help="scripted turns per mode")
    parser.add_argument("--modes", default="rules,model", help="comma-separated: rules,model")
    parser.add_argument("--wheel", type=Path, help="measure this wheel instead of building one")
    parser.add_argument("--json", type=Path, help="also write the raw results here")
    parser.add_argument("--worker", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.worker:
        print(json.dumps(_worker(args.worker, args.turns)))
        return 0
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    unknown = sorted(set(modes) - {"rules", "model"})
    if unknown:
        parser.error(f"unknown modes: {unknown}")
    results = {mode: _child(mode, args.turns) for mode in ["baseline", *modes]}
    size = measure_size(args.wheel)
    failures = report(results, size, args.turns)
    if args.json is not None:
        args.json.write_text(json.dumps({"results": results, "size": size}), encoding="utf-8")
    print()
    if failures:
        print("over budget:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("all budgets met")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
