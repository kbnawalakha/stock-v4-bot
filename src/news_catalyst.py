import re
from market_data import get_ticker_obj


POSITIVE_WORDS = [
    "beat", "beats", "raise", "raises", "upgrade", "upgraded", "strong", "growth",
    "contract", "partnership", "record", "approval", "launch", "surge", "profit",
    "guidance", "outperform", "buy rating", "price target", "ai", "semiconductor"
]

NEGATIVE_WORDS = [
    "miss", "misses", "cut", "cuts", "downgrade", "downgraded", "weak", "lawsuit",
    "probe", "delay", "recall", "loss", "warning", "underperform", "sell rating"
]


def get_recent_headlines(ticker: str, limit: int = 6) -> list[str]:
    try:
        obj = get_ticker_obj(ticker)
        news = obj.news or []
        headlines = []
        for item in news[:limit]:
            title = item.get("title") or item.get("content", {}).get("title") or ""
            if title:
                headlines.append(title)
        return headlines
    except Exception:
        return []


def news_catalyst_score(ticker: str) -> tuple[float, list[str]]:
    headlines = get_recent_headlines(ticker)
    if not headlines:
        return 0.0, []

    joined = " ".join(headlines).lower()
    pos = sum(1 for w in POSITIVE_WORDS if re.search(r"\b" + re.escape(w) + r"\b", joined))
    neg = sum(1 for w in NEGATIVE_WORDS if re.search(r"\b" + re.escape(w) + r"\b", joined))

    raw = (pos - neg) * 18
    score = max(min(raw, 100), -100)

    catalysts = []
    for h in headlines:
        hl = h.lower()
        if any(w in hl for w in POSITIVE_WORDS):
            catalysts.append(h)
        if len(catalysts) >= 2:
            break

    return float(score), catalysts
