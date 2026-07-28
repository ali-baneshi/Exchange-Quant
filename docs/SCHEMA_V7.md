# Schema v7

**Current revision:** `v7r2`

## Run Manifest

Every run freezes:

- run ID, symbol, and provider identity;
- model artifact hash;
- feature and label policy identities;
- primary metric;
- horizon, lookback, and cadence;
- minimum label trades;
- fixed eligible-sample target;
- schema and implementation revision.

The canonical cadence must be at least the forecast horizon.

## Event Time

- Trades and books record exchange and local receive timestamps independently.
- Feature windows are `[slot_start-lookback, slot_start)`.
- Label windows are `[slot_start, slot_end)`.
- Events exactly at `slot_end` belong to the next interval.

## Forecast Slots

Statuses are:

```text
scheduled
created
skipped
pending_label
resolved_eligible
resolved_ineligible
expired
failed
```

Illegal and post-terminal transitions are rejected by the store.

## Eligibility

`resolved_eligible` requires:

- provider-certified coverage for the complete label interval;
- no relevant continuity failure;
- at least the manifest minimum trade count;
- a valid frozen forecast and label;
- no structured exclusion reason.

Unavailable labels are never replaced by a current feature snapshot.

## Authority and Export

SQLite is authoritative. Raw events, coverage, forecast slots, labels, exclusions,
leases, and lifecycle events are normalized tables.

JSON is produced only by `exchange-q export` from a consistent database snapshot.
It is not accepted as resumable state.
