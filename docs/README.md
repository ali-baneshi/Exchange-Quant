# Exchange-Q Documentation Index

**English** | [فارسی](./fa/README.md) | [README.fa.md](../README.fa.md)

Central map for all project documentation. Start with the path that matches your goal.

---

## Start here

| I want to… | Read first |
|------------|------------|
| Run the project for the first time | [WORKFLOW.md](../WORKFLOW.md) |
| Start or monitor a live Born-rule run | [RUNBOOK.md](./RUNBOOK.md) |
| Understand system design | [ARCHITECTURE.md](../ARCHITECTURE.md) |
| Interpret JSON output / fallbacks | [SCHEMA_V5.md](./SCHEMA_V5.md) |
| Understand p-values and claim thresholds | [STATISTICS.md](./STATISTICS.md) |
| Contribute or review code | [CONTRIBUTING.md](../CONTRIBUTING.md) |
| Read in Persian | [docs/fa/](./fa/) |
| Know if Born rule actually works | [verification_report.md](../verification_report.md) |

---

## Operational (English)

| Document | Purpose |
|----------|---------|
| [../README.md](../README.md) | Project entry, quick start, structure |
| [../ARCHITECTURE.md](../ARCHITECTURE.md) | Data flow, Born rule, pipelines, stats framework |
| [../WORKFLOW.md](../WORKFLOW.md) | Step-by-step entry-to-exit workflow |
| [RUNBOOK.md](./RUNBOOK.md) | Live pipeline ops, monitoring, troubleshooting |
| [SCHEMA_V5.md](./SCHEMA_V5.md) | Schema v5 JSON field reference |
| [STATISTICS.md](./STATISTICS.md) | Bootstrap, Bonferroni, claim thresholds |
| [../CONTRIBUTING.md](../CONTRIBUTING.md) | Tests, review checklist |

### Scripts

| Script | Purpose |
|--------|---------|
| [../scripts/start_production_run.sh](../scripts/start_production_run.sh) | Run tests, start production v5 quantum pipeline |
| [../scripts/monitor_live.sh](../scripts/monitor_live.sh) | Tail logs, show newest v5 JSON stats |
| [../scripts/archive_legacy_results.sh](../scripts/archive_legacy_results.sh) | Move non-v5 JSON to archive |

---

## Evidence and verdict

| Document | Purpose | Language |
|----------|---------|----------|
| [../verification_report.md](../verification_report.md) | Honest empirical verdict | EN |
| [../core/research_05_results.md](../core/research_05_results.md) | Archived validation numbers (kline era deprecated) | EN + FA |

---

## Research theory (Persian)

Motivation and quantum-cognition framing — not operational runbooks.

| Document | Topic |
|----------|-------|
| [../core/research_INDEX.md](../core/research_INDEX.md) | **Index:** maps research docs → code |
| [../core/research_01_problem.md](../core/research_01_problem.md) | Intent Trilemma |
| [../core/research_02_nature.md](../core/research_02_nature.md) | Nature-inspired quantum mechanisms |
| [../core/research_03_paradoxes.md](../core/research_03_paradoxes.md) | Allais, Ellsberg, disjunction effect |
| [../core/research_04_architecture.md](../core/research_04_architecture.md) | ICDS vision (implementation differs) |
| [../core/research_05_results.md](../core/research_05_results.md) | Results archive |

---

## Persian documentation

| Document | Purpose |
|----------|---------|
| [../README.fa.md](../README.fa.md) | Executive summary + quick commands |
| [fa/README.md](./fa/README.md) | Persian doc index |
| [fa/QUICKSTART.md](./fa/QUICKSTART.md) | Operational quick start |
| [fa/GLOSSARY.md](./fa/GLOSSARY.md) | Key terms (Born rule, δ, schema v5) |

---

## Background reading (not Exchange-Q ops)

General education — **do not use as runbooks** for this repo.

| Document | Note |
|----------|------|
| [../quantum_inspired_programming.md](../quantum_inspired_programming.md) | General quantum-inspired programming |
| [../quantum_ai_lessons.md](../quantum_ai_lessons.md) | Quantum AI lessons |
| [../ai_research_study_guide_fa.md](../ai_research_study_guide_fa.md) | PHCA / FEP study guide — different project |
| [../درسنامه_ پیاده_سازی مدل_های شناخت و تصمیم_گیری کوانتومی (Quantum Cognition).md](../درسنامه_%20پیاده_سازی%20مدل_های%20شناخت%20و%20تصمیم_گیری%20کوانتومی%20(Quantum%20Cognition).md) | Persian quantum cognition lesson |
| [../درسنامه_ برنامه_نویسی با منطق کوانتومی در دنیای کلاسیک؛ چالش_ها، محدودیت_ها و واقعیت_ها.md](../درسنامه_%20برنامه_نویسی%20با%20منطق%20کوانتومی%20در%20دنیای%20کلاسیک؛%20چالش_ها،%20محدودیت_ها%20و%20واقعیت_ها.md) | Persian programming lesson |

---

## Historical audit (stale)

Forensic snapshot from **2026-07-20**. API surface and conclusions may be outdated.

| Document | Purpose |
|----------|---------|
| [../code_audit_v1/STALE.md](../code_audit_v1/STALE.md) | Read this first |
| [../code_audit_v1/audit_notes_v1.md](../code_audit_v1/audit_notes_v1.md) | Module inventory |
| [../code_audit_v1/critical_issues_pass1.md](../code_audit_v1/critical_issues_pass1.md) | Pass 1 issues |
| [../code_audit_v1/empirical_gaps_pass2.md](../code_audit_v1/empirical_gaps_pass2.md) | Statistical gaps |
| [../code_audit_v1/reproducibility_pass3.md](../code_audit_v1/reproducibility_pass3.md) | Reproducibility |
| [../code_audit_v1/FINAL_HARDENING_PLAN.md](../code_audit_v1/FINAL_HARDENING_PLAN.md) | Hardening plan (mostly done) |

---

## Key decisions (quick reference)

- **2026-07-23:** Born rule removed from kline evaluation (requires real order-book imbalance).
- **2026-07-26:** Schema v5 requires locally captured forward-window labels for primary live scoring.
- **Canonical live path:** `pipeline_live_ensemble.py` → schema v5 JSON → `analyze_live_results.py --schema-version 5`.
