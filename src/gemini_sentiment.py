import json
import logging
import os
from typing import Any

import requests

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-2.5-flash"
TIMEOUT_SECONDS = 30
LOG_SNIPPET_CHARS = 1200


def _default_result(reason: str) -> dict[str, Any]:
    return {"sentiment": 50.0, "confidence": 0.0, "reasoning": reason}


def _normalize_result(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "sentiment": max(0.0, min(100.0, float(raw.get("sentiment", 50.0)))),
        "confidence": max(0.0, min(1.0, float(raw.get("confidence", 0.0)))),
        "reasoning": str(raw.get("reasoning", "")).strip()[:700],
    }


def score_overnight_sentiments(candidates: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    defaults = {
        str(candidate.get("ticker")).upper(): _default_result("No overnight headlines available.")
        for candidate in candidates
        if candidate.get("ticker")
    }
    scored_candidates = [
        {
            "ticker": str(candidate["ticker"]).upper(),
            "overnight_headlines": candidate.get("headlines", [])[:15],
        }
        for candidate in candidates
        if candidate.get("ticker") and candidate.get("headlines")
    ]
    if not scored_candidates:
        _log_event("gemini_sentiment_skipped", reason="no candidates with headlines", candidate_count=len(defaults))
        return defaults

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        _log_event("gemini_sentiment_skipped", reason="GEMINI_API_KEY missing", candidate_count=len(scored_candidates))
        return {
            ticker: _default_result("GEMINI_API_KEY missing; sentiment score neutral.")
            for ticker in defaults
        }

    model = os.getenv("GEMINI_MODEL") or DEFAULT_MODEL
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    prompt = {
        "candidates": scored_candidates,
        "task": (
            "Score overnight market-moving sentiment for today's regular trading session. "
            "For each ticker evaluate bullishness, bearishness, catalyst strength, likelihood "
            "of same-day move, earnings implications, and guidance implications. Return one "
            "JSON result per ticker."
        ),
    }
    payload = {
        "systemInstruction": {
            "parts": [
                {
                    "text": (
                        "You are a senior equity news analyst. Be calibrated, skeptical, "
                        "and focused on same-day alpha. Output strictly valid JSON."
                    )
                }
            ]
        },
        "contents": [{"role": "user", "parts": [{"text": json.dumps(prompt)}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "object",
                "properties": {
                    "results": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "ticker": {"type": "string"},
                                "sentiment": {"type": "number"},
                                "confidence": {"type": "number"},
                                "reasoning": {"type": "string"},
                            },
                            "required": ["ticker", "sentiment", "confidence", "reasoning"],
                        },
                    }
                },
                "required": ["results"],
            },
        },
    }

    try:
        _log_event(
            "gemini_sentiment_request",
            model=model,
            candidate_count=len(scored_candidates),
            tickers=[candidate["ticker"] for candidate in scored_candidates],
        )
        response = requests.post(
            url,
            headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
            json=payload,
            timeout=TIMEOUT_SECONDS,
        )
        if response.status_code >= 400:
            _log_event(
                "gemini_sentiment_http_error",
                model=model,
                status_code=response.status_code,
                response_snippet=_safe_snippet(response.text),
            )
            response.raise_for_status()

        response_payload = response.json()
        response_text = _response_text(response_payload)
        parsed = json.loads(response_text)
        results = dict(defaults)
        returned_tickers = []
        for item in parsed.get("results", []):
            ticker = str(item.get("ticker", "")).upper()
            if ticker in results:
                results[ticker] = _normalize_result(item)
                returned_tickers.append(ticker)
        missing_tickers = sorted(set(defaults) - set(returned_tickers))
        _log_event(
            "gemini_sentiment_success",
            model=model,
            requested_count=len(scored_candidates),
            returned_count=len(returned_tickers),
            missing_tickers=missing_tickers,
        )
        return results
    except requests.Timeout as exc:
        _log_event("gemini_sentiment_timeout", model=model, timeout_seconds=TIMEOUT_SECONDS, error=str(exc))
    except requests.RequestException as exc:
        response = getattr(exc, "response", None)
        _log_event(
            "gemini_sentiment_request_failed",
            model=model,
            status_code=getattr(response, "status_code", None),
            response_snippet=_safe_snippet(getattr(response, "text", "")),
            error=str(exc),
        )
    except json.JSONDecodeError as exc:
        _log_event(
            "gemini_sentiment_json_parse_failed",
            model=model,
            error=str(exc),
            response_text_snippet=_safe_snippet(locals().get("response_text", "")),
        )
    except ValueError as exc:
        _log_event(
            "gemini_sentiment_response_shape_failed",
            model=model,
            error=str(exc),
            response_payload_snippet=_safe_snippet(json.dumps(locals().get("response_payload", {}), default=str)),
        )
    except Exception as exc:
        _log_event("gemini_sentiment_unexpected_failed", model=model, error=str(exc), error_type=type(exc).__name__)

    return {
        ticker: _default_result("Gemini sentiment request failed; sentiment score neutral.")
        for ticker in defaults
    }


def score_overnight_sentiment(ticker: str, headlines: list[str]) -> dict[str, Any]:
    return score_overnight_sentiments([{"ticker": ticker, "headlines": headlines}]).get(
        ticker.upper(),
        _default_result("Gemini sentiment request failed; sentiment score neutral."),
    )


def _response_text(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates") or []
    if not candidates:
        raise ValueError("Gemini response contained no candidates")
    parts = candidates[0].get("content", {}).get("parts") or []
    if not parts or "text" not in parts[0]:
        raise ValueError("Gemini response contained no text part")
    return parts[0]["text"]


def _safe_snippet(value: str | None) -> str:
    if not value:
        return ""
    return str(value).replace(os.getenv("GEMINI_API_KEY") or "", "[REDACTED]")[:LOG_SNIPPET_CHARS]


def _log_event(event: str, **payload: Any) -> None:
    logger.warning(json.dumps({"event": event, **payload}, default=str))
