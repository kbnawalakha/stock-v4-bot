import json
import logging
import os
from typing import Any

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://financialmodelingprep.com/api"
TIMEOUT_SECONDS = 15


class FMPClient:
    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.getenv("FMP_API_KEY")
        self.session = requests.Session()

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if not self.api_key:
            return None
        try:
            response = self.session.get(
                f"{BASE_URL}{path}",
                params={**(params or {}), "apikey": self.api_key},
                timeout=TIMEOUT_SECONDS,
            )
            if response.status_code >= 400:
                logger.warning(json.dumps({
                    "event": "fmp_http_error",
                    "path": path,
                    "status_code": response.status_code,
                    "response_snippet": response.text[:500],
                }))
                return None
            return response.json()
        except Exception as exc:
            logger.warning(json.dumps({"event": "fmp_request_failed", "path": path, "error": str(exc)}))
            return None


_CLIENT: FMPClient | None = None


def get_fmp_client() -> FMPClient:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = FMPClient()
    return _CLIENT
