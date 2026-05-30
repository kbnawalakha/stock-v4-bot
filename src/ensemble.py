from config import STRATEGY_WEIGHTS


def ensemble_score(strategy_scores: dict, weights: dict | None = None) -> float:
    weights = weights or STRATEGY_WEIGHTS
    total = 0.0
    weight_sum = 0.0
    for name, weight in weights.items():
        if name in strategy_scores:
            total += float(strategy_scores[name]) * float(weight)
            weight_sum += float(weight)
    return total / weight_sum if weight_sum else 0.0
