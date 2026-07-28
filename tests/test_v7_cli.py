from decimal import Decimal

import pytest

from exchange_q.cli import RunProfile, main
from exchange_q.domain import RunManifest, TradeEvent
from exchange_q.models import ModelArtifact
from exchange_q.providers.replay import ReplayProvider
from exchange_q.store import V7Store


def _manifest(run_id: str, artifact_hash: str = "hash") -> RunManifest:
    return RunManifest(
        run_id=run_id,
        symbol="btcusdt",
        provider="htx-ws",
        model_artifact_hash=artifact_hash,
        feature_policy="causal_trade_book_v1",
        label_policy="half_open_streamed_trades_v1",
        primary_metric="per_trade_negative_log_likelihood",
        horizon_ms=1000,
        lookback_ms=1000,
        cadence_ms=1000,
        minimum_label_trades=1,
        target_eligible=1,
        terminal_slot_limit=2,
    )


def test_missing_artifact_does_not_create_database(tmp_path):
    database = tmp_path / "missing.sqlite3"
    with pytest.raises(SystemExit):
        main(
            [
                "run",
                "--profile",
                "diagnostic",
                "--database",
                str(database),
                "--artifact",
                str(tmp_path / "missing.json"),
                "--target-eligible",
                "1",
            ]
        )
    assert not database.exists()


def test_empty_database_path_is_rejected():
    with pytest.raises(SystemExit):
        main(
            [
                "run",
                "--profile",
                "diagnostic",
                "--database",
                "",
                "--artifact",
                "artifact.json",
                "--target-eligible",
                "1",
            ]
        )


def test_empty_run_id_is_rejected(tmp_path):
    database = tmp_path / "run.sqlite3"
    with pytest.raises(SystemExit):
        main(
            [
                "run",
                "--profile",
                "diagnostic",
                "--database",
                str(database),
                "--artifact",
                "artifact.json",
                "--run-id",
                "",
                "--target-eligible",
                "1",
            ]
        )
    assert not database.exists()


def test_existing_run_requires_explicit_resume(tmp_path, monkeypatch):
    artifact_object = ModelArtifact(
        "normalized-born-v1",
        (0.0, 0.5, 1.0, 0.0, 1.0),
        10,
    )
    database = tmp_path / "existing.sqlite3"
    store = V7Store(str(database))
    try:
        store.create_run(_manifest("existing-run", artifact_object.artifact_hash))
    finally:
        store.close()

    artifact = tmp_path / "artifact.json"
    artifact.write_text(
        """
        {
          "model_id": "normalized-born-v1",
          "parameters": [0.0, 0.5, 1.0, 0.0, 1.0],
          "development_rows": 10,
          "calibration_intercept": 0.0,
          "calibration_slope": 1.0,
          "baseline_parameters": []
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.setattr("exchange_q.cli.load_artifact", lambda _: artifact_object)
    with pytest.raises(SystemExit):
        main(
            [
                "run",
                "--profile",
                "diagnostic",
                "--database",
                str(database),
                "--artifact",
                str(artifact),
                "--run-id",
                "existing-run",
                "--provider",
                "htx-ws",
                "--horizon-s",
                "1",
                "--lookback-s",
                "1",
                "--cadence-s",
                "1",
                "--minimum-label-trades",
                "1",
                "--target-eligible",
                "1",
                "--max-terminal-slots",
                "2",
            ]
        )


def test_artifact_parent_directory_is_created(tmp_path):
    output = tmp_path / "nested" / "artifact.json"
    assert (
        main(
            [
                "fit",
                "tests/fixtures/development-minimal.json",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    assert output.is_file()


def test_resume_requires_explicit_identity():
    with pytest.raises(SystemExit):
        main(["run", "--profile", "diagnostic", "--resume"])


def test_invalid_refresh_is_rejected_before_database_creation(tmp_path):
    database = tmp_path / "invalid-refresh.sqlite3"
    with pytest.raises(SystemExit):
        main(
            [
                "run",
                "--profile",
                "diagnostic",
                "--database",
                str(database),
                "--refresh-s",
                "0",
            ]
        )
    assert not database.exists()


def test_diagnostic_profile_builds_artifact_and_runs_with_generated_defaults(
    tmp_path,
    monkeypatch,
):
    artifact = tmp_path / "artifacts" / "normalized-born.json"
    database = tmp_path / "diagnostic.sqlite3"
    profile = RunProfile(
        artifact=str(artifact),
        symbol="btcusdt",
        provider="htx-ws",
        horizon_s=1,
        lookback_s=1,
        cadence_s=1,
        minimum_label_trades=1,
        target_eligible=1,
        max_terminal_slots=1,
    )
    events = [
        TradeEvent(
            provider="htx-ws",
            symbol="btcusdt",
            exchange_trade_id="first",
            exchange_time_ms=100,
            received_time_ms=101,
            aggressor_side="buy",
            price=Decimal(100),
            quantity=Decimal(1),
        ),
        TradeEvent(
            provider="htx-ws",
            symbol="btcusdt",
            exchange_trade_id="jump",
            exchange_time_ms=3000,
            received_time_ms=3001,
            aggressor_side="sell",
            price=Decimal(100),
            quantity=Decimal(1),
        ),
    ]
    monkeypatch.setattr("exchange_q.cli.DIAGNOSTIC_PROFILE", profile)
    monkeypatch.setattr(
        "exchange_q.cli.HtxWebSocketProvider",
        lambda: ReplayProvider(events),
    )

    assert (
        main(
            [
                "run",
                "--profile",
                "diagnostic",
                "--database",
                str(database),
                "--run-id",
                "automatic-diagnostic",
                "--display",
                "log",
                "--refresh-s",
                "0.01",
            ]
        )
        == 0
    )
    assert artifact.is_file()
    store = V7Store(str(database))
    try:
        status = store.status("automatic-diagnostic")
        assert status["status"] == "diagnostic_limit"
        assert status["lease"] is None
        assert status["manifest"]["terminal_slot_limit"] == 1
    finally:
        store.close()
