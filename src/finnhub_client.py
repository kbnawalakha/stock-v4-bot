import logging
import os
import time
from collections import deque
from datetime import date, timedelta
from typing import Any

import requests

BASE_URL = "https://finnhub.io/api/v1"
TIMEOUT_SECONDS = 12
MAX_RETRIES = 3
DEFAULT_MAX_CALLS_PER_MINUTE = 60

logger = logging.getLogger(__name__)


class FinnhubClient:
    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.getenv("FINNHUB_API_KEY")
        self.session = requests.Session()
        self.max_calls_per_minute = int(os.getenv("FINNHUB_MAX_CALLS_PER_MINUTE", DEFAULT_MAX_CALLS_PER_MINUTE))
        self.calls_made = 0
        self._call_timestamps = deque()

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any] | list[Any] | None:
        if not self.api_key:
            return None

        payload = {**params, "token": self.api_key}
        url = f"{BASE_URL}{path}"
        for attempt in range(MAX_RETRIES):
            try:
                self._throttle()
                self.calls_made += 1
                response = self.session.get(url, params=payload, timeout=TIMEOUT_SECONDS)
                if response.status_code == 429:
                    sleep_for = min(2 ** attempt, 8)
                    logger.warning(
                        "finnhub_rate_limit",
                        extra={"path": path, "attempt": attempt + 1, "sleep_seconds": sleep_for},
                    )
                    time.sleep(sleep_for)
                    continue
                if response.status_code >= 500:
                    time.sleep(min(2 ** attempt, 8))
                    continue
                response.raise_for_status()
                return response.json()
            except requests.RequestException as exc:
                logger.warning(
                    "finnhub_request_failed",
                    extra={"path": path, "attempt": attempt + 1, "error": str(exc)},
                )
                if attempt < MAX_RETRIES - 1:
                    time.sleep(min(2 ** attempt, 8))
        return None

    def _throttle(self) -> None:
        now = time.monotonic()
        while self._call_timestamps and now - self._call_timestamps[0] >= 60:
            self._call_timestamps.popleft()

        if len(self._call_timestamps) >= self.max_calls_per_minute:
            sleep_for = 60 - (now - self._call_timestamps[0])
            logger.info(
                "finnhub_rate_throttle",
                extra={"sleep_seconds": sleep_for, "max_calls_per_minute": self.max_calls_per_minute},
            )
            time.sleep(max(0.0, sleep_for))
            now = time.monotonic()
            while self._call_timestamps and now - self._call_timestamps[0] >= 60:
                self._call_timestamps.popleft()

        self._call_timestamps.append(time.monotonic())

    def overnight_company_news(self, ticker: str) -> list[dict[str, Any]]:
        today = date.today()
        start = today - timedelta(days=2)
        data = self._get(
            "/company-news",
            {"symbol": ticker, "from": start.isoformat(), "to": today.isoformat()},
        )
        if not isinstance(data, list):
            return []
        return sorted(data, key=lambda x: x.get("datetime", 0), reverse=True)

    def overnight_headlines(self, ticker: str, limit: int = 12) -> list[str]:
        headlines = []
        for item in self.overnight_company_news(ticker):
            headline = item.get("headline") or item.get("summary")
            if headline:
                headlines.append(str(headline))
            if len(headlines) >= limit:
                break
        return headlines

    def earnings_calendar(self, ticker: str, days_ahead: int = 45) -> list[dict[str, Any]]:
        today = date.today()
        end = today + timedelta(days=days_ahead)
        data = self._get(
            "/calendar/earnings",
            {"symbol": ticker, "from": today.isoformat(), "to": end.isoformat()},
        )
        if not isinstance(data, dict):
            return []
        earnings = data.get("earningsCalendar")
        return earnings if isinstance(earnings, list) else []

    def earnings_surprises(self, ticker: str, limit: int = 4) -> list[dict[str, Any]]:
        data = self._get("/stock/earnings", {"symbol": ticker})
        if not isinstance(data, list):
            return []
        return data[:limit]


_CLIENT: FinnhubClient | None = None


def get_finnhub_client() -> FinnhubClient:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = FinnhubClient()
    return _CLIENT
