#!/bin/sh
# Start a schema-v6r1 exploratory live evaluation.
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PIDFILE="$ROOT/live_exploratory.pid"
LOGFILE="$ROOT/live_exploratory.log"

pid_is_pipeline() {
  pid="$1"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null &&
    ps -p "$pid" -o args= 2>/dev/null | grep -q 'pipeline_live_ensemble\.py'
}

if [ -f "$PIDFILE" ]; then
  existing_pid="$(cat "$PIDFILE" 2>/dev/null || true)"
  if pid_is_pipeline "$existing_pid"; then
    echo "Exploratory run already active: PID $existing_pid"
    echo "Monitor: ./scripts/monitor_exploratory.sh"
    exit 1
  fi
  echo "Removing stale exploratory PID file: $PIDFILE"
  rm -f "$PIDFILE"
fi

mkdir -p core/_live_results
python3 -m py_compile core/pipeline_live_ensemble.py core/live_store.py core/data_fetcher.py

echo "Starting schema-v6r1 exploratory run in the foreground."
echo "  horizon=60s sample_interval=5s max_resolved=500"
echo "Monitor: ./scripts/monitor_exploratory.sh"
echo "Log:     tail -f live_exploratory.log"
echo "Analyze: python3 core/analyze_live_results.py --schema-version 6"
exec python3 -u core/pipeline_live_ensemble.py \
  --symbol btcusdt \
  --mode quantum \
  --horizon-s 60 \
  --sample-interval-s 5 \
  --window 15 \
  --max-resolved 500 \
  --pid-file "$PIDFILE" \
  >> "$LOGFILE" 2>&1
