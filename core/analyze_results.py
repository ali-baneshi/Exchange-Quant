#!/usr/bin/env python3

"""
DEPRECATED: use analyze_live_results.py instead.

Legacy analyzer for list-format live JSON results.
"""

import warnings

warnings.warn(
    "analyze_results.py is deprecated; use analyze_live_results.py",
    DeprecationWarning,
    stacklevel=2,
)

import json
import os
import sys
import statistics
import math

from validation import comprehensive_report, print_report, N_HYPOTHESES_TOTAL

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "_live_results")


def load_results(paths):
    combined = []
    for p in paths:
        with open(p) as f:
            data = json.load(f)
        combined.append((os.path.basename(p), data))
    return combined


def summarize(data_list):
    print(f"{'='*70}")
    print(f"  EXCHANGE-Q — Live Results Analysis")
    print(f"  Hypotheses under test (Bonferroni n={N_HYPOTHESES_TOTAL})")
    print(f"{'='*70}")

    all_c = []
    all_q = []
    all_labels = []
    combined_c = []
    combined_q = []

    for fname, results in data_list:
        n = len(results)
        if n < 2:
            print(f"\n  Skipping {fname}: only {n} samples")
            continue

        c_errs = [abs(r["classical"] - r["actual"]) for r in results]
        q_errs = [abs(r["prediction"] - r["actual"]) for r in results]

        report = comprehensive_report(
            c_errs, q_errs,
            label=f" [{fname}]",
            periods_per_year=35040,
        )
        print_report(report, detail=True)

        all_c.append(c_errs)
        all_q.append(q_errs)
        all_labels.append(fname)
        combined_c.extend(c_errs)
        combined_q.extend(q_errs)

    if len(data_list) > 1:
        combined_report = comprehensive_report(
            combined_c, combined_q,
            label=" [COMBINED]",
            periods_per_year=35040,
        )
        print_report(combined_report, detail=True)


def main():
    args = sys.argv[1:]
    if not args:
        files = sorted(
            f for f in os.listdir(RESULTS_DIR)
            if f.endswith(".json") and f != "state.json" and f != "results_ensemble.json"
        )
        if not files:
            print(f"  No result files found in {RESULTS_DIR}")
            print(f"  Usage: {sys.argv[0]} [file1.json file2.json ...]")
            sys.exit(1)
        paths = [os.path.join(RESULTS_DIR, f) for f in files]
    else:
        paths = [p if os.path.isabs(p) else os.path.join(RESULTS_DIR, p) for p in args]
        for p in paths:
            if not os.path.exists(p):
                print(f"  File not found: {p}")
                sys.exit(1)

    data_list = load_results(paths)
    summarize(data_list)


if __name__ == "__main__":
    main()
