def suggested_qty(price: float, score: float, cash: float = 100000.0) -> int:
    if price <= 0 or score <= 0:
        return 0

    max_trade_value = cash * 0.02
    confidence = min(max(score / 100, 0), 1)
    trade_value = max_trade_value * confidence
    return int(trade_value // price)
