#!/usr/bin/env bash
# Rebuild everything on the fixed window used for the numbers in docs/.
# Usage: scripts/build_snapshot.sh [AFTER] [BEFORE]
set -euo pipefail
cd "$(dirname "$0")/.."
AFTER=${1:-"2026-11-06 11:00:00-05:00"}
BEFORE=${2:-"2026-11-06 14:00:00-05:00"}
.venv/bin/python -m collector load-static
cd dbt_project
../.venv/bin/dbt build --profiles-dir . \
  --vars "{collected_after: '$AFTER', collected_before: '$BEFORE'}"
