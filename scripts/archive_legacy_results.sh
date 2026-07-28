#!/bin/sh
# Move pre-hardening result JSON out of the active v6r1 corpus.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/core/_live_results"
mkdir -p _archive/pre_v6r1

python3 - <<'PY'
import glob, json, os, shutil
archive = "_archive/pre_v6r1"
moved = kept = 0
for path in glob.glob("*.json"):
    if path == "state.json":
        continue
    try:
        with open(path) as f:
            data = json.load(f)
    except Exception:
        continue
    if (
        isinstance(data, dict)
        and data.get("schema_version") == 6
        and data.get("implementation_revision") == "v6r1"
        and data.get("acquisition_policy_version") == 1
    ):
        kept += 1
        continue
    shutil.move(path, os.path.join(archive, os.path.basename(path)))
    moved += 1
print(f"archived={moved} kept_v6r1={kept}")
PY
