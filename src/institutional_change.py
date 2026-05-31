import pandas as pd

from institutional import institutional_ownership_score
from market_data import get_ticker_obj
from signal_utils import clamp, safe_float


def institutional_change_score(ticker: str) -> dict[str, float | str]:
    static = institutional_ownership_score(ticker)
    try:
        obj = get_ticker_obj(ticker)
        holders = getattr(obj, "institutional_holders", None)
        frame = holders if isinstance(holders, pd.DataFrame) else pd.DataFrame()
        holder_count = len(frame)
        total_value = _total_value(frame)
        concentration = _top_holder_concentration(frame)

        change_score = 50.0
        reason = static.get("reason", "institutional support is neutral")
        if holder_count >= 20:
            change_score += 15
        elif holder_count <= 3:
            change_score -= 10
        if total_value > 1_000_000_000:
            change_score += 10
        if concentration > 40:
            change_score -= 15
            reason = "institutional concentration is high"

        merged = clamp(static.get("score", 50.0) * 0.65 + change_score * 0.35, 0, 100)
        return {
            "score": merged,
            "static_score": float(static.get("score", 50.0)),
            "holder_count": float(holder_count),
            "holder_count_change": 0.0,
            "reported_value_change": 0.0,
            "top_holder_concentration": float(concentration),
            "reason": reason,
        }
    except Exception:
        return {
            "score": float(static.get("score", 50.0)),
            "static_score": float(static.get("score", 50.0)),
            "holder_count": 0.0,
            "holder_count_change": 0.0,
            "reported_value_change": 0.0,
            "top_holder_concentration": 0.0,
            "reason": static.get("reason", "institutional change data unavailable"),
        }


def _total_value(frame: pd.DataFrame) -> float:
    if frame.empty:
        return 0.0
    total = 0.0
    for col in frame.columns:
        if "value" in str(col).lower():
            values = pd.to_numeric(frame[col], errors="coerce").fillna(0)
            total += float(values.sum())
    return total


def _top_holder_concentration(frame: pd.DataFrame) -> float:
    if frame.empty:
        return 0.0
    percent_cols = [col for col in frame.columns if "%" in str(col).lower() or "out" in str(col).lower()]
    for col in percent_cols:
        values = pd.to_numeric(frame[col].astype(str).str.replace("%", "", regex=False), errors="coerce").dropna()
        if not values.empty:
            value = safe_float(values.max())
            if value is not None:
                return value * 100 if value <= 1 else value
    return 0.0
