from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import signal
import sqlite3
import sys
import time
import uuid
from dataclasses import dataclass, replace

from exchange_q.analysis import (
    calibration_parameters,
    required_sample_size,
)
from exchange_q.artifacts import load_artifact, save_artifact
from exchange_q.certification import run_fault_certification, run_replay_certification
from exchange_q.domain import FeatureWindow, RunManifest
from exchange_q.models import NormalizedBornModel
from exchange_q.monitor import RunConsole
from exchange_q.providers.binance_ws import BinanceSequencedProvider
from exchange_q.providers.htx_ws import HtxWebSocketProvider
from exchange_q.providers.kucoin_ws import KucoinSequencedProvider
from exchange_q.report import build_analysis_document, format_research_report
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
    provider="kucoin-sequenced",
    horizon_s=60,
    lookback_s=300,
    cadence_s=60,
    minimum_label_trades=30,
    target_eligible=0,
    max_terminal_slots=0,
    mode="primary",
    capture_policy="kucoin_trade_depth_sequenced_v1",
    decision_lead_s=5,
    settlement_delay_s=5,
)
DIAGNOSTIC_DATASET = "tests/fixtures/development-minimal.json"
SEQUENCED_PROVIDERS = ("binance-sequenced", "kucoin-sequenced")
PROVIDER_CHOICES = ("htx-ws", "binance-sequenced", "kucoin-sequenced")


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

    run = subparsers.add_parser("run", help="run the schema-v8 live runner")
    run.add_argument("--profile", choices=("diagnostic", "primary"), required=True)
    run.add_argument("--study", help="frozen primary study manifest")
    run.add_argument("--database")
    run.add_argument("--artifact")
    run.add_argument("--run-id", default=None)
    run.add_argument(
        "--resume",
        action="store_true",
        help=(
            "resume an existing diagnostic run ID; primary runs are "
            "single-session and cannot be resumed"
        ),
    )
    run.add_argument("--symbol")
    run.add_argument("--provider", choices=PROVIDER_CHOICES)
    run.add_argument("--horizon-s", type=int)
    run.add_argument("--lookback-s", type=int)
    run.add_argument("--cadence-s", type=int)
    run.add_argument("--minimum-label-trades", type=int)
    run.add_argument(
        "--hours",
        type=float,
        help=(
            "approximate soak length in hours; sets --target-eligible to "
            "int(hours * 60) for 60s-cadence studies unless --target-eligible "
            "is also provided (explicit --target-eligible always wins)"
        ),
    )
    run.add_argument(
        "--target-eligible",
        type=int,
        help=(
            "scoreable-slot target; when both --hours and --target-eligible "
            "are set, --target-eligible wins"
        ),
    )
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

    analyze = subparsers.add_parser("analyze", help="score eligible schema-v8 forecasts")
    analyze.add_argument("--database", required=True)
    analyze.add_argument("--run-id", required=True)
    analyze.add_argument(
        "--human",
        action="store_true",
        help="print a researcher-readable Born vs classical verdict after the JSON",
    )

    report = subparsers.add_parser(
        "report",
        help="print a researcher-readable Born vs classical evidence verdict",
    )
    report.add_argument("--database", required=True)
    report.add_argument("--run-id", required=True)
    report.add_argument(
        "--json",
        action="store_true",
        help="also print the underlying analysis JSON after the human report",
    )

    stop = subparsers.add_parser("stop", help="stop the repository-owned run writer")
    stop.add_argument("--database", required=True)
    stop.add_argument("--run-id", required=True)
    stop.add_argument("--timeout-s", type=float, default=10.0)

    export = subparsers.add_parser("export", help="write a consistent schema-v8 JSON snapshot")
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
    doctor.add_argument("--provider", choices=PROVIDER_CHOICES)
    doctor.add_argument(
        "--connectivity-test",
        action="store_true",
        help="verify provider REST and websocket reachability",
    )
    doctor.add_argument("--symbol", default="btcusdt")
    doctor.add_argument(
        "--connectivity-timeout-s",
        type=float,
        default=15.0,
        help="websocket soak duration for --connectivity-test",
    )
    doctor.add_argument(
        "--holdout-dataset",
        help="development dataset JSON for Born vs baseline holdout gating",
    )
    doctor.add_argument(
        "--capture-database",
        help="reference capture DB used to estimate scoreable fraction / wall-clock",
    )

    certification = subparsers.add_parser(
        "provider-certify",
        help="run a bounded provider continuity certification soak",
    )
    certification.add_argument(
        "--provider",
        choices=SEQUENCED_PROVIDERS,
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
    dataset.add_argument("--provider", default="kucoin-sequenced")
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
        return asyncio.run(_doctor(parser, args))
    if args.command == "provider-certify":
        return asyncio.run(_certify_provider(parser, args))
    if args.command == "dataset":
        return _build_dataset(parser, args)

    if args.command != "run" and not os.path.isfile(args.database):
        parser.error(f"database does not exist: {args.database}")
    if args.command == "run":
        return _run_command(parser, args)
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
            # allow_nan=False: non-finite scores must fail loudly instead of
            # emitting non-standard JSON (Infinity) into the analysis record.
            document = _analysis_document(store, args.run_id)
            print(json.dumps(document, indent=2, sort_keys=True, allow_nan=False))
            if args.human:
                print()
                print(format_research_report(document, database=args.database))
            return 0
        if args.command == "report":
            document = _analysis_document(store, args.run_id)
            print(format_research_report(document, database=args.database))
            if args.json:
                print()
                print(json.dumps(document, indent=2, sort_keys=True, allow_nan=False))
            return 0
        if args.command == "export":
            document = store.export_run(args.run_id)
            temporary = args.output + ".tmp"
            with open(temporary, "w", encoding="utf-8") as handle:
                json.dump(document, handle, indent=2, sort_keys=True, allow_nan=False)
            os.replace(temporary, args.output)
            return 0
        if args.command == "stop":
            return _stop_run(store, args.run_id, args.timeout_s)
    finally:
        store.close()
    return 2


def _run_command(parser: argparse.ArgumentParser, args) -> int:
    study = _load_study(parser, args.study) if args.profile == "primary" else {}
    profile = PRIMARY_PROFILE if args.profile == "primary" else DIAGNOSTIC_PROFILE
    if args.refresh_s <= 0:
        parser.error("--refresh-s must be positive")
    if args.resume and args.profile != "diagnostic":
        parser.error("--resume is diagnostic-only; primary runs are single-session")
    if args.resume and (not args.database or not args.run_id or not args.artifact):
        parser.error("--resume requires explicit --database, --run-id, and --artifact")
    if args.profile == "primary" and not args.study:
        parser.error("--profile primary requires --study")
    run_id = (
        args.run_id
        or study.get("run_id")
        or (
            f"{profile.symbol}-{profile.mode}-{time.strftime('%Y%m%d-%H%M%S')}-"
            f"{uuid.uuid4().hex[:8]}"
        )
    )
    database = args.database or study.get("database") or f"runs/{run_id}.sqlite3"
    artifact_path = args.artifact or study.get("artifact") or profile.artifact
    if not artifact_path:
        parser.error("primary study must define an artifact")
    if not os.path.isfile(artifact_path):
        if args.artifact:
            parser.error(f"artifact does not exist: {artifact_path}")
        if args.profile != "diagnostic":
            parser.error(
                f"artifact does not exist: {artifact_path} "
                f"({args.profile} runs never auto-create artifacts; fit a primary artifact first)"
            )
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
    certification = None
    if args.profile == "primary":
        if artifact.purpose != "primary":
            parser.error("primary runs reject diagnostic or unproven artifacts")
        if artifact.calibration_status != "fitted":
            parser.error("primary runs require a fitted-calibration artifact")
        if artifact.calibration_rows < PRIMARY_MIN_CALIBRATION_ROWS:
            parser.error(
                f"primary runs require calibration_rows>={PRIMARY_MIN_CALIBRATION_ROWS}"
            )
        certification = _validate_certification(parser, study, profile)
    if args.hours is not None and args.hours <= 0:
        parser.error("--hours must be positive")
    if args.target_eligible is not None:
        target_eligible = args.target_eligible
    elif args.hours is not None:
        target_eligible = int(args.hours * 60)
    else:
        target_eligible = study.get("target_eligible")
    if target_eligible is None:
        target_eligible = profile.target_eligible
    if int(target_eligible) <= 0:
        parser.error(
            f"{args.profile} runs require a positive target_eligible "
            "(set it in the study or pass --target-eligible / --hours)"
        )
    if args.profile == "primary" and int(target_eligible) >= 360:
        holdout_dataset = study.get("development_dataset")
        if not holdout_dataset or not os.path.isfile(holdout_dataset):
            parser.error(
                "six-hour primary soaks require study.development_dataset "
                "for holdout gating; run doctor --profile primary first"
            )
        holdout = _doctor_holdout_gate(artifact, holdout_dataset)
        if not holdout.get("passed"):
            parser.error(
                "six-hour primary soak blocked by holdout gate: "
                f"{holdout.get('reason') or holdout}"
            )
    manifest = RunManifest(
        run_id=run_id,
        symbol=(args.symbol or study.get("symbol") or profile.symbol).lower(),
        provider=args.provider or study.get("provider") or profile.provider,
        model_artifact_hash=artifact.artifact_hash,
        feature_policy="causal_trade_book_v1",
        label_policy="half_open_streamed_trades_v1",
        primary_metric="per_trade_negative_log_likelihood",
        primary_comparator="regularized_logistic_v1",
        inference_policy="hac_plus_block_sensitivity_v1",
        horizon_ms=_value_or_default(args.horizon_s, profile.horizon_s) * 1000,
        lookback_ms=_value_or_default(args.lookback_s, profile.lookback_s) * 1000,
        cadence_ms=_value_or_default(args.cadence_s, profile.cadence_s) * 1000,
        minimum_label_trades=(
            _value_or_default(
                args.minimum_label_trades,
                profile.minimum_label_trades,
            )
        ),
        target_eligible=int(target_eligible),
        terminal_slot_limit=(
            _optional_positive(
                args.max_terminal_slots,
                study.get("max_terminal_slots"),
                profile.max_terminal_slots,
            )
        ),
        mode=profile.mode,
        capture_policy=(study.get("capture_policy") or profile.capture_policy),
        clock_policy=_RUN_CLOCK_POLICY,
        eligibility_policy=_RUN_ELIGIBILITY_POLICY,
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
                parser.error(f"run ID exists with an incompatible manifest: {run_id}")
            if not args.resume:
                parser.error(
                    f"run ID already exists: {run_id}\n"
                    "Use a new --run-id or add --resume intentionally."
                )
        if certification is not None:
            store.save_provider_certification(
                f"{run_id}:{certification['provider']}",
                certification["provider"],
                certification.get("symbol", manifest.symbol),
                certification["adapter_revision"],
                True,
                certification,
                expires_at_ms=certification["issued_at_ms"] + 24 * 60 * 60 * 1000,
            )
        provider = _make_provider(args.provider or study.get("provider") or profile.provider)
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
            hours=args.hours,
        )
        asyncio.run(_run_foreground(runner, console))
        final_status = store.status(run_id)["status"]
        return 2 if final_status == "failed" else 0
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
        # Console should only finish after the runner. If it crashed, keep the
        # soak alive and wait for the runner (or an operator signal).
        console_error = console_task.exception()
        if console_error is not None:
            print(
                f"[exchange-q] console ended early ({type(console_error).__name__}: "
                f"{console_error}); leaving runner active",
                flush=True,
            )
        else:
            runner.stop()
        # Wait without re-raising so failed runs can surface as status=failed
        # and exit code 2 from _run_command.
        await asyncio.wait({runner_task})
    elif runner_task in done and not console_task.done():
        await asyncio.wait({console_task})
    for task in (runner_task, console_task):
        try:
            task.result()
        except Exception as exc:
            if task is runner_task:
                print(f"[exchange-q] run ended with error: {exc}", flush=True)
            elif task is console_task:
                print(f"[exchange-q] console ended with error: {exc}", flush=True)
            else:
                raise


PRIMARY_MIN_ROWS = 500
PRIMARY_MIN_CALIBRATION_ROWS = 50


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
        dataset_hash = (
            payload.get("dataset_hash")
            or hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
        )
    else:
        rows = payload
        with open(dataset, "rb") as handle:
            dataset_hash = hashlib.sha256(handle.read()).hexdigest()
    if purpose == "primary" and len(rows) < PRIMARY_MIN_ROWS:
        raise ValueError(
            f"primary artifacts require at least {PRIMARY_MIN_ROWS} certified "
            f"development rows (got {len(rows)})"
        )
    model = NormalizedBornModel()
    fit_rows = rows
    calibration_rows = 0
    if purpose == "primary":
        split_index = max(1, int(len(rows) * 0.8))
        if split_index >= len(rows):
            raise ValueError("primary artifacts require an independent calibration split")
        fit_rows = rows[:split_index]
        calibration_rows = len(rows) - split_index
        if calibration_rows < PRIMARY_MIN_CALIBRATION_ROWS:
            raise ValueError(
                f"primary artifacts require at least {PRIMARY_MIN_CALIBRATION_ROWS} "
                f"calibration rows (got {calibration_rows})"
            )
    artifact = model.fit(
        [FeatureWindow.from_record(row["feature"]) for row in fit_rows],
        [int(row["buy_count"]) for row in fit_rows],
        [int(row["total_count"]) for row in fit_rows],
        purpose=purpose,
        dataset_hash=dataset_hash,
    )
    if purpose == "primary":
        calibration_split = rows[split_index:]
        import numpy as np

        raw_probabilities = []
        for row in calibration_split:
            probability, _ = NormalizedBornModel._raw_probability(
                FeatureWindow.from_record(row["feature"]), artifact.parameters
            )
            raw_probabilities.append(min(1.0 - 1e-9, max(1e-9, probability)))
        intercept, slope = calibration_parameters(
            np.asarray(raw_probabilities, dtype=float),
            np.asarray([int(row["buy_count"]) for row in calibration_split], dtype=float),
            np.asarray([int(row["total_count"]) for row in calibration_split], dtype=float),
        )
        calibration_fitted = (
            intercept is not None
            and slope is not None
            and math.isfinite(intercept)
            and math.isfinite(slope)
            and slope > 0
        )
        if not calibration_fitted:
            raise ValueError(
                "primary artifacts require a successful calibration fit "
                "(need diverse holdout probabilities and positive slope)"
            )
        artifact = replace(
            artifact,
            calibration_intercept=intercept,
            calibration_slope=slope,
            calibration_rows=calibration_rows,
            calibration_status="fitted",
        )
    save_artifact(output, artifact)
    return artifact, len(rows)



def _holdout_baseline_scores(artifact, rows: list[dict]) -> dict[str, float]:
    model = NormalizedBornModel()
    scores = {
        "born_nll": 0.0,
        "flow_persistence_nll": 0.0,
        "development_prior_nll": 0.0,
        "regularized_logistic_nll": 0.0,
        "total_trades": 0,
    }
    prior = artifact.baseline_map.get("development_prior_v1", (0.5,))[0]
    logistic = artifact.baseline_map.get("regularized_logistic_v1")
    for row in rows:
        feature = FeatureWindow.from_record(row["feature"])
        buy = int(row["buy_count"])
        total = int(row["total_count"])
        if total <= 0:
            continue
        forecast = model.predict(feature, artifact)
        born_p = min(1.0 - 1e-9, max(1e-9, forecast.probability_buy))
        flow_p = min(1.0 - 1e-9, max(1e-9, float(feature.buy_ratio)))
        prior_p = min(1.0 - 1e-9, max(1e-9, float(prior)))
        if logistic:
            logistic_p = min(
                1.0 - 1e-9,
                max(1e-9, NormalizedBornModel._logistic_probability(feature, logistic)),
            )
        else:
            logistic_p = prior_p
        sell = total - buy
        scores["born_nll"] += -(buy * math.log(born_p) + sell * math.log(1.0 - born_p))
        scores["flow_persistence_nll"] += -(
            buy * math.log(flow_p) + sell * math.log(1.0 - flow_p)
        )
        scores["development_prior_nll"] += -(
            buy * math.log(prior_p) + sell * math.log(1.0 - prior_p)
        )
        scores["regularized_logistic_nll"] += -(
            buy * math.log(logistic_p) + sell * math.log(1.0 - logistic_p)
        )
        scores["total_trades"] += total
    if scores["total_trades"] <= 0:
        raise ValueError("holdout split contained no trades")
    for key in (
        "born_nll",
        "flow_persistence_nll",
        "development_prior_nll",
        "regularized_logistic_nll",
    ):
        scores[key] = scores[key] / scores["total_trades"]
    return scores


def _doctor_holdout_gate(artifact, dataset_path: str) -> dict:
    with open(dataset_path, encoding="utf-8") as handle:
        payload = json.load(handle)
    rows = payload["rows"] if isinstance(payload, dict) and "rows" in payload else payload
    if len(rows) < PRIMARY_MIN_ROWS:
        return {
            "passed": False,
            "reason": f"holdout dataset has {len(rows)} rows; need {PRIMARY_MIN_ROWS}",
        }
    split_index = max(1, int(len(rows) * 0.8))
    calibration_rows = rows[split_index:]
    try:
        scores = _holdout_baseline_scores(artifact, calibration_rows)
    except ValueError as exc:
        return {"passed": False, "reason": str(exc)}
    beats_prior = scores["born_nll"] <= scores["development_prior_nll"]
    beats_flow = scores["born_nll"] <= scores["flow_persistence_nll"]
    return {
        "passed": beats_prior and beats_flow,
        "scores": scores,
        "beats_development_prior": beats_prior,
        "beats_flow_persistence": beats_flow,
        "reason": (
            None
            if beats_prior and beats_flow
            else "Born holdout NLL must beat development_prior and flow_persistence"
        ),
    }


def _estimate_scoreable_fraction(
    capture_database: str,
    provider: str,
    symbol: str,
    minimum_label_trades: int,
) -> float | None:
    store = V7Store(capture_database)
    try:
        if store.schema_version < 8:
            return None
        cadence_ms = 60_000
        bounds = store.connection.execute(
            """
            SELECT MIN(exchange_time_ms), MAX(exchange_time_ms)
            FROM trades WHERE provider=? AND symbol=?
            """,
            (provider, symbol.lower()),
        ).fetchone()
        if not bounds or bounds[0] is None:
            return None
        start = ((int(bounds[0]) + cadence_ms - 1) // cadence_ms) * cadence_ms
        end = int(bounds[1])
        total = 0
        scoreable = 0
        for target_start in range(start + 300_000, end, cadence_ms):
            target_end = target_start + cadence_ms
            if target_end > end:
                break
            if store.interval_has_unresolved_gap(
                provider, symbol.lower(), target_start - 300_000, target_end
            ):
                continue
            label = store.build_label(provider, symbol.lower(), target_start, target_end)
            total += 1
            if label.coverage_complete and label.trade_count >= minimum_label_trades:
                scoreable += 1
        if total == 0:
            return None
        return scoreable / total
    finally:
        store.close()



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


_PROVIDER_CLASSES = {
    "binance-sequenced": BinanceSequencedProvider,
    "kucoin-sequenced": KucoinSequencedProvider,
    "htx-ws": HtxWebSocketProvider,
}

# Policy revisions the v8r2 runtime enforces for primary runs. The study may
# declare them, but cannot override them.
_RUN_CLOCK_POLICY = "exchange_clock_watermark_v1"
_RUN_ELIGIBILITY_POLICY = "certified_continuity_v1"


def _make_provider(provider_name: str):
    provider_class = _PROVIDER_CLASSES.get(provider_name)
    if provider_class is None:
        raise ValueError(f"unsupported provider: {provider_name}")
    return provider_class()


def _validate_certification(parser, study, profile):
    path = study["provider_certification"]
    if not os.path.isfile(path):
        parser.error(f"provider certification does not exist: {path}")
    with open(path, encoding="utf-8") as handle:
        certification = json.load(handle)
    if not certification.get("valid"):
        parser.error("provider certification is not valid")
    expected_provider = study.get("provider") or profile.provider
    if certification.get("provider") != expected_provider:
        parser.error("provider certification does not match the primary provider")
    expected_symbol = (study.get("symbol") or profile.symbol).lower()
    if certification.get("symbol", "").lower() != expected_symbol:
        parser.error("provider certification does not match the primary symbol")
    adapter_revision = certification.get("adapter_revision")
    if not adapter_revision:
        parser.error("provider certification is missing adapter revision")
    provider_class = _PROVIDER_CLASSES.get(expected_provider)
    expected_revision = getattr(provider_class, "adapter_revision", None)
    if expected_revision is not None and adapter_revision != expected_revision:
        parser.error(
            f"provider certification adapter revision {adapter_revision!r} "
            f"does not match the runtime adapter revision {expected_revision!r}"
        )
    for policy_key, expected_policy in (
        ("clock_policy", _RUN_CLOCK_POLICY),
        ("eligibility_policy", _RUN_ELIGIBILITY_POLICY),
    ):
        declared = study.get(policy_key)
        if declared is not None and declared != expected_policy:
            parser.error(
                f"study {policy_key} {declared!r} does not match "
                f"the runtime policy revision {expected_policy!r}"
            )
    issued_at_ms = certification.get("issued_at_ms")
    if not isinstance(issued_at_ms, int) or issued_at_ms <= 0:
        parser.error("provider certification has invalid issue time")
    if int(time.time() * 1000) - issued_at_ms > 24 * 60 * 60 * 1000:
        parser.error("provider certification is older than 24 hours")
    for section in ("replay_results", "fault_results", "live_soak"):
        if section not in certification:
            parser.error(f"provider certification missing section: {section}")
        if certification[section].get("passed") is not True:
            parser.error(f"provider certification section failed: {section}")
    soak = certification["live_soak"]
    if float(soak.get("duration_s", 0)) < 60:
        parser.error("provider certification live soak is shorter than 60 seconds")
    return certification


async def _doctor(parser, args) -> int:
    if args.profile == "diagnostic":
        provider_name = args.provider or DIAGNOSTIC_PROFILE.provider
        checks = {
            "profile": "diagnostic",
            "artifact": DIAGNOSTIC_PROFILE.artifact,
            "artifact_exists": os.path.isfile(DIAGNOSTIC_PROFILE.artifact),
            "provider": provider_name,
            "primary_evidence": False,
            "ready": True,
        }
    else:
        study = _load_study(parser, args.study)
        artifact_path = study["artifact"]
        certification_path = study["provider_certification"]
        provider_name = args.provider or study.get("provider") or PRIMARY_PROFILE.provider
        checks = {
            "profile": "primary",
            "artifact": artifact_path,
            "artifact_exists": os.path.isfile(artifact_path),
            "certification": certification_path,
            "certification_exists": os.path.isfile(certification_path),
            "target_eligible": study["target_eligible"],
            "provider": provider_name,
            "systemd_forbidden": True,
            "foreground_only": True,
        }
        checks["ready"] = all(
            (
                checks["artifact_exists"],
                checks["certification_exists"],
                int(checks["target_eligible"]) > 0,
            )
        )
        if checks["artifact_exists"]:
            artifact = load_artifact(artifact_path)
            checks["artifact_purpose"] = artifact.purpose
            checks["calibration_status"] = artifact.calibration_status
            checks["development_rows"] = artifact.development_rows
            checks["calibration_rows"] = artifact.calibration_rows
            checks["ready"] = (
                checks["ready"]
                and artifact.purpose == "primary"
                and artifact.calibration_status == "fitted"
                and artifact.development_rows >= int(PRIMARY_MIN_ROWS * 0.8)
                and artifact.calibration_rows >= PRIMARY_MIN_CALIBRATION_ROWS
            )
            holdout_dataset = study.get("development_dataset") or getattr(
                args, "holdout_dataset", None
            )
            if holdout_dataset and os.path.isfile(holdout_dataset):
                holdout = _doctor_holdout_gate(artifact, holdout_dataset)
                checks["holdout"] = holdout
                checks["ready"] = checks["ready"] and holdout.get("passed", False)
            elif int(checks["target_eligible"]) >= 360:
                checks["holdout"] = {
                    "passed": False,
                    "reason": (
                        "six-hour soaks require study.development_dataset "
                        "for Born vs flow_persistence holdout gating"
                    ),
                }
                checks["ready"] = False
        capture_database = study.get("reference_capture_database") or getattr(
            args, "capture_database", None
        )
        if capture_database and os.path.isfile(capture_database):
            fraction = _estimate_scoreable_fraction(
                capture_database,
                provider_name,
                study.get("symbol") or PRIMARY_PROFILE.symbol,
                int(study.get("minimum_label_trades") or PRIMARY_PROFILE.minimum_label_trades),
            )
            checks["expected_scoreable_fraction"] = fraction
            if fraction is not None and fraction > 0:
                checks["expected_wall_clock_hours"] = (
                    int(checks["target_eligible"]) / 60.0
                ) / fraction
    if args.connectivity_test:
        if provider_name == "htx-ws":
            checks["connectivity"] = {
                "reachable": False,
                "detail": "connectivity-test requires a sequenced provider",
            }
            checks["ready"] = False
        else:
            checks["connectivity"] = await _connectivity_test(
                provider_name,
                args.symbol,
                args.connectivity_timeout_s,
            )
            if not checks["connectivity"]["reachable"]:
                checks["ready"] = False
    print(json.dumps(checks, indent=2, sort_keys=True))
    return 0 if checks["ready"] else 2


async def _connectivity_test(
    provider_name: str,
    symbol: str,
    timeout_s: float,
) -> dict:
    started_ms = int(time.time() * 1000)
    counts = {"trades": 0, "books": 0}
    detail = ""
    reachable = False
    provider = _make_provider(provider_name)
    try:
        if provider_name == "kucoin-sequenced":
            await asyncio.to_thread(provider._rest_get, "/api/v1/timestamp", {})
        elif provider_name == "binance-sequenced":
            await asyncio.to_thread(provider._rest_get, "/api/v3/time", {})
        task = asyncio.create_task(_collect_provider_events(provider, symbol, counts))
        try:
            await asyncio.sleep(timeout_s)
        finally:
            await provider.close()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        health = provider.health()
        reachable = counts["trades"] > 0 and counts["books"] > 0
        detail = health.detail or ""
    except (OSError, TimeoutError, ValueError, RuntimeError) as exc:
        detail = f"{type(exc).__name__}: {exc}"
    latency_ms = int(time.time() * 1000) - started_ms
    return {
        "reachable": reachable,
        "trades": counts["trades"],
        "books": counts["books"],
        "latency_ms": latency_ms,
        "detail": detail,
    }


async def _collect_provider_events(provider, symbol: str, counts: dict) -> None:
    async for event in provider.events(symbol):
        if event.__class__.__name__ == "TradeEvent":
            counts["trades"] += 1
        else:
            counts["books"] += 1


async def _certify_provider(parser, args) -> int:
    if args.duration_s <= 0:
        parser.error("--duration-s must be positive")
    replay_results = await run_replay_certification()
    fault_results = await run_fault_certification()
    provider = _make_provider(args.provider)
    counts = {"trades": 0, "books": 0}
    task = asyncio.create_task(_collect_provider_events(provider, args.symbol, counts))
    collection_error = None
    health = provider.health()
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=args.duration_s)
        health = provider.health()
    except asyncio.TimeoutError:
        health = provider.health()
    except Exception as exc:  # noqa: BLE001
        health = provider.health()
        collection_error = f"{type(exc).__name__}: {exc}"
    finally:
        await provider.close()
        if not task.done():
            task.cancel()
        try:
            await asyncio.wait_for(task, timeout=10.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass
        except Exception as exc:  # noqa: BLE001
            collection_error = f"{type(exc).__name__}: {exc}"
    live_soak = {
        "duration_s": args.duration_s,
        "counts": counts,
        "health": health.__dict__,
        "passed": (
            counts["trades"] > 0
            and counts["books"] > 0
            and collection_error is None
            and health.connected
            and health.coverage_certifiable
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
        "collection_error": collection_error,
        "valid": (replay_results["passed"] and fault_results["passed"] and live_soak["passed"]),
    }
    temporary = args.output + ".tmp"
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    payload = json.dumps(report, indent=2, sort_keys=True)
    _write_text(temporary, payload)
    os.replace(temporary, args.output)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["valid"] else 2


def _write_text(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)


def _build_dataset(parser, args) -> int:
    for name in ("lookback_s", "horizon_s", "cadence_s"):
        if getattr(args, name) <= 0:
            parser.error(f"--{name.replace('_', '-')} must be positive")
    store = V7Store(args.capture_database)
    try:
        if store.schema_version < 8:
            parser.error("dataset build requires a schema-v8 capture database")
        provenance_runs = []
        for run_row in store.connection.execute(
            "SELECT run_id, manifest_json FROM runs ORDER BY created_at_ms"
        ).fetchall():
            run_manifest = json.loads(run_row["manifest_json"])
            run_provider = run_manifest.get("provider", "unknown")
            if run_provider not in SEQUENCED_PROVIDERS:
                parser.error(
                    f"capture database run {run_row['run_id']} used provider "
                    f"{run_provider}, which cannot certify capture continuity"
                )
            integrity = store.run_integrity(run_row["run_id"])
            # Forecast-slot label drift from late exchange-time trades does not
            # invalidate offline recounting from the trades table. Other
            # integrity failures still quarantine the capture.
            blocking_codes = {
                code
                for code in integrity.get("error_codes", {})
                if code != "label_trade_count_mismatch"
            }
            if blocking_codes:
                parser.error(
                    f"capture database run {run_row['run_id']} failed integrity "
                    f"({', '.join(sorted(blocking_codes))}); "
                    "refusing to build a certified dataset from a quarantined capture"
                )
            provenance_runs.append(
                {
                    "run_id": run_row["run_id"],
                    "mode": run_manifest.get("mode", "diagnostic"),
                    "provider": run_provider,
                }
            )
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
            feature_start = target_start - args.lookback_s * 1000
            # Skip windows that overlap unresolved continuity gaps rather than
            # rejecting the entire capture for a localized defect.
            if store.interval_has_unresolved_gap(
                args.provider,
                args.symbol.lower(),
                feature_start,
                target_end,
            ):
                continue
            features = store.build_features(
                args.provider,
                args.symbol.lower(),
                feature_start,
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
            "dataset_hash": hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest(),
            "source": {
                "capture_database": args.capture_database,
                "provider": args.provider,
                "symbol": args.symbol.lower(),
                "runs": provenance_runs,
                "integrity_validated": True,
            },
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


def _analysis_document(store: V7Store, run_id: str) -> dict:
    return build_analysis_document(store, run_id)


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
        store.cancel_open_slots(run_id, "force_stop_before_slot_completion")
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
