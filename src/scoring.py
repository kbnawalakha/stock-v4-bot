from config import STRATEGY_WEIGHTS


def regime_adjusted_weights(regime: str | None, base_weights: dict[str, float] | None = None) -> dict[str, float]:
    weights = dict(base_weights or STRATEGY_WEIGHTS)
    if regime == "RISK_ON":
        weights["trend"] *= 1.25
        weights["options_flow"] *= 1.25
    elif regime == "RISK_OFF":
        weights["news_sentiment"] *= 1.25
        weights["opening_activity"] *= 1.25

    total = sum(weights.values())
    if total <= 0:
        return weights
    return {key: value / total for key, value in weights.items()}


def final_score(features: dict, weights: dict[str, float] | None = None) -> float:
    active_weights = weights or STRATEGY_WEIGHTS
    total = 0.0
    weight_sum = 0.0
    for key, weight in active_weights.items():
        total += features.get(key, 0.0) * weight
        weight_sum += weight
    return total / weight_sum if weight_sum else 0.0


def earnings_setup_score(row: dict) -> float:
    return (
        row.get("earnings_proximity", 0) * 0.25
        + row.get("relative_strength", 0) * 0.25
        + row.get("trend", 0) * 0.15
        + row.get("news_catalyst", 0) * 0.20
        + row.get("breakout", 0) * 0.15
    )


def catalyst_watch_score(row: dict) -> float:
    return (
        row.get("news_catalyst", 0) * 0.35
        + row.get("political_geo", 0) * 0.25
        + row.get("politician_trade", 0) * 0.15
        + row.get("relative_strength", 0) * 0.15
        + row.get("breakout", 0) * 0.10
    )
