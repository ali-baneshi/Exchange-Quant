#!/bin/sh
# Monitor parallel exploratory schema v5 run (horizon 60s profile).
# Usage: ./scripts/monitor_exploratory.sh

set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

LOG="live_exploratory.log"
PIDFILE="live_exploratory.pid"

echo "=== Exploratory log (last 8 lines) ==="
if [ -f "$LOG" ]; then
  tail -8 "$LOG"
else
  echo "  (no $LOG yet)"
fi

if [ -f "$PIDFILE" ]; then
  PID=$(cat "$PIDFILE")
  if kill -0 "$PID" 2>/dev/null; then
    echo ""
    echo "=== Exploratory run PID $PID (running) ==="
  else
    echo ""
    echo "=== Exploratory run PID $PID (not running) ==="
  fi
else
  echo ""
  echo "=== No live_exploratory.pid ==="
fi

echo ""
echo "=== Schema v5 exploratory result ==="
eval "$(python3 -c "
import glob, json, os, re

LOG = 'live_exploratory.log'
TARGET_HORIZON = 60.0


def is_v4_exploratory(path):
    try:
        with open(path) as f:
            d = json.load(f)
    except Exception:
        return False
    return (
        d.get('schema_version') == 5
        and float(d.get('horizon_s', 0)) == TARGET_HORIZON
    )


def from_log():
    if not os.path.isfile(LOG):
        return None, None
    with open(LOG) as f:
        lines = f.readlines()
    json_path = db_path = None
    for line in reversed(lines):
        m = re.search(r'output=(.+\.json)', line)
        if m:
            candidate = m.group(1)
            if os.path.isfile(candidate) and is_v4_exploratory(candidate):
                json_path = candidate
        m2 = re.search(r'database=(.+\.sqlite3)', line)
        if m2 and os.path.isfile(m2.group(1)):
            db_path = m2.group(1)
        if json_path:
            break
    return json_path, db_path


def exploratory_v4_files():
    out = []
    for p in glob.glob('core/_live_results/*.json'):
        if '_archive' in p.replace(chr(92), '/'):
            continue
        if is_v4_exploratory(p):
            out.append(p)
    return out


def by_mtime(files):
    return max(files, key=os.path.getmtime) if files else None


active_json, active_db = from_log()
files = exploratory_v4_files()
primary = active_json or by_mtime(files) or ''


def sh_quote(s):
    if not s:
        return \"''\"
    return \"'\" + s.replace(\"'\", \"'\\\\''\") + \"'\"

print(f'PRIMARY_FILE={sh_quote(primary)}')
print(f'ACTIVE_DB={sh_quote(active_db or \"\")}')
")"

if [ -n "$PRIMARY_FILE" ] && [ -f "$PRIMARY_FILE" ]; then
  echo "  file (selected):       $PRIMARY_FILE"
  if [ -n "$ACTIVE_DB" ] && [ -f "$ACTIVE_DB" ]; then
    echo "  database:              $ACTIVE_DB"
  fi
  python3 -c "
import json, sys
from collections import Counter
with open(sys.argv[1]) as f:
    d = json.load(f)
if d.get('schema_version') != 5:
    raise SystemExit('  ERROR: selected file is not schema v5')
print('  schema:', d.get('schema_version'))
print('  run_id:', d.get('run_id'))
print('  horizon_s:', d.get('horizon_s'))
print('  sample_interval_s:', d.get('sample_interval_s'))
print('  status:', d.get('status'), 'stop_reason:', d.get('stop_reason'))
print('  config_hash:', (d.get('config_hash') or '')[:16], '...')
print('  model_version:', d.get('model_version'))
print('  observations:', len(d.get('observations', [])))
preds = d.get('predictions', [])
resolved = [p for p in preds if p.get('status') == 'resolved' and p.get('score_eligible', True)]
pending = [p for p in preds if p.get('status') == 'pending']
born = sum(1 for p in resolved if p.get('fallback_reason') == 'none')
print('  resolved eligible:', len(resolved), ' pending:', len(pending), ' target: 500')
if resolved:
    print('  born_active_rate:', f'{born}/{len(resolved)} ({100*born/len(resolved):.1f}%)')
    print('  fallbacks:', dict(Counter(p.get('fallback_reason','?') for p in resolved)))
    labels = Counter(p.get('resolved_label', '?') for p in resolved)
    fw = labels.get('forward_window', 0)
    print(f'  resolved_label: {dict(labels)}  forward_window={fw}/{len(resolved)} ({100*fw/len(resolved):.1f}%)')
    if len(resolved) >= 5:
        preds = [p.get('prediction', 0) for p in resolved]
        acts = [p.get('resolved_actual', 0) for p in resolved]
        bias = sum(p - a for p, a in zip(preds, acts)) / len(resolved)
        sat = sum(1 for p in preds if p >= 0.99)
        print(f'  bias pred-act:  {bias:+.4f}')
        print(f'  saturation:     {sat}/{len(resolved)} at q>=0.99')
" "$PRIMARY_FILE"
  echo ""
  python3 core/analyze_live_results.py --schema-version 5 "$PRIMARY_FILE" 2>/dev/null | head -32
else
  echo "  No schema v5 exploratory result (horizon 60s) found yet."
  echo "  Start: ./scripts/start_exploratory_run.sh"
fi
