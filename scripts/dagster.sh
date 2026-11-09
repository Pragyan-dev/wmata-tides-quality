#!/usr/bin/env bash
# Start the Dagster UI at http://localhost:3000 for the daily batch.
# Run history is kept in orchestration/dagster_home.
set -euo pipefail
cd "$(dirname "$0")/.."
export DAGSTER_HOME="$PWD/orchestration/dagster_home"
# dagster-dbt parses the dbt project at startup and looks for `dbt` on PATH.
export PATH="$PWD/.venv/bin:$PATH"
exec .venv/bin/dagster dev -m orchestration.definitions "$@"
