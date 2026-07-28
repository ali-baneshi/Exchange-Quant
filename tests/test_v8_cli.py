import asyncio
import json


from exchange_q.cli import _analysis_document, _doctor, _parser, _slot_summary
from exchange_q.domain import ForecastStatus
from exchange_q.store import V7Store


def test_doctor_diagnostic_ready():
    parser = _parser()
    args = parser.parse_args(["doctor", "--profile", "diagnostic"])
    assert _doctor(parser, args) == 0


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
    args = parser.parse_args(
        ["doctor", "--profile", "primary", "--study", str(study)]
    )
    assert _doctor(parser, args) == 2


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
