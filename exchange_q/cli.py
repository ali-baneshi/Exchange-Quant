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
from dataclasses import dataclass

from exchange_q.analysis import required_sample_size, score_baselines, score_rows
from exchange_q.artifacts import load_artifact, save_artifact
from exchange_q.domain import FeatureWindow, RunManifest
from exchange_q.models import NormalizedBornModel
from exchange_q.monitor import RunConsole
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


DIAGNOSTIC_PROFILE = RunProfile(
    artifact="artifacts/v7/normalized-born.json",
    symbol="btcusdt",
    provider="htx-ws",
    horizon_s=60,
    lookback_s=300,
    cadence_s=60,
    minimum_label_trades=30,
    target_eligible=1,
    max_terminal_slots=10,
)
DIAGNOSTIC_DATASET = "tests/fixtures/development-minimal.json"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="exchange-q")
    subparsers = parser.add_subparsers(dest="command", required=True)

    fit = subparsers.add_parser("fit", help="fit a frozen normalized Born artifact")
    fit.add_argument("dataset", help="JSON list with feature, buy_count, total_count")
    fit.add_argument("--output", required=True)

    run = subparsers.add_parser("run", help="run the schema-v7 live evaluator")
    run.add_argument("--profile", choices=("diagnostic",), required=True)
    run.add_argument("--database")
    run.add_argument("--artifact")
    run.add_argument("--run-id", default=None)
    run.add_argument(
        "--resume",
        action="store_true",
        help="resume an existing run ID; otherwise existing IDs are rejected",
    )
    run.add_argument("--symbol")
    run.add_argument("--provider", choices=("htx-ws",))
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

    status = subparsers.add_parser("status", help="show authoritative run status")
    status.add_argument("--database", required=True)
    status.add_argument("--run-id", required=True)

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
    for argument in ("database", "artifact", "run_id", "output"):
        value = getattr(args, argument, None)
        if value is not None and not str(value).strip():
            parser.error(f"--{argument.replace('_', '-')} must not be empty")
    if args.command == "fit":
        artifact, row_count = _fit_artifact(args.dataset, args.output)
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

    if args.command != "run" and not os.path.isfile(args.database):
        parser.error(f"database does not exist: {args.database}")
    if args.command == "run":
        _run_command(parser, args)
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
            return _stop_run(store, args.run_id, args.timeout_s)
    finally:
        store.close()
    return 2


def _run_command(parser: argparse.ArgumentParser, args) -> None:
    profile = DIAGNOSTIC_PROFILE
    if args.refresh_s <= 0:
        parser.error("--refresh-s must be positive")
    if args.resume and (not args.database or not args.run_id or not args.artifact):
        parser.error("--resume requires explicit --database, --run-id, and --artifact")
    run_id = args.run_id or (
        f"{profile.symbol}-diagnostic-{time.strftime('%Y%m%d-%H%M%S')}-"
        f"{uuid.uuid4().hex[:8]}"
    )
    database = args.database or f"runs/{run_id}.sqlite3"
    artifact_path = args.artifact or profile.artifact
    if not os.path.isfile(artifact_path):
        if args.artifact:
            parser.error(f"artifact does not exist: {artifact_path}")
        _fit_artifact(DIAGNOSTIC_DATASET, artifact_path)
        print(
            f"[exchange-q] created diagnostic-only artifact: {artifact_path}",
            flush=True,
        )
    artifact = load_artifact(artifact_path)
    manifest = RunManifest(
        run_id=run_id,
        symbol=args.symbol or profile.symbol,
        provider=args.provider or profile.provider,
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
            _value_or_default(
                args.max_terminal_slots,
                profile.max_terminal_slots,
            )
        ),
    )
    store = V7Store(database)
    try:
        try:
            store.create_run(manifest)
        except sqlite3.IntegrityError:
            existing = store.status(run_id)
            if existing["manifest"] != manifest.to_record():
                raise
            if not args.resume:
                parser.error(
                    f"run ID already exists: {run_id}\n"
                    "Use a new --run-id or add --resume intentionally."
                )
        provider = HtxWebSocketProvider()
        runner = LiveRunner(store, provider, manifest, artifact)
        console = RunConsole(
            store,
            run_id,
            provider=provider,
            database_path=database,
            artifact_path=artifact_path,
            display=args.display,
            refresh_s=args.refresh_s,
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


def _fit_artifact(dataset: str, output: str):
    with open(dataset, encoding="utf-8") as handle:
        rows = json.load(handle)
    features = [FeatureWindow(**row["feature"]) for row in rows]
    artifact = NormalizedBornModel().fit(
        features,
        [int(row["buy_count"]) for row in rows],
        [int(row["total_count"]) for row in rows],
    )
    save_artifact(output, artifact)
    return artifact, len(rows)


def _value_or_default(value, default):
    return default if value is None else value


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
