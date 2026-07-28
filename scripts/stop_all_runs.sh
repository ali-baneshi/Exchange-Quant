#!/usr/bin/env bash
# Stop Exchange-Q live pipeline processes without touching unrelated PIDs.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

is_pipeline_pid() {
  local pid="$1"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null &&
    [[ "$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)" == "$ROOT" ]] &&
    ps -p "$pid" -o args= 2>/dev/null | grep -q 'core/pipeline_live_ensemble\.py'
}

stop_pipeline_pid() {
  local pid="$1"
  local label="$2"
  local deadline

  if ! is_pipeline_pid "$pid"; then
    return 0
  fi

  echo "Stopping $label PID $pid (SIGTERM)..."
  kill -TERM "$pid" 2>/dev/null || true
  deadline=$((SECONDS + 15))
  while is_pipeline_pid "$pid" && (( SECONDS < deadline )); do
    sleep 1
  done
  if is_pipeline_pid "$pid"; then
    echo "Escalating $label PID $pid (SIGKILL)..."
    kill -KILL "$pid" 2>/dev/null || true
  fi
}

for pidfile in live_quantum_v3.pid live_exploratory.pid; do
  if [[ -f "$pidfile" ]]; then
    pid="$(cat "$pidfile" 2>/dev/null || true)"
    stop_pipeline_pid "$pid" "$pidfile"
    if ! is_pipeline_pid "$pid"; then
      rm -f "$pidfile"
    fi
  fi
done

while read -r pid; do
  if is_pipeline_pid "$pid"; then
    stop_pipeline_pid "$pid" "pipeline_live_ensemble"
  fi
done < <(pgrep -f 'core/pipeline_live_ensemble\.py' 2>/dev/null || true)

echo ""
echo "=== Final status ==="
remaining=""
while read -r pid; do
  if is_pipeline_pid "$pid"; then
    remaining="${remaining}${pid} $(ps -p "$pid" -o args= 2>/dev/null)"$'\n'
  fi
done < <(pgrep -f 'core/pipeline_live_ensemble\.py' 2>/dev/null || true)
if [[ -n "$remaining" ]]; then
  echo "WARNING: live pipeline processes still running:"
  echo "$remaining"
  exit 1
fi
echo "All live pipeline processes stopped."
