import numpy as np
import pandas as pd

from swing_indicators import swing_confirmation_score, directional_bias, adx


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return float(np.clip(value, low, high))


def swing_trading_score(df: pd.DataFrame) -> dict[str, float | str | int]:
    if df.empty or len(df) < 120 or not {"Open", "High", "Low", "Close", "Volume"}.issubset(df.columns):
        return _empty("not enough swing-trading data")

    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    volume = df["Volume"]
    price = float(close.iloc[-1])
    if price <= 0:
        return _empty("invalid latest price")

    ma10 = close.rolling(10).mean()
    ma20 = close.rolling(20).mean()
    ma50 = close.rolling(50).mean()
    ma200 = close.rolling(200).mean() if len(close) >= 200 else close.rolling(120).mean()
    rsi = _rsi(close)
    atr = _atr(df)

    trend = _trend_component(price, ma20.iloc[-1], ma50.iloc[-1], ma200.iloc[-1])
    momentum = _momentum_component(close)
    setup, setup_type = _setup_component(df, price, high, low, volume, ma10, ma20, ma50)
    risk = _risk_component(price, ma20.iloc[-1], rsi.iloc[-1], atr.iloc[-1])
    rr_details = _risk_reward(price, high, low, atr.iloc[-1])
    confirmation = swing_confirmation_score(df)  # ADX trend quality + MACD + Bollinger squeeze

    score = _clamp(
        trend * 0.22
        + momentum * 0.16
        + setup * 0.22
        + risk * 0.12
        + rr_details["risk_reward_score"] * 0.12
        + confirmation["composite"] * 0.16
    )

    # Hard gate: do not flag a strong swing-long into a confirmed downtrend.
    adx_val = float(adx(df).iloc[-1])
    bias = directional_bias(df)
    downtrend_gated = bias < 0 and adx_val >= 22
    if downtrend_gated:
        score = _clamp(min(score, 45.0))

    reasons = []
    if trend >= 70:
        reasons.append("trend structure supports a multi-day hold")
    if confirmation["adx"] >= 70:
        reasons.append("trend strength (ADX) confirms the move")
    if confirmation["macd"] >= 68:
        reasons.append("MACD momentum is expanding")
    if confirmation["bollinger"] >= 70:
        reasons.append("volatility has coiled for a potential expansion")
    if momentum >= 70:
        reasons.append("short-term momentum is improving")
    if setup >= 70:
        reasons.append(setup_type)
    if risk < 45:
        reasons.append("risk is elevated from volatility or overextension")
    if rr_details["risk_reward"] >= 1.8:
        reasons.append("risk/reward is favorable")
    if downtrend_gated:
        reasons.insert(0, "capped: price is in a confirmed downtrend")
    if not reasons:
        reasons.append("swing setup is neutral")

    return {
        "score": score,
        "setup_type": setup_type,
        "entry_price": round(price, 2),
        "stop_loss": round(rr_details["stop_loss"], 2),
        "target_price": round(rr_details["target_price"], 2),
        "risk_reward": round(rr_details["risk_reward"], 2),
        "atr_pct": round(float(atr.iloc[-1] / price * 100), 2) if atr.iloc[-1] > 0 else 0.0,
        "holding_period_days": 3 if setup_type.startswith("breakout") else 7,
        "adx": confirmation["adx"],
        "macd": confirmation["macd"],
        "bollinger": confirmation["bollinger"],
        "confirmation": confirmation["composite"],
        "directional_bias": bias,
        "reason": "; ".join(reasons[:3]) + ".",
    }


def _trend_component(price: float, ma20: float, ma50: float, ma200: float) -> float:
    score = 35.0
    if price > ma20:
        score += 20
    if price > ma50:
        score += 18
    if price > ma200:
        score += 12
    if ma20 > ma50:
        score += 10
    if ma50 > ma200:
        score += 5
    return _clamp(score)


def _momentum_component(close: pd.Series) -> float:
    ret5 = _pct_return(close, 5)
    ret20 = _pct_return(close, 20)
    ret60 = _pct_return(close, 60)
    score = 50 + ret5 * 3.0 + ret20 * 1.2 + ret60 * 0.25
    if ret5 > 0 and ret20 > 0:
        score += 10
    if ret5 < -4:
        score -= 15
    return _clamp(score)


def _setup_component(
    df: pd.DataFrame,
    price: float,
    high: pd.Series,
    low: pd.Series,
    volume: pd.Series,
    ma10: pd.Series,
    ma20: pd.Series,
    ma50: pd.Series,
) -> tuple[float, str]:
    avg_vol20 = float(volume.tail(20).mean())
    rel_vol = float(volume.iloc[-1] / avg_vol20) if avg_vol20 > 0 else 1.0
    high20 = float(high.iloc[-21:-1].max())
    high55 = float(high.iloc[-56:-1].max())
    low10 = float(low.tail(10).min())
    ma10_now = float(ma10.iloc[-1])
    ma20_now = float(ma20.iloc[-1])
    ma50_now = float(ma50.iloc[-1])
    strategies = []

    if price > high55 and rel_vol >= 1.15:
        strategies.append((92.0, "breakout above a 55-day range on above-average volume"))
    if price > high20 and rel_vol >= 1.10:
        strategies.append((84.0, "breakout above a 20-day range on above-average volume"))
    if ma20_now > ma50_now and price > ma20_now and abs(price / ma20_now - 1) <= 0.03:
        strategies.append((80.0, "pullback buy near rising 20-day support"))
    if _ma_crossover_confirmed(ma10, ma20, ma50):
        strategies.append((76.0, "10-day average crossed above 20-day average with 50-day trend confirmation"))
    support_score = _support_bounce_score(df)
    if support_score:
        strategies.append(support_score)
    fibonacci_score = _fibonacci_retracement_score(df)
    if fibonacci_score:
        strategies.append(fibonacci_score)
    anchored_vwap_score = _anchored_vwap_pullback_score(df)
    if anchored_vwap_score:
        strategies.append(anchored_vwap_score)
    earnings_momentum_score = _earnings_momentum_style_score(df)
    if earnings_momentum_score:
        strategies.append(earnings_momentum_score)
    if ma10_now > ma20_now > ma50_now and price >= low10 * 1.03:
        strategies.append((72.0, "trend continuation after a shallow consolidation"))

    if strategies:
        return max(strategies, key=lambda item: item[0])
    if price < ma20_now:
        return 38.0, "price is below short-term swing support"
    return 55.0, "no clear swing entry pattern"


def bear_case_score(df: pd.DataFrame) -> dict[str, float | str]:
    if df.empty or len(df) < 120 or not {"Open", "High", "Low", "Close", "Volume"}.issubset(df.columns):
        return _empty_bear("unavailable", "not enough bearish setup data")

    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    volume = df["Volume"]
    price = float(close.iloc[-1])
    atr = _atr(df)
    ma10 = close.rolling(10).mean()
    ma20 = close.rolling(20).mean()
    ma50 = close.rolling(50).mean()
    ma200 = close.rolling(200).mean() if len(close) >= 200 else close.rolling(120).mean()
    avg_vol20 = float(volume.tail(20).mean())
    rel_vol = float(volume.iloc[-1] / avg_vol20) if avg_vol20 > 0 else 1.0

    components = []
    reasons = []
    if price < ma20.iloc[-1] < ma50.iloc[-1]:
        components.append(72.0)
        reasons.append("price is below falling short-term support")
    if price < ma200.iloc[-1] and ma20.iloc[-1] < ma50.iloc[-1]:
        components.append(78.0)
        reasons.append("trend structure is bearish below the long-term average")
    if price < low.iloc[-21:-1].min() and rel_vol >= 1.15:
        components.append(88.0)
        reasons.append("breakdown below a 20-day range on above-average volume")
    if ma10.iloc[-1] < ma20.iloc[-1] < ma50.iloc[-1]:
        components.append(82.0)
        reasons.append("moving averages are stacked bearishly")
    if _failed_breakout(df):
        components.append(80.0)
        reasons.append("recent breakout attempt failed and reversed")
    if _lower_highs_lower_lows(high, low):
        components.append(74.0)
        reasons.append("price is making lower highs and lower lows")

    if not components:
        return _empty_bear("no strong bear case", "no strong bearish swing pattern confirmed")

    score = _clamp(float(np.mean(components)))
    rr_details = _short_risk_reward(price, high, low, atr.iloc[-1])
    return {
        "score": score,
        "setup_type": reasons[0],
        "reason": "; ".join(reasons[:3]) + ".",
        "entry_price": round(price, 2),
        "stop_loss": round(rr_details["stop_loss"], 2),
        "target_price": round(rr_details["target_price"], 2),
        "risk_reward": round(rr_details["risk_reward"], 2),
        "atr_pct": round(float(atr.iloc[-1] / price * 100), 2) if atr.iloc[-1] > 0 and price > 0 else 0.0,
        "holding_period_days": 3 if "breakdown" in reasons[0] else 7,
    }


def _ma_crossover_confirmed(ma10: pd.Series, ma20: pd.Series, ma50: pd.Series) -> bool:
    if len(ma10) < 3:
        return False
    return ma10.iloc[-2] <= ma20.iloc[-2] and ma10.iloc[-1] > ma20.iloc[-1] and ma20.iloc[-1] > ma50.iloc[-1]


def _support_bounce_score(df: pd.DataFrame) -> tuple[float, str] | None:
    close = df["Close"]
    low = df["Low"]
    volume = df["Volume"]
    price = float(close.iloc[-1])
    support = float(low.iloc[-25:-5].min())
    if support <= 0:
        return None
    touched_support = low.tail(5).min() <= support * 1.015
    bounced = price >= support * 1.025
    avg_vol20 = float(volume.tail(20).mean())
    rel_vol = float(volume.tail(3).mean() / avg_vol20) if avg_vol20 > 0 else 1.0
    if touched_support and bounced and rel_vol >= 1.05:
        return 82.0, "support/resistance bounce confirmed with improving volume"
    return None


def _fibonacci_retracement_score(df: pd.DataFrame) -> tuple[float, str] | None:
    close = df["Close"]
    window = close.tail(80)
    swing_low = float(window.min())
    swing_high = float(window.max())
    price = float(close.iloc[-1])
    move = swing_high - swing_low
    if move <= 0 or price >= swing_high:
        return None
    retracement = (swing_high - price) / move
    if 0.34 <= retracement <= 0.53 and _pct_return(close, 5) >= -2:
        return 78.0, "pullback is holding a 38-50% retracement zone"
    return None


def _anchored_vwap_pullback_score(df: pd.DataFrame) -> tuple[float, str] | None:
    close = df["Close"]
    volume = df["Volume"]
    if len(close) < 25:
        return None
    returns = close.pct_change()
    anchor_candidates = returns.tail(15).abs()
    anchor_idx = anchor_candidates.idxmax()
    anchored = df.loc[anchor_idx:]
    if anchored.empty or float(anchored["Volume"].sum()) <= 0:
        return None
    vwap = float((anchored["Close"] * anchored["Volume"]).sum() / anchored["Volume"].sum())
    price = float(close.iloc[-1])
    if price > vwap and abs(price / vwap - 1) <= 0.025 and _pct_return(close, 3) >= -1:
        return 76.0, "price is pulling back toward an anchored VWAP support area"
    return None


def _earnings_momentum_style_score(df: pd.DataFrame) -> tuple[float, str] | None:
    close = df["Close"]
    open_ = df["Open"]
    volume = df["Volume"]
    if len(close) < 25:
        return None
    gap = (open_.iloc[-5] / close.iloc[-6] - 1) * 100 if close.iloc[-6] > 0 else 0
    held_gap = close.iloc[-1] > open_.iloc[-5]
    avg_vol20 = float(volume.tail(20).mean())
    gap_volume = float(volume.iloc[-5] / avg_vol20) if avg_vol20 > 0 else 1.0
    if gap >= 3.0 and held_gap and gap_volume >= 1.25:
        return 84.0, "earnings-style momentum gap is holding for a second-wave swing"
    return None


def _failed_breakout(df: pd.DataFrame) -> bool:
    close = df["Close"]
    high = df["High"]
    if len(close) < 35:
        return False
    prior_high = high.iloc[-31:-6].max()
    recent_break = high.iloc[-5:].max() > prior_high
    failed = close.iloc[-1] < prior_high * 0.99
    return bool(recent_break and failed)


def _lower_highs_lower_lows(high: pd.Series, low: pd.Series) -> bool:
    if len(high) < 15:
        return False
    recent_highs = high.tail(15).rolling(5).max().dropna()
    recent_lows = low.tail(15).rolling(5).min().dropna()
    return bool(
        len(recent_highs) >= 3
        and len(recent_lows) >= 3
        and recent_highs.iloc[-1] < recent_highs.iloc[0]
        and recent_lows.iloc[-1] < recent_lows.iloc[0]
    )


def _risk_component(price: float, ma20: float, rsi: float, atr: float) -> float:
    atr_pct = atr / price * 100 if price > 0 and atr > 0 else 8.0
    extension = (price / ma20 - 1) * 100 if ma20 > 0 else 0.0
    score = 80.0
    if atr_pct > 6:
        score -= min(35.0, (atr_pct - 6) * 7)
    if extension > 10:
        score -= min(30.0, (extension - 10) * 4)
    if rsi > 75:
        score -= min(25.0, (rsi - 75) * 2)
    if rsi < 35:
        score -= 15
    return _clamp(score)


def _risk_reward(price: float, high: pd.Series, low: pd.Series, atr: float) -> dict[str, float]:
    atr = float(atr) if atr and atr > 0 else price * 0.04
    recent_support = float(low.tail(10).min())
    stop_loss = max(0.01, min(price - atr * 1.5, recent_support - atr * 0.25))
    if stop_loss >= price:
        stop_loss = price - atr * 1.5
    resistance = float(high.tail(55).max())
    target_price = max(price + atr * 2.0, resistance)
    risk = max(price - stop_loss, 0.01)
    reward = max(target_price - price, 0.0)
    rr = reward / risk if risk > 0 else 0.0
    rr_score = _clamp(35 + rr * 25)
    return {
        "stop_loss": stop_loss,
        "target_price": target_price,
        "risk_reward": rr,
        "risk_reward_score": rr_score,
    }


def _short_risk_reward(price: float, high: pd.Series, low: pd.Series, atr: float) -> dict[str, float]:
    atr = float(atr) if atr and atr > 0 else price * 0.04
    recent_resistance = float(high.tail(10).max())
    stop_loss = max(price + atr * 1.5, recent_resistance + atr * 0.25)
    support = float(low.tail(55).min())
    target_price = min(price - atr * 2.0, support)
    target_price = max(0.01, target_price)
    risk = max(stop_loss - price, 0.01)
    reward = max(price - target_price, 0.0)
    rr = reward / risk if risk > 0 else 0.0
    return {
        "stop_loss": stop_loss,
        "target_price": target_price,
        "risk_reward": rr,
    }


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["High"]
    low = df["Low"]
    close = df["Close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean().fillna(0)


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = -delta.clip(upper=0).rolling(period).mean()
    rs = gain / (loss + 1e-9)
    return (100 - (100 / (1 + rs))).fillna(50)


def _pct_return(close: pd.Series, days: int) -> float:
    if len(close) <= days or close.iloc[-days - 1] <= 0:
        return 0.0
    return float((close.iloc[-1] / close.iloc[-days - 1] - 1) * 100)


def _empty(reason: str) -> dict[str, float | str | int]:
    return {
        "score": 50.0,
        "setup_type": "unavailable",
        "entry_price": 0.0,
        "stop_loss": 0.0,
        "target_price": 0.0,
        "risk_reward": 0.0,
        "atr_pct": 0.0,
        "holding_period_days": 0,
        "adx": 50.0,
        "macd": 50.0,
        "bollinger": 50.0,
        "confirmation": 50.0,
        "directional_bias": 0,
        "reason": reason,
    }


def _empty_bear(setup_type: str, reason: str) -> dict[str, float | str | int]:
    return {
        "score": 0.0,
        "setup_type": setup_type,
        "reason": reason,
        "entry_price": 0.0,
        "stop_loss": 0.0,
        "target_price": 0.0,
        "risk_reward": 0.0,
        "atr_pct": 0.0,
        "holding_period_days": 0,
    }
