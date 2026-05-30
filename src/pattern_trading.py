import numpy as np
import pandas as pd


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return float(np.clip(value, low, high))


def pattern_trading_score(daily: pd.DataFrame) -> dict[str, float | list[str]]:
    if daily.empty or len(daily) < 80:
        return {"score": 50.0, "patterns": ["not enough pattern data"]}

    df = daily.copy()
    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    volume = df["Volume"]
    price = float(close.iloc[-1])

    ma10 = close.rolling(10).mean()
    ma20 = close.rolling(20).mean()
    ma50 = close.rolling(50).mean()
    avg_vol20 = volume.rolling(20).mean()
    rsi = _rsi(close)
    weekly = _weekly_frame(df)

    components = []
    patterns = []

    trend_alignment = price > ma10.iloc[-1] > ma20.iloc[-1] > ma50.iloc[-1]
    if trend_alignment:
        components.append(88.0)
        patterns.append("daily moving averages are stacked bullishly")

    breakout_level = high.iloc[-21:-1].max()
    breakout_volume = avg_vol20.iloc[-1] > 0 and volume.iloc[-1] / avg_vol20.iloc[-1] >= 1.25
    if price > breakout_level and breakout_volume:
        components.append(92.0)
        patterns.append("price is breaking above a 20-day range on stronger volume")
    elif price > breakout_level:
        components.append(78.0)
        patterns.append("price is clearing a 20-day range")

    pullback_to_support = (
        price > ma20.iloc[-1]
        and abs(price / ma20.iloc[-1] - 1) <= 0.025
        and ma20.iloc[-1] > ma50.iloc[-1]
    )
    if pullback_to_support:
        components.append(76.0)
        patterns.append("price is holding a pullback near rising 20-day support")

    flag_score = _bull_flag_score(close, high, low)
    if flag_score >= 70:
        components.append(flag_score)
        patterns.append("recent action resembles a bull-flag consolidation")

    if len(rsi) >= 3 and 42 <= rsi.iloc[-2] <= 58 and rsi.iloc[-1] > rsi.iloc[-2] and price > ma20.iloc[-1]:
        components.append(72.0)
        patterns.append("momentum is rebounding while price holds above the 20-day average")

    weekly_score, weekly_reason = _weekly_trend_score(weekly)
    components.append(weekly_score)
    if weekly_reason:
        patterns.append(weekly_reason)

    if not components:
        return {"score": 45.0, "patterns": ["no high-probability daily or weekly pattern confirmed"]}

    score = _clamp(np.mean(components))
    return {"score": score, "patterns": patterns[:4]}


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = -delta.clip(upper=0).rolling(period).mean()
    rs = gain / (loss + 1e-9)
    return 100 - (100 / (1 + rs))


def _bull_flag_score(close: pd.Series, high: pd.Series, low: pd.Series) -> float:
    if len(close) < 25:
        return 0.0
    impulse = close.iloc[-12] / close.iloc[-22] - 1
    consolidation_range = (high.iloc[-8:].max() / low.iloc[-8:].min()) - 1
    drift = close.iloc[-1] / close.iloc[-8] - 1
    if impulse >= 0.08 and consolidation_range <= 0.08 and drift >= -0.03:
        return _clamp(70 + impulse * 180 - consolidation_range * 120)
    return 0.0


def _weekly_frame(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "Open": df["Open"].resample("W-FRI").first(),
        "High": df["High"].resample("W-FRI").max(),
        "Low": df["Low"].resample("W-FRI").min(),
        "Close": df["Close"].resample("W-FRI").last(),
        "Volume": df["Volume"].resample("W-FRI").sum(),
    }).dropna()


def _weekly_trend_score(weekly: pd.DataFrame) -> tuple[float, str]:
    if weekly.empty or len(weekly) < 30:
        return 50.0, ""
    close = weekly["Close"]
    price = float(close.iloc[-1])
    ma10 = close.rolling(10).mean().iloc[-1]
    ma30 = close.rolling(30).mean().iloc[-1]
    high_26 = close.iloc[-27:-1].max()

    if price > high_26 and ma10 > ma30:
        return 90.0, "weekly price is confirming a longer-term breakout"
    if price > ma10 > ma30:
        return 78.0, "weekly trend is aligned higher"
    if price > ma30:
        return 62.0, "weekly structure is constructive"
    return 42.0, "weekly trend is not yet supportive"
