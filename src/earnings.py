from datetime import datetime, timezone
import pandas as pd
import numpy as np
import logging
from finnhub_client import get_finnhub_client
from market_data import get_history, get_ticker_obj
from signal_utils import safe_float

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


def earnings_score(ticker: str, use_finnhub: bool = True, guidance_sentiment: float | None = None) -> dict[str, float | int | None | str]:
    dte = days_until_earnings(ticker)
    if use_finnhub and dte is None:
        dte = _latest_finnhub_earnings_date(ticker)

    eps_surprise = 0.0
    revenue_surprise = 0.0
    guidance_score = 50.0 if guidance_sentiment is None else _clamp(50 + guidance_sentiment / 2)

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
    drift = post_earnings_drift_score(ticker)
    drift_score = drift["score"]
    score = _clamp(eps_score * 0.25 + revenue_score * 0.20 + guidance_score * 0.15 + drift_score * 0.20 + proximity * 0.20)

    if eps_surprise > 5 and revenue_surprise > 3 and guidance_score >= 60:
        reason = "earnings quality is strongly bullish: beat with supportive guidance."
    elif eps_surprise > 0 or revenue_surprise > 0:
        reason = "earnings quality is moderately bullish."
    elif eps_surprise < -3 and guidance_score < 45:
        reason = "earnings quality is bearish: miss with weak guidance."
    else:
        reason = "earnings quality is neutral."

    result = {
        "score": score,
        "eps_surprise": float(eps_surprise),
        "revenue_surprise": float(revenue_surprise),
        "guidance_score": float(guidance_score),
        "days_to_earnings": dte,
        "post_earnings_drift_score": float(drift_score),
        "post_earnings_drift_1d": drift["drift_1d"],
        "post_earnings_drift_5d": drift["drift_5d"],
        "post_earnings_drift_20d": drift["drift_20d"],
        "reason": reason,
    }
    return result


def post_earnings_drift_score(ticker: str) -> dict[str, float]:
    try:
        obj = get_ticker_obj(ticker)
        dates = obj.earnings_dates
        if dates is None or len(dates) == 0:
            return _empty_drift()
        now = pd.Timestamp(datetime.now(timezone.utc))
        past_dates = []
        for d in dates.index:
            ts = pd.Timestamp(d)
            if ts.tzinfo is None:
                ts = ts.tz_localize("UTC")
            if ts < now:
                past_dates.append(ts)
        if not past_dates:
            return _empty_drift()
        event_date = max(past_dates).date()
        stock = get_history(ticker, period="1y")
        spy = get_history("SPY", period="1y")
        if stock.empty or spy.empty:
            return _empty_drift()
        stock_close = stock["Close"]
        spy_close = spy["Close"]
        drift_1 = _drift(stock_close, spy_close, event_date, 1)
        drift_5 = _drift(stock_close, spy_close, event_date, 5)
        drift_20 = _drift(stock_close, spy_close, event_date, 20)
        usable = [x for x in (drift_1, drift_5, drift_20) if x is not None]
        if not usable:
            return _empty_drift()
        drift_score = _clamp(50 + (sum(usable) / len(usable)) * 4)
        return {
            "score": float(drift_score),
            "drift_1d": float(drift_1 or 0.0),
            "drift_5d": float(drift_5 or 0.0),
            "drift_20d": float(drift_20 or 0.0),
        }
    except Exception:
        return _empty_drift()


def _drift(stock_close: pd.Series, spy_close: pd.Series, event_date, days: int) -> float | None:
    stock_after = stock_close[stock_close.index.date >= event_date]
    spy_after = spy_close[spy_close.index.date >= event_date]
    if len(stock_after) <= days or len(spy_after) <= days:
        return None
    stock_start = safe_float(stock_after.iloc[0])
    stock_end = safe_float(stock_after.iloc[days])
    spy_start = safe_float(spy_after.iloc[0])
    spy_end = safe_float(spy_after.iloc[days])
    if not stock_start or not stock_end or not spy_start or not spy_end:
        return None
    return (stock_end / stock_start - 1) * 100 - (spy_end / spy_start - 1) * 100


def _empty_drift() -> dict[str, float]:
    return {"score": 50.0, "drift_1d": 0.0, "drift_5d": 0.0, "drift_20d": 0.0}
