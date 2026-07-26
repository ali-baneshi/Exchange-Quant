#!/usr/bin/env python3

"""
Sparkline visualization for the synthetic experiment.

Runs the experiment (classical vs quantum on synthetic data)
and renders ASCII sparklines for comparison.

Usage:
    python3 visualize.py
"""

import math
import statistics
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from experiment import run_experiment, analyze_results


def sparkline(values, width=50, min_val=None, max_val=None):
    """Render a sparkline from a list of floats."""
    blocks = [' ', chr(0x2581), chr(0x2582), chr(0x2583),
              chr(0x2584), chr(0x2585), chr(0x2586), chr(0x2587)]
    if not values:
        return ''
    lo = min_val if min_val is not None else min(values)
    hi = max_val if max_val is not None else max(values)
    span = hi - lo
    if span == 0:
        return blocks[0] * width
    out = []
    for v in values:
        idx = int((v - lo) / span * (len(blocks) - 1))
        idx = max(0, min(idx, len(blocks) - 1))
        out.append(blocks[idx])
    stride = max(1, len(out) // width)
    sampled = out[::stride][:width]
    while len(sampled) < width:
        sampled.append(blocks[0])
    return ''.join(sampled)


def main():
    import random
    random.seed(42)

    results = run_experiment(n_agents=30, n_steps=500, window=20)
    stats = analyze_results(results, n_agents=30)

    print("=" * 72)
    print("  QUANTUM INTERFERENCE DEMONSTRATION - VISUAL REPORT")
    print("=" * 72)

    contexts = [r['hidden_context'] for r in results]
    actual_ratios = [r['actual_buy_ratio'] for r in results]
    classical_errs = [r['classical_error'] for r in results]
    quantum_errs = [r['quantum_error'] for r in results]
    quantum_oracle_errs = [r['quantum_oracle_error'] for r in results]

    all_errs = classical_errs + quantum_errs + quantum_oracle_errs
    err_min = min(all_errs)
    err_max = max(all_errs)

    print(f"\n  Hidden Context (sinusoidal sweep):")
    print(f"  {sparkline(contexts)}")
    print(f"  min={min(contexts):.2f}  max={max(contexts):.2f}")

    print(f"\n  Actual Buy Ratio:")
    print(f"  {sparkline(actual_ratios)}")
    print(f"  min={min(actual_ratios):.2f}  max={max(actual_ratios):.2f}")

    print(f"\n  Classical Prediction Error:")
    print(f"  {sparkline(classical_errs, min_val=err_min, max_val=err_max)}")
    print(f"  mean={statistics.mean(classical_errs):.4f}")

    print(f"\n  Quantum Prediction Error (computed delta):")
    print(f"  {sparkline(quantum_errs, min_val=err_min, max_val=err_max)}")
    print(f"  mean={statistics.mean(quantum_errs):.4f}")

    print(f"\n  Quantum Prediction Error (hidden-sign δ probe):")
    print(f"  {sparkline(quantum_oracle_errs, min_val=err_min, max_val=err_max)}")
    print(f"  mean={statistics.mean(quantum_oracle_errs):.4f}")

    print()
    print("-" * 72)
    print("  INTERPRETATION")
    print("-" * 72)
    print(f"""
  The sparklines above show {len(results)} time steps of a synthetic market.
  The 'hidden context' oscillates sinusoidally.

  Three models are compared:
    - Classical: rolling mean of recent buy_ratio (cannot see hidden context)
    - Quantum (computed delta): Born rule with delta from market features
    - Quantum (hidden-sign δ):  Born rule with δ=0/π from known hidden
                                context sign — heuristic probe, NOT a true
                                oracle / argmin upper bound

  If hidden-sign quantum beats classical but COMPUTED quantum does not:
    -> Some phase signal may exist, but compute_delta() fails to extract it.

  If even the hidden-sign probe cannot beat classical:
    -> The median-split Born formulation may be inadequate for this
       hidden-context structure.

  Synthetic imbalance is derived from buy_ratio — not a real order book.
""")

    print("-" * 72)
    print("  FINANCIAL INTERPRETATION")
    print("-" * 72)
    print("""
  In real markets, the 'hidden context' corresponds to:
    - Unobserved order flow (dark pool activity)
    - Latent sentiment (not yet expressed in price)
    - Macro expectations (not yet priced in)
    - MEV bots waiting for confirmation

  Live Born-rule evaluation requires real order-book imbalance
  (pipeline_live_ensemble.py), not kline proxies.
""")

    def _pct(base, model):
        return (base - model) / base * 100 if base else 0.0

    imprv_comp = _pct(stats['mean_classical_error'], stats['mean_quantum_error'])
    imprv_oracle = _pct(stats['mean_classical_error'], stats['mean_quantum_oracle_error'])
    print("=" * 72)
    print(f"  Summary: {stats['n_steps']} steps")
    print(f"    Classical err:                {stats['mean_classical_error']:.4f}")
    print(f"    Quantum err (computed δ):     {stats['mean_quantum_error']:.4f}  ({imprv_comp:+.1f}%)")
    print(f"    Quantum err (hidden-sign δ):  {stats['mean_quantum_oracle_error']:.4f}  ({imprv_oracle:+.1f}%)")
    print(f"    Hidden context separation:    {stats['mean_hidden_separation']:.4f}")
    print("=" * 72)


if __name__ == "__main__":
    main()
