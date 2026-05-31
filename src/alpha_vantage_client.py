import json
import logging
import os
from typing import Any

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://www.alphavantage.co/query"
TIMEOUT_SECONDS = 15


class AlphaVantageClient:
    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.getenv("ALPHA_VANTAGE_API_KEY")
        self.session = requests.Session()

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def query(self, function: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        if not self.api_key:
            return None
        try:
            response = self.session.get(
                BASE_URL,
                params={**(params or {}), "function": function, "apikey": self.api_key},
                timeout=TIMEOUT_SECONDS,
            )
            if response.status_code >= 400:
                logger.warning(json.dumps({
                    "event": "alpha_vantage_http_error",
                    "function": function,
                    "status_code": response.status_code,
                    "response_snippet": response.text[:500],
                }))
                return None
            data = response.json()
            if "Error Message" in data or "Note" in data:
                logger.warning(json.dumps({
                    "event": "alpha_vantage_api_warning",
                    "function": function,
                    "message": data.get("Error Message") or data.get("Note"),
                }))
                return None
            return data
        except Exception as exc:
            logger.warning(json.dumps({"event": "alpha_vantage_request_failed", "function": function, "error": str(exc)}))
            return None


_CLIENT: AlphaVantageClient | None = None


def get_alpha_vantage_client() -> AlphaVantageClient:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = AlphaVantageClient()
    return _CLIENT
