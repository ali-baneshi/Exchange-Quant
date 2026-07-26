#!/bin/sh
# Start definitive schema v5 quantum live evaluation (720 resolved hourly forecasts).
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

make test -s

mkdir -p core/_live_results/_archive/pre_v5

LOCKFILE="$ROOT/.live_quantum_v5.lock"

if [ -f live_quantum_v3.pid ] && kill -0 "$(cat live_quantum_v3.pid)" 2>/dev/null; then
  echo "Already running PID $(cat live_quantum_v3.pid)"
  exit 1
fi

setsid sh -c '
  exec 9>"$1"
  flock -n 9 || exit 1
  exec python3 -u core/pipeline_live_ensemble.py \
    --symbol btcusdt \
    --mode quantum \
    --horizon-s 3600 \
    --sample-interval-s 60 \
    --window 15 \
    --max-resolved 720 \
    >> "$2" 2>&1
' sh "$LOCKFILE" "$ROOT/live_quantum_v3.log" &
echo $! > live_quantum_v3.pid
echo "Started production run PID $(cat live_quantum_v3.pid)"
echo "Monitor: ./scripts/monitor_live.sh"
echo "Analyze: python3 core/analyze_live_results.py --schema-version 5"
