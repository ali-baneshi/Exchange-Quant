# Development Workflow

```bash
python3 -m pip install -e '.[dev]'
make test
make lint
make compile
```

Changes to model semantics, feature windows, label windows, provider semantics,
eligibility, scoring, or stopping rules require a new model/policy identity and a
fresh evidence corpus.

Before a primary run:

1. Capture and validate development data.
2. Fit and freeze every model artifact.
3. Run `exchange-q power` with preregistered assumptions.
4. Record the resulting fixed sample target in the run manifest.
5. Verify the selected provider can certify continuity.
6. Run replay, fault, lease, recovery, and static checks.

Never tune against primary results or stop because interim performance looks good.
