# Schema-v8 Runbook

## Preflight

```bash
python3 -m pip install -e '.[dev]'
make test
make lint
make compile
./scripts/exchange-q doctor --profile diagnostic
```

## Diagnostic profile

Default diagnostic runs stop after **10 slots** (`max_terminal_slots=10`), about
10 minutes at one slot per minute.

```bash
./scripts/exchange-q run --profile diagnostic --view outcome
./scripts/exchange-q run --profile diagnostic --view detail
```

### Extended diagnostic (longer HTX pipeline test)

```bash
./scripts/exchange-q run --profile diagnostic --view outcome \
  --max-terminal-slots 60 \
  --refresh-s 1
```

Approximate duration: one slot per minute. Examples:

| `--max-terminal-slots` | Approximate duration |
|------------------------|----------------------|
| 60 | 1 hour |
| 180 | 3 hours |
| 360 | 6 hours |

Resume an interrupted run:

```bash
./scripts/exchange-q run --profile diagnostic --view outcome \
  --database runs/btcusdt-diagnostic-YYYYMMDD-HHMMSS-xxxxxxxx.sqlite3 \
  --run-id btcusdt-diagnostic-YYYYMMDD-HHMMSS-xxxxxxxx \
  --artifact artifacts/v8/diagnostic-born.json \
  --resume \
  --max-terminal-slots 60
```

Diagnostic runs use HTX and the bundled four-row
`artifacts/v8/diagnostic-born.json` fixture. The dashboard shows slot tallies
(`SLOTS`, `EXCLUSIONS`) and labels captured buy-share as **diagnostic capture —
not scored**.

Press `Ctrl-C` to stop. Open slots are cancelled atomically before the run
terminates.

## Inspect and analyze

Use the **exact** run ID and database path from the run summary (not placeholders):

```bash
./scripts/exchange-q status \
  --database runs/btcusdt-diagnostic-20260728-143448-99be3c8a.sqlite3 \
  --run-id btcusdt-diagnostic-20260728-143448-99be3c8a \
  --json

./scripts/exchange-q analyze \
  --database runs/btcusdt-diagnostic-20260728-143448-99be3c8a.sqlite3 \
  --run-id btcusdt-diagnostic-20260728-143448-99be3c8a

./scripts/exchange-q export \
  --database runs/btcusdt-diagnostic-20260728-143448-99be3c8a.sqlite3 \
  --run-id btcusdt-diagnostic-20260728-143448-99be3c8a \
  --output artifacts/export-diagnostic.json
```

HTX diagnostic runs typically report `analysis_available: false` with
`reason: no scoreable labels` — that is expected.

## Primary bootstrap pipeline

Primary/scoreable evidence requires Binance capture, a primary artifact, live
certification, and a study manifest.

```mermaid
flowchart LR
    capture[Binance capture run] --> dataset[dataset build]
    dataset --> fit[fit primary artifact]
    certify[provider-certify] --> study[study manifest]
    fit --> study
    study --> primary[primary run]
```

### Step 1 — Binance capture (diagnostic profile, provider override)

```bash
./scripts/exchange-q run --profile diagnostic --view detail \
  --provider binance-sequenced \
  --max-terminal-slots 120 \
  --refresh-s 1 \
  --database runs/btcusdt-capture-dev.sqlite3 \
  --run-id btcusdt-capture-dev
```

About 120 minutes for 120 slots. Increase `--max-terminal-slots` for more history.

### Step 2 — Development dataset

```bash
./scripts/exchange-q dataset build \
  --capture-database runs/btcusdt-capture-dev.sqlite3 \
  --provider binance-sequenced \
  --symbol btcusdt \
  --output datasets/btcusdt-development.json
```

### Step 3 — Fit primary artifact

```bash
./scripts/exchange-q fit datasets/btcusdt-development.json \
  --purpose primary \
  --output artifacts/v8/btcusdt-born.json
```

### Step 4 — Provider certification (live soak)

```bash
./scripts/exchange-q provider-certify \
  --provider binance-sequenced \
  --symbol btcusdt \
  --duration-s 300 \
  --output certifications/binance-btcusdt.json
```

Use longer `--duration-s` (e.g. 3600) for production soak. Output must have
`valid: true` with `replay_results`, `fault_results`, and `live_soak` all passing.

### Step 5 — Study manifest and doctor

First live primary test uses [`studies/btcusdt-primary.json`](../studies/btcusdt-primary.json)
with `target_eligible: 5` (~5 hours at one slot per minute):

```bash
./scripts/exchange-q doctor --profile primary --study studies/btcusdt-primary.json
```

### Step 6 — Primary run

```bash
./scripts/exchange-q run --profile primary --view outcome \
  --study studies/btcusdt-primary.json \
  --refresh-s 1
```

Primary runs continue until `target_eligible` scoreable slots are collected (no
diagnostic slot cap).

### Step 7 — Analyze

```bash
./scripts/exchange-q analyze \
  --database runs/<run-id>.sqlite3 \
  --run-id <run-id>
```

## Primary profile (fail-closed)

Primary runs require:

- a frozen study manifest
- a non-synthetic `purpose: primary` artifact
- a valid provider certification with replay, fault, and live soak sections

See the bootstrap pipeline above. Example study template:
[`studies/btcusdt-primary.example.json`](../studies/btcusdt-primary.example.json)
(full study target 720 slots).

## Resume

```bash
./scripts/exchange-q run \
  --profile diagnostic \
  --database runs/<run-id>.sqlite3 \
  --run-id <run-id> \
  --artifact artifacts/v8/diagnostic-born.json \
  --resume
```

Schema v7 databases are read-only under v8 and cannot be resumed.

## References

- [docs/SCHEMA_V8.md](SCHEMA_V8.md)
- [ARCHITECTURE.md](../ARCHITECTURE.md)
