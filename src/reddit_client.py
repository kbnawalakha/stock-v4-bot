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
DEFAULT_USER_AGENT = "stock-v4-bot/1.0 contact:github.com/kbnawalakha/stock-v4-bot"

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
        try:
            payload = _fetch_subreddit_listing(subreddit, limit)
            if payload is None:
                continue
            children = payload.get("data", {}).get("children", [])
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


def _fetch_subreddit_listing(subreddit: str, limit: int) -> dict[str, Any] | None:
    params = {"limit": max(1, min(limit, 100)), "raw_json": 1}
    headers = {"User-Agent": os.getenv("REDDIT_USER_AGENT") or DEFAULT_USER_AGENT}
    urls = [
        f"https://www.reddit.com/r/{subreddit}/hot.json",
        f"https://old.reddit.com/r/{subreddit}/hot.json",
    ]

    last_status = None
    for attempt, url in enumerate(urls, start=1):
        try:
            response = requests.get(
                url,
                headers=headers,
                params=params,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            last_status = response.status_code
            if response.status_code == 429:
                logger.warning(json.dumps({
                    "event": "reddit_rate_limited",
                    "subreddit": subreddit,
                    "attempt": attempt,
                    "host": _host_label(url),
                }))
                time.sleep(2)
                continue
            if response.status_code in {401, 403, 451}:
                logger.warning(json.dumps({
                    "event": "reddit_subreddit_blocked",
                    "subreddit": subreddit,
                    "status_code": response.status_code,
                    "attempt": attempt,
                    "host": _host_label(url),
                }))
                continue
            if response.status_code >= 400:
                logger.warning(json.dumps({
                    "event": "reddit_http_error",
                    "subreddit": subreddit,
                    "status_code": response.status_code,
                    "attempt": attempt,
                    "host": _host_label(url),
                    "response_text_length": len(response.text or ""),
                }))
                continue

            try:
                payload = response.json()
            except ValueError as exc:
                logger.warning(json.dumps({
                    "event": "reddit_json_parse_failed",
                    "subreddit": subreddit,
                    "attempt": attempt,
                    "host": _host_label(url),
                    "error": str(exc),
                    "response_text_length": len(response.text or ""),
                }))
                continue
            if isinstance(payload, dict):
                return payload
        except requests.RequestException as exc:
            logger.warning(json.dumps({
                "event": "reddit_request_failed",
                "subreddit": subreddit,
                "attempt": attempt,
                "host": _host_label(url),
                "error": str(exc),
            }))

    logger.warning(json.dumps({
        "event": "reddit_subreddit_skipped",
        "subreddit": subreddit,
        "last_status_code": last_status,
    }))
    return None


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


def _host_label(url: str) -> str:
    if "old.reddit.com" in url:
        return "old.reddit.com"
    return "www.reddit.com"


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
