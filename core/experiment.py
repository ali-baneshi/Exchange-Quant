#!/usr/bin/env python3

"""
Experiment: Classical vs Quantum prediction on synthetic market data.
FIXED: delta is now computed from market context (like real pipeline),
not optimized against actual outcomes.
"""

import math
import statistics
import cmath
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from market_sim import MarketSimulator, classical_model, quantum_model
from delta_adaptive import compute_delta


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

            # FIXED: delta is computed from market-like context features,
            # NOT by searching over 21 values to minimize error.
            # This mirrors how the real pipeline works.
            delta, _ = compute_delta(lookback)
            quantum_pred = quantum_model(lookback, delta)

            results.append({
                'step': t,
                'hidden_context': hidden,
                'price': sim.history[t]['price'],
                'actual_buy_ratio': actual_ratio,
                'classical_pred': classical_pred,
                'quantum_pred': quantum_pred,
                'classical_error': abs(classical_pred - actual_ratio),
                'quantum_error': abs(quantum_pred - actual_ratio),
                'delta': delta,
            })

    return results


def analyze_results(results, n_agents):
    classical_errors = [r['classical_error'] for r in results]
    quantum_errors = [r['quantum_error'] for r in results]

    mean_classical_err = statistics.mean(classical_errors)
    mean_quantum_err = statistics.mean(quantum_errors)

    classical_wins = sum(1 for r in results if r['classical_error'] < r['quantum_error'])
    quantum_wins = sum(1 for r in results if r['quantum_error'] < r['classical_error'])
    ties = len(results) - classical_wins - quantum_wins

    high_context_results = [r for r in results if abs(r['hidden_context']) > 0.5]
    high_classical_err = statistics.mean([r['classical_error'] for r in high_context_results])
    high_quantum_err = statistics.mean([r['quantum_error'] for r in high_context_results])

    low_context_results = [r for r in results if abs(r['hidden_context']) <= 0.5]
    low_classical_err = statistics.mean([r['classical_error'] for r in low_context_results]) if low_context_results else 0
    low_quantum_err = statistics.mean([r['quantum_error'] for r in low_context_results]) if low_context_results else 0

    return {
        'mean_classical_error': mean_classical_err,
        'mean_quantum_error': mean_quantum_err,
        'classical_wins': classical_wins,
        'quantum_wins': quantum_wins,
        'ties': ties,
        'high_context_classical_err': high_classical_err,
        'high_context_quantum_err': high_quantum_err,
        'low_context_classical_err': low_classical_err,
        'low_context_quantum_err': low_quantum_err,
        'n_agents': n_agents,
        'n_steps': len(results),
    }


def print_report(stats):
    print("=" * 70)
    print("  EXPERIMENT: Classical vs Quantum Prediction")
    print(f"  Agents: {stats['n_agents']}  |  Steps: {stats['n_steps']}")
    print("=" * 70)
    print(f"\n  Overall Error (mean):")
    print(f"    Classical:  {stats['mean_classical_error']:.4f}")
    print(f"    Quantum:    {stats['mean_quantum_error']:.4f}")
    improvement = (stats['mean_classical_error'] - stats['mean_quantum_error']) / stats['mean_classical_error'] * 100
    print(f"    Improvement: {improvement:+.1f}%\n")
    print(f"  Win count:")
    print(f"    Classical better: {stats['classical_wins']} steps")
    print(f"    Quantum better:   {stats['quantum_wins']} steps")
    print(f"    Ties:             {stats['ties']} steps\n")
    print(f"  Error when |context| > 0.5 (high interference):")
    print(f"    Classical:  {stats['high_context_classical_err']:.4f}")
    print(f"    Quantum:    {stats['high_context_quantum_err']:.4f}")
    high_improvement = (stats['high_context_classical_err'] - stats['high_context_quantum_err']) / stats['high_context_classical_err'] * 100
    print(f"    Improvement: {high_improvement:+.1f}%\n")
    print(f"  Error when |context| <= 0.5 (low interference):")
    print(f"    Classical:  {stats['low_context_classical_err']:.4f}")
    print(f"    Quantum:    {stats['low_context_quantum_err']:.4f}")
    if stats['low_context_classical_err'] > 0:
        low_improvement = (stats['low_context_classical_err'] - stats['low_context_quantum_err']) / stats['low_context_classical_err'] * 100
        print(f"    Improvement: {low_improvement:+.1f}%")
    print()
    print("  NOTE: delta is computed from market context (NOT optimized")
    print("  against actual outcomes). This is an HONEST evaluation.")
    print("=" * 70)


def main():
    import random
    random.seed(42)

    print("Running experiment with FIXED delta (context-based, not optimized)...\n")
    results = run_experiment(n_agents=30, n_steps=500, window=20)
    stats = analyze_results(results, n_agents=30)
    print_report(stats)


if __name__ == "__main__":
    main()
