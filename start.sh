#!/usr/bin/env bash
# One-step launcher: check Python, create .venv, install OLIVIA, run it.
# Usage: ./start.sh [olivia arguments]   (no arguments -> `olivia chat`; `./start.sh doctor` works)
set -euo pipefail
cd "$(dirname "$0")"

# 1. Prerequisite: Python 3.11 or newer (the project's requires-python).
PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3; do
  if command -v "$candidate" >/dev/null 2>&1 \
    && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    PYTHON="$candidate"
    break
  fi
done
if [ -z "$PYTHON" ]; then
  echo "没有找到 Python 3.11 或更新版本。请先安装（macOS：brew install python@3.12），再重新运行。" >&2
  exit 1
fi

# 2. .env: OLIVIA is offline and reads no .env file or secrets (the key lives in the OS
#    keychain), so there is no .env.example to copy and this step is skipped on purpose.

# 3. Virtual environment and dependencies.
if [ ! -x .venv/bin/python ]; then
  echo "正在创建 .venv ……"
  "$PYTHON" -m venv .venv
fi
if ! .venv/bin/python -P -c "import olivia" >/dev/null 2>&1; then
  echo "正在安装 OLIVIA 和它的依赖（需要联网，只在第一次）……"
  .venv/bin/python -m pip install --quiet --upgrade pip
  .venv/bin/python -m pip install --quiet -e .
fi

# 4. Run the command-line tool; Ctrl+C stops it.
if [ "$#" -eq 0 ]; then
  set -- chat
fi
exec .venv/bin/olivia "$@"
