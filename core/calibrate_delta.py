#!/usr/bin/env python3

"""
DEPRECATED: Born rule removed from kline-based evaluation (2026-07-23).

This calibrated delta (interference phase) for the Born rule using
historical klines. Since Born rule is removed from all kline evaluation,
this calibration is no longer relevant.

The delta computation for live order-book data remains in:
  core/delta_adaptive.py
"""

import sys
import warnings

warnings.warn(
    "calibrate_delta.py is deprecated (Born rule removed from klines)",
    DeprecationWarning,
    stacklevel=2,
)


def main():
    print("""
    ========================================================================
      calibrate_delta.py — DEPRECATED (exit code 1)

      Born rule has been removed from all kline-based evaluation (2026-07-23).
      Delta calibration on klines is no longer relevant.

      Delta computation for live order-book data:
        core/delta_adaptive.py

      Classical report / live Born path:
        python3 core/validation_report.py --period 60min
        python3 core/pipeline_live_ensemble.py btcusdt 720 3600 quantum
    ========================================================================
    """)
    return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    sys.exit(main())
