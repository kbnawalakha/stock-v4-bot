from config import STRATEGY_WEIGHTS
from signal_utils import clamp, signed_to_percent, weighted_average


def regime_adjusted_weights(regime: str | None, base_weights: dict[str, float] | None = None) -> dict[str, float]:
    weights = {**STRATEGY_WEIGHTS, **(base_weights or {})}
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
    active_weights = regime_adjusted_weights(None, weights or STRATEGY_WEIGHTS)
    total = 0.0
    weight_sum = 0.0
    for key, weight in active_weights.items():
        total += features.get(key, 0.0) * weight
        weight_sum += weight
    return total / weight_sum if weight_sum else 0.0


def opportunity_score(row: dict, weights: dict[str, float] | None = None) -> float:
    weights = weights or STRATEGY_WEIGHTS
    return weighted_average([
        (row.get("trend", 50.0), weights.get("trend", 0.10)),
        (signed_to_percent(row.get("relative_strength", 0.0)), weights.get("relative_strength", 0.08)),
        (signed_to_percent(row.get("sector_strength", 0.0)), weights.get("sector_strength", 0.06)),
        (row.get("opening_activity", 50.0), weights.get("opening_activity", 0.12)),
        (row.get("volume_accumulation", 50.0), weights.get("volume_accumulation", 0.08)),
        (row.get("volatility_setup", 50.0), weights.get("volatility_setup", 0.06)),
        (row.get("options_flow", 50.0), weights.get("options_flow", 0.08)),
        (row.get("etf_flow_exposure", 50.0), 0.02),
    ])


def catalyst_score(row: dict, weights: dict[str, float] | None = None) -> float:
    weights = weights or STRATEGY_WEIGHTS
    return weighted_average([
        (row.get("news_sentiment", 50.0), weights.get("news_sentiment", 0.13)),
        (row.get("analyst_revisions", 50.0), weights.get("analyst_revisions", 0.10)),
        (row.get("earnings_quality", row.get("earnings", 50.0)), weights.get("earnings_quality", 0.08)),
        (row.get("insider_buying", 50.0), weights.get("insider_buying", 0.07)),
        (row.get("short_squeeze", 50.0), weights.get("short_squeeze", 0.04)),
        (signed_to_percent(row.get("political_geo", 0.0)), weights.get("political_geo", 0.01)),
        (signed_to_percent(row.get("politician_trade", 0.0)), weights.get("politician_trade", 0.01)),
    ])


def quality_score(row: dict, weights: dict[str, float] | None = None) -> float:
    weights = weights or STRATEGY_WEIGHTS
    return weighted_average([
        (row.get("risk_quality", 50.0), 0.08),
        (row.get("fundamental_momentum", 50.0), weights.get("fundamental_momentum", 0.10)),
        (row.get("institutional_ownership", 50.0), weights.get("institutional_ownership", 0.05)),
        (row.get("pattern_trading", 50.0), weights.get("pattern_trading", 0.05)),
        (row.get("liquidity_score", 50.0), 0.05),
    ])


def regime_adjustment_score(regime: dict | None, breadth: dict | None = None) -> float:
    regime = regime or {}
    breadth = breadth or {}
    base = 50.0
    if regime.get("regime") == "RISK_ON":
        base += 20 * float(regime.get("confidence", 0.5))
    elif regime.get("regime") == "RISK_OFF":
        base -= 20 * float(regime.get("confidence", 0.5))
    base += (float(breadth.get("breadth_score", 50.0)) - 50.0) * 0.35
    return clamp(base, 0, 100)


def staged_final_score(
    row: dict,
    regime: dict | None = None,
    breadth: dict | None = None,
    weights: dict[str, float] | None = None,
) -> float:
    active_weights = regime_adjusted_weights(None, weights or STRATEGY_WEIGHTS)
    opp = opportunity_score(row, active_weights)
    cat = catalyst_score(row, active_weights)
    qual = quality_score(row, active_weights)
    reg = regime_adjustment_score(regime, breadth)
    row["opportunity_score"] = opp
    row["catalyst_score"] = cat
    row["quality_score"] = qual
    row["regime_adjustment_score"] = reg
    score = opp * 0.35 + cat * 0.35 + qual * 0.20 + reg * 0.10
    return clamp(score, 0, 100)


def apply_reddit_blend(score: float, row: dict, reddit_by_ticker: dict[str, dict], enabled: bool = False) -> float:
    if not enabled:
        return score
    play = reddit_by_ticker.get(str(row.get("ticker", "")).upper())
    if not play or not row.get("passed_quality_filter", False):
        return score
    reddit_score = float(play.get("score", 0.0))
    if reddit_score < 35:
        return score
    boost = min(5.0, max(0.0, (reddit_score - 50.0) / 10.0))
    if row.get("liquidity_score", 0) < 50 or row.get("price", 0) < 5:
        boost *= 0.25
    row["reddit_blend_boost"] = boost
    return clamp(score + boost, 0, 100)


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
