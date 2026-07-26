#!/usr/bin/env python3

"""
Live ensemble pipeline with resolve-later scoring.

Predictions are created from current history and resolved only after the real
horizon has elapsed. This avoids scoring against the next warmup fetch.

Mode:
  ensemble  — full 2-model Ensemble (quantum + vol_regime)
  quantum   — pure Born rule (weights forced to [1.0, 0.0])
"""

import json
import os
import signal
import statistics
import sys
import time

from data_fetcher import HuobiData
from ensemble import Ensemble, _quantum_predict_with_meta
from baselines import classical_ensemble
from validation import comprehensive_report, print_report
from live_protocol import forecast_lookback, ready_for_forecast, pending_due
from config import FEE_RATE, LONG_THRESHOLD, FLAT_THRESHOLD

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "_live_results")
os.makedirs(RESULTS_DIR, exist_ok=True)

_running = True


def _handle_signal(sig, frame):
    global _running
    print(f"\n  Signal {sig} received, shutting down gracefully...")
    _running = False


def _atomic_write(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def _sleep_interruptible(seconds):
    if seconds <= 0:
        return
    deadline = time.time() + seconds
    while time.time() < deadline and _running:
        time.sleep(min(1.0, deadline - time.time()))


def _wall_ms():
    return int(time.time() * 1000)


def _observation(features, symbol, step, run_id=None):
    obs = dict(features)
    obs.update({
        "id": step,
        "run_id": run_id,
        "symbol": symbol,
        "wall_time_ms": _wall_ms(),
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    return obs


def _signal_from_prediction(pred):
    if pred >= LONG_THRESHOLD:
        return "long"
    if pred <= FLAT_THRESHOLD:
        return "flat"
    return "no_trade"


def _prediction_record(symbol, step, horizon_s, mode, obs, pred_c, preds_c, pred_q, meta, weights=None):
    rec = {
        "id": f"{symbol}-{step}-{int(obs['wall_time_ms'])}",
        "step": step,
        "symbol": symbol,
        "mode": mode,
        "status": "pending",
        "created_at_ms": obs["wall_time_ms"],
        "target_at_ms": obs["wall_time_ms"] + int(horizon_s * 1000),
        "created_time": obs["time"],
        "horizon_s": horizon_s,
        "entry_price": obs["price"],
        "entry_buy_ratio": obs["buy_ratio"],
        "entry_buy_ratio_volume": obs.get("buy_ratio_volume"),
        "entry_spread": obs.get("spread", 0.0),
        "entry_quality_flags": obs.get("quality_flags", []),
        "classical": pred_c,
        "prediction": pred_q,
        "signal": _signal_from_prediction(pred_q),
        "delta": meta.get("delta"),
        "delta_source": meta.get("delta_source", "unknown"),
        "fallback_reason": meta.get("fallback_reason", "unknown"),
        "classical_part": meta.get("classical_part"),
        "interference_term": meta.get("interference_term"),
        "confidence": meta.get("confidence", 0.5),
        "classical_models": preds_c,
    }
    if mode == "ensemble" and weights is not None:
        rec.update({
            "quantum_raw": meta["predictions"]["quantum"],
            "vol_regime_raw": meta["predictions"]["vol_regime"],
            "w_quantum": weights[0],
            "w_vol_regime": weights[1],
        })
    return rec


def _resolve_prediction(pred, obs):
    actual = obs["buy_ratio"]
    exit_price = obs["price"]
    gross_return = (exit_price - pred["entry_price"]) / pred["entry_price"] if pred["entry_price"] else 0.0
    cost = FEE_RATE * 2 + pred.get("entry_spread", 0.0) + obs.get("spread", 0.0)
    signal = pred.get("signal", "no_trade")
    if signal == "long":
        net_return = gross_return - cost
    else:
        net_return = 0.0

    pred.update({
        "status": "resolved",
        "resolved_at_ms": obs["wall_time_ms"],
        "resolved_time": obs["time"],
        "exit_price": exit_price,
        "resolved_actual": actual,
        "resolved_buy_ratio_volume": obs.get("buy_ratio_volume"),
        "exit_quality_flags": obs.get("quality_flags", []),
        "classical_error": abs(pred["classical"] - actual),
        "prediction_error": abs(pred["prediction"] - actual),
        "direction_up": 1.0 if exit_price > pred["entry_price"] else 0.0,
        "gross_return": gross_return,
        "cost": cost,
        "net_return": net_return,
        "score_eligible": not pred.get("entry_quality_flags") and not obs.get("quality_flags"),
    })
    return pred


def _write_run_state(output_path, symbol, mode, horizon_s, sample_interval, window,
                     observations, predictions, ensemble=None, run_id=None):
    payload = {
        "schema_version": 3,
        "run_id": run_id,
        "symbol": symbol,
        "mode": mode,
        "horizon_s": horizon_s,
        "sample_interval_s": sample_interval,
        "window": window,
        "observations": observations,
        "predictions": predictions,
    }
    if ensemble is not None:
        payload["ensemble_weights"] = ensemble.weights[:]
        payload["ensemble_performance"] = {
            name: errs[-30:] for name, errs in ensemble.performance.items()
        }
    _atomic_write(output_path, payload)


def _has_pending(predictions):
    return any(p.get("status") == "pending" for p in predictions)


def _summarize_resolved(predictions):
    resolved = [p for p in predictions if p.get("status") == "resolved" and p.get("score_eligible", True)]
    if not resolved:
        return None
    c_errs = [p["classical_error"] for p in resolved]
    q_errs = [p["prediction_error"] for p in resolved]
    wins = sum(1 for ce, qe in zip(c_errs, q_errs) if qe < ce)
    trades = [p for p in resolved if p.get("signal") == "long"]
    returns = [p["net_return"] for p in trades]
    return {
        "n": len(resolved),
        "wins": wins,
        "mean_c": statistics.mean(c_errs),
        "mean_q": statistics.mean(q_errs),
        "trades": len(trades),
        "avg_net_return": statistics.mean(returns) if returns else 0.0,
        "profit_factor": (
            sum(r for r in returns if r > 0) / abs(sum(r for r in returns if r < 0))
            if any(r < 0 for r in returns) else float("inf") if any(r > 0 for r in returns) else 1.0
        ),
    }


def run(symbol="btcusdt", n_steps=10000, delay=3600.0, window=15, mode="ensemble", sample_interval=60.0):
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    hd = HuobiData()
    ensemble = Ensemble(window=window)
    history = []
    observations = []
    predictions = []
    warmup_complete = False
    last_ts = None
    horizon_s = delay

    if mode == "quantum":
        ensemble.weights = [1.0, 0.0]
        output_tag = "quantum"
    else:
        output_tag = "ensemble"

    output_path = os.path.join(RESULTS_DIR, f"{symbol}_{output_tag}_{int(time.time())}.json")
    run_id = f"{symbol}-{output_tag}-{int(time.time())}"

    print(f"  {'ENSEMBLE' if mode == 'ensemble' else 'QUANTUM-ONLY'} LIVE PIPELINE")
    print(f"  symbol={symbol}  max_steps={n_steps}  horizon={horizon_s}s  sample_interval={sample_interval}s  window={window}")
    print(f"  output={output_path}")
    print(f"  PID={os.getpid()}")
    print(f"  Started at {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    for i in range(n_steps):
        if not _running:
            break

        features = hd.fetch_features(symbol)
        if features is None:
            print(f"  [{i:5d}] {time.strftime('%H:%M:%S')} NO DATA — retrying in 60s")
            time.sleep(60)
            continue

        obs = _observation(features, symbol, i, run_id=run_id)
        observations.append(obs)

        ts = features.get("timestamp") or features.get("collected_at_ms")
        duplicate_ts = ts == last_ts
        if duplicate_ts:
            obs.setdefault("quality_flags", []).append("duplicate_timestamp")
        last_ts = ts

        if not duplicate_ts:
            history.append(features)

        state_dirty = False
        for pred in predictions:
            if pred["status"] == "pending" and pending_due(pred, obs["wall_time_ms"]):
                _resolve_prediction(pred, obs)
                if mode == "ensemble":
                    lookback_for_update = forecast_lookback(history[:-1], window) or history[-window:]
                    _, w, meta = ensemble.predict_and_update(lookback_for_update, pred["resolved_actual"])
                    pred.update({
                        "w_quantum": w[0],
                        "w_vol_regime": w[1],
                        "quantum_raw": meta["predictions"]["quantum"],
                        "vol_regime_raw": meta["predictions"]["vol_regime"],
                    })
                print(f"  [{i:5d}] {time.strftime('%H:%M:%S')} RESOLVED "
                      f"id={pred['id']} act={pred['resolved_actual']:.3f} "
                      f"c_err={pred['classical_error']:.3f} q_err={pred['prediction_error']:.3f} "
                      f"ret={pred['net_return']:+.5f}")
                state_dirty = True

        if state_dirty:
            summary = _summarize_resolved(predictions)
            if summary and summary["n"] >= 30:
                print(f"         --- resolved {summary['n']}: quantum wins {summary['wins']}/{summary['n']} "
                      f"({summary['wins']/summary['n']*100:.0f}%) trades={summary['trades']} "
                      f"avg_ret={summary['avg_net_return']:+.5f}")
            _write_run_state(
                output_path, symbol, mode, horizon_s, sample_interval, window,
                observations, predictions, ensemble if mode == "ensemble" else None,
                run_id=run_id,
            )

        if ready_for_forecast(history, window) and not _has_pending(predictions):
            if not warmup_complete:
                warmup_complete = True
                print(f"  WARMUP complete — creating predictions for horizon={horizon_s}s")

            lookback = forecast_lookback(history, window)

            pred_c, preds_c = classical_ensemble(lookback)

            if mode == "quantum":
                q_pred, q_meta = _quantum_predict_with_meta(lookback)
                pred_q = q_pred
                w = [1.0, 0.0]
                meta = {
                    "predictions": {"quantum": q_pred, "vol_regime": 0.5},
                    "delta": q_meta["delta"],
                    "confidence": q_meta["confidence"],
                    "delta_source": q_meta["delta_source"],
                    "fallback_reason": q_meta["fallback_reason"],
                    "classical_part": q_meta["classical_part"],
                    "interference_term": q_meta["interference_term"],
                    "quantum_meta": q_meta,
                }
            else:
                pred_q, w, meta = ensemble.predict(lookback)

            pred_record = _prediction_record(symbol, i, horizon_s, mode, obs, pred_c, preds_c, pred_q, meta, w if mode == "ensemble" else None)
            predictions.append(pred_record)

            delta_str = f"\u03b4={meta['delta']:.2f}" if meta.get('delta') is not None else "\u03b4=None"
            print(f"  [{i:5d}] {time.strftime('%H:%M:%S')} "
                f"p={features['price']:.1f} "
                f"c={pred_c:.3f} "
                f"q={pred_q:.3f} "
                f"{delta_str} "
                f"status=pending "
                f"fallback={meta.get('fallback_reason', 'unknown')} "
                f"target={time.strftime('%H:%M:%S', time.localtime(pred_record['target_at_ms']/1000))}")

            _write_run_state(
                output_path, symbol, mode, horizon_s, sample_interval, window,
                observations, predictions, ensemble if mode == "ensemble" else None,
                run_id=run_id,
            )
        elif ready_for_forecast(history, window) and _has_pending(predictions):
            print(f"  [{i:5d}] {time.strftime('%H:%M:%S')} SKIP forecast — pending unresolved")
        else:
            print(f"  [{i:5d}] {time.strftime('%H:%M:%S')} WARMUP ({len(history)}/{window})")

        _sleep_interruptible(sample_interval)

    print(f"\n  Stopped at {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Collected {len(observations)} observations, {len(predictions)} predictions")

    if predictions or observations:
        _write_run_state(
            output_path, symbol, mode, horizon_s, sample_interval, window,
            observations, predictions, ensemble if mode == "ensemble" else None,
            run_id=run_id,
        )
        print(f"  Saved to {output_path}")

        summary = _summarize_resolved(predictions)
        if summary:
            n = summary["n"]
            if n >= 30:
                print(f"\n  FINAL: resolved={n} quantum wins {summary['wins']}/{n} ({summary['wins']/n*100:.1f}%)  "
                      f"c_err={summary['mean_c']:.4f}  q_err={summary['mean_q']:.4f}  "
                      f"trades={summary['trades']} avg_ret={summary['avg_net_return']:+.5f}")
            else:
                print(f"\n  FINAL: resolved={n}; exploratory only — suppressing win/loss summary until n>=30")

        if summary and summary["n"] >= 30:
            print(f"\n  --- Honest live evaluation (block bootstrap, Bonferroni corrected) ---")
            resolved = [p for p in predictions if p.get("status") == "resolved" and p.get("score_eligible", True)]
            c_errs = [p["classical_error"] for p in resolved]
            q_errs = [p["prediction_error"] for p in resolved]
            report = comprehensive_report(c_errs, q_errs, f" [live {mode}]")
            print_report(report, detail=True)
        else:
            print("\n  FINAL: exploratory only — need at least 30 resolved eligible predictions")


if __name__ == "__main__":
    symbol = sys.argv[1] if len(sys.argv) > 1 else "btcusdt"
    n_steps = int(sys.argv[2]) if len(sys.argv) > 2 else 10000
    delay = float(sys.argv[3]) if len(sys.argv) > 3 else 3600.0
    mode = sys.argv[4] if len(sys.argv) > 4 else "ensemble"
    sample_interval = float(sys.argv[5]) if len(sys.argv) > 5 else 60.0
    if mode not in ("ensemble", "quantum"):
        print(f"  Invalid mode '{mode}'. Use 'ensemble' or 'quantum'.")
        sys.exit(1)
    window = int(sys.argv[6]) if len(sys.argv) > 6 else 15
    run(symbol=symbol, n_steps=n_steps, delay=delay, mode=mode, sample_interval=sample_interval, window=window)
