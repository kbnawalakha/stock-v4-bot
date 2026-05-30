import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from config import STRATEGY_WEIGHTS
from market_data import get_history

logger = logging.getLogger(__name__)

PREDICTIONS_FILE = Path("predictions.csv")
STATE_FILE = Path("learning_state.json")
MIN_EVALUATION_DAYS = 1
SIGNAL_DECAY = 0.90
LEARNING_RATE = 0.35
MIN_WEIGHT_MULTIPLIER = 0.50
MAX_WEIGHT_MULTIPLIER = 1.50


def _empty_state() -> dict:
    return {
        "version": 1,
        "last_updated": None,
        "evaluated": [],
        "signal_scores": {key: 0.0 for key in STRATEGY_WEIGHTS},
        "learned_weights": dict(STRATEGY_WEIGHTS),
    }


def load_learning_state() -> dict:
    if not STATE_FILE.exists():
        return _empty_state()
    try:
        with STATE_FILE.open("r", encoding="utf-8") as handle:
            state = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("learning_state_load_failed", extra={"error": str(exc)})
        return _empty_state()

    base = _empty_state()
    base.update(state)
    base["signal_scores"] = {**_empty_state()["signal_scores"], **base.get("signal_scores", {})}
    base["learned_weights"] = _normalize_weights({
        **STRATEGY_WEIGHTS,
        **base.get("learned_weights", {}),
    })
    base["evaluated"] = list(base.get("evaluated", []))
    return base


def get_learned_weights() -> dict[str, float]:
    return load_learning_state().get("learned_weights", dict(STRATEGY_WEIGHTS))


def refresh_learning_state() -> dict[str, float]:
    state = load_learning_state()
    if not PREDICTIONS_FILE.exists():
        _save_state(state)
        return state["learned_weights"]

    try:
        predictions = pd.read_csv(PREDICTIONS_FILE)
    except Exception as exc:
        logger.warning("predictions_load_failed", extra={"error": str(exc)})
        return state["learned_weights"]

    required = {"date", "ticker", "price"}
    if predictions.empty or not required.issubset(predictions.columns):
        _save_state(state)
        return state["learned_weights"]

    evaluated = set(state.get("evaluated", []))
    today = datetime.now(timezone.utc).date()
    spy_df = get_history("SPY", period="2mo")
    updated = 0

    for idx, row in predictions.iterrows():
        rec_date = _parse_date(row.get("date"))
        ticker = str(row.get("ticker", "")).upper()
        if rec_date is None or not ticker:
            continue
        key = f"{rec_date.isoformat()}:{ticker}:{idx}"
        if key in evaluated or (today - rec_date).days < MIN_EVALUATION_DAYS:
            continue

        entry_price = _safe_float(row.get("price"))
        if not entry_price or entry_price <= 0:
            continue

        ticker_return = _return_since(ticker, entry_price)
        spy_return = _benchmark_return_since(spy_df, rec_date)
        if ticker_return is None or spy_return is None:
            continue

        alpha = ticker_return - spy_return
        reward = max(-1.0, min(1.0, alpha / 10.0))
        _update_signal_scores(state, row, reward)
        evaluated.add(key)
        updated += 1

    state["evaluated"] = sorted(evaluated)[-1000:]
    state["learned_weights"] = _weights_from_signal_scores(state["signal_scores"])
    state["last_updated"] = datetime.now(timezone.utc).isoformat()
    _save_state(state)
    logger.info(
        "learning_state_refreshed",
        extra={"evaluated_new": updated, "learned_weights": state["learned_weights"]},
    )
    return state["learned_weights"]


def _update_signal_scores(state: dict, row: pd.Series, reward: float) -> None:
    scores = state["signal_scores"]
    for key in STRATEGY_WEIGHTS:
        exposure = _safe_float(row.get(key)) or 0.0
        exposure = max(0.0, min(1.0, exposure / 100.0))
        if exposure <= 0:
            scores[key] = SIGNAL_DECAY * float(scores.get(key, 0.0))
            continue
        contribution = reward * exposure
        scores[key] = SIGNAL_DECAY * float(scores.get(key, 0.0)) + (1 - SIGNAL_DECAY) * contribution


def _weights_from_signal_scores(signal_scores: dict[str, float]) -> dict[str, float]:
    weighted = {}
    for key, base_weight in STRATEGY_WEIGHTS.items():
        signal_score = max(-1.0, min(1.0, float(signal_scores.get(key, 0.0))))
        multiplier = 1 + LEARNING_RATE * signal_score
        multiplier = max(MIN_WEIGHT_MULTIPLIER, min(MAX_WEIGHT_MULTIPLIER, multiplier))
        weighted[key] = base_weight * multiplier
    return _normalize_weights(weighted)


def _normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    cleaned = {key: max(0.0, float(weights.get(key, 0.0))) for key in STRATEGY_WEIGHTS}
    total = sum(cleaned.values())
    if total <= 0:
        return dict(STRATEGY_WEIGHTS)
    return {key: value / total for key, value in cleaned.items()}


def _return_since(ticker: str, entry_price: float) -> float | None:
    df = get_history(ticker, period="2mo")
    if df.empty:
        return None
    latest = _safe_float(df["Close"].iloc[-1])
    if latest is None or latest <= 0:
        return None
    return (latest / entry_price - 1) * 100


def _benchmark_return_since(spy_df: pd.DataFrame, rec_date) -> float | None:
    if spy_df.empty:
        return None
    close = spy_df["Close"]
    dated = close[close.index.date >= rec_date]
    if dated.empty:
        return None
    entry = _safe_float(dated.iloc[0])
    latest = _safe_float(close.iloc[-1])
    if not entry or not latest or entry <= 0:
        return None
    return (latest / entry - 1) * 100


def _parse_date(value):
    try:
        return pd.Timestamp(value).date()
    except Exception:
        return None


def _safe_float(value) -> float | None:
    try:
        if pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
