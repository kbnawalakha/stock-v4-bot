import math
from typing import Any

import numpy as np
import pandas as pd


def clamp(value: float | int | None, low: float = 0.0, high: float = 100.0) -> float:
    try:
        if value is None or pd.isna(value):
            return float((low + high) / 2)
        return float(np.clip(float(value), low, high))
    except Exception:
        return float((low + high) / 2)


def neutral_signed(reason: str = "data unavailable") -> dict[str, Any]:
    return {"score": 0.0, "reason": reason}


def signed_to_percent(score: float | int | None) -> float:
    return clamp(50.0 + float(score or 0.0) / 2.0, 0.0, 100.0)


def safe_float(value: Any) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def pct_change(newer: float | None, older: float | None) -> float | None:
    if newer is None or older in (None, 0):
        return None
    return (newer / older - 1.0) * 100.0


def weighted_average(parts: list[tuple[float, float]]) -> float:
    total_weight = sum(weight for _, weight in parts if weight > 0)
    if total_weight <= 0:
        return 0.0
    return sum(value * weight for value, weight in parts if weight > 0) / total_weight


def informative_weighted_average(
    parts: list[tuple[float, float]],
    neutral: float = 50.0,
    missing_weight_factor: float = 0.2,
    neutral_tol: float = 0.5,
) -> float:
    """Weighted average that down-weights signals sitting at their neutral
    placeholder (e.g. 50.0 when an API key is missing or there is no data).

    Signals with real information keep full weight; placeholder-neutral signals
    are kept at a small fraction of their weight so they nudge, but do not
    dilute, the composite. This prevents the common failure mode where many
    missing signals default to 50 and crush every stock's score into a narrow
    band, destroying the ranking's ability to separate winners from losers.

    If every signal is neutral the result is the neutral value (not 0), so a
    data-starved row scores as genuinely neutral rather than as a hard zero.
    """
    adjusted = []
    for value, weight in parts:
        if weight <= 0:
            continue
        if abs(float(value) - neutral) <= neutral_tol:
            weight *= missing_weight_factor
        adjusted.append((float(value), weight))
    total_weight = sum(weight for _, weight in adjusted)
    if total_weight <= 0:
        return float(neutral)
    return sum(value * weight for value, weight in adjusted) / total_weight


def freshness_warning(missing: list[str]) -> str:
    if not missing:
        return "all core data available"
    return "missing: " + ", ".join(sorted(set(missing)))


def log_score(value: float, scale: float = 12.0, cap: float = 100.0) -> float:
    if value <= 0:
        return 0.0
    return clamp(math.log1p(value) * scale, 0.0, cap)
