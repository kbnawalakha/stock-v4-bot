import pandas as pd

from signal_utils import clamp


def volume_accumulation_score(ticker: str, price_df: pd.DataFrame) -> dict[str, float | str]:
    if price_df is None or price_df.empty or len(price_df) < 35:
        return _neutral("not enough volume history")

    df = price_df.dropna().copy()
    required = {"High", "Low", "Close", "Volume"}
    if not required.issubset(df.columns):
        return _neutral("volume data unavailable")

    volume = df["Volume"].astype(float)
    close = df["Close"].astype(float)
    high = df["High"].astype(float)
    low = df["Low"].astype(float)

    avg_volume_30 = float(volume.tail(31).iloc[:-1].mean()) if len(volume) >= 31 else float(volume.mean())
    latest_volume = float(volume.iloc[-1])
    relative_volume = latest_volume / avg_volume_30 if avg_volume_30 > 0 else 1.0

    direction = close.diff().fillna(0).apply(lambda x: 1 if x > 0 else -1 if x < 0 else 0)
    obv = (direction * volume).cumsum()
    obv_trend = _slope_percent(obv.tail(20))

    money_flow_multiplier = ((close - low) - (high - close)) / ((high - low).replace(0, pd.NA))
    money_flow_volume = money_flow_multiplier.fillna(0) * volume
    ad_line = money_flow_volume.cumsum()
    accumulation_distribution_trend = _slope_percent(ad_line.tail(20))
    cmf_den = volume.tail(20).sum()
    chaikin_money_flow = float(money_flow_volume.tail(20).sum() / cmf_den) if cmf_den > 0 else 0.0

    price_return_5d = (close.iloc[-1] / close.iloc[-6] - 1) * 100 if len(close) > 6 and close.iloc[-6] else 0.0
    rel_volume_score = clamp((relative_volume - 1.0) * 35 + 50, 0, 100)
    obv_score = clamp(obv_trend * 3 + 50, 0, 100)
    ad_score = clamp(accumulation_distribution_trend * 3 + 50, 0, 100)
    cmf_score = clamp(chaikin_money_flow * 150 + 50, 0, 100)
    price_volume_bonus = 10 if price_return_5d > 0 and relative_volume > 1.2 else -10 if price_return_5d < 0 and relative_volume > 1.2 else 0

    score = clamp(rel_volume_score * 0.30 + obv_score * 0.25 + ad_score * 0.20 + cmf_score * 0.25 + price_volume_bonus)
    reason = "Accumulation is supportive." if score >= 60 else "Distribution pressure is visible." if score <= 40 else "Volume accumulation is neutral."
    return {
        "score": score,
        "relative_volume": float(relative_volume),
        "obv_trend": float(obv_trend),
        "accumulation_distribution_trend": float(accumulation_distribution_trend),
        "chaikin_money_flow": float(chaikin_money_flow),
        "reason": reason,
    }


def _neutral(reason: str) -> dict[str, float | str]:
    return {
        "score": 50.0,
        "relative_volume": 1.0,
        "obv_trend": 0.0,
        "accumulation_distribution_trend": 0.0,
        "chaikin_money_flow": 0.0,
        "reason": reason,
    }


def _slope_percent(series: pd.Series) -> float:
    clean = series.dropna()
    if len(clean) < 2:
        return 0.0
    start = float(clean.iloc[0])
    end = float(clean.iloc[-1])
    denom = abs(start) if abs(start) > 1 else max(abs(end), 1.0)
    return (end - start) / denom * 100.0
