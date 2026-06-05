"""Swing-trading confirmation indicators.

These add trend-quality and momentum confirmation that the original model was
missing. Every public ``*_score`` function returns a 0-100 value where higher is
more bullish/constructive for a multi-day swing hold, so they can be blended into
the existing swing score without changing its scale.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    try:
        return float(np.clip(float(value), low, high))
    except Exception:
        return float((low + high) / 2)


def _wilder_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average Directional Index (Wilder). Measures trend *strength*, not direction."""
    high, low = df["High"], df["Low"]
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    atr = _wilder_atr(df, period).replace(0, np.nan)
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / period, adjust=False).mean().fillna(0.0)


def directional_bias(df: pd.DataFrame, period: int = 14) -> int:
    """+1 if +DI above -DI (uptrend), -1 if downtrend, 0 if undecided."""
    high, low = df["High"], df["Low"]
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    atr = _wilder_atr(df, period).replace(0, np.nan)
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / atr
    p, m = float(plus_di.iloc[-1]), float(minus_di.iloc[-1])
    if np.isnan(p) or np.isnan(m):
        return 0
    return 1 if p > m else -1 if m > p else 0


def adx_score(df: pd.DataFrame) -> float:
    """High when a *directional* trend is strong enough to swing-hold (ADX > 20-25)."""
    if df.empty or len(df) < 30:
        return 50.0
    series = adx(df)
    value = float(series.iloc[-1])
    bias = directional_bias(df)
    # Map ADX 15->~45, 25->~70, 40+->~95. This measures *bullish* trend quality, so a
    # confirmed downtrend is forced low regardless of how strong the trend is, and a
    # stronger downtrend scores lower (worse) rather than better.
    strength = _clamp(20 + value * 1.9)
    if bias < 0:
        strength = _clamp(38 - value * 0.6, 0, 38)
    elif bias == 0:
        strength = _clamp(strength - 12)
    return strength


def macd_components(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9):
    close = df["Close"]
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def macd_score(df: pd.DataFrame) -> float:
    """High when MACD histogram is positive and expanding (momentum building)."""
    if df.empty or len(df) < 35:
        return 50.0
    _, _, hist = macd_components(df)
    price = float(df["Close"].iloc[-1]) or 1.0
    h_now = float(hist.iloc[-1])
    h_prev = float(hist.iloc[-2])
    # Normalize histogram by price so it is comparable across tickers.
    norm = h_now / price * 1000
    rising = h_now > h_prev
    score = 50 + norm * 6
    if h_now > 0 and rising:
        score += 18
    elif h_now > 0 and not rising:
        score += 4
    elif h_now < 0 and rising:
        score -= 4  # still negative but improving
    else:
        score -= 18
    return _clamp(score)


def bollinger_squeeze_score(df: pd.DataFrame, period: int = 20) -> float:
    """High when bands are unusually tight (low volatility coil that often precedes
    a swing-tradable expansion), especially when price is pressing the upper band."""
    if df.empty or len(df) < period + 40:
        return 50.0
    close = df["Close"]
    ma = close.rolling(period).mean()
    sd = close.rolling(period).std()
    width = (4 * sd) / ma.replace(0, np.nan)  # (upper-lower)/mid = 4*sd/ma
    width = width.dropna()
    if width.empty:
        return 50.0
    current = float(width.iloc[-1])
    # Percentile of current width within the last ~6 months: low pct = tight squeeze.
    lookback = width.tail(126)
    pct = float((lookback <= current).mean())
    squeeze = (1 - pct) * 100  # tighter -> higher
    # Reward when price sits in the upper half of the band (expansion likely upward).
    upper = ma + 2 * sd
    lower = ma - 2 * sd
    rng = float((upper.iloc[-1] - lower.iloc[-1]) or 1.0)
    position = (float(close.iloc[-1]) - float(lower.iloc[-1])) / rng
    directional = 60 + (position - 0.5) * 60  # 0.5 -> 60, 1.0 -> 90
    return _clamp(0.6 * squeeze + 0.4 * directional)


def swing_confirmation_score(df: pd.DataFrame) -> dict[str, float]:
    """Composite confirmation used to strengthen the swing setup score."""
    a = adx_score(df)
    m = macd_score(df)
    b = bollinger_squeeze_score(df)
    composite = _clamp(0.45 * a + 0.35 * m + 0.20 * b)
    return {"adx": round(a, 1), "macd": round(m, 1), "bollinger": round(b, 1), "composite": round(composite, 1)}
