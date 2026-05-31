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


def freshness_warning(missing: list[str]) -> str:
    if not missing:
        return "all core data available"
    return "missing: " + ", ".join(sorted(set(missing)))


def log_score(value: float, scale: float = 12.0, cap: float = 100.0) -> float:
    if value <= 0:
        return 0.0
    return clamp(math.log1p(value) * scale, 0.0, cap)
