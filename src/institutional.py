import json
import logging

import numpy as np
import pandas as pd

from market_data import get_ticker_obj

logger = logging.getLogger(__name__)


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return float(np.clip(value, low, high))


def institutional_ownership_score(ticker: str) -> dict[str, float | str]:
    try:
        obj = get_ticker_obj(ticker)
        institutional = _safe_frame(getattr(obj, "institutional_holders", None))
        mutual_funds = _safe_frame(getattr(obj, "mutualfund_holders", None))
        major = _safe_frame(getattr(obj, "major_holders", None))

        institutional_pct = _major_holder_percent(major)
        holder_count = len(institutional)
        mutual_fund_count = len(mutual_funds)
        top_holder_weight = _top_holder_weight(institutional)
        total_reported_value = _total_reported_value(institutional)

        ownership_score = _clamp(institutional_pct * 1.15) if institutional_pct else 50.0
        breadth_score = _clamp(np.log1p(holder_count + mutual_fund_count) * 18)
        value_score = _clamp(np.log10(max(total_reported_value, 1.0)) * 7)
        concentration_score = _clamp(100 - max(0.0, top_holder_weight - 12) * 4)

        score = _clamp(
            ownership_score * 0.40
            + breadth_score * 0.25
            + value_score * 0.20
            + concentration_score * 0.15
        )

        return {
            "score": score,
            "institutional_percent": float(institutional_pct),
            "holder_count": float(holder_count),
            "mutual_fund_count": float(mutual_fund_count),
            "top_holder_weight": float(top_holder_weight),
            "reported_value": float(total_reported_value),
            "reason": _reason(score, institutional_pct, holder_count, top_holder_weight),
        }
    except Exception as exc:
        logger.warning(json.dumps({"event": "institutional_score_failed", "ticker": ticker, "error": str(exc)}))
        return {
            "score": 50.0,
            "institutional_percent": 0.0,
            "holder_count": 0.0,
            "mutual_fund_count": 0.0,
            "top_holder_weight": 0.0,
            "reported_value": 0.0,
            "reason": "institutional data unavailable",
        }


def _safe_frame(value) -> pd.DataFrame:
    try:
        if value is None or not isinstance(value, pd.DataFrame):
            return pd.DataFrame()
        return value.dropna(how="all")
    except Exception:
        return pd.DataFrame()


def _major_holder_percent(major: pd.DataFrame) -> float:
    if major.empty:
        return 0.0
    for raw in major.astype(str).stack().tolist():
        text = raw.strip()
        if "%" not in text:
            continue
        try:
            value = float(text.replace("%", "").strip())
        except ValueError:
            continue
        if 0 <= value <= 100:
            return value
    return 0.0


def _top_holder_weight(institutional: pd.DataFrame) -> float:
    if institutional.empty:
        return 0.0
    percent_cols = [c for c in institutional.columns if "out" in str(c).lower() or "%" in str(c).lower()]
    values = []
    for col in percent_cols:
        series = institutional[col]
        for item in series:
            try:
                if isinstance(item, str):
                    values.append(float(item.replace("%", "")))
                else:
                    value = float(item)
                    values.append(value * 100 if value <= 1 else value)
            except (TypeError, ValueError):
                continue
    return max(values) if values else 0.0


def _total_reported_value(institutional: pd.DataFrame) -> float:
    if institutional.empty:
        return 0.0
    value_cols = [c for c in institutional.columns if "value" in str(c).lower()]
    if not value_cols:
        return 0.0
    total = 0.0
    for col in value_cols:
        total += float(pd.to_numeric(institutional[col], errors="coerce").fillna(0).sum())
    return total


def _reason(score: float, institutional_pct: float, holder_count: int, top_holder_weight: float) -> str:
    if score >= 70 and institutional_pct:
        return f"institutional ownership is strong at about {institutional_pct:.0f}%"
    if holder_count >= 20:
        return "institutional holder breadth is supportive"
    if top_holder_weight and top_holder_weight <= 12:
        return "ownership is not overly concentrated"
    return "institutional support is neutral"
