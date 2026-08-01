import asyncio
import json
from argparse import Namespace

from exchange_q.cli import _analysis_document, _doctor, _parser
from exchange_q.domain import ForecastStatus
from exchange_q.providers.base import ProviderHealth
from exchange_q.report import _slot_summary
from exchange_q.store import V7Store


def test_provider_certification_fails_fast_on_collection_error(tmp_path, monkeypatch):
    from exchange_q import cli

    async def passing_certification():
        return {"passed": True}

    monkeypatch.setattr(cli, "run_replay_certification", passing_certification)
    monkeypatch.setattr(cli, "run_fault_certification", passing_certification)

    class FailingProvider:
        name = "kucoin-sequenced"
        adapter_revision = "test"

        def health(self):
            return ProviderHealth(
                connected=False,
                last_event_received_ms=None,
                reconnects=0,
                sequence_gaps=0,
                coverage_certifiable=False,
                unresolved_gaps=0,
                clock_uncertainty_ms=None,
            )

        async def close(self):
            return None

        async def events(self, symbol):
            raise RuntimeError("websocket rejected")
            yield

    monkeypatch.setattr(cli, "_make_provider", lambda _: FailingProvider())
    output = tmp_path / "certification.json"
    args = Namespace(
        duration_s=300,
        provider="kucoin-sequenced",
        symbol="btcusdt",
        output=str(output),
    )
    parser = cli._parser()
    assert asyncio.run(cli._certify_provider(parser, args)) == 2
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["valid"] is False
    assert "websocket rejected" in payload["collection_error"]


def test_provider_certification_passes_when_soak_reaches_timeout(tmp_path, monkeypatch):
    from decimal import Decimal

    from exchange_q import cli
    from exchange_q.domain import BookEvent, TradeEvent

    async def passing_certification():
        return {"passed": True}

    monkeypatch.setattr(cli, "run_replay_certification", passing_certification)
    monkeypatch.setattr(cli, "run_fault_certification", passing_certification)

    class StreamingProvider:
        name = "kucoin-sequenced"
        adapter_revision = "kucoin-spot-sequenced-v2"

        def __init__(self):
            self._closed = False
            self._counter = 0

        def health(self):
            return ProviderHealth(
                connected=not self._closed,
                last_event_received_ms=1,
                reconnects=0,
                sequence_gaps=0,
                coverage_certifiable=True,
                unresolved_gaps=0,
                clock_uncertainty_ms=12.5,
            )

        async def close(self):
            self._closed = True

        async def events(self, symbol):
            while not self._closed:
                await asyncio.sleep(0)
                self._counter += 1
                if self._counter % 2:
                    yield TradeEvent(
                        provider=self.name,
                        symbol=symbol,
                        exchange_trade_id=str(self._counter),
                        exchange_time_ms=1000 + self._counter,
                        received_time_ms=1001 + self._counter,
                        aggressor_side="buy",
                        price=Decimal(100),
                        quantity=Decimal(1),
                    )
                else:
                    yield BookEvent(
                        provider=self.name,
                        symbol=symbol,
                        exchange_time_ms=1000 + self._counter,
                        received_time_ms=1001 + self._counter,
                        best_bid=Decimal(99),
                        best_ask=Decimal(101),
                        bid_quantity=Decimal(6),
                        ask_quantity=Decimal(4),
                    )

    monkeypatch.setattr(cli, "_make_provider", lambda _: StreamingProvider())
    output = tmp_path / "certification.json"
    args = Namespace(
        duration_s=0.05,
        provider="kucoin-sequenced",
        symbol="btcusdt",
        output=str(output),
    )
    parser = cli._parser()
    assert asyncio.run(cli._certify_provider(parser, args)) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["valid"] is True
    assert payload["live_soak"]["passed"] is True
    assert payload["live_soak"]["health"]["connected"] is True
    assert payload["live_soak"]["health"]["coverage_certifiable"] is True
    assert payload["live_soak"]["counts"]["trades"] > 0
    assert payload["live_soak"]["counts"]["books"] > 0


def test_doctor_diagnostic_ready():
    parser = _parser()
    args = parser.parse_args(["doctor", "--profile", "diagnostic"])
    assert asyncio.run(_doctor(parser, args)) == 0


def test_doctor_primary_not_ready_without_study(tmp_path):
    parser = _parser()
    study = tmp_path / "study.json"
    study.write_text(
        json.dumps(
            {
                "artifact": "missing.json",
                "provider_certification": "missing-cert.json",
                "target_eligible": 10,
            }
        ),
        encoding="utf-8",
    )
    args = parser.parse_args(["doctor", "--profile", "primary", "--study", str(study)])
    assert asyncio.run(_doctor(parser, args)) == 2


def test_analysis_zero_scoreable_report(tmp_path):
    store = V7Store(str(tmp_path / "run.sqlite3"))
    from exchange_q.domain import RunManifest

    manifest = RunManifest(
        run_id="analyze-run",
        symbol="btcusdt",
        provider="replay",
        model_artifact_hash="hash",
        feature_policy="causal_trade_book_v1",
        label_policy="half_open_streamed_trades_v1",
        primary_metric="per_trade_negative_log_likelihood",
        horizon_ms=1000,
        lookback_ms=1000,
        cadence_ms=1000,
        minimum_label_trades=2,
        target_eligible=2,
    )
    store.create_run(manifest)
    try:
        document = _analysis_document(store, "analyze-run")
        assert document["analysis_available"] is False
        assert document["reason"] == "no scoreable labels"
        assert document["slot_summary"]["total"] == 0
    finally:
        store.close()


def test_slot_summary_groups_statuses():
    summary = _slot_summary(
        {
            ForecastStatus.RESOLVED_SCOREABLE.value: 2,
            ForecastStatus.RESOLVED_UNSCOREABLE.value: 1,
            ForecastStatus.SKIPPED.value: 3,
            ForecastStatus.CANCELLED.value: 1,
        }
    )
    assert summary["scoreable"] == 2
    assert summary["unscoreable"] == 1
    assert summary["skipped"] == 3
    assert summary["cancelled"] == 1


def test_certification_modules_pass():
    from exchange_q.certification import run_fault_certification, run_replay_certification

    replay = asyncio.run(run_replay_certification())
    fault = asyncio.run(run_fault_certification())
    assert replay["passed"] is True
    assert fault["passed"] is True


class _HarnessRunner:
    def __init__(self, store, provider, manifest, artifact):
        self.manifest = manifest

    def stop(self):
        return None


class _HarnessConsole:
    def __init__(self, *args, **kwargs):
        pass

    async def watch(self, task):
        return None


def _patch_run_harness(monkeypatch, cli, provider=None):
    monkeypatch.setattr(cli, "_make_provider", lambda _: provider or object())
    monkeypatch.setattr(cli, "LiveRunner", _HarnessRunner)
    monkeypatch.setattr(cli, "RunConsole", _HarnessConsole)

    async def _foreground(runner, console):
        return None

    monkeypatch.setattr(cli, "_run_foreground", _foreground)


def _write_primary_study(tmp_path, *, target_eligible=5, artifact_path=None):
    import time

    from exchange_q.artifacts import save_artifact
    from exchange_q.models import ModelArtifact

    if artifact_path is None:
        artifact_path = tmp_path / "primary-artifact.json"
        save_artifact(
            str(artifact_path),
            ModelArtifact(
                "normalized_born_v1",
                (0.1, -0.2, 0.05, 0.01, 0.3),
                400,
                purpose="primary",
                calibration_status="fitted",
                calibration_rows=100,
                calibration_intercept=0.0,
                calibration_slope=1.0,
            ),
        )
    certification_path = tmp_path / "certification.json"
    certification_path.write_text(
        json.dumps(
            {
                "provider": "kucoin-sequenced",
                "symbol": "btcusdt",
                "adapter_revision": "kucoin-spot-sequenced-v2",
                "valid": True,
                "issued_at_ms": int(time.time() * 1000),
                "replay_results": {"passed": True},
                "fault_results": {"passed": True},
                "live_soak": {"passed": True, "duration_s": 300},
            }
        ),
        encoding="utf-8",
    )
    study = {
        "artifact": str(artifact_path),
        "provider_certification": str(certification_path),
        "provider": "kucoin-sequenced",
        "symbol": "btcusdt",
    }
    if target_eligible is not None:
        study["target_eligible"] = target_eligible
    study_path = tmp_path / "study.json"
    study_path.write_text(json.dumps(study), encoding="utf-8")
    return study_path


def test_run_threads_study_target_eligible_into_manifest(tmp_path, monkeypatch):
    from exchange_q import cli

    _patch_run_harness(monkeypatch, cli)
    study = _write_primary_study(tmp_path, target_eligible=7)
    database = tmp_path / "primary.sqlite3"
    exit_code = cli.main(
        [
            "run",
            "--profile",
            "primary",
            "--study",
            str(study),
            "--database",
            str(database),
            "--run-id",
            "study-target",
        ]
    )
    assert exit_code == 0
    store = V7Store(str(database))
    try:
        manifest = store.status("study-target")["manifest"]
    finally:
        store.close()
    assert manifest["target_eligible"] == 7


def test_run_hours_sets_target_eligible_for_60s_cadence(tmp_path, monkeypatch):
    from exchange_q import cli

    _patch_run_harness(monkeypatch, cli)
    study = _write_primary_study(tmp_path, target_eligible=7)
    dataset = tmp_path / "holdout.json"
    dataset.write_text("{}", encoding="utf-8")
    document = json.loads(study.read_text(encoding="utf-8"))
    document["development_dataset"] = str(dataset)
    study.write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setattr(
        cli,
        "_doctor_holdout_gate",
        lambda *_args, **_kwargs: {"passed": True, "reason": None},
    )
    database = tmp_path / "hours.sqlite3"
    exit_code = cli.main(
        [
            "run",
            "--profile",
            "primary",
            "--study",
            str(study),
            "--database",
            str(database),
            "--run-id",
            "hours-target",
            "--hours",
            "6",
        ]
    )
    assert exit_code == 0
    store = V7Store(str(database))
    try:
        manifest = store.status("hours-target")["manifest"]
    finally:
        store.close()
    assert manifest["target_eligible"] == 360


def test_run_target_eligible_wins_over_hours(tmp_path, monkeypatch):
    from exchange_q import cli

    _patch_run_harness(monkeypatch, cli)
    study = _write_primary_study(tmp_path, target_eligible=7)
    database = tmp_path / "hours-override.sqlite3"
    exit_code = cli.main(
        [
            "run",
            "--profile",
            "primary",
            "--study",
            str(study),
            "--database",
            str(database),
            "--run-id",
            "hours-override",
            "--hours",
            "6",
            "--target-eligible",
            "12",
        ]
    )
    assert exit_code == 0
    store = V7Store(str(database))
    try:
        manifest = store.status("hours-override")["manifest"]
    finally:
        store.close()
    assert manifest["target_eligible"] == 12


def test_parser_exposes_hours_help():
    import argparse

    from exchange_q import cli

    parser = cli._parser()
    run_parser = None
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            run_parser = action.choices["run"]
            break
    assert run_parser is not None
    help_text = run_parser.format_help()
    assert "--hours" in help_text
    assert "always wins" in help_text


def test_primary_run_requires_positive_target_eligible(tmp_path, monkeypatch):
    import pytest

    from exchange_q import cli

    _patch_run_harness(monkeypatch, cli)
    study = _write_primary_study(tmp_path, target_eligible=None)
    database = tmp_path / "primary.sqlite3"
    with pytest.raises(SystemExit):
        cli.main(
            [
                "run",
                "--profile",
                "primary",
                "--study",
                str(study),
                "--database",
                str(database),
                "--run-id",
                "no-target",
            ]
        )
    assert not database.exists()


def test_primary_run_rejects_missing_artifact_without_clobbering(tmp_path, monkeypatch):
    import pytest

    from exchange_q import cli

    _patch_run_harness(monkeypatch, cli)
    missing_artifact = tmp_path / "missing-artifact.json"
    study = _write_primary_study(tmp_path, artifact_path=missing_artifact)
    with pytest.raises(SystemExit):
        cli.main(
            [
                "run",
                "--profile",
                "primary",
                "--study",
                str(study),
                "--database",
                str(tmp_path / "primary.sqlite3"),
                "--run-id",
                "missing-artifact",
            ]
        )
    assert not missing_artifact.exists()


def test_primary_run_rejects_mismatched_adapter_revision(tmp_path, monkeypatch):
    import pytest

    from exchange_q import cli

    _patch_run_harness(monkeypatch, cli)
    study = _write_primary_study(tmp_path)
    certification = json.loads((tmp_path / "certification.json").read_text(encoding="utf-8"))
    certification["adapter_revision"] = "kucoin-spot-sequenced-v0-stale"
    (tmp_path / "certification.json").write_text(json.dumps(certification), encoding="utf-8")
    with pytest.raises(SystemExit):
        cli.main(
            [
                "run",
                "--profile",
                "primary",
                "--study",
                str(study),
                "--database",
                str(tmp_path / "revision.sqlite3"),
                "--run-id",
                "revision-mismatch",
            ]
        )


def test_primary_run_rejects_mismatched_study_policy(tmp_path, monkeypatch):
    import pytest

    from exchange_q import cli

    _patch_run_harness(monkeypatch, cli)
    study = _write_primary_study(tmp_path)
    document = json.loads(study.read_text(encoding="utf-8"))
    document["clock_policy"] = "local_received_time_v0"
    study.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(SystemExit):
        cli.main(
            [
                "run",
                "--profile",
                "primary",
                "--study",
                str(study),
                "--database",
                str(tmp_path / "policy.sqlite3"),
                "--run-id",
                "policy-mismatch",
            ]
        )


def test_primary_run_persists_validated_certification(tmp_path, monkeypatch):
    from exchange_q import cli

    _patch_run_harness(monkeypatch, cli)
    study = _write_primary_study(tmp_path)
    database = tmp_path / "certified.sqlite3"
    exit_code = cli.main(
        [
            "run",
            "--profile",
            "primary",
            "--study",
            str(study),
            "--database",
            str(database),
            "--run-id",
            "certified-run",
        ]
    )
    assert exit_code == 0
    store = V7Store(str(database))
    try:
        rows = store.connection.execute(
            "SELECT provider, symbol, adapter_revision, valid FROM provider_certifications"
        ).fetchall()
    finally:
        store.close()
    assert len(rows) == 1
    assert rows[0]["provider"] == "kucoin-sequenced"
    assert rows[0]["adapter_revision"] == "kucoin-spot-sequenced-v2"
    assert rows[0]["valid"] == 1


def test_failed_run_returns_exit_code_2(tmp_path, monkeypatch):
    from exchange_q import cli

    class FailingProvider:
        def health(self):
            return ProviderHealth(
                connected=False,
                last_event_received_ms=None,
                reconnects=0,
                sequence_gaps=0,
                coverage_certifiable=False,
            )

        async def close(self):
            return None

        async def events(self, symbol):
            raise RuntimeError("provider exploded")
            yield

    monkeypatch.setattr(cli, "_make_provider", lambda _: FailingProvider())
    monkeypatch.setattr(cli, "RunConsole", _HarnessConsole)
    database = tmp_path / "failing.sqlite3"
    artifact = tmp_path / "artifact.json"
    cli._fit_artifact(cli.DIAGNOSTIC_DATASET, str(artifact), purpose="diagnostic_fixture")
    exit_code = cli.main(
        [
            "run",
            "--profile",
            "diagnostic",
            "--database",
            str(database),
            "--run-id",
            "failing-run",
            "--artifact",
            str(artifact),
        ]
    )
    assert exit_code == 2
    store = V7Store(str(database))
    try:
        assert store.status("failing-run")["status"] == "failed"
    finally:
        store.close()


def test_stop_run_force_path_cancels_open_slots(tmp_path, monkeypatch):
    from exchange_q import cli
    from exchange_q.domain import RunManifest

    store = V7Store(str(tmp_path / "stop.sqlite3"))
    try:
        store.create_run(
            RunManifest(
                run_id="stop-run",
                symbol="btcusdt",
                provider="replay",
                model_artifact_hash="hash",
                feature_policy="causal_trade_book_v1",
                label_policy="half_open_streamed_trades_v1",
                primary_metric="per_trade_negative_log_likelihood",
                horizon_ms=1000,
                lookback_ms=1000,
                cadence_ms=1000,
                minimum_label_trades=1,
                target_eligible=1,
            )
        )
        store.schedule_slot("stop-run", 1000, 2000)
        store.acquire_lease("stop-run", "owner-1", 424242)
        monkeypatch.setattr(cli, "_verify_repository_writer", lambda pid: None)
        monkeypatch.setattr(cli.os, "kill", lambda pid, sig: None)
        monkeypatch.setattr(cli, "_process_exists", lambda pid: False)
        assert cli._stop_run(store, "stop-run", 0.5) == 0
        status = store.status("stop-run")
        assert status["status"] == "stopped_forcefully"
        assert status["lease"] is None
        open_count = store.connection.execute(
            """
            SELECT COUNT(*) FROM forecast_slots
            WHERE run_id = 'stop-run' AND status IN ('scheduled', 'forecasted', 'awaiting_label')
            """
        ).fetchone()[0]
        assert open_count == 0
        assert status["integrity"]["valid"] is True
    finally:
        store.close()


def _calibration_dataset_rows(count=500):
    rows = []
    for index in range(count):
        group = index % 2
        imbalance = [-0.6, -0.3, 0.0, 0.3, 0.6][index % 5]
        feature_buy = 8 if group else 2
        ratio_center = 0.35 + 0.3 * group + 0.1 * imbalance
        noise = [-0.15, -0.05, 0.05, 0.15][index % 4]
        label_ratio = min(0.9, max(0.1, ratio_center + noise))
        rows.append(
            {
                "feature": {
                    "start_ms": index * 60000,
                    "end_ms": (index + 1) * 60000,
                    "trade_count": 10,
                    "buy_count": feature_buy,
                    "sell_count": 10 - feature_buy,
                    "buy_ratio": feature_buy / 10,
                    "signed_imbalance": imbalance,
                    "spread": 0.001,
                    "volatility": 0.01,
                },
                "buy_count": round(label_ratio * 10),
                "total_count": 10,
            }
        )
    return rows


def test_fit_calibrates_on_split_and_analyze_reports_availability(tmp_path):
    from decimal import Decimal

    from exchange_q import cli
    from exchange_q.artifacts import load_artifact
    from exchange_q.domain import BookEvent, RunManifest, TradeEvent
    from exchange_q.providers.replay import ReplayProvider
    from exchange_q.runner import LiveRunner

    dataset = tmp_path / "dataset.json"
    dataset.write_text(json.dumps(_calibration_dataset_rows()), encoding="utf-8")
    output = tmp_path / "artifact.json"
    artifact, row_count = cli._fit_artifact(str(dataset), str(output), purpose="primary")
    assert row_count == 500
    assert artifact.calibration_status == "fitted"
    assert artifact.calibration_rows == 100
    assert artifact.calibration_slope > 0
    assert (artifact.calibration_intercept, artifact.calibration_slope) != (0.0, 1.0)
    loaded = load_artifact(str(output))
    assert loaded.calibration_status == "fitted"
    assert loaded.calibration_intercept == artifact.calibration_intercept
    assert loaded.calibration_slope == artifact.calibration_slope

    manifest = RunManifest(
        run_id="calibrated-run",
        symbol="btcusdt",
        provider="replay",
        model_artifact_hash=loaded.artifact_hash,
        feature_policy="causal_trade_book_v1",
        label_policy="half_open_streamed_trades_v1",
        primary_metric="per_trade_negative_log_likelihood",
        horizon_ms=1000,
        lookback_ms=1000,
        cadence_ms=1000,
        minimum_label_trades=2,
        target_eligible=5,
        terminal_slot_limit=3,
        artifact_purpose="primary",
    )

    def _trade(identifier, timestamp, side):
        return TradeEvent(
            provider="replay",
            symbol="btcusdt",
            exchange_trade_id=identifier,
            exchange_time_ms=timestamp,
            received_time_ms=timestamp + 1,
            aggressor_side=side,
            price=Decimal(100),
            quantity=Decimal(1),
        )

    events = [
        BookEvent(
            provider="replay",
            symbol="btcusdt",
            exchange_time_ms=100,
            received_time_ms=101,
            best_bid=Decimal(99),
            best_ask=Decimal(101),
            bid_quantity=Decimal(6),
            ask_quantity=Decimal(4),
        ),
        _trade("history-1", 200, "buy"),
        _trade("history-2", 800, "sell"),
        _trade("label-1", 1100, "buy"),
        _trade("label-2", 1500, "sell"),
        _trade("advance", 2500, "buy"),
    ]
    store = V7Store(str(tmp_path / "calibrated.sqlite3"))
    store.create_run(manifest)
    try:
        asyncio.run(
            LiveRunner(store, ReplayProvider(events), manifest, loaded).run()
        )
        document = _analysis_document(store, "calibrated-run")
        assert document["analysis_available"] is True
        assert document["calibration_status"] == "fitted"
        assert document["calibration_available"] is True
    finally:
        store.close()


def test_run_normalizes_symbol_at_manifest_boundary(tmp_path, monkeypatch):
    from exchange_q import cli

    _patch_run_harness(monkeypatch, cli)
    database = tmp_path / "symbol.sqlite3"
    artifact = tmp_path / "artifact.json"
    cli._fit_artifact(cli.DIAGNOSTIC_DATASET, str(artifact), purpose="diagnostic_fixture")
    exit_code = cli.main(
        [
            "run",
            "--profile",
            "diagnostic",
            "--database",
            str(database),
            "--run-id",
            "symbol-case",
            "--symbol",
            "BTCUSDT",
            "--artifact",
            str(artifact),
        ]
    )
    assert exit_code == 0
    store = V7Store(str(database))
    try:
        manifest = store.status("symbol-case")["manifest"]
    finally:
        store.close()
    assert manifest["symbol"] == "btcusdt"


def test_manifest_rejects_non_normalized_symbol():
    import pytest

    from exchange_q.domain import RunManifest

    with pytest.raises(ValueError, match="symbol"):
        RunManifest(
            run_id="bad-symbol",
            symbol="BTCUSDT",
            provider="replay",
            model_artifact_hash="hash",
            feature_policy="causal_trade_book_v1",
            label_policy="half_open_streamed_trades_v1",
            primary_metric="per_trade_negative_log_likelihood",
            horizon_ms=1000,
            lookback_ms=1000,
            cadence_ms=1000,
            minimum_label_trades=1,
            target_eligible=1,
        )


def test_diagnostic_run_auto_creates_fixture_artifact(tmp_path, monkeypatch):
    import dataclasses

    from exchange_q import cli

    _patch_run_harness(monkeypatch, cli)
    artifact = tmp_path / "diagnostic-artifact.json"
    monkeypatch.setattr(
        cli,
        "DIAGNOSTIC_PROFILE",
        dataclasses.replace(cli.DIAGNOSTIC_PROFILE, artifact=str(artifact)),
    )
    exit_code = cli.main(
        [
            "run",
            "--profile",
            "diagnostic",
            "--database",
            str(tmp_path / "diagnostic.sqlite3"),
            "--run-id",
            "diagnostic-autofit",
        ]
    )
    assert exit_code == 0
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert payload["purpose"] == "diagnostic_fixture"


def test_primary_run_rejects_resume(tmp_path, monkeypatch):
    import pytest

    from exchange_q import cli

    _patch_run_harness(monkeypatch, cli)
    study = _write_primary_study(tmp_path)
    artifact = json.loads(study.read_text(encoding="utf-8"))["artifact"]
    with pytest.raises(SystemExit):
        cli.main(
            [
                "run",
                "--profile",
                "primary",
                "--study",
                str(study),
                "--database",
                str(tmp_path / "primary.sqlite3"),
                "--run-id",
                "primary-resume",
                "--artifact",
                artifact,
                "--resume",
            ]
        )


def test_diagnostic_run_rejects_explicit_missing_artifact(tmp_path, monkeypatch):
    import pytest

    from exchange_q import cli

    _patch_run_harness(monkeypatch, cli)
    database = tmp_path / "diagnostic.sqlite3"
    with pytest.raises(SystemExit):
        cli.main(
            [
                "run",
                "--profile",
                "diagnostic",
                "--database",
                str(database),
                "--run-id",
                "diagnostic-missing-artifact",
                "--artifact",
                str(tmp_path / "missing.json"),
            ]
        )
    assert not database.exists()


def _write_capture_database(tmp_path, *, provider="kucoin-sequenced", quarantine=False):
    from decimal import Decimal

    from exchange_q.domain import BookEvent, FeatureWindow, Forecast, RunManifest, TradeEvent
    from exchange_q.store import V7Store

    database = tmp_path / "capture.sqlite3"
    store = V7Store(str(database))
    try:
        store.create_run(
            RunManifest(
                run_id="capture-run",
                symbol="btcusdt",
                provider=provider,
                model_artifact_hash="hash",
                feature_policy="causal_trade_book_v1",
                label_policy="half_open_streamed_trades_v1",
                primary_metric="per_trade_negative_log_likelihood",
                horizon_ms=1000,
                lookback_ms=1000,
                cadence_ms=1000,
                minimum_label_trades=1,
                target_eligible=1,
            )
        )
        for index in range(40):
            timestamp = (index + 1) * 500
            store.save_book(
                BookEvent(
                    provider=provider,
                    symbol="btcusdt",
                    exchange_time_ms=timestamp,
                    received_time_ms=timestamp + 1,
                    best_bid=Decimal(99),
                    best_ask=Decimal(101),
                    bid_quantity=Decimal(6),
                    ask_quantity=Decimal(4),
                )
            )
            store.save_trade(
                TradeEvent(
                    provider=provider,
                    symbol="btcusdt",
                    exchange_trade_id=f"t{index}",
                    exchange_time_ms=timestamp,
                    received_time_ms=timestamp + 1,
                    aggressor_side="buy" if index % 2 else "sell",
                    price=Decimal(100),
                    quantity=Decimal(1),
                )
            )
        store.mark_coverage(provider, "btcusdt", 0, 20_000, True)
        if quarantine:
            store.schedule_slot("capture-run", 5000, 6000)
            store.create_forecast(
                "capture-run",
                5000,
                FeatureWindow(4000, 5000, 2, 1, 1, 0.5, 0.0, 0.001, 0.0),
                Forecast("model", 0.5, 0.5),
                "hash",
                observed_decision_ms=4000,
            )
        store.set_run_status("capture-run", "stopped")
        store.cancel_open_slots("capture-run", "test_complete")
    finally:
        store.close()
    return database


def test_dataset_build_records_capture_provenance(tmp_path):
    from exchange_q import cli

    database = _write_capture_database(tmp_path)
    output = tmp_path / "dataset.json"
    exit_code = cli.main(
        [
            "dataset",
            "build",
            "--capture-database",
            str(database),
            "--provider",
            "kucoin-sequenced",
            "--symbol",
            "btcusdt",
            "--lookback-s",
            "1",
            "--horizon-s",
            "1",
            "--cadence-s",
            "1",
            "--output",
            str(output),
        ]
    )
    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    source = payload["source"]
    assert source["capture_database"] == str(database)
    assert source["provider"] == "kucoin-sequenced"
    assert source["symbol"] == "btcusdt"
    assert source["integrity_validated"] is True
    assert source["runs"] == [
        {"run_id": "capture-run", "mode": "diagnostic", "provider": "kucoin-sequenced"}
    ]
    assert payload["rows"]


def test_dataset_build_refuses_quarantined_capture(tmp_path):
    import pytest

    from exchange_q import cli

    database = _write_capture_database(tmp_path, quarantine=True)
    with pytest.raises(SystemExit):
        cli.main(
            [
                "dataset",
                "build",
                "--capture-database",
                str(database),
                "--provider",
                "kucoin-sequenced",
                "--symbol",
                "btcusdt",
                "--lookback-s",
                "1",
                "--horizon-s",
                "1",
                "--cadence-s",
                "1",
                "--output",
                str(tmp_path / "dataset.json"),
            ]
        )


def test_dataset_build_refuses_uncertifiable_provider_capture(tmp_path):
    import pytest

    from exchange_q import cli

    database = _write_capture_database(tmp_path, provider="htx-ws")
    with pytest.raises(SystemExit):
        cli.main(
            [
                "dataset",
                "build",
                "--capture-database",
                str(database),
                "--provider",
                "htx-ws",
                "--symbol",
                "btcusdt",
                "--lookback-s",
                "1",
                "--horizon-s",
                "1",
                "--cadence-s",
                "1",
                "--output",
                str(tmp_path / "dataset.json"),
            ]
        )


def test_report_command_prints_human_verdict_for_blocked_run(tmp_path, capsys):
    from decimal import Decimal

    from exchange_q import cli
    from exchange_q.domain import FeatureWindow, Forecast, RunManifest, TradeEvent
    from exchange_q.store import V7Store

    database = tmp_path / "blocked.sqlite3"
    store = V7Store(str(database))
    try:
        store.create_run(
            RunManifest(
                run_id="blocked-cli",
                symbol="btcusdt",
                provider="htx-ws",
                model_artifact_hash="hash",
                feature_policy="causal_trade_book_v1",
                label_policy="half_open_streamed_trades_v1",
                primary_metric="per_trade_negative_log_likelihood",
                horizon_ms=1000,
                lookback_ms=1000,
                cadence_ms=1000,
                minimum_label_trades=2,
                target_eligible=1,
                mode="diagnostic",
                artifact_purpose="diagnostic_fixture",
            )
        )
        store.schedule_slot("blocked-cli", 1000, 2000)
        store.create_forecast(
            "blocked-cli",
            1000,
            FeatureWindow(0, 1000, 2, 1, 1, 0.5, 0.0, 0.001, 0.0),
            Forecast("model", 0.5, 0.5),
            "hash",
            observed_decision_ms=1000,
        )
        store.mark_coverage(
            "htx-ws", "btcusdt", 1000, 2000, False, ("provider_coverage_not_certifiable",)
        )
        store.save_trade(
            TradeEvent(
                provider="htx-ws",
                symbol="btcusdt",
                exchange_trade_id="1",
                exchange_time_ms=1000,
                received_time_ms=1001,
                aggressor_side="buy",
                price=Decimal(100),
                quantity=Decimal(1),
            )
        )
        label = store.build_label("htx-ws", "btcusdt", 1000, 2000)
        store.resolve_slot("blocked-cli", 1000, label, 2, observed_decision_ms=2000)
        store.set_run_status("blocked-cli", "diagnostic_limit")
    finally:
        store.close()

    exit_code = cli.main(
        ["report", "--database", str(database), "--run-id", "blocked-cli"]
    )
    assert exit_code == 0
    output = capsys.readouterr().out
    assert "VERDICT: NO COMPARATIVE EVIDENCE" in output
    assert "HTX cannot certify capture continuity" in output
