from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass
class CaptureHooks:
    record_clock_sample: Callable[[int, int, int], None] | None = None
    record_recovery: Callable[[str, str, int, int, str, int, str], None] | None = None
    record_continuity_gap: Callable[..., None] | None = None
