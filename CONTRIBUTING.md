# Contributing

- Keep the live evaluator fail closed.
- Preserve half-open causal windows.
- Do not add online model adaptation to a frozen primary run.
- Use mature numerical/statistical libraries instead of unverified custom methods.
- Add replay and fault tests for every lifecycle or acquisition change.
- Keep historical and synthetic experiments under `research/`.
- Do not restore deprecated v2–v6 executable entry points.

Run before submitting:

```bash
make test
make lint
make compile
```
