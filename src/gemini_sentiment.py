import json
import logging
import os
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-2.5-flash"
TIMEOUT_SECONDS = int(os.getenv("GEMINI_TIMEOUT_SECONDS", "120"))
MAX_ATTEMPTS = int(os.getenv("GEMINI_MAX_ATTEMPTS", "2"))
BATCH_SIZE = int(os.getenv("GEMINI_BATCH_SIZE", "5"))
REDDIT_BATCH_SIZE = int(os.getenv("GEMINI_REDDIT_BATCH_SIZE") or "5")
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
    results = dict(defaults)
    for batch_index, batch in enumerate(_chunks(scored_candidates, BATCH_SIZE), start=1):
        batch_results = _score_batch(batch, results, model, api_key, batch_index)
        results.update(batch_results)
    return results


def _score_batch(
    scored_candidates: list[dict[str, Any]],
    defaults: dict[str, dict[str, Any]],
    model: str,
    api_key: str,
    batch_index: int,
) -> dict[str, dict[str, Any]]:
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

    last_error = "Gemini sentiment request failed; sentiment score neutral."
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            _log_event(
                "gemini_sentiment_request",
                model=model,
                batch_index=batch_index,
                attempt=attempt,
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
                    batch_index=batch_index,
                    attempt=attempt,
                    status_code=response.status_code,
                    response_snippet=_safe_snippet(response.text),
                )
                response.raise_for_status()

            response_payload = response.json()
            response_text = _response_text(response_payload)
            parsed = json.loads(response_text)
            results = {}
            returned_tickers = []
            requested_tickers = {candidate["ticker"] for candidate in scored_candidates}
            for item in parsed.get("results", []):
                ticker = str(item.get("ticker", "")).upper()
                if ticker in requested_tickers:
                    results[ticker] = _normalize_result(item)
                    returned_tickers.append(ticker)
            missing_tickers = sorted(requested_tickers - set(returned_tickers))
            _log_event(
                "gemini_sentiment_success",
                model=model,
                batch_index=batch_index,
                attempt=attempt,
                requested_count=len(scored_candidates),
                returned_count=len(returned_tickers),
                missing_tickers=missing_tickers,
            )
            for ticker in missing_tickers:
                results[ticker] = _default_result("Gemini sentiment result missing; sentiment score neutral.")
            return results
        except requests.Timeout as exc:
            last_error = "Gemini sentiment request timed out; sentiment score neutral."
            _log_event(
                "gemini_sentiment_timeout",
                model=model,
                batch_index=batch_index,
                attempt=attempt,
                timeout_seconds=TIMEOUT_SECONDS,
                error=str(exc),
            )
        except requests.RequestException as exc:
            last_error = "Gemini sentiment request failed; sentiment score neutral."
            response = getattr(exc, "response", None)
            _log_event(
                "gemini_sentiment_request_failed",
                model=model,
                batch_index=batch_index,
                attempt=attempt,
                status_code=getattr(response, "status_code", None),
                response_snippet=_safe_snippet(getattr(response, "text", "")),
                error=str(exc),
            )
        except json.JSONDecodeError as exc:
            last_error = "Gemini sentiment JSON parse failed; sentiment score neutral."
            _log_event(
                "gemini_sentiment_json_parse_failed",
                model=model,
                batch_index=batch_index,
                attempt=attempt,
                error=str(exc),
                response_text_snippet=_safe_snippet(locals().get("response_text", "")),
            )
        except ValueError as exc:
            last_error = "Gemini sentiment response shape failed; sentiment score neutral."
            _log_event(
                "gemini_sentiment_response_shape_failed",
                model=model,
                batch_index=batch_index,
                attempt=attempt,
                error=str(exc),
                response_payload_snippet=_safe_snippet(json.dumps(locals().get("response_payload", {}), default=str)),
            )
        except Exception as exc:
            last_error = "Gemini sentiment request failed unexpectedly; sentiment score neutral."
            _log_event(
                "gemini_sentiment_unexpected_failed",
                model=model,
                batch_index=batch_index,
                attempt=attempt,
                error=str(exc),
                error_type=type(exc).__name__,
            )

        if attempt < MAX_ATTEMPTS:
            sleep_seconds = min(2 ** attempt, 8)
            _log_event("gemini_sentiment_retrying", model=model, batch_index=batch_index, next_attempt=attempt + 1, sleep_seconds=sleep_seconds)
            time.sleep(sleep_seconds)

    tickers = [candidate["ticker"] for candidate in scored_candidates]
    _log_event("gemini_sentiment_batch_failed", model=model, batch_index=batch_index, tickers=tickers, error=last_error)
    return {
        ticker: _default_result(last_error)
        for ticker in tickers
    }


def score_overnight_sentiment(ticker: str, headlines: list[str]) -> dict[str, Any]:
    return score_overnight_sentiments([{"ticker": ticker, "headlines": headlines}]).get(
        ticker.upper(),
        _default_result("Gemini sentiment request failed; sentiment score neutral."),
    )


def analyze_reddit_plays(candidates: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    candidates = candidates[:limit]
    if not candidates:
        _log_event("gemini_reddit_skipped", reason="no reddit candidates")
        return []

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        _log_event("gemini_reddit_skipped", reason="GEMINI_API_KEY missing", candidate_count=len(candidates))
        return [_fallback_reddit_result(candidate) for candidate in candidates]

    model = os.getenv("GEMINI_MODEL") or DEFAULT_MODEL
    results: dict[str, dict[str, Any]] = {}
    for batch_index, batch in enumerate(_chunks(candidates, REDDIT_BATCH_SIZE), start=1):
        batch_results = _analyze_reddit_batch(batch, model, api_key, batch_index)
        results.update(batch_results)

    output = []
    for candidate in candidates:
        ticker = str(candidate.get("ticker", "")).upper()
        output.append(results.get(ticker, _fallback_reddit_result(candidate)))
    return sorted(output, key=lambda item: item["score"], reverse=True)


def _analyze_reddit_batch(
    candidates: list[dict[str, Any]],
    model: str,
    api_key: str,
    batch_index: int,
) -> dict[str, dict[str, Any]]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    prompt = {
        "reddit_candidates": [_compact_reddit_candidate(candidate) for candidate in candidates],
        "task": (
            "Identify which stocks appear to be actionable Reddit-related daily or weekly trading plays. "
            "Score only the Reddit signal, not the full stock. Penalize spam, jokes, stale chatter, low "
            "specificity, and tickers mentioned only in passing. Reward broad fresh attention, strong "
            "engagement, catalyst specificity, squeeze/options/earnings discussion, and clear bullish or "
            "bearish trading intent."
        ),
    }
    payload = {
        "systemInstruction": {
            "parts": [
                {
                    "text": (
                        "You are a skeptical market-structure analyst evaluating Reddit-driven stock flows. "
                        "Output strictly valid JSON."
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
                                "score": {"type": "number"},
                                "signal": {"type": "string"},
                                "confidence": {"type": "number"},
                                "reasoning": {"type": "string"},
                            },
                            "required": ["ticker", "score", "signal", "confidence", "reasoning"],
                        },
                    }
                },
                "required": ["results"],
            },
        },
    }

    last_error = "Gemini Reddit analysis failed; using fallback Reddit score."
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            _log_event(
                "gemini_reddit_request",
                model=model,
                batch_index=batch_index,
                attempt=attempt,
                candidate_count=len(candidates),
                tickers=[str(candidate.get("ticker", "")).upper() for candidate in candidates],
            )
            response = requests.post(
                url,
                headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
                json=payload,
                timeout=TIMEOUT_SECONDS,
            )
            if response.status_code >= 400:
                _log_event(
                    "gemini_reddit_http_error",
                    model=model,
                    batch_index=batch_index,
                    attempt=attempt,
                    status_code=response.status_code,
                    response_snippet=_safe_snippet(response.text),
                )
                response.raise_for_status()

            response_payload = response.json()
            response_text = _response_text(response_payload)
            parsed = json.loads(response_text)
            requested = {str(candidate.get("ticker", "")).upper(): candidate for candidate in candidates}
            results = {}
            for item in parsed.get("results", []):
                ticker = str(item.get("ticker", "")).upper()
                if ticker in requested:
                    results[ticker] = _normalize_reddit_result(item, requested[ticker])
            missing = sorted(set(requested) - set(results))
            for ticker in missing:
                results[ticker] = _fallback_reddit_result(requested[ticker])
            _log_event(
                "gemini_reddit_success",
                model=model,
                batch_index=batch_index,
                attempt=attempt,
                requested_count=len(candidates),
                returned_count=len(results) - len(missing),
                missing_tickers=missing,
            )
            return results
        except requests.Timeout as exc:
            last_error = "Gemini Reddit request timed out; using fallback Reddit score."
            _log_event("gemini_reddit_timeout", model=model, batch_index=batch_index, attempt=attempt, timeout_seconds=TIMEOUT_SECONDS, error=str(exc))
        except requests.RequestException as exc:
            last_error = "Gemini Reddit request failed; using fallback Reddit score."
            response = getattr(exc, "response", None)
            _log_event(
                "gemini_reddit_request_failed",
                model=model,
                batch_index=batch_index,
                attempt=attempt,
                status_code=getattr(response, "status_code", None),
                response_snippet=_safe_snippet(getattr(response, "text", "")),
                error=str(exc),
            )
        except json.JSONDecodeError as exc:
            last_error = "Gemini Reddit JSON parse failed; using fallback Reddit score."
            _log_event("gemini_reddit_json_parse_failed", model=model, batch_index=batch_index, attempt=attempt, error=str(exc), response_text_snippet=_safe_snippet(locals().get("response_text", "")))
        except Exception as exc:
            last_error = "Gemini Reddit analysis failed unexpectedly; using fallback Reddit score."
            _log_event("gemini_reddit_unexpected_failed", model=model, batch_index=batch_index, attempt=attempt, error=str(exc), error_type=type(exc).__name__)

        if attempt < MAX_ATTEMPTS:
            sleep_seconds = min(2 ** attempt, 8)
            _log_event("gemini_reddit_retrying", model=model, batch_index=batch_index, next_attempt=attempt + 1, sleep_seconds=sleep_seconds)
            time.sleep(sleep_seconds)

    _log_event(
        "gemini_reddit_batch_failed",
        model=model,
        batch_index=batch_index,
        tickers=[str(candidate.get("ticker", "")).upper() for candidate in candidates],
        error=last_error,
    )
    return {
        str(candidate.get("ticker", "")).upper(): _fallback_reddit_result(candidate, last_error)
        for candidate in candidates
        if candidate.get("ticker")
    }


def _compact_reddit_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "ticker": candidate.get("ticker"),
        "mention_count": candidate.get("mention_count", 0),
        "cashtag_mentions": candidate.get("cashtag_mentions", 0),
        "engagement": candidate.get("engagement", 0),
        "subreddits": candidate.get("subreddits", []),
        "sample_posts": candidate.get("sample_posts", [])[:3],
    }


def _normalize_reddit_result(raw: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    fallback = _fallback_reddit_result(candidate)
    return {
        "ticker": str(raw.get("ticker") or fallback["ticker"]).upper(),
        "score": max(0.0, min(100.0, float(raw.get("score", fallback["score"])))),
        "signal": _normalize_reddit_signal(str(raw.get("signal") or fallback["signal"])),
        "confidence": max(0.0, min(1.0, float(raw.get("confidence", fallback["confidence"])))),
        "reasoning": str(raw.get("reasoning") or fallback["reasoning"]).strip()[:700],
        "mention_count": int(candidate.get("mention_count", 0)),
        "engagement": int(candidate.get("engagement", 0)),
        "subreddits": candidate.get("subreddits", []),
    }


def _fallback_reddit_result(candidate: dict[str, Any], reason: str | None = None) -> dict[str, Any]:
    mention_count = int(candidate.get("mention_count", 0))
    engagement = int(candidate.get("engagement", 0))
    subreddit_count = len(candidate.get("subreddits", []))
    score = min(100.0, mention_count * 10 + min(35, engagement ** 0.5) + min(15, subreddit_count * 4))
    reasoning = reason or (
        f"Reddit attention is elevated with {mention_count} mentions"
        f" across {subreddit_count} subreddit(s) and engagement of {engagement}."
    )
    return {
        "ticker": str(candidate.get("ticker", "")).upper(),
        "score": float(score),
        "signal": "MIXED",
        "confidence": 0.35 if score >= 40 else 0.2,
        "reasoning": reasoning,
        "mention_count": mention_count,
        "engagement": engagement,
        "subreddits": candidate.get("subreddits", []),
    }


def _normalize_reddit_signal(value: str) -> str:
    upper = value.upper()
    if "BEAR" in upper:
        return "BEARISH"
    if "BULL" in upper:
        return "BULLISH"
    return "MIXED"


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


def _chunks(items: list[dict[str, Any]], size: int):
    size = max(1, size)
    for start in range(0, len(items), size):
        yield items[start:start + size]
