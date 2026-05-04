"""Timing utilities for acceptance tests.

Tracks execution time and compares against baselines. Issues warnings
(not failures) when runtime exceeds expectations.
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path

BASELINES_FILE = Path(__file__).parent.parent.parent / "test_data" / "acceptance" / "timing_baselines.json"


def load_baselines() -> dict:
    """Load timing baselines from JSON file."""
    if BASELINES_FILE.exists():
        with open(BASELINES_FILE) as f:
            return json.load(f)
    return {}


def check_timing(test_key: str, elapsed: float) -> None:
    """Compare elapsed time against baseline, warn if too slow.

    Args:
        test_key: Key like "esmfold_protein_gpu" matching baselines file.
        elapsed: Actual wall-clock time in seconds.
    """
    baselines = load_baselines()
    baseline = baselines.get(test_key)
    if baseline is None:
        return

    typical = baseline.get("typical_s", 0)
    max_expected = baseline.get("max_s", typical * 3)

    if elapsed > max_expected:
        warnings.warn(
            f"Timing regression: {test_key} took {elapsed:.1f}s "
            f"(expected max {max_expected:.0f}s, typical {typical:.0f}s)",
            stacklevel=2,
        )
