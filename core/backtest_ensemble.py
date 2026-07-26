#!/usr/bin/env python3

"""
DEPRECATED: Born rule removed from kline-based evaluation (2026-07-23).

Born rule requires order-book imbalance and cannot work on kline-only data.
All quantum comparisons on klines showed p = 1.0.
Classical-only backtesting is handled by `backtest.py`.

See also: core/pipeline_live_ensemble.py (Born rule on live order-book data)
"""

import sys
import warnings

warnings.warn(
    "backtest_ensemble.py is deprecated (Born rule removed from klines)",
    DeprecationWarning,
    stacklevel=2,
)


def main():
    print("""
    ========================================================================
      backtest_ensemble.py — DEPRECATED (exit code 1)

      Born rule has been removed from all kline-based evaluation (2026-07-23).
      Reason: Born rule requires real order-book imbalance data which is
      not available in historical klines. All p-values were 1.0 on 5000
      candles across all timeframes.

      Use instead:
        python3 core/backtest.py
        python3 core/validation_report.py --period 60min
        python3 core/pipeline_live_ensemble.py btcusdt 720 3600 quantum
    ========================================================================
    """)
    return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    sys.exit(main())
