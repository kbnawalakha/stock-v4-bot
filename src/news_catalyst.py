import re
from market_data import get_ticker_obj

POSITIVE_WORDS = [
    "beat", "beats", "raise", "raises", "upgrade", "upgraded", "strong", "growth",
    "contract", "partnership", "record", "approval", "launch", "surge", "profit",
    "guidance", "outperform", "buy rating", "price target", "ai", "semiconductor",
    "deal", "expansion", "wins", "award", "order", "demand"
]

NEGATIVE_WORDS = [
    "miss", "misses", "cut", "cuts", "downgrade", "downgraded", "weak", "lawsuit",
    "probe", "delay", "recall", "loss", "warning", "underperform", "sell rating",
    "sanction", "ban", "investigation"
]

CATALYST_WORDS = [
    "earnings", "guidance", "contract", "upgrade", "approval", "partnership",
    "launch", "ai", "tariff", "sanctions", "war", "defense", "government",
    "chips", "semiconductor", "energy", "nuclear", "cybersecurity", "data center"
]


def get_recent_headlines(ticker: str, limit: int = 8) -> list[str]:
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


def catalyst_details(ticker: str, headlines: list[str] | None = None) -> dict:
    headlines = headlines if headlines is not None else get_recent_headlines(ticker)
    if not headlines:
        return {
            "score": 0.0,
            "catalysts": [],
            "has_catalyst": False,
            "polarity": "NONE",
            "positive_hits": 0,
            "negative_hits": 0,
            "catalyst_hits": 0,
        }

    joined = " ".join(headlines).lower()
    pos = sum(1 for w in POSITIVE_WORDS if re.search(r"\b" + re.escape(w) + r"\b", joined))
    neg = sum(1 for w in NEGATIVE_WORDS if re.search(r"\b" + re.escape(w) + r"\b", joined))
    catalyst_hits = sum(1 for w in CATALYST_WORDS if re.search(r"\b" + re.escape(w) + r"\b", joined))

    raw = (pos - neg) * 16 + catalyst_hits * 8
    score = max(min(raw, 100), -100)

    catalysts = []
    for h in headlines:
        hl = h.lower()
        if any(w in hl for w in POSITIVE_WORDS + NEGATIVE_WORDS + CATALYST_WORDS):
            catalysts.append(h)
        if len(catalysts) >= 2:
            break

    polarity = "MIXED"
    if pos > neg:
        polarity = "POSITIVE"
    elif neg > pos:
        polarity = "NEGATIVE"
    elif catalyst_hits == 0:
        polarity = "NONE"

    return {
        "score": float(score),
        "catalysts": catalysts,
        "has_catalyst": catalyst_hits > 0,
        "polarity": polarity,
        "positive_hits": pos,
        "negative_hits": neg,
        "catalyst_hits": catalyst_hits,
    }


def news_catalyst_score(ticker: str) -> tuple[float, list[str], bool]:
    details = catalyst_details(ticker)
    return float(details["score"]), list(details["catalysts"]), bool(details["has_catalyst"])
