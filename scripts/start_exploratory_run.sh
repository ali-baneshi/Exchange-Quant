#!/bin/sh
# Start parallel exploratory schema v5 run (fast horizon, many resolves).
# Does NOT touch production lock/PID — safe to run alongside start_production_run.sh.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

mkdir -p core/_live_results

PIDFILE="$ROOT/live_exploratory.pid"
LOGFILE="$ROOT/live_exploratory.log"

if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "Exploratory run already running PID $(cat "$PIDFILE")"
  echo "Monitor: ./scripts/monitor_exploratory.sh"
  exit 1
fi

setsid python3 -u core/pipeline_live_ensemble.py \
  --symbol btcusdt \
  --mode quantum \
  --horizon-s 60 \
  --sample-interval-s 5 \
  --window 15 \
  --max-resolved 500 \
  >> "$LOGFILE" 2>&1 &
echo $! > "$PIDFILE"
echo "Started exploratory run PID $(cat "$PIDFILE")"
echo "  horizon=60s  sample=5s  max-resolved=500  (~8-10 hours)"
echo "Monitor: ./scripts/monitor_exploratory.sh"
echo "Log:     tail -f live_exploratory.log"
echo "Analyze: python3 core/analyze_live_results.py --schema-version 5"
