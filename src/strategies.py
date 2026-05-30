import numpy as np
import pandas as pd


def _clip(value: float, low: float = -100.0, high: float = 100.0) -> float:
    return float(np.clip(value, low, high))


def momentum_strategy(df: pd.DataFrame) -> float:
    if len(df) < 25:
        return 0.0
    close = df["Close"]
    ret_5 = close.iloc[-1] / close.iloc[-5] - 1
    ret_20 = close.iloc[-1] / close.iloc[-20] - 1
    score = (ret_5 * 45 + ret_20 * 55) * 100
    return _clip(score)


def trend_strategy(df: pd.DataFrame) -> float:
    if len(df) < 60:
        return 0.0
    close = df["Close"]
    price = float(close.iloc[-1])
    ma10 = float(close.rolling(10).mean().iloc[-1])
    ma20 = float(close.rolling(20).mean().iloc[-1])
    ma50 = float(close.rolling(50).mean().iloc[-1])
    score = 0.0
    if price > ma10:
        score += 25
    if price > ma20:
        score += 25
    if ma10 > ma20:
        score += 25
    if ma20 > ma50:
        score += 25
    return _clip(score, 0, 100)


def anomaly_strategy(df: pd.DataFrame) -> float:
    if len(df) < 40:
        return 0.0
    close = df["Close"]
    volume = df["Volume"]
    returns = close.pct_change().dropna()
    ret_z = (returns.iloc[-1] - returns.tail(30).mean()) / (returns.tail(30).std() + 1e-9)
    vol_mean = volume.tail(30).mean()
    vol_std = volume.tail(30).std()
    vol_z = (volume.iloc[-1] - vol_mean) / (vol_std + 1e-9)
    score = max(ret_z, -2) * 25 + max(vol_z, 0) * 20
    return _clip(score)


def mean_reversion_strategy(df: pd.DataFrame) -> float:
    if len(df) < 25:
        return 0.0
    close = df["Close"]
    ma20 = close.rolling(20).mean().iloc[-1]
    std20 = close.rolling(20).std().iloc[-1]
    z = (close.iloc[-1] - ma20) / (std20 + 1e-9)
    if -1.8 <= z <= -0.4:
        return _clip(55 + abs(z) * 20, 0, 100)
    if z < -1.8:
        return 20.0
    if z > 2.0:
        return -25.0
    return 15.0


def score_all_strategies(df: pd.DataFrame) -> dict:
    return {
        "momentum": momentum_strategy(df),
        "trend": trend_strategy(df),
        "anomaly": anomaly_strategy(df),
        "mean_reversion": mean_reversion_strategy(df),
    }
