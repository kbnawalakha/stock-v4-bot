import os
import requests
from bs4 import BeautifulSoup

CACHE = {}


def _configured_api_score(ticker: str) -> tuple[float, list[str]]:
    api_url = os.getenv("POLITICIAN_TRADE_API_URL")
    api_key = os.getenv("POLITICIAN_TRADE_API_KEY")

    if not api_url:
        return 0.0, []

    try:
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        resp = requests.get(api_url, params={"ticker": ticker}, headers=headers, timeout=15)
        if resp.status_code != 200:
            return 0.0, []

        data = resp.json()
        trades = data.get("trades", data if isinstance(data, list) else [])
        buys = []
        sells = []

        for trade in trades[:20]:
            side = str(trade.get("transaction", trade.get("type", ""))).lower()
            politician = trade.get("politician") or trade.get("representative") or trade.get("name") or "politician"
            if "buy" in side or "purchase" in side:
                buys.append(politician)
            if "sell" in side:
                sells.append(politician)

        score = min(len(buys) * 20 - len(sells) * 10, 100)
        reasons = [f"recent politician buy: {name}" for name in buys[:2]]
        return float(max(score, -50)), reasons

    except Exception:
        return 0.0, []


def _capitol_trades_public_check(ticker: str) -> tuple[float, list[str]]:
    # This is a lightweight public-page check. It may break if the site changes.
    # For reliable production use, configure POLITICIAN_TRADE_API_URL.
    if ticker in CACHE:
        return CACHE[ticker]

    try:
        url = f"https://www.capitoltrades.com/trades?issuer={ticker}"
        resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        text = resp.text.lower()

        if resp.status_code != 200 or ticker.lower() not in text:
            CACHE[ticker] = (0.0, [])
            return CACHE[ticker]

        soup = BeautifulSoup(resp.text, "html.parser")
        page_text = soup.get_text(" ", strip=True).lower()

        buy_hits = page_text.count(" buy ")
        sell_hits = page_text.count(" sell ")
        score = min(buy_hits * 8 - sell_hits * 4, 60)

        reasons = []
        if buy_hits > 0:
            reasons.append("politician trade page shows buy activity")

        CACHE[ticker] = (float(max(score, -30)), reasons[:2])
        return CACHE[ticker]

    except Exception:
        CACHE[ticker] = (0.0, [])
        return CACHE[ticker]


def politician_trade_score(ticker: str) -> tuple[float, list[str]]:
    score, reasons = _configured_api_score(ticker)
    if score != 0 or reasons:
        return score, reasons

    return _capitol_trades_public_check(ticker)
