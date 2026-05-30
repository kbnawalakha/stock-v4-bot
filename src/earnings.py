from datetime import datetime, timezone
import pandas as pd
import numpy as np
import logging
from finnhub_client import get_finnhub_client
from market_data import get_ticker_obj

logger = logging.getLogger(__name__)


def days_until_earnings(ticker: str) -> int | None:
    try:
        obj = get_ticker_obj(ticker)
        dates = obj.earnings_dates
        if dates is None or len(dates) == 0:
            return None

        idx = dates.index
        now = pd.Timestamp(datetime.now(timezone.utc))
        future_dates = []
        for d in idx:
            ts = pd.Timestamp(d)
            if ts.tzinfo is None:
                ts = ts.tz_localize("UTC")
            if ts >= now:
                future_dates.append(ts)

        if not future_dates:
            return None

        next_date = min(future_dates)
        return int((next_date - now).days)
    except Exception:
        return None


def earnings_proximity_score(days: int | None) -> float:
    if days is None:
        return 0.0
    if days < 0 or days > 21:
        return 0.0
    if days <= 3:
        return 100.0
    if days <= 7:
        return 80.0
    if days <= 14:
        return 60.0
    return 40.0


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return float(np.clip(value, low, high))


def _latest_finnhub_earnings_date(ticker: str) -> int | None:
    client = get_finnhub_client()
    try:
        calendar = client.earnings_calendar(ticker)
        dates = []
        now = pd.Timestamp(datetime.now(timezone.utc)).normalize()
        for item in calendar:
            raw_date = item.get("date")
            if not raw_date:
                continue
            ts = pd.Timestamp(raw_date)
            if ts.tzinfo is None:
                ts = ts.tz_localize("UTC")
            if ts >= now:
                dates.append(ts)
        if not dates:
            return None
        return int((min(dates) - now).days)
    except Exception as exc:
        logger.warning("finnhub_earnings_calendar_failed", extra={"ticker": ticker, "error": str(exc)})
        return None


def earnings_score(ticker: str, use_finnhub: bool = False) -> dict[str, float | int | None]:
    dte = days_until_earnings(ticker)
    if use_finnhub and dte is None:
        dte = _latest_finnhub_earnings_date(ticker)

    eps_surprise = 0.0
    revenue_surprise = 0.0
    guidance_score = 50.0

    if use_finnhub:
        try:
            surprises = get_finnhub_client().earnings_surprises(ticker)
            if surprises:
                latest = surprises[0]
                actual = latest.get("actual")
                estimate = latest.get("estimate")
                if actual is not None and estimate not in (None, 0):
                    eps_surprise = (float(actual) - float(estimate)) / abs(float(estimate)) * 100

                revenue_actual = latest.get("revenueActual") or latest.get("actualRevenue")
                revenue_estimate = latest.get("revenueEstimate") or latest.get("estimateRevenue")
                if revenue_actual is not None and revenue_estimate not in (None, 0):
                    revenue_surprise = (float(revenue_actual) - float(revenue_estimate)) / abs(float(revenue_estimate)) * 100

                surprise_pct = latest.get("surprisePercent")
                if surprise_pct is not None and eps_surprise == 0:
                    eps_surprise = float(surprise_pct)
        except Exception as exc:
            logger.warning("earnings_surprise_failed", extra={"ticker": ticker, "error": str(exc)})

    proximity = earnings_proximity_score(dte)
    eps_score = _clamp(50 + eps_surprise * 4)
    revenue_score = _clamp(50 + revenue_surprise * 3)
    score = _clamp(eps_score * 0.35 + revenue_score * 0.25 + guidance_score * 0.15 + proximity * 0.25)

    result = {
        "score": score,
        "eps_surprise": float(eps_surprise),
        "revenue_surprise": float(revenue_surprise),
        "guidance_score": float(guidance_score),
        "days_to_earnings": dte,
    }
    return result
