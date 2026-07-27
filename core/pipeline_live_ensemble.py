#!/usr/bin/env python3

"""
Live ensemble pipeline with resolve-later scoring.

Predictions are created from current history and resolved only after the real
horizon has elapsed. This avoids scoring against the next warmup fetch.

Mode:
  ensemble  — full 2-model Ensemble (quantum + vol_regime)
  quantum   — pure Born rule (weights forced to [1.0, 0.0])
"""

import argparse
import hashlib
import json
import os
import signal
import statistics
import sys
import time

from data_fetcher import HuobiData, compute_buy_ratio_for_window
from ensemble import Ensemble, _quantum_predict_with_meta
from baselines import classical_ensemble
from validation import comprehensive_report, print_report
from live_protocol import forecast_lookback, ready_for_forecast, pending_due
from config import (
    DATA_POLICY_VERSION,
    DISQUALIFYING_QUALITY_FLAGS,
    FEE_RATE,
    LONG_THRESHOLD,
    FLAT_THRESHOLD,
    MIN_SIGNIFICANCE_N,
    LIVE_SCHEMA_VERSION,
    TRADE_CAPTURE_SIZE,
    TRADE_RETENTION_DAYS,
    feature_lookback_s,
    min_forward_trades,
)
from live_store import LiveRunStore

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "_live_results")
os.makedirs(RESULTS_DIR, exist_ok=True)

JSON_EXPORT_INTERVAL = 50

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


def _wall_ms(time_fn=None):
    return int((time_fn or time.time)() * 1000)


def _observation(features, symbol, step, run_id=None, time_fn=None):
    now = (time_fn or time.time)()
    obs = dict(features)
    obs.update({
        "id": step,
        "run_id": run_id,
        "symbol": symbol,
        "wall_time_ms": int(now * 1000),
        "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
    })
    return obs


def _exit_code_for_stop_reason(stop_reason):
    return 0 if stop_reason == "max_resolved" else 2


def _signal_from_prediction(pred):
    if pred >= LONG_THRESHOLD:
        return "long"
    if pred <= FLAT_THRESHOLD:
        return "flat"
    return "no_trade"


def _prediction_record(
    symbol, step, horizon_s, mode, obs, pred_c, preds_c, pred_q, meta,
    weights=None, lookback_observation_ids=None,
):
    preds = meta.get("predictions", {})
    entry_flags = list(obs.get("quality_flags", []))
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
        "entry_quality_flags": entry_flags,
        "lookback_observation_ids": list(lookback_observation_ids or []),
        "classical": pred_c,
        "prediction": pred_q,
        "signal": _signal_from_prediction(pred_q),
        "delta": meta.get("delta"),
        "delta_source": meta.get("delta_source", "unknown"),
        "bucket_feature": meta.get("bucket_feature", "buy_ratio"),
        "fallback_reason": meta.get("fallback_reason", "unknown"),
        "classical_part": meta.get("classical_part"),
        "interference_term": meta.get("interference_term"),
        "confidence": meta.get("confidence", 0.5),
        "classical_models": preds_c,
        "quantum_raw": preds.get("quantum", pred_q),
        "vol_regime_raw": preds.get("vol_regime", 0.5),
    }
    if mode == "ensemble" and weights is not None:
        rec.update({
            "w_quantum": weights[0],
            "w_vol_regime": weights[1],
        })
    elif mode == "quantum":
        rec.update({
            "w_quantum": 1.0,
            "w_vol_regime": 0.0,
        })
    return rec


def _resolve_prediction(pred, obs, sample_interval_s=60.0, trades=None, horizon_s=60.0,
                        label_complete=True, label_metadata=None):
    target_ms = pred.get("target_at_ms", obs["wall_time_ms"])
    start_ms = pred.get("created_at_ms", target_ms)
    end_ms = target_ms
    resolved_ms = obs["wall_time_ms"]
    min_trades = min_forward_trades(horizon_s)
    forward = None
    forward_count = 0
    if trades:
        forward, forward_count = compute_buy_ratio_for_window(
            trades, start_ms, end_ms, min_trades=min_trades,
        )
    if forward is not None and label_complete:
        actual = forward["buy_ratio"]
        resolved_volume = forward.get("buy_ratio_volume")
        resolved_label = "forward_window"
    else:
        actual = obs["buy_ratio"]
        resolved_volume = obs.get("buy_ratio_volume")
        resolved_label = "label_unavailable"

    exit_price = obs["price"]
    gross_return = (exit_price - pred["entry_price"]) / pred["entry_price"] if pred["entry_price"] else 0.0
    cost = FEE_RATE * 2 + pred.get("entry_spread", 0.0) + obs.get("spread", 0.0)
    signal = pred.get("signal", "no_trade")
    if signal == "long":
        net_return = gross_return - cost
    else:
        net_return = 0.0

    resolution_lag_s = max(0.0, (resolved_ms - target_ms) / 1000)
    exit_quality_flags = list(obs.get("quality_flags", []))
    if resolution_lag_s > max(1.0, sample_interval_s * 2):
        exit_quality_flags.append("late_resolution")
    if forward is None:
        exit_quality_flags.append("short_forward_window")
    if forward is None or not label_complete:
        exit_quality_flags.append("label_unavailable")
    elif forward is not None and forward_count <= min_trades + 2:
        exit_quality_flags.append("sparse_forward_window")

    pred.update({
        "status": "resolved",
        "resolved_at_ms": resolved_ms,
        "resolved_time": obs["time"],
        "exit_price": exit_price,
        "resolved_actual": actual,
        "resolved_buy_ratio_volume": resolved_volume,
        "resolved_label": resolved_label,
        "forward_window_start_ms": start_ms,
        "forward_window_end_ms": end_ms,
        "forward_window_trade_count": forward_count,
        "forward_window_min_trades": min_trades,
        "label_capture_complete": bool(label_complete),
        "label_capture": dict(label_metadata or {}),
        "exit_quality_flags": exit_quality_flags,
        "classical_error": abs(pred["classical"] - actual),
        "prediction_error": abs(pred["prediction"] - actual),
        "direction_up": 1.0 if exit_price > pred["entry_price"] else 0.0,
        "gross_return": gross_return,
        "cost": cost,
        "net_return": net_return,
        "resolution_lag_s": resolution_lag_s,
        "score_eligible": (
            not any(f in DISQUALIFYING_QUALITY_FLAGS for f in pred.get("entry_quality_flags", []))
            and not any(f in DISQUALIFYING_QUALITY_FLAGS for f in exit_quality_flags)
        ),
    })
    return pred


def _write_run_state(output_path, store, symbol, mode, horizon_s, sample_interval, window,
                     observations, predictions, ensemble=None, run_id=None,
                     status="running", stop_reason=None, config_hash=None):
    payload = {
        "schema_version": LIVE_SCHEMA_VERSION,
        "run_id": run_id,
        "experiment_id": run_id,
        "config_hash": config_hash,
        "model_version": "born_constructive_v1",
        "data_policy_version": DATA_POLICY_VERSION,
        "experiment_manifest": {
            "model_version": "born_constructive_v1",
            "label_policy": "captured_trade_window_v1",
            "primary_metric": "paired_mae_difference",
            "primary_horizon_s": horizon_s,
            "min_resolved_eligible": MIN_SIGNIFICANCE_N,
        },
        "symbol": symbol,
        "mode": mode,
        "horizon_s": horizon_s,
        "sample_interval_s": sample_interval,
        "window": window,
        "status": status,
        "stop_reason": stop_reason,
    }
    if ensemble is not None:
        payload["ensemble_weights"] = ensemble.weights[:]
        payload["ensemble_performance"] = {
            name: errs[-30:] for name, errs in ensemble.performance.items()
        }
    store.save_state(payload)
    _atomic_write(output_path, store.export_document(payload))


def _has_pending(predictions):
    return any(p.get("status") == "pending" for p in predictions)


def _summarize_resolved(predictions):
    resolved = [p for p in predictions if p.get("status") == "resolved" and p.get("score_eligible", True)]
    if not resolved:
        return None
    c_errs = [p["classical_error"] for p in resolved]
    q_errs = [p["prediction_error"] for p in resolved]
    acts = [p["resolved_actual"] for p in resolved]
    wins = sum(1 for ce, qe in zip(c_errs, q_errs) if qe < ce)
    trades = [p for p in resolved if p.get("signal") == "long"]
    returns = [p["net_return"] for p in trades]
    null_mae = statistics.mean(abs(0.5 - a) for a in acts) if acts else 0.0
    return {
        "n": len(resolved),
        "wins": wins,
        "mean_c": statistics.mean(c_errs),
        "mean_q": statistics.mean(q_errs),
        "null_mae": null_mae,
        "trades": len(trades),
        "avg_net_return": statistics.mean(returns) if returns else 0.0,
        "profit_factor": (
            sum(r for r in returns if r > 0) / abs(sum(r for r in returns if r < 0))
            if any(r < 0 for r in returns) else float("inf") if any(r > 0 for r in returns) else 1.0
        ),
    }


def _stop_reason(predictions, fetch_count, elapsed_s, max_resolved, max_fetches, max_runtime_s):
    eligible_resolved = sum(
        1 for pred in predictions
        if pred.get("status") == "resolved" and pred.get("score_eligible", True)
    )
    if max_resolved is not None and eligible_resolved >= max_resolved:
        return "max_resolved"
    if max_fetches is not None and fetch_count >= max_fetches:
        return "max_fetches"
    if max_runtime_s > 0 and elapsed_s >= max_runtime_s:
        return "max_runtime"
    return None


def _config_hash(symbol, mode, horizon_s, sample_interval, window):
    raw = json.dumps(
        {
            "symbol": symbol,
            "mode": mode,
            "horizon_s": float(horizon_s),
            "sample_interval_s": float(sample_interval),
            "window": int(window),
            "model_version": "born_constructive_v1",
            "data_policy_version": DATA_POLICY_VERSION,
            "label_policy": "captured_trade_window_v1",
            "schema_version": LIVE_SCHEMA_VERSION,
        },
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _resume_paths(run_id):
    prefix = os.path.join(RESULTS_DIR, run_id.replace("-", "_"))
    candidates = [
        os.path.join(RESULTS_DIR, f"{run_id}.sqlite3"),
        prefix + ".sqlite3",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path, os.path.splitext(path)[0] + ".json"
    raise FileNotFoundError(f"No durable run found for {run_id!r}")


def run(symbol="btcusdt", n_steps=None, delay=3600.0, window=15, mode="ensemble",
        sample_interval=60.0, max_resolved=None, max_fetches=None,
        max_runtime_s=0.0, resume_run_id=None,
        _time_fn=None, _monotonic_fn=None, _sleep_fn=None, _data_provider=None):
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    time_fn = _time_fn or time.time
    monotonic_fn = _monotonic_fn or time.monotonic
    sleep_fn = _sleep_fn or _sleep_interruptible

    if delay <= 0 or sample_interval <= 0 or window < 2:
        raise ValueError("horizon, sample interval, and window must be positive")
    if mode not in ("ensemble", "quantum"):
        raise ValueError("mode must be 'ensemble' or 'quantum'")
    if n_steps is not None and max_fetches is None:
        max_fetches = n_steps
    if max_resolved is None and max_fetches is None and max_runtime_s <= 0:
        max_resolved = 720

    hd = _data_provider or HuobiData()
    ensemble = Ensemble(window=window)
    history = []
    observations = []
    predictions = []
    warmup_complete = False
    last_ts = None
    horizon_s = delay
    fetch_count = 0
    started_monotonic = monotonic_fn()
    stop_reason = "user_stop"

    if mode == "quantum":
        ensemble.weights = [1.0, 0.0]
        output_tag = "quantum"
    else:
        output_tag = "ensemble"

    if resume_run_id:
        db_path, output_path = _resume_paths(resume_run_id)
        run_id = resume_run_id
    else:
        started_epoch = int(time.time())
        run_id = f"{symbol}-{output_tag}-{started_epoch}"
        base = os.path.join(RESULTS_DIR, run_id)
        db_path = base + ".sqlite3"
        output_path = base + ".json"

    config_hash = _config_hash(symbol, mode, horizon_s, sample_interval, window)
    store = LiveRunStore(db_path)
    store.prune_trades_before(_wall_ms(time_fn) - TRADE_RETENTION_DAYS * 24 * 3600 * 1000)
    restored = store.load_state()
    if restored:
        if restored.get("config_hash") != config_hash:
            store.close()
            raise ValueError("Resume configuration does not match stored run")
        document = store.export_document(restored)
        observations = document.get("observations", [])
        predictions = document.get("predictions", [])
        history = [
            {k: v for k, v in obs.items() if k not in ("id", "run_id", "symbol", "wall_time_ms", "time")}
            for obs in observations
            if "duplicate_timestamp" not in obs.get("quality_flags", [])
        ]
        last_ts = observations[-1].get("timestamp") if observations else None
        fetch_count = max(
            (int(obs.get("id", -1)) for obs in observations),
            default=-1,
        ) + 1
        warmup_complete = ready_for_forecast(history, window)
        if mode == "ensemble":
            performance = restored.get("ensemble_performance", {})
            for name in ensemble.MODEL_NAMES:
                ensemble.performance[name] = list(performance.get(name, []))
            ensemble._refresh_weights()

    print(f"  {'ENSEMBLE' if mode == 'ensemble' else 'QUANTUM-ONLY'} LIVE PIPELINE")
    print(f"  symbol={symbol}  max_resolved={max_resolved or 'unlimited'}  "
          f"max_fetches={max_fetches or 'unlimited'}  "
          f"max_runtime={'unlimited' if not max_runtime_s else f'{max_runtime_s}s'}")
    print(f"  horizon={horizon_s}s  sample_interval={sample_interval}s  window={window}")
    print(f"  output={output_path}")
    print(f"  database={db_path}")
    print(f"  PID={os.getpid()}")
    print(f"  Started at {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    while _running:
        limit_reason = _stop_reason(
            predictions,
            fetch_count,
            monotonic_fn() - started_monotonic,
            max_resolved,
            max_fetches,
            max_runtime_s,
        )
        if limit_reason:
            stop_reason = limit_reason
            break

        i = fetch_count
        fetch_count += 1
        if not _running:
            break

        if hasattr(hd, "fetch_features_with_trades"):
            features, captured_trades = hd.fetch_features_with_trades(
                symbol,
                trade_size=TRADE_CAPTURE_SIZE,
                feature_lookback_s=feature_lookback_s(horizon_s),
            )
        else:
            features = hd.fetch_features(
                symbol,
                feature_lookback_s=feature_lookback_s(horizon_s),
            )
            captured_trades = hd.fetch_trades(symbol, size=TRADE_CAPTURE_SIZE) if features else []
        if features is None:
            print(f"  [{i:5d}] {time.strftime('%H:%M:%S')} NO DATA — retrying in {sample_interval:.0f}s")
            sleep_fn(sample_interval)
            continue

        obs = _observation(features, symbol, i, run_id=run_id, time_fn=time_fn)
        store.save_trade_batch(
            symbol,
            captured_trades,
            obs["wall_time_ms"],
            TRADE_CAPTURE_SIZE,
        )
        ts = features.get("timestamp") or features.get("collected_at_ms")
        duplicate_ts = ts == last_ts
        if duplicate_ts:
            obs.setdefault("quality_flags", []).append("duplicate_timestamp")
        accepted = store.save_observation(obs)
        if not accepted:
            duplicate_ts = True
            obs.setdefault("quality_flags", []).append("duplicate_timestamp")
        else:
            observations.append(obs)
        if not duplicate_ts and accepted:
            last_ts = ts
            history.append(features)

        state_dirty = False
        for pred in predictions:
            if pred["status"] == "pending" and pending_due(pred, obs["wall_time_ms"]):
                label_window = store.trade_window(
                    symbol,
                    pred.get("created_at_ms", obs["wall_time_ms"]),
                    pred.get("target_at_ms", obs["wall_time_ms"]),
                    sample_interval,
                )
                _resolve_prediction(
                    pred, obs, sample_interval_s=sample_interval,
                    trades=label_window["trades"],
                    horizon_s=horizon_s,
                    label_complete=label_window["capture_complete"],
                    label_metadata={
                        key: value for key, value in label_window.items() if key != "trades"
                    },
                )
                if mode == "ensemble" and pred.get("score_eligible"):
                    stored_raw = {
                        "quantum": pred["quantum_raw"],
                        "vol_regime": pred["vol_regime_raw"],
                    }
                    ensemble.update_from_predictions(stored_raw, pred["resolved_actual"])
                    w = ensemble.weights[:]
                    pred.update({
                        "w_quantum": w[0],
                        "w_vol_regime": w[1],
                    })
                store.save_forecast(pred)
                print(f"  [{i:5d}] {time.strftime('%H:%M:%S')} RESOLVED "
                      f"id={pred['id']} act={pred['resolved_actual']:.3f} "
                      f"c_err={pred['classical_error']:.3f} q_err={pred['prediction_error']:.3f} "
                      f"ret={pred['net_return']:+.5f}")
                state_dirty = True

        if state_dirty:
            summary = _summarize_resolved(predictions)
            if summary and summary["n"] >= 30:
                print(f"         --- resolved {summary['n']}: MAE c={summary['mean_c']:.4f} "
                      f"q={summary['mean_q']:.4f} null(0.5)={summary['null_mae']:.4f} "
                      f"wins={summary['wins']}/{summary['n']} "
                      f"({summary['wins']/summary['n']*100:.0f}%)")
            _write_run_state(
                output_path, store, symbol, mode, horizon_s, sample_interval, window,
                observations, predictions, ensemble if mode == "ensemble" else None,
                run_id=run_id, config_hash=config_hash,
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
                    "bucket_feature": q_meta.get("bucket_feature", "buy_ratio"),
                    "quantum_meta": q_meta,
                }
            else:
                pred_q, w, meta = ensemble.predict(lookback)

            lookback_ids = [o["id"] for o in observations[-window:]]
            pred_record = _prediction_record(
                symbol, i, horizon_s, mode, obs, pred_c, preds_c, pred_q, meta,
                w if mode == "ensemble" else None,
                lookback_observation_ids=lookback_ids,
            )
            predictions.append(pred_record)
            store.save_forecast(pred_record)

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
                output_path, store, symbol, mode, horizon_s, sample_interval, window,
                observations, predictions, ensemble if mode == "ensemble" else None,
                run_id=run_id, config_hash=config_hash,
            )
        elif ready_for_forecast(history, window) and _has_pending(predictions):
            print(f"  [{i:5d}] {time.strftime('%H:%M:%S')} SKIP forecast — pending unresolved")
        else:
            print(f"  [{i:5d}] {time.strftime('%H:%M:%S')} WARMUP ({len(history)}/{window})")

        if (
            not state_dirty
            and i % JSON_EXPORT_INTERVAL == 0
            and (observations or predictions)
            and (_has_pending(predictions) or not warmup_complete)
        ):
            _write_run_state(
                output_path, store, symbol, mode, horizon_s, sample_interval, window,
                observations, predictions, ensemble if mode == "ensemble" else None,
                run_id=run_id, config_hash=config_hash,
            )

        sleep_fn(sample_interval)

    print(f"\n  Stopped at {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Collected {len(observations)} observations, {len(predictions)} predictions")

    if predictions or observations:
        _write_run_state(
            output_path, store, symbol, mode, horizon_s, sample_interval, window,
            observations, predictions, ensemble if mode == "ensemble" else None,
            run_id=run_id, status="completed" if stop_reason == "max_resolved" else "incomplete",
            stop_reason=stop_reason, config_hash=config_hash,
        )
        print(f"  Saved to {output_path}")

        summary = _summarize_resolved(predictions)
        if summary:
            n = summary["n"]
            if n >= 30:
                print(f"\n  FINAL: resolved={n}  c_err={summary['mean_c']:.4f}  q_err={summary['mean_q']:.4f}  "
                      f"null(0.5)={summary['null_mae']:.4f}  "
                      f"wins={summary['wins']}/{n} ({summary['wins']/n*100:.1f}%)")
                if summary["trades"]:
                    print(f"         price-sim diagnostic: {summary['trades']} long  "
                          f"avg_ret={summary['avg_net_return']:+.5f} (not primary metric)")
            else:
                print(f"\n  FINAL: resolved={n}; exploratory only — suppressing win/loss summary until n>=30")

        if summary and summary["n"] >= MIN_SIGNIFICANCE_N:
            print(f"\n  --- Honest live evaluation (block bootstrap, Bonferroni corrected, n>={MIN_SIGNIFICANCE_N}) ---")
            resolved = [p for p in predictions if p.get("status") == "resolved" and p.get("score_eligible", True)]
            c_errs = [p["classical_error"] for p in resolved]
            q_errs = [p["prediction_error"] for p in resolved]
            report = comprehensive_report(
                c_errs, q_errs, f" [live {mode}]",
                periods_per_year=(365.25 * 24 * 3600) / horizon_s,
                live=True,
            )
            print_report(report, detail=True)
        elif summary and summary["n"] >= 30:
            print(f"\n  FINAL: exploratory summary only — need n>={MIN_SIGNIFICANCE_N} for significance report")
        else:
            print("\n  FINAL: exploratory only — need at least 30 resolved eligible predictions")
    store.close()
    return _exit_code_for_stop_reason(stop_reason)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Durable live Exchange-Q evaluation")
    parser.add_argument("legacy", nargs="*", help=argparse.SUPPRESS)
    parser.add_argument("--symbol", default="btcusdt")
    parser.add_argument("--mode", choices=("quantum", "ensemble"), default="quantum")
    parser.add_argument("--horizon-s", type=float, default=3600.0)
    parser.add_argument("--sample-interval-s", type=float, default=60.0)
    parser.add_argument("--window", type=int, default=15)
    parser.add_argument("--max-resolved", type=int, default=None)
    parser.add_argument("--max-fetches", type=int, default=None)
    parser.add_argument("--max-runtime-s", type=float, default=0.0)
    parser.add_argument("--resume", default=None, metavar="RUN_ID")
    args = parser.parse_args()

    if args.legacy:
        if len(args.legacy) > 6:
            parser.error("too many positional arguments")
        symbol = args.legacy[0] if len(args.legacy) > 0 else args.symbol
        max_fetches = int(args.legacy[1]) if len(args.legacy) > 1 else args.max_fetches
        horizon_s = float(args.legacy[2]) if len(args.legacy) > 2 else args.horizon_s
        mode = args.legacy[3] if len(args.legacy) > 3 else args.mode
        sample_interval_s = float(args.legacy[4]) if len(args.legacy) > 4 else args.sample_interval_s
        window = int(args.legacy[5]) if len(args.legacy) > 5 else args.window
        print("WARNING: positional CLI is deprecated; use named options", file=sys.stderr)
    else:
        symbol = args.symbol
        max_fetches = args.max_fetches
        horizon_s = args.horizon_s
        mode = args.mode
        sample_interval_s = args.sample_interval_s
        window = args.window

    sys.exit(run(
        symbol=symbol,
        delay=horizon_s,
        mode=mode,
        sample_interval=sample_interval_s,
        window=window,
        max_resolved=args.max_resolved,
        max_fetches=max_fetches,
        max_runtime_s=args.max_runtime_s,
        resume_run_id=args.resume,
    ))
