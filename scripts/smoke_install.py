"""Install a built wheel the way a tester would and smoke-test the ``olivia`` command.

    python scripts/smoke_install.py DIST_DIR --installer venv|pipx

``venv`` pip-installs the wheel into a new virtual environment; ``pipx`` installs it with
``python -m pipx`` (pipx must be importable by this interpreter). Either way everything
lives in a temporary directory, and every command runs from there with ``OLIVIA_HOME``
pointing into it and no ``PYTHONPATH``, so neither the source tree nor the real user data
directory is involved.

Checks:
1. The wheel holds every file under ``olivia/data`` in this checkout (the perception
   model, the signed hotline file and its ``.sig`` included).
2. ``olivia --version`` matches the wheel; ``olivia --help`` lists the commands.
3. A scripted first visit (onboarding, one message, ``/exit``) exits 0 and saves the
   profile; ``olivia resources`` then shows the CN card, and ``olivia chat --model
   --inspect`` shows the packaged perception student in use.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import venv
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXE_SUFFIX = ".exe" if os.name == "nt" else ""

# Same answers as tests/cli/cli_support.py ONBOARD_CN: accept, 18+, name, default agent
# name, the one persona, no taboo topics, region 1 (CN), skip the consent.
ONBOARD_CN = ["1", "1", "小林", "", "", "", "1", "跳过"]
MESSAGE = "今天上班好累"
GOODBYE = "好，今天就先聊到这里"


def find_wheel(dist: Path) -> Path:
    wheels = sorted(dist.glob("olivia-*.whl"))
    if len(wheels) != 1:
        raise SystemExit(f"expected one olivia wheel in {dist}, found {wheels}")
    return wheels[0].resolve()


def check_wheel(wheel: Path) -> str:
    """Assert the wheel ships all package data; return its version."""
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
    expected = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "olivia" / "data").rglob("*")
        if path.is_file() and not path.name.startswith(".") and "__pycache__" not in path.parts
    }
    missing = sorted(expected - names)
    if missing:
        raise SystemExit(f"wheel is missing package data: {missing}")
    print(f"wheel {wheel.name}: {len(names)} files, all {len(expected)} data files present")
    for name in sorted(n for n in names if n.startswith("olivia/data/models/")):
        print(f"  {name}")
    return wheel.name.split("-")[1]


def clean_env(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env.update(extra)
    return env


def install_venv(wheel: Path, tmp: Path) -> Path:
    target = tmp / "venv"
    venv.create(target, with_pip=True)
    scripts = target / ("Scripts" if os.name == "nt" else "bin")
    python = scripts / f"python{EXE_SUFFIX}"
    subprocess.run(
        [str(python), "-m", "pip", "install", "-q", str(wheel)], check=True, env=clean_env()
    )
    return scripts / f"olivia{EXE_SUFFIX}"


def install_pipx(wheel: Path, tmp: Path) -> Path:
    bin_dir = tmp / "pipx-bin"
    env = clean_env(PIPX_HOME=str(tmp / "pipx-home"), PIPX_BIN_DIR=str(bin_dir))
    subprocess.run(
        [sys.executable, "-m", "pipx", "install", "--python", sys.executable, str(wheel)],
        check=True,
        env=env,
    )
    return bin_dir / f"olivia{EXE_SUFFIX}"


def run(exe: Path, args: list[str], home: Path, lines: list[str] | None = None) -> str:
    stdin = "".join(f"{line}\n" for line in lines or [])
    done = subprocess.run(
        [str(exe), *args],
        input=stdin.encode("utf-8"),
        capture_output=True,
        cwd=home.parent,
        env=clean_env(OLIVIA_HOME=str(home)),
        timeout=120,
        check=False,
    )
    out = done.stdout.decode("utf-8")
    print(f"$ olivia {' '.join(args)}  (exit {done.returncode})")
    print(out.rstrip())
    if done.returncode != 0:
        print(done.stderr.decode("utf-8", "replace"), file=sys.stderr)
        raise SystemExit(f"olivia {' '.join(args)} exited {done.returncode}")
    return out


def smoke(exe: Path, version: str, home: Path) -> None:
    out = run(exe, ["--version"], home)
    if out.strip() != f"olivia {version}":
        raise SystemExit(f"--version printed {out.strip()!r}, the wheel is {version}")
    if "开始聊天" not in run(exe, ["--help"], home):
        raise SystemExit("--help does not list the chat command")
    if GOODBYE not in run(exe, ["chat"], home, [*ONBOARD_CN, MESSAGE, "/exit"]):
        raise SystemExit("chat did not end with the goodbye line")
    if not (home / "profile.json").is_file():
        raise SystemExit("onboarding did not save the profile")
    if "12356" not in run(exe, ["resources"], home):
        raise SystemExit("resources did not show the CN card")
    # A student that fails to load falls back to rules only without an error, so check
    # the inspect panel names it: that proves the packaged model files load from the wheel.
    if "风险模型 student:" not in run(
        exe, ["chat", "--model", "--inspect"], home, [MESSAGE, "/exit"]
    ):
        raise SystemExit("chat --model did not load the packaged perception student")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dist", type=Path, help="directory holding the built wheel")
    parser.add_argument("--installer", choices=["venv", "pipx"], required=True)
    args = parser.parse_args()

    wheel = find_wheel(args.dist)
    version = check_wheel(wheel)
    with tempfile.TemporaryDirectory() as name:
        tmp = Path(name).resolve()
        install = install_venv if args.installer == "venv" else install_pipx
        exe = install(wheel, tmp)
        smoke(exe, version, tmp / "olivia-home")
    print(f"smoke ({args.installer}): ok")


if __name__ == "__main__":
    main()
