from datetime import datetime, timedelta, timezone
from typing import Any

from fmp_client import get_fmp_client
from signal_utils import clamp, safe_float


def analyst_revision_score(ticker: str) -> dict[str, float | None | str]:
    client = get_fmp_client()
    if not client.available:
        return _neutral("FMP_API_KEY missing; analyst revision data unavailable.")

    estimates = _as_list(client.get(f"/v3/analyst-estimates/{ticker}", {"period": "quarter", "limit": 8}))
    price_targets = _as_list(client.get(f"/v4/price-target", {"symbol": ticker}))
    changes = _as_list(client.get(f"/v4/upgrades-downgrades", {"symbol": ticker}))

    eps_revision = _revision(estimates, ["estimatedEpsAvg", "estimatedEps", "epsAvg", "eps"])
    revenue_revision = _revision(estimates, ["estimatedRevenueAvg", "estimatedRevenue", "revenueAvg", "revenue"])
    price_target_change = _target_change(price_targets)
    upgrade_score = _upgrade_downgrade_score(changes)

    components = []
    if eps_revision is not None:
        components.append(clamp(eps_revision * 8, -100, 100))
    if revenue_revision is not None:
        components.append(clamp(revenue_revision * 5, -100, 100))
    if price_target_change is not None:
        components.append(clamp(price_target_change * 4, -100, 100))
    components.append(upgrade_score)

    if not components or all(value == 0 for value in components):
        return _neutral("No recent analyst revision data found.")

    score = clamp(sum(components) / len(components), -100, 100)
    reason = _reason(score, eps_revision, revenue_revision, price_target_change, upgrade_score)
    return {
        "score": score,
        "eps_revision_30d": eps_revision,
        "revenue_revision_30d": revenue_revision,
        "price_target_change_30d": price_target_change,
        "upgrade_downgrade_score": upgrade_score,
        "reason": reason,
    }


def _neutral(reason: str) -> dict[str, float | None | str]:
    return {
        "score": 0.0,
        "eps_revision_30d": None,
        "revenue_revision_30d": None,
        "price_target_change_30d": None,
        "upgrade_downgrade_score": 0.0,
        "reason": reason,
    }


def _as_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        for key in ("data", "results", "historical"):
            if isinstance(value.get(key), list):
                return [item for item in value[key] if isinstance(item, dict)]
    return []


def _revision(rows: list[dict[str, Any]], keys: list[str]) -> float | None:
    if len(rows) < 2:
        return None
    sorted_rows = sorted(rows, key=lambda item: str(item.get("date") or item.get("calendarDate") or ""), reverse=True)
    latest = _first_number(sorted_rows[0], keys)
    prior = None
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=45)
    for row in sorted_rows[1:]:
        row_date = _parse_date(row.get("date") or row.get("calendarDate"))
        value = _first_number(row, keys)
        if value is None:
            continue
        prior = value
        if row_date is None or row_date <= cutoff:
            break
    if latest is None or prior in (None, 0):
        return None
    return (latest / prior - 1.0) * 100.0


def _target_change(rows: list[dict[str, Any]]) -> float | None:
    recent = [_first_number(row, ["priceTarget", "priceTargetAverage", "newPriceTarget", "targetPrice"]) for row in rows]
    recent = [value for value in recent if value is not None and value > 0]
    if len(recent) < 2:
        return None
    latest_avg = sum(recent[:3]) / min(3, len(recent))
    prior_slice = recent[3:8] or recent[1:4]
    prior_avg = sum(prior_slice) / len(prior_slice)
    if prior_avg <= 0:
        return None
    return (latest_avg / prior_avg - 1.0) * 100.0


def _upgrade_downgrade_score(rows: list[dict[str, Any]]) -> float:
    score = 0.0
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=45)
    for row in rows[:20]:
        row_date = _parse_date(row.get("publishedDate") or row.get("date"))
        if row_date and row_date < cutoff:
            continue
        text = " ".join(str(row.get(key, "")) for key in ("action", "newGrade", "previousGrade", "gradingCompany")).lower()
        if "upgrade" in text:
            score += 25
        elif "downgrade" in text:
            score -= 25
        elif any(word in text for word in ("buy", "outperform", "overweight", "positive")):
            score += 10
        elif any(word in text for word in ("sell", "underperform", "underweight", "negative")):
            score -= 10
    return clamp(score, -100, 100)


def _first_number(row: dict[str, Any], keys: list[str]) -> float | None:
    for key in keys:
        value = safe_float(row.get(key))
        if value is not None:
            return value
    return None


def _parse_date(value: Any):
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except Exception:
        return None


def _reason(score: float, eps: float | None, revenue: float | None, target: float | None, upgrade: float) -> str:
    if score > 20:
        direction = "positive"
    elif score < -20:
        direction = "negative"
    else:
        direction = "neutral"
    parts = []
    if eps is not None:
        parts.append(f"EPS revisions {eps:.1f}%")
    if revenue is not None:
        parts.append(f"revenue revisions {revenue:.1f}%")
    if target is not None:
        parts.append(f"price targets {target:.1f}%")
    if upgrade:
        parts.append(f"upgrade/downgrade score {upgrade:.0f}")
    return f"Analyst revision signal is {direction}: " + "; ".join(parts[:3])
