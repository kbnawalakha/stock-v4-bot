from pathlib import Path
from datetime import datetime, timezone
import pandas as pd

LOG_FILE = Path("predictions.csv")
MAX_HISTORY_ROWS = 5000


def log_predictions(rows: list[dict]) -> None:
    if not rows:
        print("No predictions to log.")
        return

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    sent_at = datetime.now(timezone.utc).isoformat()
    enriched = []
    for rank, row in enumerate(rows, start=1):
        ticker = str(row.get("ticker", "")).upper()
        record = dict(row)
        direction = str(record.get("direction", "BULL") or "BULL").upper()
        swing_details = row.get("swing_details", {}) or {}
        bear_details = row.get("bear_case_details", {}) or {}
        record.update({
            "date": today,
            "sent_at_utc": sent_at,
            "rank": rank,
            "recommendation_id": f"{today}:{ticker}:{direction}:{rank}",
            "direction": direction,
            "top_drivers": _join_text(row.get("top_drivers", [])),
            "top_risks": _join_text(row.get("top_risks", [])),
            "swing_entry": swing_details.get("entry_price"),
            "swing_stop": swing_details.get("stop_loss"),
            "swing_target": swing_details.get("target_price"),
            "swing_setup_type": swing_details.get("setup_type"),
            "bear_case_score": bear_details.get("score"),
            "bear_case_reason": bear_details.get("reason"),
        })
        enriched.append(record)
    df = pd.DataFrame(enriched)

    cols = [
        "recommendation_id", "date", "sent_at_utc", "rank", "direction", "ticker", "price",
        "score", "recommendation_confidence", "opportunity_score", "catalyst_score", "quality_score",
        "opening_activity", "pre_market_activity", "post_market_activity", "swing_setup", "swing_risk_reward", "news_sentiment",
        "trend", "relative_strength", "sector_strength", "breakout", "options_flow",
        "earnings", "earnings_quality", "analyst_revisions", "fundamental_momentum",
        "volume_accumulation", "short_squeeze", "insider_buying", "volatility_setup",
        "etf_flow_exposure", "institutional_ownership", "pattern_trading", "news_catalyst",
        "political_geo", "politician_trade", "risk_quality", "days_to_earnings",
        "regime", "market_breadth_regime", "market_breadth_score", "sentiment_confidence", "catalyst_watch_score",
        "top_drivers", "top_risks", "swing_entry", "swing_stop", "swing_target", "swing_setup_type",
        "bear_case_score", "bear_case_reason",
    ]
    df = df[[c for c in cols if c in df.columns]]

    existing = _load_existing_history()
    if not existing.empty:
        combined = pd.concat([existing, df], ignore_index=True)
    else:
        combined = df
    if "recommendation_id" in combined.columns:
        combined = combined.drop_duplicates(subset=["recommendation_id"], keep="last")
    if len(combined) > MAX_HISTORY_ROWS:
        combined = combined.tail(MAX_HISTORY_ROWS)
    ordered = [c for c in cols if c in combined.columns]
    ordered += [c for c in combined.columns if c not in ordered]
    combined[ordered].to_csv(LOG_FILE, index=False)
    print(f"Logged {len(rows)} recommendations to {LOG_FILE}.")


def _load_existing_history() -> pd.DataFrame:
    if not LOG_FILE.exists():
        return pd.DataFrame()
    try:
        existing = pd.read_csv(LOG_FILE)
    except Exception as exc:
        print(f"Could not load existing recommendation history; starting fresh. Error: {exc}")
        return pd.DataFrame()
    if "recommendation_id" not in existing.columns and {"date", "ticker"}.issubset(existing.columns):
        existing = existing.copy()
        existing["recommendation_id"] = [
            f"{row.get('date')}:{str(row.get('ticker', '')).upper()}:{idx}"
            for idx, row in existing.iterrows()
        ]
    return existing


def _join_text(value) -> str:
    if isinstance(value, list):
        return " | ".join(str(item) for item in value if str(item).strip())
    return str(value or "")
