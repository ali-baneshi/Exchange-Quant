# Exchange-Q Documentation Index

**English** | [فارسی](fa/README.md) | [Persian summary](../README.fa.md)

## Current Operational Truth

| Need | Read |
|---|---|
| Start, monitor, stop, or resume | [RUNBOOK.md](RUNBOOK.md) |
| Understand system flow | [../ARCHITECTURE.md](../ARCHITECTURE.md) |
| Read fields and eligibility rules | [SCHEMA_V6.md](SCHEMA_V6.md) |
| Interpret metrics and claims | [STATISTICS.md](STATISTICS.md) |
| Know current empirical status | [EVIDENCE_STATUS.md](EVIDENCE_STATUS.md) |
| Follow all workflows | [../WORKFLOW.md](../WORKFLOW.md) |
| Review or contribute | [../CONTRIBUTING.md](../CONTRIBUTING.md) |

The canonical live path is:

```text
pipeline_live_ensemble.py → SQLite authoritative state → schema-v6r1 JSON export
→ analyze_live_results.py --schema-version 6
```

## Guides

| Language | Current entry |
|---|---|
| English | [en/guide/README.md](en/guide/README.md) |
| Persian | [fa/darsname/README.md](fa/darsname/README.md) |
| Persian quick operational guide | [fa/QUICKSTART.md](fa/QUICKSTART.md) |
| Persian terminology | [fa/GLOSSARY.md](fa/GLOSSARY.md) |

## Evidence and Historical Records

| Record type | Location | Interpretation |
|---|---|---|
| Current evidence boundary | [EVIDENCE_STATUS.md](EVIDENCE_STATUS.md) | Current claim policy |
| v6r1 hardening record | [HARDENING_V6R1.md](HARDENING_V6R1.md) | Implemented reliability changes and v7 boundary |
| Dated audit | [../AUDIT_REPORT.md](../AUDIT_REPORT.md) | Preserve findings; see status banner |
| Dated verification report | [../verification_report.md](../verification_report.md) | Historical analysis, not current v6 evidence |
| Run artifacts | [../artifacts/](../artifacts/) | Dated diagnostics, not automatically reusable evidence |
| Old schemas | [SCHEMA_V3.md](SCHEMA_V3.md), [SCHEMA_V5.md](SCHEMA_V5.md) | Historical references only |
| Legacy audit | [../code_audit_v1/STALE.md](../code_audit_v1/STALE.md) | Historical code-audit context |

## Background Material

Standalone theory, quantum-cognition, PHCA, and general programming documents are
background reading, not Exchange-Q operational instructions or empirical evidence.
Their catalog and scope notes are in [BACKGROUND_MATERIAL.md](BACKGROUND_MATERIAL.md).
