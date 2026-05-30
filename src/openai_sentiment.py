import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def _default_result(reason: str) -> dict[str, Any]:
    return {"sentiment": 50.0, "confidence": 0.0, "reasoning": reason}


def score_overnight_sentiment(ticker: str, headlines: list[str]) -> dict[str, Any]:
    if not headlines:
        return _default_result("No overnight headlines available.")

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return _default_result("OPENAI_API_KEY missing; sentiment score neutral.")

    try:
        from openai import OpenAI
    except Exception as exc:
        logger.warning("openai_import_failed", extra={"ticker": ticker, "error": str(exc)})
        return _default_result("OpenAI package unavailable; sentiment score neutral.")

    prompt = {
        "ticker": ticker,
        "overnight_headlines": headlines[:15],
        "task": (
            "Score overnight market-moving sentiment for today's regular trading session. "
            "Evaluate bullishness, bearishness, catalyst strength, likelihood of same-day move, "
            "earnings implications, and guidance implications. Return only valid JSON with "
            "sentiment from 0 to 100, confidence from 0 to 1, and concise reasoning."
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
                    "name": "overnight_sentiment",
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "sentiment": {"type": "number", "minimum": 0, "maximum": 100},
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                            "reasoning": {"type": "string"},
                        },
                        "required": ["sentiment", "confidence", "reasoning"],
                    },
                }
            },
        )
        content = response.output_text
        parsed = json.loads(content)
        result = {
            "sentiment": max(0.0, min(100.0, float(parsed.get("sentiment", 50.0)))),
            "confidence": max(0.0, min(1.0, float(parsed.get("confidence", 0.0)))),
            "reasoning": str(parsed.get("reasoning", "")).strip()[:700],
        }
        return result
    except Exception as exc:
        logger.warning("openai_sentiment_failed", extra={"ticker": ticker, "error": str(exc)})
        return _default_result("OpenAI sentiment request failed; sentiment score neutral.")
