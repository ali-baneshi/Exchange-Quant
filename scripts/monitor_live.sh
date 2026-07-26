#!/bin/sh
# Daily monitor for schema v3 live quantum runs.
# Usage: ./scripts/monitor_live.sh

set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "=== Live run logs (last 5 lines) ==="
for log in live_smoke_24h.log live_quantum_v3.log; do
  if [ -f "$log" ]; then
    echo "--- $log ---"
    tail -5 "$log"
  fi
done

echo ""
echo "=== Newest schema v3 result file ==="
LATEST=$(ls -t core/_live_results/btcusdt_quantum_*.json 2>/dev/null | head -1)
if [ -n "$LATEST" ]; then
  python3 -c "
import json, sys
with open(sys.argv[1]) as f:
    d = json.load(f)
print('  file:', sys.argv[1])
print('  schema:', d.get('schema_version'))
print('  run_id:', d.get('run_id'))
preds = d.get('predictions', [])
resolved = [p for p in preds if p.get('status') == 'resolved']
pending = [p for p in preds if p.get('status') == 'pending']
print('  resolved:', len(resolved), ' pending:', len(pending))
" "$LATEST"
  echo ""
  python3 core/analyze_live_results.py "$LATEST" 2>/dev/null | head -20
else
  echo "  No result files found."
fi

echo ""
echo "=== Tests ==="
make test -s 2>/dev/null | tail -3
