from decimal import Decimal

from exchange_q.analysis import paired_block_bootstrap_test
from exchange_q.cli import _analysis_document
from exchange_q.domain import FeatureWindow, Forecast, RunManifest, TradeEvent
from exchange_q.store import V7Store


def test_analysis_blocks_on_quarantine(tmp_path):
    store = V7Store(str(tmp_path / "run.sqlite3"))
    manifest = RunManifest(
        run_id="quarantine-run",
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
    store.create_run(manifest)
    store.mark_coverage("replay", "btcusdt", 1000, 2000, True)
    store.schedule_slot("quarantine-run", 1000, 2000)
    features = FeatureWindow(0, 1000, 2, 1, 1, 0.5, 0.0, 0.001, 0.0)
    store.create_forecast(
        "quarantine-run",
        1000,
        features,
        Forecast("model", 0.5, 0.5),
        "hash",
    )
    store.save_trade(
        TradeEvent(
            provider="replay",
            symbol="btcusdt",
            exchange_trade_id="1",
            exchange_time_ms=1000,
            received_time_ms=1001,
            aggressor_side="buy",
            price=Decimal(100),
            quantity=Decimal(1),
        )
    )
    label = store.build_label("replay", "btcusdt", 1000, 2000)
    store.resolve_slot("quarantine-run", 1000, label, 1)
    store.connection.execute(
        """
        UPDATE lifecycle_events SET created_at_ms = 1500
        WHERE run_id = 'quarantine-run'
          AND json_extract(payload_json, '$.to') IN (
              'resolved_eligible', 'resolved_scoreable'
          )
        """
    )
    try:
        document = _analysis_document(store, "quarantine-run")
        assert document["analysis_available"] is False
        assert "timing integrity" in document["reason"]
    finally:
        store.close()


def test_block_bootstrap_is_reproducible():
    result = paired_block_bootstrap_test(
        [0.3] * 30,
        [0.2] * 30,
        iterations=100,
    )
    assert result["one_sided_p_value"] == 0.0
    assert result["seed"] == 42


def test_analysis_document_reports_lag_sensitivity(tmp_path):
    store = V7Store(str(tmp_path / "run.sqlite3"))
    try:
        store.create_run(
            RunManifest(
                run_id="analysis-run",
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
                target_eligible=4,
            )
        )
        for index, slot_start in enumerate((1000, 2000, 3000, 4000)):
            store.schedule_slot("analysis-run", slot_start, slot_start + 1000)
            buy_count = 5 + index % 2
            for trade_index in range(10):
                store.save_trade(
                    TradeEvent(
                        provider="replay",
                        symbol="btcusdt",
                        exchange_trade_id=f"t{slot_start}-{trade_index}",
                        exchange_time_ms=slot_start + trade_index,
                        received_time_ms=slot_start + trade_index + 1,
                        aggressor_side="buy" if trade_index < buy_count else "sell",
                        price=Decimal(100),
                        quantity=Decimal(1),
                    )
                )
            store.mark_coverage("replay", "btcusdt", slot_start, slot_start + 1000, True)
            features = FeatureWindow(
                slot_start - 1000,
                slot_start,
                10,
                buy_count,
                10 - buy_count,
                buy_count / 10,
                0.0,
                0.001,
                0.01,
            )
            forecast = Forecast(
                "normalized_born_v1",
                0.4 + 0.05 * index,
                0.4 + 0.05 * index,
                {
                    "artifact_hash": "hash",
                    "baseline_probabilities": {
                        "development_prior_v1": 0.5,
                        "flow_persistence_v1": 0.45 + 0.05 * index,
                        "regularized_logistic_v1": 0.42 + 0.05 * index,
                    },
                },
            )
            store.create_forecast(
                "analysis-run",
                slot_start,
                features,
                forecast,
                "hash",
                observed_decision_ms=slot_start,
            )
            label = store.build_label("replay", "btcusdt", slot_start, slot_start + 1000)
            store.resolve_slot(
                "analysis-run",
                slot_start,
                label,
                2,
                observed_decision_ms=slot_start + 1000,
            )
        document = _analysis_document(store, "analysis-run")
        assert document["analysis_available"] is True
        inference = document["paired_inference"]
        lag_entries = inference["lag_sensitivity"]
        lags = [entry["max_lags"] for entry in lag_entries]
        assert lags == sorted(set(lags))
        assert len(lags) >= 2
        assert inference["hac"]["max_lags"] in lags
        for entry in lag_entries:
            assert 0.0 <= entry["one_sided_p_value"] <= 1.0
    finally:
        store.close()
