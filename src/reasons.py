def why_buy(row: dict, is_earnings: bool = False, is_catalyst: bool = False) -> str:
    reasons = []

    if is_earnings and row.get("days_to_earnings") is not None:
        reasons.append(f"earnings in {row['days_to_earnings']} days")
    if row.get("relative_strength", 0) >= 25:
        reasons.append("beating SPY/QQQ")
    if row.get("trend", 0) >= 75:
        reasons.append("strong uptrend")
    if row.get("sector_strength", 0) >= 20:
        reasons.append("strong sector")
    if row.get("breakout", 0) >= 55:
        reasons.append("breakout setup")
    if row.get("opening_activity", 0) >= 70:
        reasons.append("positive opening volume spike")
    if row.get("options_flow", 0) >= 70:
        reasons.append("bullish options activity")
    if row.get("earnings", 0) >= 70:
        reasons.append("positive earnings setup")
    if row.get("news_sentiment", 0) >= 70:
        reasons.append("strong overnight news")
    if row.get("news_catalyst", 0) >= 25:
        reasons.append("positive news catalyst")
    if row.get("political_geo", 0) >= 20:
        reasons.append("political/geopolitical tailwind")
    if row.get("politician_trade", 0) >= 10:
        reasons.append("politician buying signal")
    if row.get("risk_quality", 0) >= 70:
        reasons.append("clean risk profile")

    if is_catalyst and row.get("catalysts"):
        short = row["catalysts"][0]
        if len(short) > 85:
            short = short[:82] + "..."
        reasons.insert(0, f"catalyst: {short}")

    if row.get("political_reasons"):
        reasons.append(row["political_reasons"][0])
    if row.get("politician_reasons"):
        reasons.append(row["politician_reasons"][0])

    if not reasons:
        reasons.append("best combined setup today")

    return "; ".join(reasons[:3]).capitalize() + "."
