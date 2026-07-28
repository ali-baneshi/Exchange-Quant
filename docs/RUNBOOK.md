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
./scripts/exchange-q fit tests/fixtures/development-minimal.json \
  --output artifacts/v7/normalized-born.json
```

Development data must precede the primary evaluation period.

The bundled fixture and generated `artifacts/v7/normalized-born.json` artifact are
for diagnostic connectivity tests only. Do not use them for a primary study.

## Diagnostic Stream

```bash
DATABASE="runs/diagnostic.sqlite3"
RUN_ID="diagnostic-$(date +%Y%m%d-%H%M%S)"

./scripts/exchange-q run \
  --database "$DATABASE" \
  --artifact artifacts/v7/normalized-born.json \
  --run-id "$RUN_ID" \
  --provider htx-ws \
  --horizon-s 60 \
  --lookback-s 300 \
  --cadence-s 60 \
  --minimum-label-trades 30 \
  --target-eligible 100 \
  --max-terminal-slots 10
```

Use a fresh run ID or omit `--run-id` and copy the generated ID printed at startup.
Reusing an existing ID is rejected unless `--resume` is supplied explicitly.

The bundled HTX adapter cannot certify continuity, so these labels remain
ineligible by design. This command tests connectivity, persistence, scheduling,
shutdown, and resource behavior only.

## Monitor and Stop

```bash
./scripts/exchange-q monitor \
  --database "$DATABASE" \
  --run-id "$RUN_ID"

./scripts/exchange-q monitor \
  --database "$DATABASE" \
  --run-id "$RUN_ID" \
  --watch \
  --interval-s 5

./scripts/exchange-q status \
  --database "$DATABASE" \
  --run-id "$RUN_ID"

./scripts/exchange-q stop \
  --database "$DATABASE" \
  --run-id "$RUN_ID"
```

Shell variables are names, not values. Use `"$RUN_ID"` after assigning it; do not
write `"$btcusdt-v7-..."`, which asks the shell to expand a different variable.

The run terminal now prints startup, heartbeat, slot, and terminal progress lines.
`monitor --watch` refreshes one dashboard in an interactive terminal and exits when
the run finishes or when its writer becomes dead, stale, or orphaned.

The stop command verifies the process working directory and command line before
sending `SIGTERM`, waits for full exit, and uses `SIGKILL` only after the configurable
timeout. It removes a verified stale lease if forced termination prevented normal
cleanup. The foreground runner closes the active socket, updates run state, and
releases its lease on `SIGINT` or `SIGTERM`.

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
