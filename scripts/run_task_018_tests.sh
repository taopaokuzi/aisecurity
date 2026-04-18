#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

PYTHON_BIN="${PYTHON_BIN:-./.venv/bin/python}"
# Usage:
# 1. If TEST_DATABASE_URL / TEST_ADMIN_DATABASE_URL are provided, the script uses them directly.
# 2. Otherwise it tries POSTGRES_HOST/PORT/USER/PASSWORD (default 127.0.0.1:5432).
# 3. If no external PostgreSQL is reachable, it starts an embedded real PostgreSQL for this run.
"${PYTHON_BIN}" scripts/run_task_018_tests.py
