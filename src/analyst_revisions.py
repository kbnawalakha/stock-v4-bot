from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from fmp_client import get_fmp_client
from market_data import get_ticker_obj
from signal_utils import clamp, safe_float

# FMP's legacy v3/v4 analyst endpoints below are only served to subscriptions
# created before 2025-08-31; for everyone else they return a legacy error and
# the FMP client disables itself for the run. When FMP yields nothing we fall
# back to yfinance (already a dependency) so the analyst signal is not stuck at
# neutral for every ticker.


def analyst_revision_score(ticker: str) -> dict[str, float | None | str]:
    fmp = _from_fmp(ticker)
    if fmp.get("data_available"):
        return _strip_internal(fmp)
    yfin = _from_yfinance(ticker)
    if yfin.get("data_available"):
        return _strip_internal(yfin)
    return _strip_internal(_neutral("No recent analyst revision data found."))


def _from_fmp(ticker: str) -> dict[str, float | None | str | bool]:
    client = get_fmp_client()
    if not client.available:
        return {**_neutral("FMP_API_KEY missing; using yfinance fallback."), "data_available": False}

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
    if upgrade_score:
        components.append(upgrade_score)

    if not components or all(value == 0 for value in components):
        return {**_neutral("No recent FMP analyst revision data found."), "data_available": False}

    score = clamp(sum(components) / len(components), -100, 100)
    return {
        "score": score,
        "eps_revision_30d": eps_revision,
        "revenue_revision_30d": revenue_revision,
        "price_target_change_30d": price_target_change,
        "upgrade_downgrade_score": upgrade_score,
        "reason": _reason("FMP", score, eps_revision, revenue_revision, price_target_change, upgrade_score),
        "data_available": True,
    }


def _from_yfinance(ticker: str, lookback_days: int = 60) -> dict[str, float | None | str | bool]:
    try:
        obj = get_ticker_obj(ticker)
    except Exception:
        return {**_neutral("analyst revision data unavailable"), "data_available": False}

    upgrade_score = _yf_upgrade_downgrade_score(obj, lookback_days)
    rec_trend = _yf_recommendation_trend(obj)
    target_gap = _yf_price_target_gap(obj)

    components = [value for value in (upgrade_score, rec_trend, target_gap) if value is not None]
    if not components or all(value == 0 for value in components):
        return {**_neutral("No recent analyst revision data found."), "data_available": False}

    score = clamp(sum(components) / len(components), -100, 100)
    return {
        "score": score,
        "eps_revision_30d": None,
        "revenue_revision_30d": None,
        "price_target_change_30d": target_gap,
        "upgrade_downgrade_score": upgrade_score or 0.0,
        "reason": _reason("yfinance", score, None, None, target_gap, upgrade_score or 0.0),
        "data_available": True,
    }


def _yf_upgrade_downgrade_score(obj: Any, lookback_days: int) -> float | None:
    try:
        df = getattr(obj, "upgrades_downgrades", None)
    except Exception:
        df = None
    if not isinstance(df, pd.DataFrame) or df.empty:
        return None
    frame = df.copy()
    # GradeDate may be the index or a column depending on yfinance version.
    if "GradeDate" in frame.columns:
        frame = frame.set_index("GradeDate")
    try:
        idx = pd.to_datetime(frame.index)
        cutoff = pd.Timestamp.now(tz=idx.tz) - pd.Timedelta(days=lookback_days)
        recent = frame[idx >= cutoff]
    except Exception:
        recent = frame.tail(15)
    if recent.empty:
        recent = frame.tail(10)

    score = 0.0
    for _, row in recent.iterrows():
        action = str(row.get("Action", "")).lower()
        to_grade = str(row.get("ToGrade", "")).lower()
        if action in ("up", "upgrade"):
            score += 25
        elif action in ("down", "downgrade"):
            score -= 25
        elif any(word in to_grade for word in ("buy", "outperform", "overweight", "positive")):
            score += 10
        elif any(word in to_grade for word in ("sell", "underperform", "underweight", "negative")):
            score -= 10
    return clamp(score, -100, 100)


def _yf_recommendation_trend(obj: Any) -> float | None:
    frame = None
    for attr in ("recommendations_summary", "recommendations"):
        try:
            candidate = getattr(obj, attr, None)
        except Exception:
            candidate = None
        if isinstance(candidate, pd.DataFrame) and not candidate.empty and "strongBuy" in candidate.columns:
            frame = candidate
            break
    if frame is None:
        return None

    def net(row) -> float | None:
        total = sum(safe_float(row.get(col)) or 0.0 for col in ("strongBuy", "buy", "hold", "sell", "strongSell"))
        if total <= 0:
            return None
        bullish = (safe_float(row.get("strongBuy")) or 0.0) + (safe_float(row.get("buy")) or 0.0)
        bearish = (safe_float(row.get("sell")) or 0.0) + (safe_float(row.get("strongSell")) or 0.0)
        return (bullish - bearish) / total

    rows = [frame.iloc[i] for i in range(len(frame))]
    now_net = next((net(r) for r in rows if net(r) is not None), None)
    if now_net is None:
        return None
    older_net = next((net(r) for r in reversed(rows) if net(r) is not None), None)
    if older_net is not None and len(rows) > 1 and older_net != now_net:
        # Reward an improving analyst mix over the trailing periods (a revision).
        return clamp((now_net - older_net) * 100 + now_net * 40, -100, 100)
    # Only a single period available: use its level as a mild tilt.
    return clamp(now_net * 60, -100, 100)


def _yf_price_target_gap(obj: Any) -> float | None:
    mean = current = None
    try:
        targets = getattr(obj, "analyst_price_targets", None)
    except Exception:
        targets = None
    if isinstance(targets, dict):
        mean = safe_float(targets.get("mean"))
        current = safe_float(targets.get("current"))
    if mean is None or current is None:
        try:
            info = getattr(obj, "info", None) or {}
        except Exception:
            info = {}
        mean = mean if mean is not None else safe_float(info.get("targetMeanPrice"))
        current = current if current is not None else safe_float(
            info.get("currentPrice") or info.get("regularMarketPrice")
        )
    if not mean or not current or current <= 0:
        return None
    gap = (mean / current - 1.0) * 100.0
    return clamp(gap * 4, -100, 100)


def _strip_internal(result: dict[str, Any]) -> dict[str, float | None | str]:
    return {key: value for key, value in result.items() if key != "data_available"}


def _neutral(reason: str) -> dict[str, float | None | str]:
    return {
        "score": 0.0,
        "eps_revision_30d": None,
        "revenue_revision_30d": None,
        "price_target_change_30d": None,
        "upgrade_downgrade_score": 0.0,
        "reason": reason,
        "data_available": False,
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


def _reason(source: str, score: float, eps: float | None, revenue: float | None, target: float | None, upgrade: float) -> str:
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
        parts.append(f"price target gap {target:.1f}%")
    if upgrade:
        parts.append(f"upgrade/downgrade score {upgrade:.0f}")
    return f"Analyst revision signal ({source}) is {direction}: " + "; ".join(parts[:3])
