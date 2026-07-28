from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sqlite3
import sys
import time

from exchange_q.analysis import required_sample_size, score_baselines, score_rows
from exchange_q.artifacts import load_artifact, save_artifact
from exchange_q.domain import FeatureWindow, RunManifest
from exchange_q.models import NormalizedBornModel
from exchange_q.providers.htx_ws import HtxWebSocketProvider
from exchange_q.runner import LiveRunner
from exchange_q.store import V7Store


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="exchange-q")
    subparsers = parser.add_subparsers(dest="command", required=True)

    fit = subparsers.add_parser("fit", help="fit a frozen normalized Born artifact")
    fit.add_argument("dataset", help="JSON list with feature, buy_count, total_count")
    fit.add_argument("--output", required=True)

    run = subparsers.add_parser("run", help="run the schema-v7 live evaluator")
    run.add_argument("--database", required=True)
    run.add_argument("--artifact", required=True)
    run.add_argument("--run-id", default=None)
    run.add_argument("--symbol", default="btcusdt")
    run.add_argument("--provider", choices=("htx-ws",), default="htx-ws")
    run.add_argument("--horizon-s", type=int, default=3600)
    run.add_argument("--lookback-s", type=int, default=3600)
    run.add_argument("--cadence-s", type=int, default=3600)
    run.add_argument("--minimum-label-trades", type=int, default=30)
    run.add_argument("--target-eligible", type=int, required=True)
    run.add_argument(
        "--max-terminal-slots",
        type=int,
        default=None,
        help="Bound diagnostic runs even when the provider cannot certify labels",
    )

    status = subparsers.add_parser("status", help="show authoritative run status")
    status.add_argument("--database", required=True)
    status.add_argument("--run-id", required=True)

    analyze = subparsers.add_parser("analyze", help="score eligible v7 forecasts")
    analyze.add_argument("--database", required=True)
    analyze.add_argument("--run-id", required=True)

    stop = subparsers.add_parser("stop", help="stop the repository-owned run writer")
    stop.add_argument("--database", required=True)
    stop.add_argument("--run-id", required=True)

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
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "fit":
        with open(args.dataset, encoding="utf-8") as handle:
            rows = json.load(handle)
        features = [FeatureWindow(**row["feature"]) for row in rows]
        artifact = NormalizedBornModel().fit(
            features,
            [int(row["buy_count"]) for row in rows],
            [int(row["total_count"]) for row in rows],
        )
        save_artifact(args.output, artifact)
        print(json.dumps({"artifact_hash": artifact.artifact_hash, "rows": len(rows)}))
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

    store = V7Store(args.database)
    try:
        if args.command == "status":
            print(json.dumps(store.status(args.run_id), indent=2, sort_keys=True))
            return 0
        if args.command == "analyze":
            rows = store.eligible_rows(args.run_id)
            report = score_rows(rows)
            baselines = score_baselines(rows)
            print(
                json.dumps(
                    {
                        "model": report.__dict__,
                        "baselines": {
                            name: baseline.__dict__
                            for name, baseline in baselines.items()
                        },
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "export":
            document = store.export_run(args.run_id)
            temporary = args.output + ".tmp"
            with open(temporary, "w", encoding="utf-8") as handle:
                json.dump(document, handle, indent=2, sort_keys=True)
            os.replace(temporary, args.output)
            return 0
        if args.command == "stop":
            status = store.status(args.run_id)
            lease = status.get("lease")
            if not lease:
                print("No active writer lease.")
                return 0
            pid = int(lease["pid"])
            process_cwd = os.path.realpath(f"/proc/{pid}/cwd")
            repository_root = os.path.realpath(
                os.path.join(os.path.dirname(__file__), "..")
            )
            try:
                with open(f"/proc/{pid}/cmdline", "rb") as handle:
                    command_line = handle.read().replace(b"\0", b" ").decode(errors="replace")
            except OSError as exc:
                raise RuntimeError(f"cannot verify writer process {pid}: {exc}") from exc
            if process_cwd != repository_root or "exchange_q" not in command_line:
                raise RuntimeError("refusing to signal a process not owned by this repository")
            os.kill(pid, signal.SIGTERM)
            return 0
        if args.command == "run":
            artifact = load_artifact(args.artifact)
            run_id = args.run_id or f"{args.symbol}-v7-{int(time.time())}"
            manifest = RunManifest(
                run_id=run_id,
                symbol=args.symbol,
                provider=args.provider,
                model_artifact_hash=artifact.artifact_hash,
                feature_policy="causal_trade_book_v1",
                label_policy="half_open_streamed_trades_v1",
                primary_metric="per_trade_negative_log_likelihood",
                horizon_ms=args.horizon_s * 1000,
                lookback_ms=args.lookback_s * 1000,
                cadence_ms=args.cadence_s * 1000,
                minimum_label_trades=args.minimum_label_trades,
                target_eligible=args.target_eligible,
            )
            try:
                store.create_run(manifest)
            except sqlite3.IntegrityError:
                existing = store.status(run_id)
                if existing["manifest"] != manifest.to_record():
                    raise
            provider = HtxWebSocketProvider()
            runner = LiveRunner(
                store,
                provider,
                manifest,
                artifact,
                max_terminal_slots=args.max_terminal_slots,
            )
            asyncio.run(runner.run())
            return 0
    finally:
        store.close()
    return 2


if __name__ == "__main__":
    sys.exit(main())
