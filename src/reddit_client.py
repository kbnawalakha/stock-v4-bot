import json
import logging
import os
import re
import time
from collections import defaultdict
from typing import Any

import requests

logger = logging.getLogger(__name__)

DEFAULT_SUBREDDITS = [
    "wallstreetbets",
    "stocks",
    "investing",
    "StockMarket",
    "options",
    "pennystocks",
]
DEFAULT_POST_LIMIT = 30
REQUEST_TIMEOUT_SECONDS = 15
USER_AGENT = "stock-v4-bot/1.0"

CASHTAG_RE = re.compile(r"\$([A-Z]{1,5})(?![A-Z])")
UPPER_TICKER_RE = re.compile(r"\b([A-Z]{2,5})\b")

COMMON_FALSE_TICKERS = {
    "A", "AI", "ALL", "AM", "APR", "ARE", "ATH", "BE", "CEO", "CFO", "CPI",
    "DD", "DIY", "DTE", "ETF", "EV", "EPS", "ER", "EU", "FDA", "FED", "FOMC",
    "FOR", "GDP", "HODL", "IPO", "IRA", "IRS", "ITM", "IV", "LOL", "MACD",
    "MAY", "MOON", "NAV", "NYSE", "OTM", "PE", "PM", "PR", "QQQ", "SEC",
    "SPY", "TA", "THE", "USA", "USD", "VIX", "VWAP", "YOLO",
}


def fetch_reddit_posts(
    subreddits: list[str] | None = None,
    limit_per_subreddit: int | None = None,
) -> list[dict[str, Any]]:
    subreddits = subreddits or _configured_subreddits()
    limit = limit_per_subreddit or int(os.getenv("REDDIT_POST_LIMIT") or DEFAULT_POST_LIMIT)
    posts: list[dict[str, Any]] = []

    for subreddit in subreddits:
        url = f"https://www.reddit.com/r/{subreddit}/hot.json"
        try:
            response = requests.get(
                url,
                headers={"User-Agent": USER_AGENT},
                params={"limit": max(1, min(limit, 100))},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            if response.status_code == 429:
                logger.warning(json.dumps({"event": "reddit_rate_limited", "subreddit": subreddit}))
                time.sleep(2)
                continue
            if response.status_code >= 400:
                logger.warning(json.dumps({
                    "event": "reddit_http_error",
                    "subreddit": subreddit,
                    "status_code": response.status_code,
                    "response_snippet": response.text[:500],
                }))
                continue

            children = response.json().get("data", {}).get("children", [])
            subreddit_posts = []
            for child in children:
                data = child.get("data", {})
                if not data or data.get("stickied"):
                    continue
                subreddit_posts.append({
                    "title": str(data.get("title") or ""),
                    "selftext": str(data.get("selftext") or "")[:1200],
                    "subreddit": subreddit,
                    "score": int(data.get("score") or 0),
                    "num_comments": int(data.get("num_comments") or 0),
                    "created_utc": data.get("created_utc"),
                    "permalink": f"https://www.reddit.com{data.get('permalink', '')}",
                })
            posts.extend(subreddit_posts)
            logger.info(json.dumps({
                "event": "reddit_posts_fetched",
                "subreddit": subreddit,
                "post_count": len(subreddit_posts),
            }))
        except Exception as exc:
            logger.warning(json.dumps({"event": "reddit_fetch_failed", "subreddit": subreddit, "error": str(exc)}))
            continue

    logger.info(json.dumps({"event": "reddit_posts_total", "post_count": len(posts)}))
    return posts


def extract_reddit_candidates(
    posts: list[dict[str, Any]],
    universe: set[str] | None = None,
    limit: int = 12,
) -> list[dict[str, Any]]:
    universe = {ticker.upper() for ticker in universe or set()}
    by_ticker: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "ticker": "",
        "mention_count": 0,
        "cashtag_mentions": 0,
        "engagement": 0,
        "subreddits": set(),
        "sample_posts": [],
    })

    for post in posts:
        text = f"{post.get('title', '')} {post.get('selftext', '')}"
        cashtags = {match.upper() for match in CASHTAG_RE.findall(text)}
        uppercase_mentions = {match.upper() for match in UPPER_TICKER_RE.findall(text)}
        tickers = {
            ticker for ticker in cashtags | uppercase_mentions
            if _looks_like_ticker(ticker, cashtags, universe)
        }
        if not tickers:
            continue

        engagement = max(0, int(post.get("score") or 0)) + max(0, int(post.get("num_comments") or 0)) * 2
        for ticker in tickers:
            row = by_ticker[ticker]
            row["ticker"] = ticker
            row["mention_count"] += 1
            row["cashtag_mentions"] += 1 if ticker in cashtags else 0
            row["engagement"] += engagement
            row["subreddits"].add(str(post.get("subreddit") or "reddit"))
            if len(row["sample_posts"]) < 3:
                row["sample_posts"].append({
                    "title": post.get("title", ""),
                    "subreddit": post.get("subreddit", ""),
                    "score": post.get("score", 0),
                    "num_comments": post.get("num_comments", 0),
                    "permalink": post.get("permalink", ""),
                })

    candidates = []
    for row in by_ticker.values():
        row["subreddits"] = sorted(row["subreddits"])
        row["raw_score"] = (
            row["mention_count"] * 10
            + row["cashtag_mentions"] * 15
            + min(45, row["engagement"] ** 0.5)
            + min(20, len(row["subreddits"]) * 5)
        )
        candidates.append(dict(row))

    candidates = sorted(candidates, key=lambda item: item["raw_score"], reverse=True)[:limit]
    logger.info(json.dumps({
        "event": "reddit_candidates_extracted",
        "candidate_count": len(candidates),
        "tickers": [candidate["ticker"] for candidate in candidates],
    }))
    return candidates


def _configured_subreddits() -> list[str]:
    configured = os.getenv("REDDIT_SUBREDDITS", "")
    if configured.strip():
        return [item.strip().strip("/").replace("r/", "") for item in configured.split(",") if item.strip()]
    return DEFAULT_SUBREDDITS


def _looks_like_ticker(ticker: str, cashtags: set[str], universe: set[str]) -> bool:
    if ticker in COMMON_FALSE_TICKERS:
        return False
    if not 1 <= len(ticker) <= 5 or not ticker.isalpha():
        return False
    if ticker in cashtags:
        return True
    if ticker in universe:
        return True
    return 2 <= len(ticker) <= 5
