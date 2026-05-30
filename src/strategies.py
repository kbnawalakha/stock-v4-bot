import numpy as np
import pandas as pd


def momentum_strategy(df: pd.DataFrame) -> float:
    if len(df) < 25:
        return 0.0
    close = df["Close"]
    ret_5 = close.iloc[-1] / close.iloc[-5] - 1
    ret_20 = close.iloc[-1] / close.iloc[-20] - 1
    score = (ret_5 * 40) + (ret_20 * 60)
    return float(np.clip(score * 100, -100, 100))


def trend_strategy(df: pd.DataFrame) -> float:
    if len(df) < 60:
        return 0.0
    close = df["Close"]
    ma20 = float(close.rolling(20).mean().iloc[-1])
    ma50 = float(close.rolling(50).mean().iloc[-1])
    price = float(close.iloc[-1])

    score = 0
    if price > ma20:
        score += 40
    if ma20 > ma50:
        score += 40
    if price > ma50:
        score += 20
    return float(score)


def anomaly_strategy(df: pd.DataFrame) -> float:
    if len(df) < 40:
        return 0.0

    returns = df["Close"].pct_change().dropna()
    volume = df["Volume"]

    ret_z = (returns.iloc[-1] - returns.mean()) / (returns.std() + 1e-9)
    vol_mean = volume.rolling(30).mean().iloc[-1]
    vol_std = volume.rolling(30).std().iloc[-1]
    vol_z = (volume.iloc[-1] - vol_mean) / (vol_std + 1e-9)

    score = ret_z * 35 + max(vol_z, 0) * 20
    return float(np.clip(score, -100, 100))


def mean_reversion_strategy(df: pd.DataFrame) -> float:
    if len(df) < 25:
        return 0.0
    close = df["Close"]
    ma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    z = (close.iloc[-1] - ma20.iloc[-1]) / (std20.iloc[-1] + 1e-9)

    if -2.0 <= z <= -0.5:
        return float(60 + abs(z) * 15)
    if z < -2.0:
        return 20.0
    if z > 2.0:
        return -30.0
    return 10.0


def score_all_strategies(df: pd.DataFrame) -> dict:
    return {
        "momentum": momentum_strategy(df),
        "trend": trend_strategy(df),
        "anomaly": anomaly_strategy(df),
        "mean_reversion": mean_reversion_strategy(df),
    }
