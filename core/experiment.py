#!/usr/bin/env python3

"""
Experiment: Classical vs Quantum prediction on synthetic market data.

Delta for the live-like path comes from compute_delta (market features).
A separate hidden-sign probe uses delta=0/π from the known hidden context —
this is NOT a true oracle / argmin upper bound.
"""

import math
import statistics
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from market_sim import MarketSimulator, classical_model, quantum_model, quantum_model_diagnostic
from delta_adaptive import compute_delta


def _pct_improvement(baseline_err, model_err):
    if not baseline_err:
        return 0.0
    return (baseline_err - model_err) / baseline_err * 100


def run_experiment(n_agents=30, n_steps=500, window=20):
    sim = MarketSimulator(n_agents=n_agents)

    context_sequence = []
    for i in range(n_steps):
        phase = 2 * math.pi * i / n_steps
        context_sequence.append(1.2 * math.sin(phase))

    results = []

    for t in range(n_steps):
        hidden = context_sequence[t]
        sim.step(hidden)

        if t >= window:
            lookback = sim.history[t - window:t]

            actual_ratio = sim.history[t]['buy_ratio']

            classical_pred = classical_model(lookback)

            delta, _ = compute_delta(lookback)
            quantum_pred = quantum_model(lookback, delta)

            # Hidden-sign probe: delta=0 if hidden>0 else π.
            # Heuristic only — not an optimized argmin over δ.
            hidden_sign_delta = 0.0 if hidden > 0 else math.pi
            quantum_hidden_sign_pred = quantum_model(lookback, hidden_sign_delta)

            _, diag_computed = quantum_model_diagnostic(lookback, delta)

            results.append({
                'step': t,
                'hidden_context': hidden,
                'price': sim.history[t]['price'],
                'actual_buy_ratio': actual_ratio,
                'classical_pred': classical_pred,
                'quantum_pred': quantum_pred,
                'quantum_oracle_pred': quantum_hidden_sign_pred,  # legacy key
                'quantum_hidden_sign_pred': quantum_hidden_sign_pred,
                'classical_error': abs(classical_pred - actual_ratio),
                'quantum_error': abs(quantum_pred - actual_ratio),
                'quantum_oracle_error': abs(quantum_hidden_sign_pred - actual_ratio),
                'quantum_hidden_sign_error': abs(quantum_hidden_sign_pred - actual_ratio),
                'delta': delta,
                'oracle_delta': hidden_sign_delta,
                'hidden_sign_delta': hidden_sign_delta,
                'hidden_separation': diag_computed.get('hidden_separation', 0),
                'mean_hidden_high': diag_computed.get('mean_hidden_high', 0),
                'mean_hidden_low': diag_computed.get('mean_hidden_low', 0),
            })

    return results


def analyze_results(results, n_agents):
    classical_errors = [r['classical_error'] for r in results]
    quantum_errors = [r['quantum_error'] for r in results]
    quantum_hidden_sign_errors = [r['quantum_hidden_sign_error'] for r in results]

    mean_classical_err = statistics.mean(classical_errors)
    mean_quantum_err = statistics.mean(quantum_errors)
    mean_quantum_hidden_sign_err = statistics.mean(quantum_hidden_sign_errors)

    classical_wins = sum(1 for r in results if r['classical_error'] < r['quantum_error'])
    quantum_wins = sum(1 for r in results if r['quantum_error'] < r['classical_error'])
    ties = len(results) - classical_wins - quantum_wins

    hs_beats_classical = sum(
        1 for r in results if r['quantum_hidden_sign_error'] < r['classical_error']
    )
    hs_ties_classical = sum(
        1 for r in results if r['quantum_hidden_sign_error'] == r['classical_error']
    )
    hs_loses = len(results) - hs_beats_classical - hs_ties_classical

    high_context_results = [r for r in results if abs(r['hidden_context']) > 0.5]
    high_classical_err = statistics.mean([r['classical_error'] for r in high_context_results]) if high_context_results else 0
    high_quantum_err = statistics.mean([r['quantum_error'] for r in high_context_results]) if high_context_results else 0
    high_quantum_hs_err = statistics.mean([r['quantum_hidden_sign_error'] for r in high_context_results]) if high_context_results else 0

    low_context_results = [r for r in results if abs(r['hidden_context']) <= 0.5]
    low_classical_err = statistics.mean([r['classical_error'] for r in low_context_results]) if low_context_results else 0
    low_quantum_err = statistics.mean([r['quantum_error'] for r in low_context_results]) if low_context_results else 0
    low_quantum_hs_err = statistics.mean([r['quantum_hidden_sign_error'] for r in low_context_results]) if low_context_results else 0

    hidden_seps = [r.get('hidden_separation', 0) for r in results]
    mean_hidden_high = statistics.mean([r.get('mean_hidden_high', 0) for r in results])
    mean_hidden_low = statistics.mean([r.get('mean_hidden_low', 0) for r in results])

    return {
        'mean_classical_error': mean_classical_err,
        'mean_quantum_error': mean_quantum_err,
        'mean_quantum_oracle_error': mean_quantum_hidden_sign_err,  # legacy alias
        'mean_quantum_hidden_sign_error': mean_quantum_hidden_sign_err,
        'classical_wins': classical_wins,
        'quantum_wins': quantum_wins,
        'ties': ties,
        'oracle_beats_classical': hs_beats_classical,
        'oracle_ties_classical': hs_ties_classical,
        'oracle_loses': hs_loses,
        'high_context_classical_err': high_classical_err,
        'high_context_quantum_err': high_quantum_err,
        'high_context_quantum_oracle_err': high_quantum_hs_err,
        'low_context_classical_err': low_classical_err,
        'low_context_quantum_err': low_quantum_err,
        'low_context_quantum_oracle_err': low_quantum_hs_err,
        'mean_hidden_separation': statistics.mean(hidden_seps) if hidden_seps else 0,
        'mean_hidden_high': mean_hidden_high,
        'mean_hidden_low': mean_hidden_low,
        'n_agents': n_agents,
        'n_steps': len(results),
    }


def print_report(stats):
    print("=" * 70)
    print("  EXPERIMENT: Classical vs Quantum Prediction (Synthetic Data)")
    print(f"  Agents: {stats['n_agents']}  |  Steps: {stats['n_steps']}")
    print("=" * 70)

    print(f"\n  ┌─ MODEL COMPARISON ─────────────────────────────┐")
    print(f"  │ {'Model':<30s} {'Mean Error':>12s} │")
    print(f"  ├────────────────────────────────────────────────┤")
    print(f"  │ {'Classical (rolling mean)':<30s} {stats['mean_classical_error']:>12.4f} │")
    print(f"  │ {'Quantum (computed delta)':<30s} {stats['mean_quantum_error']:>12.4f} │")
    print(f"  │ {'Quantum (hidden-sign δ)':<30s} {stats['mean_quantum_hidden_sign_error']:>12.4f} │")
    print(f"  └────────────────────────────────────────────────┘")

    imprv_comp = _pct_improvement(stats['mean_classical_error'], stats['mean_quantum_error'])
    imprv_hs = _pct_improvement(
        stats['mean_classical_error'], stats['mean_quantum_hidden_sign_error']
    )
    print(f"\n  Improvement (computed delta):   {imprv_comp:+.1f}%")
    print(f"  Improvement (hidden-sign delta): {imprv_hs:+.1f}%")

    print(f"\n  ┌─ WIN COUNTS ────────────────────────────────────┐")
    print(f"  │ {'Comparison':<25s} {'Wins':>6s} {'Ties':>5s} {'Losses':>7s} │")
    print(f"  ├────────────────────────────────────────────────┤")
    print(f"  │ {'Classical vs Quantum':<25s} {stats['classical_wins']:>6d} {stats['ties']:>5d} {stats['quantum_wins']:>7d} │")
    print(f"  │ {'Classical vs hidden-sign':<25s} {stats['oracle_loses']:>6d} {stats['oracle_ties_classical']:>5d} {stats['oracle_beats_classical']:>7d} │")
    print(f"  └────────────────────────────────────────────────┘")

    print(f"\n  ┌─ HIGH CONTEXT (|context| > 0.5) ────────────────┐")
    print(f"  │ {'Classical':<30s} {stats['high_context_classical_err']:>12.4f} │")
    print(f"  │ {'Quantum (computed)':<30s} {stats['high_context_quantum_err']:>12.4f} │")
    print(f"  │ {'Quantum (hidden-sign)':<30s} {stats['high_context_quantum_oracle_err']:>12.4f} │")
    print(f"  └────────────────────────────────────────────────┘")

    print(f"\n  ┌─ LOW CONTEXT (|context| <= 0.5) ────────────────┐")
    print(f"  │ {'Classical':<30s} {stats['low_context_classical_err']:>12.4f} │")
    print(f"  │ {'Quantum (computed)':<30s} {stats['low_context_quantum_err']:>12.4f} │")
    print(f"  │ {'Quantum (hidden-sign)':<30s} {stats['low_context_quantum_oracle_err']:>12.4f} │")
    print(f"  └────────────────────────────────────────────────┘")

    print(f"\n  ┌─ MEDIAN SPLIT DIAGNOSTIC ───────────────────────┐")
    print(f"  │ Mean hidden context in HIGH bucket:  {stats['mean_hidden_high']:>10.4f} │")
    print(f"  │ Mean hidden context in LOW bucket:   {stats['mean_hidden_low']:>10.4f} │")
    print(f"  │ Hidden context separation (high-low): {stats['mean_hidden_separation']:>10.4f} │")
    print(f"  └────────────────────────────────────────────────┘")
    if stats['mean_hidden_separation'] < 0.3:
        print(f"  >>> WARNING: Median split barely separates hidden context.")
        print(f"  >>> The Born rule cannot exploit interference if the")
        print(f"  >>> two buckets have similar hidden context values.")

    print()
    print("  NOTE: 'computed delta' uses compute_delta() from market features")
    print("        (same path as live). 'hidden-sign delta' sets δ=0/π from")
    print("        known hidden context sign — a heuristic probe, NOT a true")
    print("        oracle / argmin upper bound over δ.")
    print("=" * 70)


def main():
    import random
    random.seed(42)

    print("Running experiment with computed delta + hidden-sign delta probe...\n")
    results = run_experiment(n_agents=30, n_steps=500, window=20)
    stats = analyze_results(results, n_agents=30)
    print_report(stats)

    if stats['mean_quantum_hidden_sign_error'] < stats['mean_classical_error']:
        print(f"\n  >>> HIDDEN-SIGN Born probe beats classical by "
              f"{_pct_improvement(stats['mean_classical_error'], stats['mean_quantum_hidden_sign_error']):.1f}%")
        print(f"  >>> Suggests some phase signal exists, but this is not a true optimum.")
    else:
        print(f"\n  >>> HIDDEN-SIGN Born probe does NOT beat classical either.")
        print(f"  >>> The quantum model formulation / median split may be inadequate")
        print(f"  >>> for this synthetic data structure.")


if __name__ == "__main__":
    main()
