#!/usr/bin/env bash
# Single quality gate shared by local development and CI.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

# Resolve one interpreter and run every tool through it (`python -m ...`), so the
# gate does not depend on where a platform puts console scripts (bin/ vs Scripts/).
if [ -n "${PY_BIN_DIR:-}" ]; then
    PY="$PY_BIN_DIR/python"
elif [ -f .venv/bin/python ]; then
    PY=".venv/bin/python"
elif [ -f .venv/Scripts/python ]; then
    PY=".venv/Scripts/python"
elif [ -f .venv/Scripts/python.exe ]; then
    PY=".venv/Scripts/python.exe"
else
    echo "check.sh: no Python interpreter found; create .venv or set PY_BIN_DIR" >&2
    exit 1
fi

"$PY" -m ruff check olivia tests
"$PY" -m ruff format --check olivia tests
"$PY" -m mypy --strict olivia
"$PY" -m pytest --cov=olivia --cov-fail-under=85 -q
# Latency budgets only mean something without line tracing, so the performance tests
# skipped under coverage run again here on their own.
"$PY" -m pytest -q tests/safety/test_performance.py
"$PY" scripts/validate_taxonomy.py
