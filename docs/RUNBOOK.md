# Schema-v7 Runbook

## Preflight

```bash
python3 -m pip install -e '.[dev]'
make test
make lint
make compile
```

Do not start a primary study without a frozen artifact, power-derived sample target,
and a provider whose health reports `coverage_certifiable=true`.

## Fit

```bash
./scripts/exchange-q fit development.json \
  --output artifacts/v7/normalized-born.json
```

Development data must precede the primary evaluation period.

## Diagnostic Stream

```bash
./scripts/exchange-q run \
  --database runs/diagnostic.sqlite3 \
  --artifact artifacts/v7/normalized-born.json \
  --run-id diagnostic-001 \
  --provider htx-ws \
  --horizon-s 60 \
  --lookback-s 300 \
  --cadence-s 60 \
  --minimum-label-trades 30 \
  --target-eligible 100 \
  --max-terminal-slots 10
```

The bundled HTX adapter cannot certify continuity, so these labels remain
ineligible by design. This command tests connectivity, persistence, scheduling,
shutdown, and resource behavior only.

## Monitor and Stop

```bash
./scripts/exchange-q status \
  --database runs/diagnostic.sqlite3 \
  --run-id diagnostic-001

./scripts/exchange-q stop \
  --database runs/diagnostic.sqlite3 \
  --run-id diagnostic-001
```

The stop command verifies the process working directory and command line before
sending `SIGTERM`. The foreground runner closes the active socket, updates run
state, and releases its lease on `SIGINT` or `SIGTERM`.

## Restart

Run the same command with the same run ID, database, artifact, and manifest values.
The runner restores the latest scheduled or pending slot. A configuration mismatch
is rejected.

## Analyze and Export

```bash
./scripts/exchange-q analyze --database runs/primary.sqlite3 --run-id RUN_ID
./scripts/exchange-q export \
  --database runs/primary.sqlite3 \
  --run-id RUN_ID \
  --output artifacts/v7/RUN_ID.json
```

No significance or superiority claim is permitted merely because these commands
produce output.

## Failure Rules

- Provider continuity failure: keep raw events; resolve affected labels ineligible.
- Lost writer lease: stop immediately.
- Invalid event: reject or quarantine; never coerce it into a valid event.
- Missing feature history: persist a skipped slot.
- Missing label coverage: resolve ineligible; never use a snapshot fallback.
- Crash: restart from SQLite; never recover from JSON.
