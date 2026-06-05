import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from config import STRATEGY_WEIGHTS
from market_data import get_history
from swing_trading import bear_case_score

logger = logging.getLogger(__name__)

PREDICTIONS_FILE = Path("predictions.csv")
STATE_FILE = Path("learning_state.json")
OUTCOMES_FILE = Path("recommendation_outcomes.csv")
MIN_EVALUATION_DAYS = 1
# Swing evaluation horizon (trading days). Picks are graded on their forward return
# over this fixed window rather than on "price as of today", so a 2-day-old pick and a
# 40-day-old pick are scored on the same, swing-relevant timescale.
EVAL_HORIZON_DAYS = int(float(os.getenv("LEARNING_EVAL_HORIZON_DAYS", "5") or 5))
# Alpha (vs SPY, over the horizon) that counts as a full +/-1 reward.
REWARD_ALPHA_SCALE = float(os.getenv("LEARNING_REWARD_ALPHA_SCALE", "5.0") or 5.0)
SIGNAL_DECAY = 0.90
LEARNING_RATE = 0.35
MIN_WEIGHT_MULTIPLIER = 0.50
MAX_WEIGHT_MULTIPLIER = 1.50
# Signals stored on a signed -100..100 scale (neutral = 0). Everything else is on a
# 0..100 scale (neutral = 50). This distinction is essential for correct attribution.
SIGNED_SIGNALS = {"relative_strength", "sector_strength", "political_geo", "politician_trade"}
MAX_EVALUATED_KEYS = 5000
MAX_EVALUATION_HISTORY = 1000
MAX_OUTCOME_ROWS = 5000
DOWNSIDE_ALERT_LOOKBACK_DAYS = 30
DOWNSIDE_ALERT_MAX_SCAN = 80
DOWNSIDE_ALERT_MIN_BEAR_SCORE = 70.0
DOWNSIDE_ALERT_MIN_LOSS_PCT = -2.0


def _empty_state() -> dict:
    return {
        "version": 2,
        "last_updated": None,
        "evaluated": [],
        "evaluated_recommendations": [],
        "evaluation_history": [],
        "last_evaluation_summary": {},
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
    evaluated = list(base.get("evaluated_recommendations") or base.get("evaluated", []))
    base["evaluated"] = evaluated
    base["evaluated_recommendations"] = evaluated
    base["evaluation_history"] = list(base.get("evaluation_history", []))
    base["last_evaluation_summary"] = dict(base.get("last_evaluation_summary", {}))
    return base


def get_learned_weights() -> dict[str, float]:
    return load_learning_state().get("learned_weights", dict(STRATEGY_WEIGHTS))


def refresh_learning_state() -> dict[str, float]:
    state = load_learning_state()
    if not PREDICTIONS_FILE.exists():
        _save_state(state)
        return state["learned_weights"]

    predictions = _load_predictions()
    if predictions.empty:
        _save_state(state)
        return state["learned_weights"]

    required = {"date", "ticker", "price"}
    if not required.issubset(predictions.columns):
        _save_state(state)
        return state["learned_weights"]

    evaluated = set(state.get("evaluated_recommendations") or state.get("evaluated", []))
    today = datetime.now(timezone.utc).date()
    spy_df = get_history("SPY", period="2mo")
    updated = 0
    outcome_records = []

    for idx, row in predictions.iterrows():
        rec_date = _parse_date(row.get("date"))
        ticker = str(row.get("ticker", "")).upper()
        if rec_date is None or not ticker:
            continue
        key = _recommendation_key(row, idx, rec_date, ticker)
        if key in evaluated or (today - rec_date).days < MIN_EVALUATION_DAYS:
            continue

        entry_price = _safe_float(row.get("price"))
        if not entry_price or entry_price <= 0:
            continue

        ticker_return, latest_price = _return_since(ticker, entry_price, rec_date)
        spy_return = _benchmark_return_since(spy_df, rec_date)
        if ticker_return is None or spy_return is None:
            continue

        direction = _direction(row)
        position_return, benchmark_return = _directional_returns(direction, ticker_return, spy_return)
        alpha = position_return - benchmark_return
        reward = max(-1.0, min(1.0, alpha / REWARD_ALPHA_SCALE))
        if direction == "BULL":
            _update_signal_scores(state, row, reward)
        outcome_records.append(
            _outcome_record(
                key,
                row,
                rec_date,
                ticker,
                direction,
                entry_price,
                latest_price,
                ticker_return,
                spy_return,
                position_return,
                benchmark_return,
                alpha,
                reward,
            )
        )
        evaluated.add(key)
        updated += 1

    state["evaluated"] = sorted(evaluated)[-MAX_EVALUATED_KEYS:]
    state["evaluated_recommendations"] = state["evaluated"]
    state["evaluation_history"] = (state.get("evaluation_history", []) + outcome_records)[-MAX_EVALUATION_HISTORY:]
    state["last_evaluation_summary"] = _evaluation_summary(outcome_records)
    state["learned_weights"] = _weights_from_signal_scores(state["signal_scores"])
    state["last_updated"] = datetime.now(timezone.utc).isoformat()
    _save_state(state)
    _append_outcome_records(outcome_records)
    _log_event(
        "learning_state_refreshed",
        evaluated_new=updated,
        summary=state["last_evaluation_summary"],
        learned_weights=state["learned_weights"],
    )
    return state["learned_weights"]


def historical_downside_alerts(
    limit: int = 5,
    lookback_days: int = DOWNSIDE_ALERT_LOOKBACK_DAYS,
    min_bear_score: float = DOWNSIDE_ALERT_MIN_BEAR_SCORE,
) -> list[dict]:
    predictions = _load_predictions()
    required = {"date", "ticker", "price"}
    if predictions.empty or not required.issubset(predictions.columns):
        return []

    today = datetime.now(timezone.utc).date()
    candidates = []
    for idx, row in predictions.iterrows():
        rec_date = _parse_date(row.get("date"))
        if rec_date is None:
            continue
        age_days = (today - rec_date).days
        if age_days < MIN_EVALUATION_DAYS or age_days > lookback_days:
            continue
        if _direction(row) != "BULL":
            continue
        ticker = str(row.get("ticker", "")).upper()
        entry_price = _safe_float(row.get("price"))
        if ticker and entry_price and entry_price > 0:
            candidates.append((rec_date, idx, row, age_days, ticker, entry_price))

    alerts = []
    seen = set()
    scanned = 0
    for rec_date, idx, row, age_days, ticker, entry_price in sorted(candidates, key=lambda item: (item[0], item[1]), reverse=True):
        if ticker in seen:
            continue
        seen.add(ticker)
        if scanned >= DOWNSIDE_ALERT_MAX_SCAN:
            break
        scanned += 1

        try:
            df = get_history(ticker, period="2mo")
            if df.empty:
                continue
            latest_price = _safe_float(df["Close"].iloc[-1])
            if latest_price is None or latest_price <= 0:
                continue
            current_return = (latest_price / entry_price - 1) * 100
            bear = bear_case_score(df)
            bear_score = float(bear.get("score", 0.0))
            if bear_score < min_bear_score and not (
                bear_score >= min_bear_score - 10.0 and current_return <= DOWNSIDE_ALERT_MIN_LOSS_PCT
            ):
                continue
            alerts.append({
                "ticker": ticker,
                "date": rec_date.isoformat(),
                "age_days": age_days,
                "entry_price": entry_price,
                "current_price": latest_price,
                "return_pct": current_return,
                "bear_score": bear_score,
                "setup_type": bear.get("setup_type", ""),
                "reason": bear.get("reason", ""),
                "recommendation_score": _safe_float(row.get("score")) or 0.0,
                "recommendation_confidence": _safe_float(row.get("recommendation_confidence")) or 0.0,
                "risk_score": bear_score + max(0.0, -current_return) * 1.5,
            })
        except Exception as exc:
            _log_event("historical_downside_alert_failed", ticker=ticker, error=str(exc))
            continue

    alerts = sorted(alerts, key=lambda item: item["risk_score"], reverse=True)[:limit]
    _log_event("historical_downside_alerts", count=len(alerts), tickers=[item["ticker"] for item in alerts])
    return alerts


def _update_signal_scores(state: dict, row: pd.Series, reward: float) -> None:
    scores = state["signal_scores"]
    for key in STRATEGY_WEIGHTS:
        if key not in row or pd.isna(row.get(key)):
            continue
        # Center exposure around the signal's neutral value so a neutral reading gets
        # ZERO credit (previously a 50/100 -> 0.5 exposure meant every neutral signal
        # was half-credited for every outcome, which washed out real signal over time).
        exposure = _exposure(key, _safe_float(row.get(key)))
        if exposure is None or abs(exposure) < 0.10:
            scores[key] = SIGNAL_DECAY * float(scores.get(key, 0.0))
            continue
        contribution = reward * exposure
        scores[key] = SIGNAL_DECAY * float(scores.get(key, 0.0)) + (1 - SIGNAL_DECAY) * contribution


def _exposure(key: str, raw: float | None) -> float | None:
    if raw is None:
        return None
    if key in SIGNED_SIGNALS:
        return max(-1.0, min(1.0, raw / 100.0))
    return max(-1.0, min(1.0, (raw - 50.0) / 50.0))


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


def _return_since(ticker: str, entry_price: float, rec_date=None, horizon: int = EVAL_HORIZON_DAYS) -> tuple[float | None, float | None]:
    """Forward return measured `horizon` trading days after rec_date (capped at the
    latest available bar). Falls back to latest close if rec_date is unknown."""
    df = get_history(ticker, period="3mo")
    if df.empty or "Close" not in df:
        return None, None
    close = df["Close"]
    exit_price = None
    if rec_date is not None:
        try:
            forward = close[close.index.date > rec_date]
        except Exception:
            forward = close
        if not forward.empty:
            pos = min(horizon - 1, len(forward) - 1)
            exit_price = _safe_float(forward.iloc[pos])
    if exit_price is None:
        exit_price = _safe_float(close.iloc[-1])
    if exit_price is None or exit_price <= 0:
        return None, None
    return (exit_price / entry_price - 1) * 100, exit_price


def _benchmark_return_since(spy_df: pd.DataFrame, rec_date, horizon: int = EVAL_HORIZON_DAYS) -> float | None:
    """SPY forward return over the same fixed horizon, for a like-for-like comparison."""
    if spy_df.empty:
        return None
    close = spy_df["Close"]
    dated = close[close.index.date >= rec_date]
    if dated.empty:
        return None
    entry = _safe_float(dated.iloc[0])
    pos = min(horizon, len(dated) - 1)
    exit_price = _safe_float(dated.iloc[pos])
    if not entry or not exit_price or entry <= 0:
        return None
    return (exit_price / entry - 1) * 100


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


def _direction(row: pd.Series) -> str:
    direction = str(row.get("direction", "BULL") or "BULL").upper()
    return "SHORT" if direction == "SHORT" else "BULL"


def _directional_returns(direction: str, ticker_return: float, spy_return: float) -> tuple[float, float]:
    if direction == "SHORT":
        return -ticker_return, -spy_return
    return ticker_return, spy_return


def _save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_predictions() -> pd.DataFrame:
    if not PREDICTIONS_FILE.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(PREDICTIONS_FILE)
    except Exception as exc:
        _log_event("predictions_load_failed", error=str(exc))
        return pd.DataFrame()


def _recommendation_key(row: pd.Series, idx: int, rec_date, ticker: str) -> str:
    raw_key = str(row.get("recommendation_id", "")).strip()
    if raw_key and raw_key.lower() != "nan":
        return raw_key
    rank = _safe_float(row.get("rank"))
    rank_part = int(rank) if rank and rank > 0 else idx
    return f"{rec_date.isoformat()}:{ticker}:{rank_part}"


def _outcome_record(
    evaluation_id: str,
    row: pd.Series,
    rec_date,
    ticker: str,
    direction: str,
    entry_price: float,
    latest_price: float | None,
    ticker_return: float,
    spy_return: float,
    position_return: float,
    benchmark_return: float,
    alpha: float,
    reward: float,
) -> dict:
    return {
        "evaluation_id": evaluation_id,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "date": rec_date.isoformat(),
        "ticker": ticker,
        "direction": direction,
        "entry_price": float(entry_price),
        "latest_price": float(latest_price or 0.0),
        "ticker_return_pct": float(ticker_return),
        "spy_return_pct": float(spy_return),
        "position_return_pct": float(position_return),
        "benchmark_return_pct": float(benchmark_return),
        "alpha_return_pct": float(alpha),
        "learning_reward": float(reward),
        "score": _safe_float(row.get("score")) or 0.0,
        "recommendation_confidence": _safe_float(row.get("recommendation_confidence")) or 0.0,
        "regime": str(row.get("regime", "")),
    }


def _evaluation_summary(records: list[dict]) -> dict:
    if not records:
        return {"evaluated_new": 0, "avg_alpha_return_pct": 0.0, "win_rate": 0.0}
    alphas = [float(record["alpha_return_pct"]) for record in records]
    wins = [alpha for alpha in alphas if alpha > 0]
    best = max(records, key=lambda record: float(record["alpha_return_pct"]))
    worst = min(records, key=lambda record: float(record["alpha_return_pct"]))
    return {
        "evaluated_new": len(records),
        "avg_alpha_return_pct": sum(alphas) / len(alphas),
        "win_rate": len(wins) / len(records),
        "best": {"ticker": best["ticker"], "alpha_return_pct": best["alpha_return_pct"]},
        "worst": {"ticker": worst["ticker"], "alpha_return_pct": worst["alpha_return_pct"]},
    }


def _append_outcome_records(records: list[dict]) -> None:
    if not records:
        return
    new_rows = pd.DataFrame(records)
    if OUTCOMES_FILE.exists():
        try:
            existing = pd.read_csv(OUTCOMES_FILE)
        except Exception as exc:
            _log_event("recommendation_outcomes_load_failed", error=str(exc))
            existing = pd.DataFrame()
        combined = pd.concat([existing, new_rows], ignore_index=True)
    else:
        combined = new_rows
    if "evaluation_id" in combined.columns:
        combined = combined.drop_duplicates(subset=["evaluation_id"], keep="last")
    if len(combined) > MAX_OUTCOME_ROWS:
        combined = combined.tail(MAX_OUTCOME_ROWS)
    ordered = [column for column in [
        "evaluation_id", "evaluated_at", "date", "ticker", "entry_price", "latest_price",
        "direction", "ticker_return_pct", "spy_return_pct", "position_return_pct",
        "benchmark_return_pct", "alpha_return_pct", "learning_reward",
        "score", "recommendation_confidence", "regime",
    ] if column in combined.columns]
    ordered += [column for column in combined.columns if column not in ordered]
    combined[ordered].to_csv(OUTCOMES_FILE, index=False)


def _log_event(event: str, **payload) -> None:
    logger.info(json.dumps({"event": event, **payload}, default=str))
