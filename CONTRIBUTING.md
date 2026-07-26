# Contributing to Exchange-Q

## Development Setup

```bash
python3 --version   # 3.8+
pip install -r requirements-dev.txt
make test
```

Runtime code uses **stdlib only**. Pytest is a dev dependency.

## Running Tests

```bash
make test
# or
cd core && python -m pytest test_*.py -v
```

CI (`.github/workflows/test.yml`) runs on Python 3.10 and 3.12. Current suite: **68 tests**.

### Optional pre-commit check

Before pushing, run:

```bash
make test
python -m compileall core
```

To install a local git hook:

```bash
printf '#!/bin/sh\nmake test\n' > .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
```

Weekly drift detection: `.github/workflows/validation-weekly.yml` (Mondays 06:00 UTC).

## Code Review Checklist

- [ ] Live changes use `live_protocol` (`pending_due`, `forecast_lookback`, `resolve_buy_ratio`)
- [ ] Born rule predictions go through `quantum_core.born_rule_predict` only
- [ ] Do not re-enable Born rule on kline backtests without order-book imbalance
- [ ] Statistical claims include sample size and Bonferroni correction
- [ ] Update [docs/SCHEMA_V5.md](./docs/SCHEMA_V5.md) if prediction JSON fields change
- [ ] New constants are documented at module level
- [ ] One pending forecast at a time in live pipelines

## Pipeline Guidelines

| Module | Role |
|--------|------|
| `pipeline_live_ensemble.py` | Canonical long-running evaluation |
| `pipeline_one_shot.py` | Scheduled cron runs with state persistence |
| `pipeline_real.py` | Demo/smoke only |
| `pipeline_live_long.py` | Legacy — avoid for new experiments |

## Target Variable Warning

- **Kline backtest:** binary `direction` (0/1)
- **Live pipeline:** continuous `buy_ratio` [0, 1]

These metrics are **not directly comparable**.

## Adding Tests

Priority areas when changing code:

1. `test_validation.py` — any change to significance metrics
2. `test_quantum_core.py` — Born rule, delta logic, destructive-interference gate
3. `test_live_protocol.py` — resolve timing contract
4. `test_data_historical.py` — candle ordering regressions
