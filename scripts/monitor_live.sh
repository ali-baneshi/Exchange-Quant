#!/bin/sh
# Monitor the active schema-v6r1 production evaluation.
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

LOG="$ROOT/live_quantum_v3.log"
PIDFILE="$ROOT/live_quantum_v3.pid"

echo "=== Production log (last 12 lines) ==="
if [ -f "$LOG" ]; then
  tail -12 "$LOG"
else
  echo "  No log file yet."
fi

echo ""
echo "=== Production process ==="
if [ -f "$PIDFILE" ]; then
  pid="$(cat "$PIDFILE" 2>/dev/null || true)"
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null &&
    ps -p "$pid" -o args= 2>/dev/null | grep -q 'pipeline_live_ensemble\.py'; then
    echo "  PID $pid is running."
  else
    echo "  PID file is stale or process is not the live pipeline."
  fi
else
  echo "  No PID file."
fi

echo ""
echo "=== SQLite-authoritative status ==="
python3 - "$ROOT" "$LOG" <<'PY'
import json
import os
import re
import sqlite3
import sys
from collections import Counter

root, log_path = sys.argv[1:]
results_dir = os.path.join(root, "core", "_live_results")
expected_horizon_s = 3600


def state_for(path):
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2)
        row = connection.execute(
            "SELECT data_json, updated_at_ms FROM run_state WHERE singleton = 1"
        ).fetchone()
        if not row:
            return None
        state = json.loads(row[0])
        if state.get("schema_version") != 6:
            return None
        if float(state.get("horizon_s", 0)) != expected_horizon_s:
            return None
        state["_db_path"] = path
        state["_updated_at_ms"] = row[1]
        return state
    except (OSError, sqlite3.Error, json.JSONDecodeError):
        return None
    finally:
        if "connection" in locals():
            connection.close()


def active_db_from_log():
    try:
        with open(log_path, encoding="utf-8") as handle:
            for line in reversed(handle.readlines()):
                match = re.search(r"database=(.+\.sqlite3)\s*$", line)
                if match and os.path.isfile(match.group(1)):
                    return match.group(1)
    except OSError:
        pass
    return None


database_path = active_db_from_log()
candidate_paths = [database_path] if database_path else []
if os.path.isdir(results_dir):
    candidate_paths.extend(
        os.path.join(results_dir, name)
        for name in os.listdir(results_dir)
        if name.endswith(".sqlite3")
    )
states = [
    state
    for state in (state_for(path) for path in dict.fromkeys(candidate_paths))
    if state
]
if not states:
    print("  No schema-v6 durable run state found.")
    raise SystemExit(0)

state = max(states, key=lambda item: item["_updated_at_ms"])
connection = sqlite3.connect(
    f"file:{state['_db_path']}?mode=ro", uri=True, timeout=2
)
try:
    predictions = [
        json.loads(row[0])
        for row in connection.execute(
            "SELECT data_json FROM forecasts ORDER BY sequence_no"
        )
    ]
    observations = connection.execute(
        "SELECT COUNT(*) FROM observations"
    ).fetchone()[0]
finally:
    connection.close()

resolved = [item for item in predictions if item.get("status") == "resolved"]
eligible = [item for item in resolved if item.get("score_eligible") is True]
pending = [item for item in predictions if item.get("status") == "pending"]
excluded = [item for item in resolved if item.get("score_eligible") is not True]
reasons = Counter()
fallbacks = Counter(item.get("fallback_reason", "unknown") for item in eligible)
for item in excluded:
    reasons.update(item.get("entry_quality_flags", []))
    reasons.update(item.get("exit_quality_flags", []))
    reasons.update(item.get("label_capture", {}).get("capture_failure_reasons", []))
    if item.get("resolved_label") != "forward_window":
        reasons["non_forward_label"] += 1
    if item.get("label_capture_complete") is not True:
        reasons["incomplete_capture"] += 1

print(f"  database:              {state['_db_path']}")
print(f"  run_id:                {state.get('run_id')}")
print(
    "  schema/model/revision: "
    f"v{state.get('schema_version')} / {state.get('model_version')} / "
    f"{state.get('implementation_revision', 'pre-hardening')}"
)
print(f"  status:                {state.get('status')} ({state.get('stop_reason')})")
print(f"  observations:          {observations}")
print(f"  forecasts:             {len(predictions)} total, {len(pending)} pending")
print(
    f"  resolved:              {len(resolved)} total, "
    f"{len(eligible)} eligible, {len(excluded)} excluded"
)
print(f"  state updated_at_ms:   {state['_updated_at_ms']}")
if pending:
    print(f"  pending target_at_ms:  {pending[0].get('target_at_ms')}")
if fallbacks:
    print(f"  eligible fallbacks:    {dict(fallbacks)}")
if reasons:
    print(f"  exclusion reasons:     {dict(reasons)}")
PY
