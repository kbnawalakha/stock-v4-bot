from indicators import pct_return


def market_breadth_regime(universe_price_data: dict[str, object]) -> dict[str, float | str]:
    total = 0
    above20 = 0
    above50 = 0
    above200 = 0
    advances = 0
    declines = 0
    new_highs = 0
    new_lows = 0

    for df in universe_price_data.values():
        try:
            if df is None or df.empty or len(df) < 60:
                continue
            total += 1
            close = df["Close"]
            price = float(close.iloc[-1])
            if len(close) >= 20 and price > float(close.rolling(20).mean().iloc[-1]):
                above20 += 1
            if len(close) >= 50 and price > float(close.rolling(50).mean().iloc[-1]):
                above50 += 1
            if len(close) >= 200 and price > float(close.rolling(200).mean().iloc[-1]):
                above200 += 1
            ret_1d = pct_return(df, 1)
            if ret_1d > 0:
                advances += 1
            elif ret_1d < 0:
                declines += 1
            if len(close) >= 60:
                if price >= float(close.tail(60).max()):
                    new_highs += 1
                if price <= float(close.tail(60).min()):
                    new_lows += 1
        except Exception:
            continue

    if total <= 0:
        return _neutral()

    pct_above20 = above20 / total * 100
    pct_above50 = above50 / total * 100
    pct_above200 = above200 / total * 100
    advance_decline_ratio = advances / max(declines, 1)
    high_low_balance = (new_highs - new_lows) / total * 100

    breadth_score = (
        pct_above20 * 0.25
        + pct_above50 * 0.30
        + pct_above200 * 0.20
        + min(100.0, advance_decline_ratio * 35) * 0.15
        + max(0.0, min(100.0, high_low_balance + 50)) * 0.10
    )

    if breadth_score >= 65:
        regime = "BREADTH_STRONG"
    elif breadth_score <= 40:
        regime = "BREADTH_WEAK"
    else:
        regime = "BREADTH_NEUTRAL"

    return {
        "regime": regime,
        "breadth_score": float(breadth_score),
        "percent_above_20dma": float(pct_above20),
        "percent_above_50dma": float(pct_above50),
        "percent_above_200dma": float(pct_above200),
        "advance_decline_ratio": float(advance_decline_ratio),
        "new_highs": float(new_highs),
        "new_lows": float(new_lows),
        "confidence": min(1.0, max(0.35, abs(breadth_score - 50) / 50)),
    }


def _neutral() -> dict[str, float | str]:
    return {
        "regime": "BREADTH_NEUTRAL",
        "breadth_score": 50.0,
        "percent_above_20dma": 50.0,
        "percent_above_50dma": 50.0,
        "percent_above_200dma": 50.0,
        "advance_decline_ratio": 1.0,
        "new_highs": 0.0,
        "new_lows": 0.0,
        "confidence": 0.35,
    }
