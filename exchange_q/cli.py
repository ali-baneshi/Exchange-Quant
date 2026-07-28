from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import signal
import sqlite3
import sys
import time
import uuid
from dataclasses import dataclass, replace

from exchange_q.analysis import paired_hac_test, required_sample_size, score_baselines, score_rows
from exchange_q.artifacts import load_artifact, save_artifact
from exchange_q.certification import run_fault_certification, run_replay_certification
from exchange_q.domain import FeatureWindow, ForecastStatus, RunManifest, SCOREABLE_STATUSES
from exchange_q.models import NormalizedBornModel
from exchange_q.monitor import RunConsole
from exchange_q.providers.binance_ws import BinanceSequencedProvider
from exchange_q.providers.htx_ws import HtxWebSocketProvider
from exchange_q.runner import LiveRunner
from exchange_q.store import V7Store


@dataclass(frozen=True)
class RunProfile:
    artifact: str
    symbol: str
    provider: str
    horizon_s: int
    lookback_s: int
    cadence_s: int
    minimum_label_trades: int
    target_eligible: int
    max_terminal_slots: int
    mode: str = "diagnostic"
    capture_policy: str = "uncertified_stream_v1"
    decision_lead_s: int = 0
    settlement_delay_s: int = 0


DIAGNOSTIC_PROFILE = RunProfile(
    artifact="artifacts/v8/diagnostic-born.json",
    symbol="btcusdt",
    provider="htx-ws",
    horizon_s=60,
    lookback_s=300,
    cadence_s=60,
    minimum_label_trades=30,
    target_eligible=1,
    max_terminal_slots=10,
)
PRIMARY_PROFILE = RunProfile(
    artifact="",
    symbol="btcusdt",
    provider="binance-sequenced",
    horizon_s=60,
    lookback_s=300,
    cadence_s=60,
    minimum_label_trades=30,
    target_eligible=0,
    max_terminal_slots=0,
    mode="primary",
    capture_policy="binance_trade_depth_sequenced_v1",
    decision_lead_s=5,
    settlement_delay_s=5,
)
DIAGNOSTIC_DATASET = "tests/fixtures/development-minimal.json"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="exchange-q")
    subparsers = parser.add_subparsers(dest="command", required=True)

    fit = subparsers.add_parser("fit", help="fit a frozen normalized Born artifact")
    fit.add_argument("dataset", help="JSON list with feature, buy_count, total_count")
    fit.add_argument("--output", required=True)
    fit.add_argument(
        "--purpose",
        choices=("diagnostic_fixture", "primary"),
        default="diagnostic_fixture",
    )

    run = subparsers.add_parser("run", help="run the schema-v7 live evaluator")
    run.add_argument("--profile", choices=("diagnostic", "primary"), required=True)
    run.add_argument("--study", help="frozen primary study manifest")
    run.add_argument("--database")
    run.add_argument("--artifact")
    run.add_argument("--run-id", default=None)
    run.add_argument(
        "--resume",
        action="store_true",
        help="resume an existing run ID; otherwise existing IDs are rejected",
    )
    run.add_argument("--symbol")
    run.add_argument("--provider", choices=("htx-ws", "binance-sequenced"))
    run.add_argument("--horizon-s", type=int)
    run.add_argument("--lookback-s", type=int)
    run.add_argument("--cadence-s", type=int)
    run.add_argument("--minimum-label-trades", type=int)
    run.add_argument("--target-eligible", type=int)
    run.add_argument(
        "--max-terminal-slots",
        type=int,
        help="Bound diagnostic runs even when the provider cannot certify labels",
    )
    run.add_argument(
        "--display",
        choices=("auto", "dashboard", "log"),
        default="auto",
    )
    run.add_argument("--refresh-s", type=float, default=2.0)
    run.add_argument("--view", choices=("outcome", "detail"), default="outcome")

    status = subparsers.add_parser("status", help="show authoritative run status")
    status.add_argument("--database", required=True)
    status.add_argument("--run-id", required=True)
    status.add_argument("--json", action="store_true")

    analyze = subparsers.add_parser("analyze", help="score eligible v7 forecasts")
    analyze.add_argument("--database", required=True)
    analyze.add_argument("--run-id", required=True)

    stop = subparsers.add_parser("stop", help="stop the repository-owned run writer")
    stop.add_argument("--database", required=True)
    stop.add_argument("--run-id", required=True)
    stop.add_argument("--timeout-s", type=float, default=10.0)

    export = subparsers.add_parser("export", help="write a consistent v7 JSON snapshot")
    export.add_argument("--database", required=True)
    export.add_argument("--run-id", required=True)
    export.add_argument("--output", required=True)

    power = subparsers.add_parser("power", help="calculate a fixed sample target")
    power.add_argument("--mean-difference", type=float, required=True)
    power.add_argument("--standard-deviation", type=float, required=True)
    power.add_argument("--autocorrelation", type=float, required=True)
    power.add_argument("--alpha", type=float, default=0.05)
    power.add_argument("--power", type=float, default=0.8)

    doctor = subparsers.add_parser("doctor", help="validate a run profile preflight")
    doctor.add_argument("--profile", choices=("diagnostic", "primary"), required=True)
    doctor.add_argument("--study")

    certification = subparsers.add_parser(
        "provider-certify",
        help="run a bounded provider continuity certification soak",
    )
    certification.add_argument(
        "--provider",
        choices=("binance-sequenced",),
        required=True,
    )
    certification.add_argument("--symbol", default="btcusdt")
    certification.add_argument("--duration-s", type=float, default=60.0)
    certification.add_argument("--output", required=True)

    dataset = subparsers.add_parser(
        "dataset",
        help="build a development dataset from a certified capture database",
    )
    dataset.add_argument("action", choices=("build",))
    dataset.add_argument("--capture-database", required=True)
    dataset.add_argument("--provider", default="binance-sequenced")
    dataset.add_argument("--symbol", default="btcusdt")
    dataset.add_argument("--lookback-s", type=int, default=300)
    dataset.add_argument("--horizon-s", type=int, default=60)
    dataset.add_argument("--cadence-s", type=int, default=60)
    dataset.add_argument("--output", required=True)
    return parser


def main(argv=None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    for argument in ("database", "artifact", "run_id", "output"):
        value = getattr(args, argument, None)
        if value is not None and not str(value).strip():
            parser.error(f"--{argument.replace('_', '-')} must not be empty")
    if args.command == "fit":
        artifact, row_count = _fit_artifact(
            args.dataset,
            args.output,
            purpose=getattr(args, "purpose", "diagnostic_fixture"),
        )
        print(json.dumps({"artifact_hash": artifact.artifact_hash, "rows": row_count}))
        return 0

    if args.command == "power":
        print(
            required_sample_size(
                args.mean_difference,
                args.standard_deviation,
                args.autocorrelation,
                args.alpha,
                args.power,
            )
        )
        return 0
    if args.command == "doctor":
        return _doctor(parser, args)
    if args.command == "provider-certify":
        return asyncio.run(_certify_provider(parser, args))
    if args.command == "dataset":
        return _build_dataset(parser, args)

    if args.command != "run" and not os.path.isfile(args.database):
        parser.error(f"database does not exist: {args.database}")
    if args.command == "run":
        _run_command(parser, args)
        return 0
    store = V7Store(args.database)
    try:
        if args.command == "status":
            document = store.status(args.run_id)
            if args.json:
                print(json.dumps(document, indent=2, sort_keys=True))
            else:
                print(_format_status(document, store.schema_version))
            return 0
        if args.command == "analyze":
            print(json.dumps(_analysis_document(store, args.run_id), indent=2, sort_keys=True))
            return 0
        if args.command == "export":
            document = store.export_run(args.run_id)
            temporary = args.output + ".tmp"
            with open(temporary, "w", encoding="utf-8") as handle:
                json.dump(document, handle, indent=2, sort_keys=True)
            os.replace(temporary, args.output)
            return 0
        if args.command == "stop":
            return _stop_run(store, args.run_id, args.timeout_s)
    finally:
        store.close()
    return 2


def _run_command(parser: argparse.ArgumentParser, args) -> None:
    study = _load_study(parser, args.study) if args.profile == "primary" else {}
    profile = PRIMARY_PROFILE if args.profile == "primary" else DIAGNOSTIC_PROFILE
    if args.refresh_s <= 0:
        parser.error("--refresh-s must be positive")
    if args.resume and (not args.database or not args.run_id or not args.artifact):
        parser.error("--resume requires explicit --database, --run-id, and --artifact")
    if args.profile == "primary" and not args.study:
        parser.error("--profile primary requires --study")
    run_id = args.run_id or study.get("run_id") or (
        f"{profile.symbol}-{profile.mode}-{time.strftime('%Y%m%d-%H%M%S')}-"
        f"{uuid.uuid4().hex[:8]}"
    )
    database = args.database or study.get("database") or f"runs/{run_id}.sqlite3"
    artifact_path = args.artifact or study.get("artifact") or profile.artifact
    if not artifact_path:
        parser.error("primary study must define an artifact")
    if not os.path.isfile(artifact_path):
        if args.artifact:
            parser.error(f"artifact does not exist: {artifact_path}")
        _fit_artifact(
            DIAGNOSTIC_DATASET,
            artifact_path,
            purpose="diagnostic_fixture",
        )
        print(
            f"[exchange-q] created diagnostic-only artifact: {artifact_path}",
            flush=True,
        )
    artifact = load_artifact(artifact_path)
    if args.profile == "primary":
        if artifact.purpose != "primary":
            parser.error("primary runs reject diagnostic or unproven artifacts")
        _validate_certification(parser, study, profile)
    manifest = RunManifest(
        run_id=run_id,
        symbol=args.symbol or study.get("symbol") or profile.symbol,
        provider=args.provider or study.get("provider") or profile.provider,
        model_artifact_hash=artifact.artifact_hash,
        feature_policy="causal_trade_book_v1",
        label_policy="half_open_streamed_trades_v1",
        primary_metric="per_trade_negative_log_likelihood",
        horizon_ms=_value_or_default(args.horizon_s, profile.horizon_s) * 1000,
        lookback_ms=_value_or_default(args.lookback_s, profile.lookback_s) * 1000,
        cadence_ms=_value_or_default(args.cadence_s, profile.cadence_s) * 1000,
        minimum_label_trades=(
            _value_or_default(
                args.minimum_label_trades,
                profile.minimum_label_trades,
            )
        ),
        target_eligible=_value_or_default(
            args.target_eligible,
            profile.target_eligible,
        ),
        terminal_slot_limit=(
            _optional_positive(
                args.max_terminal_slots,
                study.get("max_terminal_slots"),
                profile.max_terminal_slots,
            )
        ),
        mode=profile.mode,
        capture_policy=profile.capture_policy,
        clock_policy="exchange_clock_watermark_v1",
        eligibility_policy="certified_continuity_v1",
        decision_lead_ms=profile.decision_lead_s * 1000,
        settlement_delay_ms=profile.settlement_delay_s * 1000,
        artifact_purpose=artifact.purpose,
        book_depth_levels=1000,
    )
    store = V7Store(database)
    try:
        if store.legacy_read_only:
            parser.error("schema-v7 runs are read-only and cannot be resumed")
        try:
            store.create_run(manifest)
        except sqlite3.IntegrityError:
            existing = store.status(run_id)
            if existing["manifest"] != manifest.to_record():
                parser.error(
                    f"run ID exists with an incompatible manifest: {run_id}"
                )
            if not args.resume:
                parser.error(
                    f"run ID already exists: {run_id}\n"
                    "Use a new --run-id or add --resume intentionally."
                )
        provider = (
            BinanceSequencedProvider()
            if (args.provider or study.get("provider") or profile.provider)
            == "binance-sequenced"
            else HtxWebSocketProvider()
        )
        runner = LiveRunner(store, provider, manifest, artifact)
        console = RunConsole(
            store,
            run_id,
            provider=provider,
            database_path=database,
            artifact_path=artifact_path,
            display=args.display,
            refresh_s=args.refresh_s,
            view=args.view,
        )
        asyncio.run(_run_foreground(runner, console))
    finally:
        store.close()


async def _run_foreground(runner: LiveRunner, console: RunConsole) -> None:
    runner_task = asyncio.create_task(runner.run())
    console_task = asyncio.create_task(console.watch(runner_task))
    done, _ = await asyncio.wait(
        (runner_task, console_task),
        return_when=asyncio.FIRST_COMPLETED,
    )
    if console_task in done and not runner_task.done():
        runner.stop()
        await runner_task
    if runner_task in done:
        await console_task
    runner_task.result()
    console_task.result()


def _fit_artifact(
    dataset: str,
    output: str,
    *,
    purpose: str = "diagnostic_fixture",
):
    with open(dataset, encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, dict) and "rows" in payload:
        rows = payload["rows"]
        dataset_hash = payload.get("dataset_hash") or hashlib.sha256(
            json.dumps(rows, sort_keys=True).encode()
        ).hexdigest()
    else:
        rows = payload
        with open(dataset, "rb") as handle:
            dataset_hash = hashlib.sha256(handle.read()).hexdigest()
    if purpose == "primary" and len(rows) < 10:
        raise ValueError("primary artifacts require a larger certified development dataset")
    features = [FeatureWindow(**row["feature"]) for row in rows]
    model = NormalizedBornModel()
    artifact = model.fit(
        features,
        [int(row["buy_count"]) for row in rows],
        [int(row["total_count"]) for row in rows],
        purpose=purpose,
        dataset_hash=dataset_hash,
    )
    if purpose == "primary":
        split_index = max(1, int(len(rows) * 0.8))
        artifact = replace(
            artifact,
            calibration_rows=len(rows) - split_index,
            calibration_status="uncalibrated",
        )
    save_artifact(output, artifact)
    return artifact, len(rows)


def _value_or_default(value, default):
    return default if value is None else value


def _optional_positive(*values):
    for value in values:
        if value is not None and int(value) > 0:
            return int(value)
    return None


def _load_study(parser, path):
    if not path or not os.path.isfile(path):
        parser.error(f"study manifest does not exist: {path or '-'}")
    with open(path, encoding="utf-8") as handle:
        document = json.load(handle)
    required = ("artifact", "provider_certification", "target_eligible")
    missing = [name for name in required if not document.get(name)]
    if missing:
        parser.error(f"study manifest missing: {', '.join(missing)}")
    return document


def _validate_certification(parser, study, profile):
    path = study["provider_certification"]
    if not os.path.isfile(path):
        parser.error(f"provider certification does not exist: {path}")
    with open(path, encoding="utf-8") as handle:
        certification = json.load(handle)
    if not certification.get("valid"):
        parser.error("provider certification is not valid")
    if certification.get("provider") != profile.provider:
        parser.error("provider certification does not match the primary provider")
    for section in ("replay_results", "fault_results", "live_soak"):
        if section not in certification:
            parser.error(f"provider certification missing section: {section}")


def _doctor(parser, args) -> int:
    if args.profile == "diagnostic":
        checks = {
            "profile": "diagnostic",
            "artifact": DIAGNOSTIC_PROFILE.artifact,
            "artifact_exists": os.path.isfile(DIAGNOSTIC_PROFILE.artifact),
            "provider": DIAGNOSTIC_PROFILE.provider,
            "primary_evidence": False,
            "ready": True,
        }
    else:
        study = _load_study(parser, args.study)
        artifact_path = study["artifact"]
        certification_path = study["provider_certification"]
        checks = {
            "profile": "primary",
            "artifact": artifact_path,
            "artifact_exists": os.path.isfile(artifact_path),
            "certification": certification_path,
            "certification_exists": os.path.isfile(certification_path),
            "target_eligible": study["target_eligible"],
        }
        checks["ready"] = all(
            (
                checks["artifact_exists"],
                checks["certification_exists"],
                int(checks["target_eligible"]) > 0,
            )
        )
        if checks["artifact_exists"]:
            checks["artifact_purpose"] = load_artifact(artifact_path).purpose
            checks["ready"] = checks["ready"] and checks["artifact_purpose"] == "primary"
    print(json.dumps(checks, indent=2, sort_keys=True))
    return 0 if checks["ready"] else 2


async def _certify_provider(parser, args) -> int:
    if args.duration_s <= 0:
        parser.error("--duration-s must be positive")
    replay_results = await run_replay_certification()
    fault_results = await run_fault_certification()
    provider = BinanceSequencedProvider()
    counts = {"trades": 0, "books": 0}

    async def collect():
        async for event in provider.events(args.symbol):
            if event.__class__.__name__ == "TradeEvent":
                counts["trades"] += 1
            else:
                counts["books"] += 1

    task = asyncio.create_task(collect())
    try:
        await asyncio.sleep(args.duration_s)
    finally:
        await provider.close()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    health = provider.health()
    live_soak = {
        "duration_s": args.duration_s,
        "counts": counts,
        "health": health.__dict__,
        "passed": (
            counts["trades"] > 0
            and counts["books"] > 0
            and health.unresolved_gaps == 0
            and health.clock_uncertainty_ms is not None
            and health.clock_uncertainty_ms <= 500
        ),
    }
    report = {
        "certification_id": f"{provider.name}-{args.symbol.lower()}-{int(time.time())}",
        "provider": provider.name,
        "symbol": args.symbol.lower(),
        "adapter_revision": provider.adapter_revision,
        "issued_at_ms": int(time.time() * 1000),
        "replay_results": replay_results,
        "fault_results": fault_results,
        "live_soak": live_soak,
        "unresolved_gaps": health.unresolved_gaps,
        "clock_uncertainty_ms": health.clock_uncertainty_ms,
        "valid": (
            replay_results["passed"]
            and fault_results["passed"]
            and live_soak["passed"]
        ),
    }
    temporary = args.output + ".tmp"
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
    os.replace(temporary, args.output)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["valid"] else 2


def _build_dataset(parser, args) -> int:
    for name in ("lookback_s", "horizon_s", "cadence_s"):
        if getattr(args, name) <= 0:
            parser.error(f"--{name.replace('_', '-')} must be positive")
    store = V7Store(args.capture_database)
    try:
        if store.schema_version < 8:
            parser.error("dataset build requires a schema-v8 capture database")
        if store.unresolved_gap_count(args.provider, args.symbol.lower()) > 0:
            parser.error("capture database contains unresolved continuity gaps")
        bounds = store.connection.execute(
            """
            SELECT MIN(exchange_time_ms), MAX(exchange_time_ms)
            FROM trades WHERE provider=? AND symbol=?
            """,
            (args.provider, args.symbol.lower()),
        ).fetchone()
        if not bounds or bounds[0] is None:
            parser.error("capture database contains no matching trades")
        cadence_ms = args.cadence_s * 1000
        start = ((int(bounds[0]) + cadence_ms - 1) // cadence_ms) * cadence_ms
        end = int(bounds[1])
        rows = []
        for target_start in range(start + args.lookback_s * 1000, end, cadence_ms):
            target_end = target_start + args.horizon_s * 1000
            if target_end > end:
                break
            features = store.build_features(
                args.provider,
                args.symbol.lower(),
                target_start - args.lookback_s * 1000,
                target_start,
            )
            label = store.build_label(
                args.provider,
                args.symbol.lower(),
                target_start,
                target_end,
            )
            if features is None or not label.coverage_complete or label.trade_count == 0:
                continue
            rows.append(
                {
                    "feature": features.to_record(),
                    "buy_count": label.buy_count,
                    "total_count": label.trade_count,
                }
            )
        if not rows:
            parser.error("no certified development rows could be constructed")
        split_index = max(1, int(len(rows) * 0.8))
        development_rows = rows[:split_index]
        calibration_rows = rows[split_index:]
        payload = {
            "dataset_hash": hashlib.sha256(
                json.dumps(rows, sort_keys=True).encode()
            ).hexdigest(),
            "development_start_ms": development_rows[0]["feature"]["start_ms"],
            "development_end_ms": development_rows[-1]["feature"]["end_ms"],
            "calibration_start_ms": (
                calibration_rows[0]["feature"]["start_ms"] if calibration_rows else None
            ),
            "calibration_end_ms": (
                calibration_rows[-1]["feature"]["end_ms"] if calibration_rows else None
            ),
            "rows": rows,
        }
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        temporary = args.output + ".tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
        os.replace(temporary, args.output)
        print(
            json.dumps(
                {
                    "rows": len(rows),
                    "development_rows": len(development_rows),
                    "calibration_rows": len(calibration_rows),
                    "output": args.output,
                }
            )
        )
        return 0
    finally:
        store.close()


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


def _analysis_document(store: V7Store, run_id: str) -> dict:
    status = store.status(run_id)
    counts = status["forecast_counts"]
    exclusions = {}
    for row in store.connection.execute(
        "SELECT exclusion_json FROM forecast_slots WHERE run_id=?",
        (run_id,),
    ):
        for reason in json.loads(row["exclusion_json"]):
            exclusions[reason] = exclusions.get(reason, 0) + 1
    summary = _slot_summary(counts)
    document = {
        "run_id": run_id,
        "schema_version": store.schema_version,
        "status": status["status"],
        "integrity": status["integrity"],
        "evidence": status.get("evidence", {}),
        "slot_counts": counts,
        "slot_summary": summary,
        "exclusions": exclusions,
        "analysis_available": False,
    }
    try:
        rows = store.eligible_rows(run_id)
    except ValueError as exc:
        document["reason"] = str(exc)
        return document
    if not rows:
        document["reason"] = "no scoreable labels"
        return document
    calibration_status = "unknown"
    try:
        for path in ("artifacts/v8/diagnostic-born.json",):
            if os.path.isfile(path):
                calibration_status = load_artifact(path).calibration_status
                break
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass
    report = score_rows(rows)
    baselines = score_baselines(rows)
    document.update(
        {
            "analysis_available": True,
            "calibration_status": calibration_status,
            "calibration_available": calibration_status == "fitted",
            "model": report.__dict__,
            "baselines": {
                name: baseline.__dict__ for name, baseline in baselines.items()
            },
        }
    )
    if len(rows) >= 3 and baselines:
        baseline_name = sorted(baselines)[0]
        import numpy as np
        from scipy.special import xlogy

        def _losses(probabilities):
            buy_counts = np.array([row["label"]["buy_count"] for row in rows], dtype=float)
            total_counts = np.array(
                [row["label"]["trade_count"] for row in rows], dtype=float
            )
            return -(
                xlogy(buy_counts, probabilities)
                + xlogy(total_counts - buy_counts, 1.0 - probabilities)
            ) / total_counts

        model_probs = np.array(
            [row["forecast"]["probability_buy"] for row in rows], dtype=float
        )
        baseline_probs = np.array(
            [
                row["forecast"]["diagnostics"]["baseline_probabilities"][baseline_name]
                for row in rows
            ],
            dtype=float,
        )
        document["paired_inference"] = {
            "baseline": baseline_name,
            "hac": paired_hac_test(
                _losses(baseline_probs).tolist(),
                _losses(model_probs).tolist(),
            ),
        }
    else:
        document["paired_inference"] = {
            "available": False,
            "reason": "requires at least three scoreable labels",
        }
    return document


def _format_status(document: dict, schema_version: int) -> str:
    counts = document["forecast_counts"]
    evidence = document.get("evidence", {})
    lines = [
        f"Exchange-Q run {document['run_id']}",
        f"schema:     v{schema_version}",
        f"status:     {document['status']}",
        f"mode:       {document['manifest'].get('mode', 'legacy')}",
        f"provider:   {document['manifest']['provider']}",
        f"slots:      {json.dumps(counts, sort_keys=True)}",
        f"integrity:  {document['integrity']['state']}",
        f"capture:    {evidence.get('capture_quality', '-')}",
        f"evidence:   {evidence.get('evidence_status', '-')}",
        f"writer:     {'active' if document['lease'] else 'none'}",
    ]
    return "\n".join(lines)


def _stop_run(store: V7Store, run_id: str, timeout_s: float) -> int:
    if timeout_s <= 0:
        raise ValueError("stop timeout must be positive")
    status = store.status(run_id)
    lease = status.get("lease")
    if not lease:
        print("No active writer lease.")
        return 0
    pid = int(lease["pid"])
    owner_id = lease["owner_id"]
    _verify_repository_writer(pid)
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not _process_exists(pid):
            break
        time.sleep(0.1)
    else:
        _verify_repository_writer(pid)
        os.kill(pid, signal.SIGKILL)
        kill_deadline = time.monotonic() + 2.0
        while time.monotonic() < kill_deadline and _process_exists(pid):
            time.sleep(0.05)
        if _process_exists(pid):
            raise RuntimeError(f"writer process {pid} did not exit after SIGKILL")

    current = store.status(run_id)
    current_lease = current.get("lease")
    if current_lease and current_lease["owner_id"] == owner_id:
        store.release_lease(run_id, owner_id)
        store.set_run_status(run_id, "stopped_forcefully", "writer exited before cleanup")
    print(f"Writer {pid} stopped; no active lease remains.")
    return 0


def _verify_repository_writer(pid: int) -> None:
    repository_root = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))
    try:
        process_cwd = os.path.realpath(f"/proc/{pid}/cwd")
        with open(f"/proc/{pid}/cmdline", "rb") as handle:
            command_line = handle.read().replace(b"\0", b" ").decode(errors="replace")
    except OSError as exc:
        raise RuntimeError(f"cannot verify writer process {pid}: {exc}") from exc
    if process_cwd != repository_root or "exchange_q" not in command_line:
        raise RuntimeError("refusing to signal a process not owned by this repository")


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


if __name__ == "__main__":
    sys.exit(main())
