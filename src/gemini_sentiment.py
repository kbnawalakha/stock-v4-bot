import json
import logging
import os
from typing import Any

import requests

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-2.5-flash"
TIMEOUT_SECONDS = 30


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
        return defaults

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
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
        response = requests.post(
            url,
            headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
            json=payload,
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        parsed = json.loads(_response_text(response.json()))
        results = dict(defaults)
        for item in parsed.get("results", []):
            ticker = str(item.get("ticker", "")).upper()
            if ticker in results:
                results[ticker] = _normalize_result(item)
        return results
    except Exception as exc:
        logger.warning(json.dumps({"event": "gemini_sentiment_batch_failed", "error": str(exc)}))
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
