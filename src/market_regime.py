import logging

from indicators import pct_return
from market_data import get_history

logger = logging.getLogger(__name__)

RISK_ON = "RISK_ON"
NEUTRAL = "NEUTRAL"
RISK_OFF = "RISK_OFF"


def classify_market_regime() -> dict[str, float | str]:
    try:
        spy = get_history("SPY", period="6mo")
        qqq = get_history("QQQ", period="6mo")
        vix = get_history("^VIX", period="6mo")
        if spy.empty or qqq.empty or vix.empty:
            return {"regime": NEUTRAL, "confidence": 0.35}

        spy_5 = pct_return(spy, 5)
        spy_20 = pct_return(spy, 20)
        qqq_5 = pct_return(qqq, 5)
        qqq_20 = pct_return(qqq, 20)
        vix_5 = pct_return(vix, 5)
        vix_level = float(vix["Close"].iloc[-1])

        risk_score = 0.0
        risk_score += 1.0 if spy_5 > 0 else -1.0
        risk_score += 1.0 if qqq_5 > 0 else -1.0
        risk_score += 1.0 if spy_20 > 1 else -1.0 if spy_20 < -2 else 0.0
        risk_score += 1.0 if qqq_20 > 1 else -1.0 if qqq_20 < -2 else 0.0
        risk_score += 1.0 if vix_level < 18 else -1.0 if vix_level > 24 else 0.0
        risk_score += 1.0 if vix_5 < -5 else -1.0 if vix_5 > 8 else 0.0

        if risk_score >= 3:
            regime = RISK_ON
        elif risk_score <= -3:
            regime = RISK_OFF
        else:
            regime = NEUTRAL

        confidence = min(1.0, max(0.35, abs(risk_score) / 6))
        result = {"regime": regime, "confidence": float(confidence)}
        return result
    except Exception as exc:
        logger.warning("market_regime_failed", extra={"error": str(exc)})
        return {"regime": NEUTRAL, "confidence": 0.25}
