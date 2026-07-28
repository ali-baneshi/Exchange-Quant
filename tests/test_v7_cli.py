import pytest

from exchange_q.cli import main
from exchange_q.domain import RunManifest
from exchange_q.models import ModelArtifact
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


def test_monitor_reports_terminal_progress_limit(tmp_path, capsys):
    database = tmp_path / "monitor.sqlite3"
    store = V7Store(str(database))
    try:
        store.create_run(_manifest("monitor-run"))
        store.schedule_slot("monitor-run", 1000, 2000)
        store.skip_slot("monitor-run", 1000, ["diagnostic"])
    finally:
        store.close()
    assert (
        main(
            [
                "monitor",
                "--database",
                str(database),
                "--run-id",
                "monitor-run",
            ]
        )
        == 0
    )
    assert "terminal slots: 1/2" in capsys.readouterr().out
