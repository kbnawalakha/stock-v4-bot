def why_buy(row: dict, is_earnings: bool = False) -> str:
    reasons = []

    if row.get("relative_strength", 0) >= 25:
        reasons.append("beating SPY/QQQ")
    if row.get("trend", 0) >= 75:
        reasons.append("strong uptrend")
    if row.get("sector_strength", 0) >= 20:
        reasons.append("strong sector")
    if row.get("breakout", 0) >= 55:
        reasons.append("breakout setup")
    if row.get("news_catalyst", 0) >= 25:
        reasons.append("positive news catalyst")
    if row.get("risk_quality", 0) >= 70:
        reasons.append("clean risk profile")
    if is_earnings and row.get("days_to_earnings") is not None:
        reasons.append(f"earnings in {row['days_to_earnings']} days")

    if not reasons:
        reasons.append("best combined technical setup today")

    return "; ".join(reasons[:3]).capitalize() + "."
