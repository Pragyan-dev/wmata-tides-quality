#!/usr/bin/env bash
# Stop the background collector. It finishes cleanly on SIGTERM.
set -euo pipefail
cd "$(dirname "$0")/.."

PID_FILE=data/collector.pid
if [[ ! -f $PID_FILE ]] || ! kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "Collector is not running."
  rm -f "$PID_FILE"
  exit 0
fi

PID=$(cat "$PID_FILE")
kill -TERM "$PID"
for _ in $(seq 1 20); do
  kill -0 "$PID" 2>/dev/null || { echo "Collector stopped."; exit 0; }
  sleep 1
done
echo "Collector (pid $PID) did not stop within 20 seconds."
exit 1
