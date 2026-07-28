from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sqlite3
import sys
import time
import uuid

from exchange_q.analysis import required_sample_size, score_baselines, score_rows
from exchange_q.artifacts import load_artifact, save_artifact
from exchange_q.domain import FeatureWindow, RunManifest
from exchange_q.monitor import format_monitor_report, monitor_snapshot
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
    run.add_argument(
        "--resume",
        action="store_true",
        help="resume an existing run ID; otherwise existing IDs are rejected",
    )
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
        default=10,
        help="Bound diagnostic runs even when the provider cannot certify labels",
    )
    run.add_argument("--progress-interval-s", type=float, default=10.0)

    status = subparsers.add_parser("status", help="show authoritative run status")
    status.add_argument("--database", required=True)
    status.add_argument("--run-id", required=True)

    monitor = subparsers.add_parser(
        "monitor", help="show a human-readable live activity snapshot"
    )
    monitor.add_argument("--database", required=True)
    monitor.add_argument("--run-id", required=True)
    monitor.add_argument("--json", action="store_true", help="emit JSON instead of text")
    monitor.add_argument(
        "--watch",
        action="store_true",
        help="refresh until the run is no longer running",
    )
    monitor.add_argument("--interval-s", type=float, default=5.0)
    monitor.add_argument("--slots", type=int, default=5)
    monitor.add_argument("--events", type=int, default=8)

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
    return parser


def main(argv=None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
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

    if args.command == "run" and not os.path.isfile(args.artifact):
        parser.error(
            f"artifact does not exist: {args.artifact}\n"
            "Create the diagnostic artifact with:\n"
            "  ./scripts/exchange-q fit tests/fixtures/development-minimal.json "
            "--output artifacts/v7/normalized-born.json"
        )
    if args.command != "run" and not os.path.isfile(args.database):
        parser.error(f"database does not exist: {args.database}")
    store = V7Store(args.database)
    try:
        if args.command == "status":
            print(json.dumps(store.status(args.run_id), indent=2, sort_keys=True))
            return 0
        if args.command == "monitor":
            return _monitor(store, args)
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
            return _stop_run(store, args.run_id, args.timeout_s)
        if args.command == "run":
            artifact = load_artifact(args.artifact)
            run_id = args.run_id or (
                f"{args.symbol}-v7-{int(time.time())}-{uuid.uuid4().hex[:8]}"
            )
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
                terminal_slot_limit=args.max_terminal_slots,
            )
            try:
                store.create_run(manifest)
            except sqlite3.IntegrityError:
                existing = store.status(run_id)
                if existing["manifest"] != manifest.to_record():
                    raise
                if not args.resume:
                    parser.error(
                        f"run ID already exists: {run_id}\n"
                        "Use a new --run-id, omit --run-id for an automatic ID, "
                        "or add --resume intentionally."
                    )
            print(f"[exchange-q] run_id={run_id}")
            print(
                "[exchange-q] monitor with: "
                f"./scripts/exchange-q monitor --database {args.database} "
                f"--run-id {run_id} --watch",
                flush=True,
            )
            provider = HtxWebSocketProvider()
            runner = LiveRunner(
                store,
                provider,
                manifest,
                artifact,
                progress_interval_s=args.progress_interval_s,
            )
            asyncio.run(runner.run())
            return 0
    finally:
        store.close()
    return 2


def _monitor(store: V7Store, args) -> int:
    if args.interval_s <= 0 or args.slots <= 0 or args.events <= 0:
        raise ValueError("monitor interval, slots, and events must be positive")
    while True:
        snapshot = monitor_snapshot(
            store,
            args.run_id,
            recent_slots=args.slots,
            recent_events=args.events,
        )
        if args.json:
            print(json.dumps(snapshot, indent=2, sort_keys=True))
        else:
            if args.watch and sys.stdout.isatty():
                print("\033[2J\033[H", end="")
            print(format_monitor_report(snapshot))
        if not args.watch:
            return 0
        if snapshot["status"] != "running":
            return 0
        if snapshot["writer_state"] in {"orphaned", "stale", "dead"}:
            return 2
        time.sleep(args.interval_s)
        print()


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
