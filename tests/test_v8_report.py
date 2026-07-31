from decimal import Decimal

from exchange_q.domain import FeatureWindow, Forecast, RunManifest, TradeEvent
from exchange_q.report import build_analysis_document, format_research_report
from exchange_q.store import V7Store


def test_report_blocked_for_hour_run_style_diagnostic(tmp_path):
    store = V7Store(str(tmp_path / "blocked.sqlite3"))
    try:
        store.create_run(
            RunManifest(
                run_id="blocked-run",
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
        store.schedule_slot("blocked-run", 1000, 2000)
        store.create_forecast(
            "blocked-run",
            1000,
            FeatureWindow(0, 1000, 2, 1, 1, 0.5, 0.0, 0.001, 0.0),
            Forecast("model", 0.5, 0.5),
            "hash",
            observed_decision_ms=1000,
        )
        store.mark_coverage(
            "htx-ws",
            "btcusdt",
            1000,
            2000,
            False,
            ("provider_coverage_not_certifiable",),
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
        store.resolve_slot("blocked-run", 1000, label, 2, observed_decision_ms=2000)
        store.set_run_status("blocked-run", "diagnostic_limit")

        document = build_analysis_document(store, "blocked-run")
        text = format_research_report(document, database=str(tmp_path / "blocked.sqlite3"))
        assert "VERDICT: NO COMPARATIVE EVIDENCE" in text
        assert "provider=htx-ws" in text
        assert "Born vs classical: NOT COMPUTED" in text
        assert "HTX cannot certify capture continuity" in text
        assert "exchange-q report --database <primary-run.sqlite3> --run-id <primary-run-id>" in text
        assert document["analysis_available"] is False
    finally:
        store.close()


def test_report_shows_born_vs_baselines_when_scoreable(tmp_path):
    store = V7Store(str(tmp_path / "scoreable.sqlite3"))
    try:
        store.create_run(
            RunManifest(
                run_id="scoreable-run",
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
            store.schedule_slot("scoreable-run", slot_start, slot_start + 1000)
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
                "scoreable-run",
                slot_start,
                FeatureWindow(
                    slot_start - 1000,
                    slot_start,
                    10,
                    buy_count,
                    10 - buy_count,
                    buy_count / 10,
                    0.0,
                    0.001,
                    0.01,
                ),
                forecast,
                "hash",
                observed_decision_ms=slot_start,
            )
            label = store.build_label("replay", "btcusdt", slot_start, slot_start + 1000)
            store.resolve_slot(
                "scoreable-run",
                slot_start,
                label,
                2,
                observed_decision_ms=slot_start + 1000,
            )

        document = build_analysis_document(store, "scoreable-run")
        text = format_research_report(document)
        assert document["analysis_available"] is True
        assert "VERDICT: COMPARATIVE EVIDENCE AVAILABLE" in text
        assert "model (Born)" in text
        assert "regularized_logistic_v1" in text
        assert "paired vs primary_comparator" in text
        assert "HAC one-sided p=" in text
    finally:
        store.close()
