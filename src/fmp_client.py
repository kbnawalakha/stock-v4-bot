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
        self._disabled_reason: str | None = None

    @property
    def available(self) -> bool:
        return bool(self.api_key) and self._disabled_reason is None

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if not self.api_key or self._disabled_reason is not None:
            return None
        try:
            response = self.session.get(
                f"{BASE_URL}{path}",
                params={**(params or {}), "apikey": self.api_key},
                timeout=TIMEOUT_SECONDS,
            )
            if response.status_code >= 400:
                if _is_legacy_endpoint_error(response.text):
                    self._disabled_reason = "FMP legacy endpoints unavailable for this API key."
                    logger.warning(json.dumps({
                        "event": "fmp_disabled",
                        "path": path,
                        "status_code": response.status_code,
                        "reason": self._disabled_reason,
                    }))
                    return None
                logger.warning(json.dumps({
                    "event": "fmp_http_error",
                    "path": path,
                    "status_code": response.status_code,
                    "response_text_length": len(response.text or ""),
                }))
                return None
            return response.json()
        except Exception as exc:
            logger.warning(json.dumps({"event": "fmp_request_failed", "path": path, "error": str(exc)}))
            return None


def _is_legacy_endpoint_error(text: str) -> bool:
    lowered = (text or "").lower()
    return "legacy endpoint" in lowered and "no longer supported" in lowered


_CLIENT: FMPClient | None = None


def get_fmp_client() -> FMPClient:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = FMPClient()
    return _CLIENT
