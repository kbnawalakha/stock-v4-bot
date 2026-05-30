import logging

import numpy as np

from market_data import get_ticker_obj

logger = logging.getLogger(__name__)


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return float(np.clip(value, low, high))


def options_flow_score(ticker: str) -> dict[str, float]:
    try:
        obj = get_ticker_obj(ticker)
        expirations = obj.options or []
        if not expirations:
            return _empty_score()

        call_volume = 0.0
        put_volume = 0.0
        call_oi = 0.0
        put_oi = 0.0
        unusual_contracts = 0
        inspected = 0

        for expiry in expirations[:3]:
            chain = obj.option_chain(expiry)
            calls = chain.calls
            puts = chain.puts
            inspected += len(calls) + len(puts)

            call_volume += float(calls.get("volume", 0).fillna(0).sum())
            put_volume += float(puts.get("volume", 0).fillna(0).sum())
            call_oi += float(calls.get("openInterest", 0).fillna(0).sum())
            put_oi += float(puts.get("openInterest", 0).fillna(0).sum())

            for frame in (calls, puts):
                volume = frame.get("volume", 0).fillna(0)
                oi = frame.get("openInterest", 0).fillna(0)
                unusual_contracts += int(((volume >= 100) & (volume / (oi + 1) >= 1.5)).sum())

        total_volume = call_volume + put_volume
        total_oi = call_oi + put_oi
        call_put_ratio = call_volume / max(put_volume, 1.0)
        volume_oi_ratio = total_volume / max(total_oi, 1.0)

        call_ratio_score = _clamp((call_put_ratio - 0.7) * 45)
        activity_score = _clamp(np.log1p(total_volume) * 10)
        volume_oi_score = _clamp(volume_oi_ratio * 250)
        unusual_score = _clamp(unusual_contracts * 12)
        oi_score = _clamp(np.log1p(total_oi) * 8)

        score = _clamp(
            call_ratio_score * 0.30
            + activity_score * 0.20
            + volume_oi_score * 0.25
            + unusual_score * 0.20
            + oi_score * 0.05
        )

        result = {
            "score": score,
            "call_volume": call_volume,
            "put_volume": put_volume,
            "call_put_ratio": call_put_ratio,
            "open_interest": total_oi,
            "volume_open_interest_ratio": volume_oi_ratio,
            "unusual_contracts": float(unusual_contracts),
            "contracts_inspected": float(inspected),
        }
        return result
    except Exception as exc:
        logger.warning("options_flow_failed", extra={"ticker": ticker, "error": str(exc)})
        return _empty_score()


def _empty_score() -> dict[str, float]:
    return {
        "score": 50.0,
        "call_volume": 0.0,
        "put_volume": 0.0,
        "call_put_ratio": 1.0,
        "open_interest": 0.0,
        "volume_open_interest_ratio": 0.0,
        "unusual_contracts": 0.0,
        "contracts_inspected": 0.0,
    }
