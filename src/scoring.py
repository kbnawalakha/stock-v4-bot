from config import STRATEGY_WEIGHTS


def final_score(features: dict) -> float:
    total = 0.0
    weight_sum = 0.0
    for key, weight in STRATEGY_WEIGHTS.items():
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
