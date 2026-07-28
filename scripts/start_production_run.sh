#!/bin/sh
# Start definitive schema-v6r1 quantum live evaluation (720 eligible hourly forecasts).
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

make test -s

mkdir -p core/_live_results/_archive/pre_v6r1

pid_is_pipeline() {
  pid="$1"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null &&
    ps -p "$pid" -o args= 2>/dev/null | grep -q 'pipeline_live_ensemble\.py'
}

PIDFILE="$ROOT/live_quantum_v3.pid"
if [ -f "$PIDFILE" ]; then
  existing_pid="$(cat "$PIDFILE" 2>/dev/null || true)"
  if pid_is_pipeline "$existing_pid"; then
    echo "Production run already active: PID $existing_pid"
    exit 1
  fi
  echo "Removing stale production PID file: $PIDFILE"
  rm -f "$PIDFILE"
fi

echo "Starting schema-v6r1 production run in the foreground."
echo "Monitor: ./scripts/monitor_live.sh"
echo "Analyze: python3 core/analyze_live_results.py --schema-version 6"
exec python3 -u core/pipeline_live_ensemble.py \
  --symbol btcusdt \
  --mode quantum \
  --horizon-s 3600 \
  --sample-interval-s 60 \
  --window 15 \
  --max-resolved 720 \
  --pid-file "$PIDFILE" \
  >> "$ROOT/live_quantum_v3.log" 2>&1
