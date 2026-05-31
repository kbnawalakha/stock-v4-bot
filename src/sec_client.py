import json
import logging
import os
from functools import lru_cache
from typing import Any

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://data.sec.gov"
TICKER_URL = "https://www.sec.gov/files/company_tickers.json"
TIMEOUT_SECONDS = 15


def sec_headers() -> dict[str, str] | None:
    user_agent = os.getenv("SEC_USER_AGENT")
    if not user_agent:
        return None
    return {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate", "Host": "data.sec.gov"}


@lru_cache(maxsize=1)
def ticker_cik_map() -> dict[str, str]:
    headers = sec_headers()
    if headers is None:
        return {}
    try:
        response = requests.get(
            TICKER_URL,
            headers={**headers, "Host": "www.sec.gov"},
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()
        mapping = {}
        for item in data.values():
            ticker = str(item.get("ticker", "")).upper()
            cik = str(item.get("cik_str", "")).zfill(10)
            if ticker and cik:
                mapping[ticker] = cik
        return mapping
    except Exception as exc:
        logger.warning(json.dumps({"event": "sec_ticker_map_failed", "error": str(exc)}))
        return {}


def cik_for_ticker(ticker: str) -> str | None:
    return ticker_cik_map().get(ticker.upper())


def submissions(ticker: str) -> dict[str, Any] | None:
    cik = cik_for_ticker(ticker)
    headers = sec_headers()
    if not cik or headers is None:
        return None
    try:
        response = requests.get(f"{BASE_URL}/submissions/CIK{cik}.json", headers=headers, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        logger.warning(json.dumps({"event": "sec_submissions_failed", "ticker": ticker, "error": str(exc)}))
        return None
