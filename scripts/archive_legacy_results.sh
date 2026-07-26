#!/bin/sh
# Move non-schema-v5 result JSON out of active _live_results root.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/core/_live_results"
mkdir -p _archive/pre_v5

python3 - <<'PY'
import glob, json, os, shutil
archive = "_archive/pre_v5"
moved = kept = 0
for path in glob.glob("*.json"):
    if path == "state.json":
        continue
    try:
        with open(path) as f:
            data = json.load(f)
    except Exception:
        continue
    if isinstance(data, dict) and data.get("schema_version") == 5:
        kept += 1
        continue
    shutil.move(path, os.path.join(archive, os.path.basename(path)))
    moved += 1
print(f"archived={moved} kept_v5={kept}")
PY
