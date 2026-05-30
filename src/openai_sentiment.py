import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


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
        str(candidate.get("ticker")): _default_result("No overnight headlines available.")
        for candidate in candidates
        if candidate.get("ticker")
    }
    scored_candidates = [
        {
            "ticker": str(candidate["ticker"]),
            "overnight_headlines": candidate.get("headlines", [])[:15],
        }
        for candidate in candidates
        if candidate.get("ticker") and candidate.get("headlines")
    ]
    if not scored_candidates:
        return defaults

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return {
            ticker: _default_result("OPENAI_API_KEY missing; sentiment score neutral.")
            for ticker in defaults
        }

    try:
        from openai import OpenAI
    except Exception as exc:
        logger.warning("openai_import_failed", extra={"error": str(exc)})
        return {
            ticker: _default_result("OpenAI package unavailable; sentiment score neutral.")
            for ticker in defaults
        }

    prompt = {
        "candidates": scored_candidates,
        "task": (
            "Score overnight market-moving sentiment for today's regular trading session. "
            "For each ticker evaluate bullishness, bearishness, catalyst strength, likelihood "
            "of same-day move, earnings implications, and guidance implications. Return only "
            "valid JSON with one result per ticker."
        ),
    }

    try:
        client = OpenAI(api_key=api_key)
        response = client.responses.create(
            model="gpt-5-mini",
            input=[
                {
                    "role": "system",
                    "content": (
                        "You are a senior equity news analyst. Be calibrated, skeptical, "
                        "and focused on same-day alpha. Output strictly valid JSON."
                    ),
                },
                {"role": "user", "content": json.dumps(prompt)},
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "overnight_sentiment_batch",
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "results": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "properties": {
                                        "ticker": {"type": "string"},
                                        "sentiment": {"type": "number", "minimum": 0, "maximum": 100},
                                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                                        "reasoning": {"type": "string"},
                                    },
                                    "required": ["ticker", "sentiment", "confidence", "reasoning"],
                                },
                            }
                        },
                        "required": ["results"],
                    },
                }
            },
        )
        parsed = json.loads(response.output_text)
        results = dict(defaults)
        for item in parsed.get("results", []):
            ticker = str(item.get("ticker", "")).upper()
            if ticker in results:
                results[ticker] = _normalize_result(item)
        return results
    except Exception as exc:
        logger.warning("openai_sentiment_batch_failed", extra={"error": str(exc)})
        return {
            ticker: _default_result("OpenAI sentiment request failed; sentiment score neutral.")
            for ticker in defaults
        }


def score_overnight_sentiment(ticker: str, headlines: list[str]) -> dict[str, Any]:
    return score_overnight_sentiments([{"ticker": ticker, "headlines": headlines}]).get(
        ticker,
        _default_result("OpenAI sentiment request failed; sentiment score neutral."),
    )
