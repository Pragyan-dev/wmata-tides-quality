#!/usr/bin/env bash
# Start the collector in the background.
# caffeinate -is keeps the Mac from idle sleep (and from system sleep on AC power)
# while the collector runs. Closing the lid still sleeps the Mac.
# This does not restart the collector after a crash or a reboot.
set -euo pipefail
cd "$(dirname "$0")/.."

PID_FILE=data/collector.pid
LOG_FILE=data/logs/collector.log

if [[ ! -f .env ]]; then
  echo "No .env file. Run: cp .env.example .env, then add your WMATA_API_KEY."
  exit 1
fi
if [[ -f $PID_FILE ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "Collector already running, pid $(cat "$PID_FILE")."
  exit 1
fi

mkdir -p data/logs
nohup caffeinate -is .venv/bin/python -m collector run >> "$LOG_FILE" 2>&1 &
sleep 3

if [[ -f $PID_FILE ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "Collector started, pid $(cat "$PID_FILE"). Log: $LOG_FILE"
else
  echo "Collector did not start. Last log lines:"
  tail -n 20 "$LOG_FILE"
  exit 1
fi
