import asyncio
import json
from argparse import Namespace

from exchange_q.cli import _analysis_document, _doctor, _parser, _slot_summary
from exchange_q.domain import ForecastStatus
from exchange_q.providers.base import ProviderHealth
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
