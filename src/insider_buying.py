from datetime import datetime, timedelta, timezone
from typing import Any

from alpha_vantage_client import get_alpha_vantage_client
from fmp_client import get_fmp_client
from sec_client import submissions
from signal_utils import clamp, safe_float


def insider_buying_score(ticker: str) -> dict[str, float | str]:
    av = _from_alpha_vantage(ticker)
    if av["data_available"]:
        return av
    fmp = _from_fmp(ticker)
    if fmp["data_available"]:
        return fmp
    sec = _from_sec(ticker)
    if sec["data_available"]:
        return sec
    return {
        "score": 0.0,
        "recent_buy_count": 0.0,
        "recent_sell_count": 0.0,
        "cluster_buy_count": 0.0,
        "net_purchase_value": 0.0,
        "reason": "insider transaction data unavailable",
    }


def _from_alpha_vantage(ticker: str) -> dict[str, float | str | bool]:
    client = get_alpha_vantage_client()
    if not client.available:
        return {**_empty("ALPHA_VANTAGE_API_KEY missing"), "data_available": False}
    data = client.query("INSIDER_TRANSACTIONS", {"symbol": ticker})
    rows = []
    if isinstance(data, dict):
        rows = data.get("data") or data.get("transactions") or []
    return _score_rows(rows, "Alpha Vantage")


def _from_fmp(ticker: str) -> dict[str, float | str | bool]:
    client = get_fmp_client()
    if not client.available:
        return {**_empty("FMP_API_KEY missing"), "data_available": False}
    rows = client.get("/v4/insider-trading", {"symbol": ticker, "page": 0})
    return _score_rows(rows if isinstance(rows, list) else [], "FMP")


def _from_sec(ticker: str) -> dict[str, float | str | bool]:
    data = submissions(ticker)
    if not data:
        return {**_empty("SEC_USER_AGENT missing or SEC data unavailable"), "data_available": False}
    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=90)
    form4_count = 0
    for form, filing_date in zip(forms, dates):
        if form != "4":
            continue
        parsed = _date(filing_date)
        if parsed and parsed >= cutoff:
            form4_count += 1
    if form4_count <= 0:
        return {**_empty("SEC filings show no recent Form 4 activity"), "data_available": True}
    return {
        "score": 5.0,
        "recent_buy_count": 0.0,
        "recent_sell_count": 0.0,
        "cluster_buy_count": 0.0,
        "net_purchase_value": 0.0,
        "reason": f"SEC shows {form4_count} recent Form 4 filing(s), but transaction direction was not parsed.",
        "data_available": True,
    }


def _score_rows(rows: Any, source: str) -> dict[str, float | str | bool]:
    if not isinstance(rows, list) or not rows:
        return {**_empty(f"{source} insider transactions unavailable"), "data_available": False}
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=90)
    buy_count = 0
    sell_count = 0
    cluster_buy_count = 0
    net_value = 0.0
    buyers = set()
    for row in rows[:100]:
        if not isinstance(row, dict):
            continue
        trade_date = _date(row.get("transactionDate") or row.get("filingDate") or row.get("date"))
        if trade_date and trade_date < cutoff:
            continue
        side_text = " ".join(str(row.get(key, "")) for key in ("transactionType", "transaction", "type", "acquistionOrDisposition", "acquisitionOrDisposition")).lower()
        title = str(row.get("executiveTitle") or row.get("reportingName") or row.get("ownerName") or "").lower()
        value = _transaction_value(row)
        is_buy = any(word in side_text for word in ("buy", "purchase", "acquisition", "a -"))
        is_sell = any(word in side_text for word in ("sell", "sale", "disposition", "d -"))
        if is_buy:
            buy_count += 1
            net_value += value
            buyers.add(title or str(row.get("reportingName") or row.get("ownerName") or len(buyers)))
            if any(role in title for role in ("ceo", "chief executive", "cfo", "chief financial", "director")):
                cluster_buy_count += 1
        elif is_sell and "option" not in side_text and "exercise" not in side_text:
            sell_count += 1
            net_value -= value

    cluster_buy_count = max(cluster_buy_count, len(buyers) if buy_count >= 3 else 0)
    score = buy_count * 18 + cluster_buy_count * 10 - sell_count * 7 + clamp(net_value / 250000, -25, 25)
    score = clamp(score, -100, 100)
    reason = "Recent insider buying is supportive." if score > 20 else "Insider selling pressure is a risk." if score < -20 else "Insider activity is neutral."
    return {
        "score": score,
        "recent_buy_count": float(buy_count),
        "recent_sell_count": float(sell_count),
        "cluster_buy_count": float(cluster_buy_count),
        "net_purchase_value": float(net_value),
        "reason": reason,
        "data_available": True,
    }


def _empty(reason: str) -> dict[str, float | str]:
    return {
        "score": 0.0,
        "recent_buy_count": 0.0,
        "recent_sell_count": 0.0,
        "cluster_buy_count": 0.0,
        "net_purchase_value": 0.0,
        "reason": reason,
    }


def _transaction_value(row: dict[str, Any]) -> float:
    direct = safe_float(row.get("transactionValue") or row.get("value"))
    if direct is not None:
        return direct
    shares = safe_float(row.get("securitiesTransacted") or row.get("securitiesTransactedShares") or row.get("shares"))
    price = safe_float(row.get("price") or row.get("transactionPrice"))
    if shares is None or price is None:
        return 0.0
    return shares * price


def _date(value: Any):
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except Exception:
        return None
