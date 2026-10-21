#!/usr/bin/env bash
# Single quality gate shared by local development and CI.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

PY_BIN_DIR="${PY_BIN_DIR:-.venv/bin}"

"$PY_BIN_DIR/ruff" check olivia tests
"$PY_BIN_DIR/ruff" format --check olivia tests
"$PY_BIN_DIR/mypy" --strict olivia
"$PY_BIN_DIR/pytest" --cov=olivia --cov-fail-under=85 -q
"$PY_BIN_DIR/python" scripts/validate_taxonomy.py
