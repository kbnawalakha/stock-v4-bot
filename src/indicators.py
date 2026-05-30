import numpy as np
import pandas as pd


def clamp(x, low=-100, high=100):
    return float(np.clip(x, low, high))


def pct_return(df: pd.DataFrame, days: int) -> float:
    if df.empty or len(df) <= days:
        return 0.0
    return float((df["Close"].iloc[-1] / df["Close"].iloc[-days - 1] - 1) * 100)


def trend_score(df: pd.DataFrame) -> float:
    if len(df) < 200:
        return 0.0
    close = df["Close"]
    price = close.iloc[-1]
    ma20 = close.rolling(20).mean().iloc[-1]
    ma50 = close.rolling(50).mean().iloc[-1]
    ma200 = close.rolling(200).mean().iloc[-1]
    score = 0
    if price > ma20: score += 30
    if price > ma50: score += 30
    if price > ma200: score += 20
    if ma20 > ma50: score += 20
    return clamp(score, 0, 100)


def relative_strength_score(stock_df: pd.DataFrame, spy_df: pd.DataFrame, qqq_df: pd.DataFrame) -> float:
    stock_20 = pct_return(stock_df, 20)
    spy_20 = pct_return(spy_df, 20)
    qqq_20 = pct_return(qqq_df, 20)
    rs = ((stock_20 - spy_20) + (stock_20 - qqq_20)) / 2
    return clamp(rs * 5, -100, 100)


def sector_strength_score(sector_df: pd.DataFrame, spy_df: pd.DataFrame) -> float:
    if sector_df.empty:
        return 0.0
    sector_20 = pct_return(sector_df, 20)
    spy_20 = pct_return(spy_df, 20)
    return clamp((sector_20 - spy_20) * 8, -100, 100)


def volatility_compression_score(df: pd.DataFrame) -> float:
    if len(df) < 70:
        return 0.0
    returns = df["Close"].pct_change()
    vol20 = returns.tail(20).std()
    vol60 = returns.tail(60).std()
    if vol60 == 0 or np.isnan(vol60):
        return 0.0
    ratio = vol20 / vol60
    return clamp((1 - ratio) * 100, -50, 100)


def high_52_week_score(df: pd.DataFrame) -> float:
    if len(df) < 120:
        return 0.0
    close = df["Close"]
    high_52 = close.tail(252).max()
    if high_52 <= 0:
        return 0.0
    proximity = close.iloc[-1] / high_52
    return clamp(proximity * 100, 0, 100)


def volume_surge_score(df: pd.DataFrame) -> float:
    if len(df) < 31:
        return 0.0
    avg_vol = df["Volume"].tail(30).mean()
    today_vol = df["Volume"].iloc[-1]
    if avg_vol <= 0:
        return 0.0
    ratio = today_vol / avg_vol
    return clamp((ratio - 1) * 50, -50, 100)


def breakout_score(df: pd.DataFrame) -> float:
    return clamp(
        0.45 * high_52_week_score(df)
        + 0.35 * volatility_compression_score(df)
        + 0.20 * volume_surge_score(df),
        -100,
        100,
    )


def atr_risk_quality_score(df: pd.DataFrame) -> float:
    if len(df) < 15:
        return 50.0
    high = df["High"]
    low = df["Low"]
    close = df["Close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(14).mean().iloc[-1]
    price = close.iloc[-1]
    atr_pct = atr / price * 100 if price else 10
    return clamp(100 - atr_pct * 12, 0, 100)


def rsi_score(df: pd.DataFrame) -> float:
    if len(df) < 20:
        return 50.0
    delta = df["Close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = -delta.clip(upper=0).rolling(14).mean()
    rs = gain / (loss + 1e-9)
    rsi = 100 - (100 / (1 + rs.iloc[-1]))
    if 45 <= rsi <= 65:
        return 80.0
    if 35 <= rsi < 45:
        return 65.0
    if 65 < rsi <= 75:
        return 55.0
    if rsi > 75:
        return 25.0
    return 35.0


def risk_quality_score(df: pd.DataFrame) -> float:
    return clamp(0.70 * atr_risk_quality_score(df) + 0.30 * rsi_score(df), 0, 100)
