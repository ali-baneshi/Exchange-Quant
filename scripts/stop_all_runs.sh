#!/bin/sh
# Stop all Exchange-Q live pipeline processes (production + exploratory + any stray).
# Usage: ./scripts/stop_all_runs.sh
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

stop_pid() {
  pid="$1"
  label="$2"
  if [ -z "$pid" ]; then
    return 0
  fi
  if kill -0 "$pid" 2>/dev/null; then
    echo "Stopping $label PID $pid (SIGTERM)..."
    kill -TERM "$pid" 2>/dev/null || true
  fi
}

for pidfile in live_quantum_v3.pid live_exploratory.pid; do
  if [ -f "$pidfile" ]; then
    stop_pid "$(cat "$pidfile")" "$pidfile"
  fi
done

for pid in $(pgrep -f 'pipeline_live_ensemble\.py' 2>/dev/null || true); do
  stop_pid "$pid" "pipeline_live_ensemble"
done

sleep 5

for pid in $(pgrep -f 'pipeline_live_ensemble\.py' 2>/dev/null || true); do
  echo "Force killing PID $pid (SIGKILL)..."
  kill -KILL "$pid" 2>/dev/null || true
done

rm -f live_quantum_v3.pid live_exploratory.pid

echo ""
echo "=== Final status ==="
remaining=$(pgrep -af 'pipeline_live_ensemble\.py' 2>/dev/null || true)
if [ -n "$remaining" ]; then
  echo "WARNING: processes still running:"
  echo "$remaining"
  exit 1
fi
echo "All pipeline_live_ensemble processes stopped."
echo "PID files removed."
