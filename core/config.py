#!/usr/bin/env python3

"""
Shared configuration constants for Exchange-Q.
"""

# Historical data
HELD_OUT_FRAC = 0.2

# Ensemble weighting
RELATIVE_K = 10.0

# Live pipeline trading simulation
FEE_RATE = 0.001
LONG_THRESHOLD = 0.60
FLAT_THRESHOLD = 0.40

# Statistical testing (increment when adding a new pre-registered hypothesis)
N_HYPOTHESES_TOTAL = 5

# Live protocol defaults
DEFAULT_WINDOW = 15
DEFAULT_HORIZON_S = 3600.0
