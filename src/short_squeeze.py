from indicators import pct_return
from market_data import get_history, get_ticker_obj
from signal_utils import clamp, safe_float


def short_squeeze_score(ticker: str) -> dict[str, float | str]:
    try:
        info = getattr(get_ticker_obj(ticker), "info", {}) or {}
        short_percent = safe_float(info.get("shortPercentOfFloat"))
        if short_percent is not None and short_percent <= 1:
            short_percent *= 100
        shares_short = safe_float(info.get("sharesShort"))
        short_ratio = safe_float(info.get("shortRatio") or info.get("daysToCover"))

        df = get_history(ticker, period="6mo")
        price_trend = pct_return(df, 20) if not df.empty else 0.0
        volume_trend = _volume_ratio(df)

        if short_percent is None and shares_short is None and short_ratio is None:
            return _neutral("short interest data unavailable")

        si_score = clamp((short_percent or 0) * 3, 0, 100)
        cover_score = clamp((short_ratio or 0) * 12, 0, 100)
        trend_score = clamp(price_trend * 5 + 50, 0, 100)
        volume_score = clamp((volume_trend - 1) * 35 + 50, 0, 100)

        score = clamp(si_score * 0.35 + cover_score * 0.25 + trend_score * 0.25 + volume_score * 0.15)
        if price_trend <= 0:
            score = min(score, 65.0)
        reason = "Short squeeze setup is elevated." if score >= 70 else "Short interest exists but confirmation is limited." if score >= 50 else "Short squeeze pressure is low."
        return {
            "score": score,
            "short_percent_float": float(short_percent or 0.0),
            "shares_short": float(shares_short or 0.0),
            "days_to_cover": float(short_ratio or 0.0),
            "price_trend_20d": float(price_trend),
            "relative_volume": float(volume_trend),
            "reason": reason,
        }
    except Exception:
        return _neutral("short interest data unavailable")


def _neutral(reason: str) -> dict[str, float | str]:
    return {
        "score": 50.0,
        "short_percent_float": 0.0,
        "shares_short": 0.0,
        "days_to_cover": 0.0,
        "price_trend_20d": 0.0,
        "relative_volume": 1.0,
        "reason": reason,
    }


def _volume_ratio(df) -> float:
    if df.empty or len(df) < 35:
        return 1.0
    avg = float(df["Volume"].tail(31).iloc[:-1].mean())
    latest = float(df["Volume"].iloc[-1])
    return latest / avg if avg > 0 else 1.0
