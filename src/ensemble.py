DEFAULT_WEIGHTS = {
    "momentum": 0.35,
    "trend": 0.30,
    "anomaly": 0.20,
    "mean_reversion": 0.15,
}


def ensemble_score(strategy_scores: dict, weights: dict = None) -> float:
    weights = weights or DEFAULT_WEIGHTS
    total = 0.0
    weight_sum = 0.0

    for name, weight in weights.items():
        if name in strategy_scores:
            total += strategy_scores[name] * weight
            weight_sum += weight

    return total / weight_sum if weight_sum else 0.0
