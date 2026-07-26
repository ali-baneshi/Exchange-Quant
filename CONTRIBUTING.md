# Contributing to Exchange-Q

## Development Setup

```bash
python3 --version
pip install -r requirements-dev.txt
make test
make compile
```

The runtime is standard-library-only. CI runs the test suite on Python 3.10 and 3.12; use one of those versions for release validation.

## Required Checks

Before opening a review:

```bash
make test
make compile
for file in scripts/*.sh; do sh -n "$file"; done
git diff --check
```

Do not commit generated live databases, live JSON, caches, logs, or local PID files.

## Change Classification

| Change type | Required accompanying work |
|---|---|
| Live feature or trade capture | Unit tests for malformed/duplicate/out-of-order data and integration coverage for label eligibility |
| Forecast lifecycle | Tests for pending, resolution timing, resume, and no look-ahead leakage |
| Schema-v5 field | `docs/SCHEMA_V5.md`, analyzer tests, and English/Persian operational docs |
| Model/delta/gate behavior | `test_quantum_core.py`, frozen model version decision, and statistical-policy review |
| Statistic/reporting behavior | `test_validation.py`, `docs/STATISTICS.md`, and explicit claim-policy review |
| Script/CLI change | `--help`/shell syntax validation and `docs/RUNBOOK.md`/`WORKFLOW.md` updates |

## Review Checklist

- [ ] The change preserves the boundary: evaluator only, no order execution.
- [ ] Live model predictions use `quantum_core.born_rule_predict`.
- [ ] A primary score uses only a complete local future trade window.
- [ ] `score_eligible` is false for incomplete labels or disqualifying data quality.
- [ ] Resume rejects mismatched `config_hash` values.
- [ ] Schema-v5 documents and analyzer behavior match.
- [ ] Current English and Persian operational documentation are updated together.
- [ ] Historical documentation is not silently rewritten as current evidence.
- [ ] Tests cover the changed behavior and the complete suite passes.

## Documentation Policy

| Document class | Rule |
|---|---|
| Current operational docs | Must describe schema v5 and current commands |
| Persian operational docs | Must remain equivalent to English policy and commands |
| Research theory | Must separate conceptual claims from implemented behavior |
| Historical audit/lessons | Preserve original substance; add an archive banner and link to current docs |
| PDFs | Treat as fixed reference artifacts unless a maintained source is available |

## Naming and Compatibility

- New current live output must use the schema version in `core/config.py`.
- A behaviorally meaningful model change requires a new `model_version` and a new corpus.
- Do not add compatibility fallbacks that permit legacy labels to become primary evidence.
- Keep public CLI options backward-compatible when practical; clearly deprecate positional or legacy forms in the runbook.

## Where to Add Tests

| Area | Primary test file |
|---|---|
| Live persistence and raw trades | `core/test_live_store.py` |
| Live resolution and eligibility | `core/test_live_pipeline.py` |
| Resume and end-to-end lifecycle | `core/test_live_runner_integration.py` |
| Result filtering and aggregation | `core/test_analyze_live_results.py` |
| Born-rule behavior | `core/test_quantum_core.py` |
| Statistical inference | `core/test_validation.py` |
