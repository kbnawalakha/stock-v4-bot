import contextlib
import io
import logging

import numpy as np
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)
_INTRADAY_CACHE: dict[str, pd.DataFrame] = {}


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return float(np.clip(value, low, high))


def get_intraday_history(ticker: str) -> pd.DataFrame:
    key = ticker.upper()
    if key in _INTRADAY_CACHE:
        return _INTRADAY_CACHE[key].copy()
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            df = yf.download(
                ticker,
                period="5d",
                interval="1m",
                auto_adjust=True,
                progress=False,
                threads=False,
                prepost=True,
                repair=False,
            )
        if df is None or df.empty:
            return pd.DataFrame()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]
        cleaned = df.dropna()
        _INTRADAY_CACHE[key] = cleaned
        return cleaned.copy()
    except Exception as exc:
        logger.warning("opening_activity_download_failed", extra={"ticker": ticker, "error": str(exc)})
        return pd.DataFrame()


def opening_activity_score(ticker: str) -> dict[str, float]:
    df = get_intraday_history(ticker)
    if df.empty or not {"Open", "High", "Low", "Close", "Volume"}.issubset(df.columns):
        return _empty_extended_result()

    if df.index.tz is None:
        df = df.tz_localize("UTC")
    eastern = df.tz_convert("America/New_York")
    latest_date = eastern.index[-1].date()
    today = eastern[eastern.index.date == latest_date]
    opening = today.between_time("09:30", "10:05")
    if opening.empty:
        opening = today.head(35)
    if opening.empty:
        result = _empty_extended_result()
        result.update(_extended_hours_scores(eastern, latest_date))
        return result

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

    result = {
        "score": score,
        "opening_volume_spike": volume_score,
        "opening_return": return_score,
        "vwap_position": vwap_score,
        "gap_follow_through": follow_score,
        "opening_raw_return_pct": opening_return,
        "opening_volume_ratio": volume_ratio,
    }
    result.update(_extended_hours_scores(eastern, latest_date))
    return result


def _extended_hours_scores(eastern: pd.DataFrame, latest_date) -> dict[str, float]:
    return {
        **_session_activity_score(eastern, latest_date, "04:00", "09:29", "pre_market"),
        **_session_activity_score(eastern, latest_date, "16:00", "20:00", "post_market"),
    }


def _session_activity_score(
    eastern: pd.DataFrame,
    latest_date,
    start_time: str,
    end_time: str,
    prefix: str,
) -> dict[str, float]:
    session = _latest_nonempty_session(eastern, latest_date, start_time, end_time)
    if session.empty:
        return _empty_session(prefix)

    session_date = session.index[-1].date()
    previous = eastern[eastern.index.date < session_date]
    historical_volumes = []
    for day in sorted(set(previous.index.date))[-4:]:
        day_session = previous[previous.index.date == day].between_time(start_time, end_time)
        if not day_session.empty:
            historical_volumes.append(float(day_session["Volume"].sum()))

    avg_volume = float(np.mean(historical_volumes)) if historical_volumes else 0.0
    session_volume = float(session["Volume"].sum())
    volume_ratio = session_volume / avg_volume if avg_volume > 0 else 1.0

    first_px = float(session["Open"].iloc[0])
    last_px = float(session["Close"].iloc[-1])
    raw_return = (last_px / first_px - 1) * 100 if first_px > 0 else 0.0

    pv = (session["Close"] * session["Volume"]).sum()
    volume = session["Volume"].sum()
    vwap = float(pv / volume) if volume > 0 else last_px
    vwap_position = (last_px / vwap - 1) * 100 if vwap > 0 else 0.0

    volume_score = _clamp((volume_ratio - 1.0) * 30 + 50)
    return_score = _clamp(raw_return * 10 + 50)
    vwap_score = _clamp(vwap_position * 18 + 50)
    score = _clamp(volume_score * 0.40 + return_score * 0.35 + vwap_score * 0.25)

    return {
        f"{prefix}_activity": score,
        f"{prefix}_volume_spike": volume_score,
        f"{prefix}_return": return_score,
        f"{prefix}_vwap_position": vwap_score,
        f"{prefix}_raw_return_pct": raw_return,
        f"{prefix}_volume_ratio": volume_ratio,
        f"{prefix}_data_available": 1.0,
    }


def _latest_nonempty_session(eastern: pd.DataFrame, latest_date, start_time: str, end_time: str) -> pd.DataFrame:
    for day in sorted(set(eastern.index.date), reverse=True):
        if day > latest_date:
            continue
        session = eastern[eastern.index.date == day].between_time(start_time, end_time)
        if not session.empty:
            return session
    return pd.DataFrame()


def _empty_extended_result() -> dict[str, float]:
    return {
        "score": 50.0,
        "opening_volume_spike": 0.0,
        "opening_return": 0.0,
        "vwap_position": 0.0,
        "gap_follow_through": 0.0,
        "opening_raw_return_pct": 0.0,
        "opening_volume_ratio": 0.0,
        **_empty_session("pre_market"),
        **_empty_session("post_market"),
    }


def _empty_session(prefix: str) -> dict[str, float]:
    return {
        f"{prefix}_activity": 50.0,
        f"{prefix}_volume_spike": 0.0,
        f"{prefix}_return": 0.0,
        f"{prefix}_vwap_position": 0.0,
        f"{prefix}_raw_return_pct": 0.0,
        f"{prefix}_volume_ratio": 0.0,
        f"{prefix}_data_available": 0.0,
    }


def clear_intraday_cache() -> None:
    _INTRADAY_CACHE.clear()
