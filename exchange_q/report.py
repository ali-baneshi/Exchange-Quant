from __future__ import annotations

import json
from typing import Any

from exchange_q.analysis import (
    paired_block_bootstrap_test,
    paired_hac_test,
    score_baselines,
    score_rows,
)
from exchange_q.domain import SCOREABLE_STATUSES, ForecastStatus
from exchange_q.store import V7Store

_HTX_PROVIDER = "htx-ws"
_SEQUENCED_HINT = "kucoin-sequenced"


def build_analysis_document(store: V7Store, run_id: str) -> dict[str, Any]:
    status = store.status(run_id)
    counts = status["forecast_counts"]
    exclusions: dict[str, int] = {}
    for row in store.connection.execute(
        "SELECT exclusion_json FROM forecast_slots WHERE run_id=?",
        (run_id,),
    ):
        for reason in json.loads(row["exclusion_json"]):
            exclusions[reason] = exclusions.get(reason, 0) + 1
    summary = _slot_summary(counts)
    manifest = status["manifest"]
    document: dict[str, Any] = {
        "run_id": run_id,
        "schema_version": store.schema_version,
        "status": status["status"],
        "integrity": status["integrity"],
        "evidence": status.get("evidence", {}),
        "slot_counts": counts,
        "slot_summary": summary,
        "exclusions": exclusions,
        "analysis_available": False,
        "mode": manifest.get("mode", "diagnostic"),
        "provider": manifest.get("provider"),
        "primary_comparator": manifest.get("primary_comparator", "regularized_logistic_v1"),
        "symbol": manifest.get("symbol"),
    }
    try:
        rows = store.eligible_rows(run_id)
    except ValueError as exc:
        document["reason"] = str(exc)
        return document
    if not rows:
        document["reason"] = "no scoreable labels"
        return document
    calibration_statuses = {
        row["forecast"].get("diagnostics", {}).get("calibration_status", "unknown") for row in rows
    }
    calibration_status = (
        next(iter(calibration_statuses)) if len(calibration_statuses) == 1 else "mixed"
    )
    report = score_rows(rows)
    baselines = score_baselines(rows)
    document.update(
        {
            "analysis_available": True,
            "calibration_status": calibration_status,
            "calibration_available": calibration_status == "fitted",
            "model": report.__dict__,
            "baselines": {name: baseline.__dict__ for name, baseline in baselines.items()},
        }
    )
    if len(rows) >= 3 and baselines:
        baseline_name = document["primary_comparator"]
        if baseline_name not in baselines:
            document["reason"] = f"primary comparator is unavailable: {baseline_name}"
            return document
        import numpy as np
        from scipy.special import xlogy

        def _losses(probabilities):
            buy_counts = np.array([row["label"]["buy_count"] for row in rows], dtype=float)
            total_counts = np.array([row["label"]["trade_count"] for row in rows], dtype=float)
            return (
                -(
                    xlogy(buy_counts, probabilities)
                    + xlogy(total_counts - buy_counts, 1.0 - probabilities)
                )
                / total_counts
            )

        model_probs = np.array([row["forecast"]["probability_buy"] for row in rows], dtype=float)
        baseline_probs = np.array(
            [
                row["forecast"]["diagnostics"]["baseline_probabilities"][baseline_name]
                for row in rows
            ],
            dtype=float,
        )
        baseline_losses = _losses(baseline_probs).tolist()
        model_losses = _losses(model_probs).tolist()
        default_lags = max(1, int(len(rows) ** (1 / 3)))
        sensitivity_lags = sorted({1, default_lags, min(2 * default_lags, len(rows) - 1)})
        document["paired_inference"] = {
            "baseline": baseline_name,
            "hac": paired_hac_test(baseline_losses, model_losses),
            "block_bootstrap": paired_block_bootstrap_test(baseline_losses, model_losses),
            "lag_sensitivity": [
                {
                    "max_lags": lags,
                    "one_sided_p_value": paired_hac_test(
                        baseline_losses, model_losses, max_lags=lags
                    )["one_sided_p_value"],
                }
                for lags in sensitivity_lags
            ],
        }
    else:
        document["paired_inference"] = {
            "available": False,
            "reason": "requires at least three scoreable labels",
        }
    return document


def report_document_from_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Build a lightweight analysis-shaped document from a monitor snapshot."""
    manifest = snapshot.get("manifest") or {}
    tally = snapshot.get("slot_tally") or {}
    progress = snapshot.get("eligible_progress") or {}
    forecast_counts = snapshot.get("forecast_counts") or {}
    scoreable = int(progress.get("eligible", tally.get("scoreable", 0) or 0))
    total = int(sum(forecast_counts.values()) if forecast_counts else 0)
    if total == 0:
        total = sum(
            int(tally.get(key, 0) or 0)
            for key in ("awaiting", "scoreable", "unscoreable", "skipped", "cancelled", "failed")
        )
    exclusions = dict(snapshot.get("exclusion_counts") or {})
    document: dict[str, Any] = {
        "run_id": snapshot["run_id"],
        "status": snapshot["status"],
        "integrity": snapshot.get("integrity") or {},
        "evidence": snapshot.get("evidence") or {},
        "slot_counts": forecast_counts,
        "slot_summary": {
            "total": total,
            "scoreable": scoreable,
            "unscoreable": int(tally.get("unscoreable", 0) or 0),
            "skipped": int(tally.get("skipped", 0) or 0),
            "cancelled": int(tally.get("cancelled", 0) or 0),
            "failed": int(tally.get("failed", 0) or 0),
        },
        "exclusions": exclusions,
        "analysis_available": False,
        "mode": manifest.get("mode", "diagnostic"),
        "provider": manifest.get("provider"),
        "primary_comparator": manifest.get("primary_comparator", "regularized_logistic_v1"),
        "symbol": manifest.get("symbol"),
    }
    if scoreable == 0:
        document["reason"] = "no scoreable labels"
    return document


def format_research_report(
    document: dict[str, Any],
    *,
    database: str | None = None,
) -> str:
    mode = document.get("mode") or (document.get("evidence") or {}).get("evidence_status") or "-"
    provider = document.get("provider") or "-"
    summary = document.get("slot_summary") or {}
    scoreable = int(summary.get("scoreable", 0) or 0)
    total = int(summary.get("total", 0) or 0)
    lines: list[str] = []

    if document.get("analysis_available") and document.get("model"):
        model = document["model"]
        n = int(model.get("n", scoreable) or scoreable)
        lines.append(f"VERDICT: COMPARATIVE EVIDENCE AVAILABLE (n={n})")
        lines.append(f"  mode={mode} provider={provider} scoreable={scoreable}/{total or scoreable}")
        lines.append(
            "  model (Born)"
            f" NLL={_fmt(model.get('negative_log_likelihood'))}"
            f"  Brier={_fmt(model.get('brier'))}"
            f"  MAE={_fmt(model.get('mae'))}"
        )
        baselines = document.get("baselines") or {}
        model_nll = model.get("negative_log_likelihood")
        if baselines:
            lines.append("  baselines:")
            for name, baseline in sorted(baselines.items()):
                delta = None
                if model_nll is not None and baseline.get("negative_log_likelihood") is not None:
                    delta = float(model_nll) - float(baseline["negative_log_likelihood"])
                delta_text = f"  ΔNLL={_fmt(delta)}" if delta is not None else ""
                lines.append(
                    f"    {name}"
                    f"  NLL={_fmt(baseline.get('negative_log_likelihood'))}"
                    f"  Brier={_fmt(baseline.get('brier'))}"
                    f"{delta_text}"
                )
        inference = document.get("paired_inference") or {}
        if inference.get("hac"):
            hac = inference["hac"]
            bootstrap = inference.get("block_bootstrap") or {}
            comparator = inference.get("baseline") or document.get("primary_comparator")
            lines.append(f"  paired vs primary_comparator ({comparator}):")
            lines.append(
                f"    HAC one-sided p={_fmt(hac.get('one_sided_p_value'))}"
                f"  mean_Δ={_fmt(hac.get('mean_loss_difference'))}"
            )
            if bootstrap:
                lines.append(
                    f"    block bootstrap p={_fmt(bootstrap.get('one_sided_p_value'))}"
                    f"  block_length={bootstrap.get('block_length')}"
                )
        elif inference.get("available") is False:
            lines.append(f"  paired inference: unavailable ({inference.get('reason', '-')})")
        if document.get("calibration_status"):
            lines.append(
                f"  calibration: {document.get('calibration_status')}"
                f" (available={document.get('calibration_available')})"
            )
        return "\n".join(lines)

    lines.append("VERDICT: NO COMPARATIVE EVIDENCE")
    lines.append(f"  mode={mode} provider={provider} scoreable={scoreable}/{total}")
    for why_line in _blocked_why_lines(document):
        lines.append(f"  {why_line}")
    lines.append("  Born vs classical: NOT COMPUTED (fail-closed)")
    lines.append("  next:")
    for index, step in enumerate(_next_steps(document, database=database), start=1):
        lines.append(f"    {index}) {step}")
    return "\n".join(lines)


def _blocked_why_lines(document: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    provider = document.get("provider")
    reason = document.get("reason")
    exclusions = document.get("exclusions") or {}
    if provider == _HTX_PROVIDER:
        lines.append("why: HTX cannot certify capture continuity")
    elif reason:
        lines.append(f"why: {reason}")
    else:
        lines.append("why: no scoreable labels for comparative scoring")
    if exclusions:
        top = sorted(exclusions.items(), key=lambda item: (-item[1], item[0]))[:4]
        detail = ", ".join(f"{name}={count}" for name, count in top)
        lines.append(f"     exclusions: {detail}")
    evidence = document.get("evidence") or {}
    if evidence.get("capture_quality") == "uncertified":
        lines.append("     capture_quality=uncertified (not a primary record)")
    return lines


def _next_steps(document: dict[str, Any], *, database: str | None) -> list[str]:
    provider = document.get("provider")
    steps = [
        f"capture with {_SEQUENCED_HINT} (diagnostic profile, provider override)",
        "dataset build → fit --purpose primary",
        "provider-certify → run --profile primary --study studies/btcusdt-primary.json",
        # Report must target the *new* primary run DB/ID from the dashboard —
        # re-running report on this diagnostic DB always yields NO EVIDENCE.
        "exchange-q report --database <primary-run.sqlite3> --run-id <primary-run-id>",
    ]
    if provider == _HTX_PROVIDER:
        steps[0] = (
            f"capture with {_SEQUENCED_HINT} "
            "(HTX diagnostic runs cannot produce comparative evidence)"
        )
    return steps


def _slot_summary(counts: dict[str, int]) -> dict[str, int]:
    scoreable = sum(counts.get(status.value, 0) for status in SCOREABLE_STATUSES)
    unscoreable = counts.get(ForecastStatus.RESOLVED_UNSCOREABLE.value, 0) + counts.get(
        ForecastStatus.RESOLVED_INELIGIBLE.value, 0
    )
    return {
        "total": sum(counts.values()),
        "scoreable": scoreable,
        "unscoreable": unscoreable,
        "skipped": counts.get(ForecastStatus.SKIPPED.value, 0),
        "cancelled": counts.get(ForecastStatus.CANCELLED.value, 0),
        "failed": counts.get(ForecastStatus.FAILED.value, 0),
    }


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)
