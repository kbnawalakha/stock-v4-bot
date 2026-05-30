import logging

import numpy as np
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return float(np.clip(value, low, high))


def get_intraday_history(ticker: str) -> pd.DataFrame:
    try:
        df = yf.download(ticker, period="5d", interval="1m", auto_adjust=True, progress=False, threads=False)
        if df is None or df.empty:
            return pd.DataFrame()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]
        return df.dropna()
    except Exception as exc:
        logger.warning("opening_activity_download_failed", extra={"ticker": ticker, "error": str(exc)})
        return pd.DataFrame()


def opening_activity_score(ticker: str) -> dict[str, float]:
    df = get_intraday_history(ticker)
    if df.empty or not {"Open", "High", "Low", "Close", "Volume"}.issubset(df.columns):
        return {"score": 50.0, "opening_volume_spike": 0.0, "opening_return": 0.0, "vwap_position": 0.0, "gap_follow_through": 0.0}

    if df.index.tz is None:
        df = df.tz_localize("UTC")
    eastern = df.tz_convert("America/New_York")
    latest_date = eastern.index[-1].date()
    today = eastern[eastern.index.date == latest_date]
    opening = today.between_time("09:30", "10:05")
    if opening.empty:
        opening = today.head(35)
    if opening.empty:
        return {"score": 50.0, "opening_volume_spike": 0.0, "opening_return": 0.0, "vwap_position": 0.0, "gap_follow_through": 0.0}

    previous = eastern[eastern.index.date < latest_date]
    prev_close = float(previous["Close"].iloc[-1]) if not previous.empty else float(opening["Open"].iloc[0])
    open_px = float(opening["Open"].iloc[0])
    last_px = float(opening["Close"].iloc[-1])

    historical_opening = []
    for day in sorted(set(previous.index.date))[-4:]:
        day_opening = previous[previous.index.date == day].between_time("09:30", "10:05")
        if not day_opening.empty:
            historical_opening.append(float(day_opening["Volume"].sum()))
    avg_opening_volume = float(np.mean(historical_opening)) if historical_opening else 0.0
    opening_volume = float(opening["Volume"].sum())
    volume_ratio = opening_volume / avg_opening_volume if avg_opening_volume > 0 else 1.0

    pv = (opening["Close"] * opening["Volume"]).sum()
    volume = opening["Volume"].sum()
    vwap = float(pv / volume) if volume > 0 else last_px

    opening_return = (last_px / open_px - 1) * 100 if open_px > 0 else 0.0
    gap = (open_px / prev_close - 1) * 100 if prev_close > 0 else 0.0
    follow_through = opening_return if gap >= 0 else -opening_return
    vwap_position = (last_px / vwap - 1) * 100 if vwap > 0 else 0.0

    volume_score = _clamp((volume_ratio - 1.0) * 35 + 50)
    return_score = _clamp(opening_return * 12 + 50)
    vwap_score = _clamp(vwap_position * 20 + 50)
    follow_score = _clamp(follow_through * 12 + 50)
    score = _clamp(volume_score * 0.35 + return_score * 0.25 + vwap_score * 0.20 + follow_score * 0.20)

    return {
        "score": score,
        "opening_volume_spike": volume_score,
        "opening_return": return_score,
        "vwap_position": vwap_score,
        "gap_follow_through": follow_score,
    }
