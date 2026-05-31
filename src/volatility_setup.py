import pandas as pd

from signal_utils import clamp


def volatility_setup_score(ticker: str, price_df: pd.DataFrame) -> dict[str, float | bool | str]:
    if price_df is None or price_df.empty or len(price_df) < 80:
        return _neutral("not enough volatility history")
    if not {"High", "Low", "Close"}.issubset(price_df.columns):
        return _neutral("volatility data unavailable")

    df = price_df.dropna()
    close = df["Close"].astype(float)
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()

    ma20 = close.rolling(20).mean()
    ma50 = close.rolling(50).mean()
    std20 = close.rolling(20).std()
    bb_width = ((ma20 + 2 * std20) - (ma20 - 2 * std20)) / ma20.replace(0, pd.NA)
    latest_width = float(bb_width.iloc[-1])
    width_window = bb_width.tail(120).dropna()
    bb_width_percentile = float((width_window <= latest_width).mean() * 100) if not width_window.empty else 50.0

    atr_recent = float(atr.tail(10).mean())
    atr_prior = float(atr.tail(40).head(20).mean())
    atr_contraction = (1 - atr_recent / atr_prior) * 100 if atr_prior > 0 else 0.0

    ranges = (high - low).tail(7)
    nr7 = bool(len(ranges) == 7 and ranges.iloc[-1] <= ranges.min())
    high_52 = float(high.tail(252).max())
    near_high = close.iloc[-1] / high_52 >= 0.90 if high_52 > 0 else False
    breakout = close.iloc[-1] > high.iloc[-21:-1].max() if len(high) > 22 else False
    rising_support = close.iloc[-1] > ma20.iloc[-1] > ma50.iloc[-1]

    compression_score = clamp(100 - bb_width_percentile, 0, 100)
    atr_score = clamp(atr_contraction * 2 + 50, 0, 100)
    nr7_score = 75.0 if nr7 else 50.0
    breakout_score = 90.0 if breakout and near_high else 70.0 if breakout else 50.0
    support_score = 75.0 if rising_support else 45.0
    score = clamp(compression_score * 0.30 + atr_score * 0.20 + nr7_score * 0.15 + breakout_score * 0.20 + support_score * 0.15)

    reason = "Volatility contraction is setting up near strength." if score >= 65 else "Volatility setup is neutral." if score >= 40 else "Volatility profile is not constructive."
    return {
        "score": score,
        "bb_width_percentile": bb_width_percentile,
        "atr_contraction": float(atr_contraction),
        "nr7": nr7,
        "near_52_week_high": bool(near_high),
        "breakout": bool(breakout),
        "reason": reason,
    }


def _neutral(reason: str) -> dict[str, float | bool | str]:
    return {
        "score": 50.0,
        "bb_width_percentile": 50.0,
        "atr_contraction": 0.0,
        "nr7": False,
        "near_52_week_high": False,
        "breakout": False,
        "reason": reason,
    }
