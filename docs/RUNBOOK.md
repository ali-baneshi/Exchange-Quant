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

## Diagnostic Stream

```bash
./scripts/exchange-q run --profile diagnostic
```

This is the normal operator workflow. It automatically:

- creates the bundled diagnostic artifact when missing;
- generates one unique run ID and matching SQLite path;
- applies bounded HTX-safe timing and slot defaults;
- renders one integrated foreground dashboard;
- switches to compact transition logs when output is redirected.

The bundled HTX adapter cannot certify continuity, so these labels remain
ineligible by design. This command tests connectivity, persistence, scheduling,
shutdown, and resource behavior only.

## Display and Stop

```bash
./scripts/exchange-q run --profile diagnostic --display dashboard
./scripts/exchange-q run --profile diagnostic --display log
```

The dashboard shows the generated database path, run identity, provider health,
stream activity and rates, current slot phase, accurate next action, terminal
progress, exclusion totals, recent transitions, and the HTX evidence warning.
Heartbeat lines are not printed.

Press `Ctrl-C` in the run terminal. The foreground runner closes the active socket,
updates run state, releases its lease, and exits completely.

## Restart

Copy the database, run ID, and artifact shown by the dashboard:

```bash
./scripts/exchange-q run \
  --profile diagnostic \
  --database runs/RUN_ID.sqlite3 \
  --run-id RUN_ID \
  --artifact artifacts/v7/normalized-born.json \
  --resume
```

Resume requires explicit identity paths. A configuration mismatch is rejected.

## Advanced Overrides

```bash
./scripts/exchange-q run \
  --profile diagnostic \
  --database runs/custom.sqlite3 \
  --run-id custom-diagnostic \
  --max-terminal-slots 20 \
  --display dashboard \
  --refresh-s 1
```

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
