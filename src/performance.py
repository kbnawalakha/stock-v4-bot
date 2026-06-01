from pathlib import Path
from datetime import datetime, timezone
import pandas as pd

LOG_FILE = Path("predictions.csv")


def log_predictions(rows: list[dict]) -> None:
    if not rows:
        print("No predictions to log.")
        return

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    df = pd.DataFrame(rows)
    df.insert(0, "date", today)

    cols = [
        "date", "ticker", "price", "score", "opportunity_score", "catalyst_score", "quality_score",
        "opening_activity", "pre_market_activity", "post_market_activity", "news_sentiment",
        "trend", "relative_strength", "sector_strength", "breakout", "options_flow",
        "earnings", "earnings_quality", "analyst_revisions", "fundamental_momentum",
        "volume_accumulation", "short_squeeze", "insider_buying", "volatility_setup",
        "etf_flow_exposure", "institutional_ownership", "pattern_trading", "news_catalyst",
        "political_geo", "politician_trade", "risk_quality", "days_to_earnings",
        "regime", "market_breadth_regime", "market_breadth_score", "sentiment_confidence", "catalyst_watch_score"
    ]
    df = df[[c for c in cols if c in df.columns]]

    header = not LOG_FILE.exists()
    df.to_csv(LOG_FILE, mode="a", header=header, index=False)
    print(f"Logged {len(rows)} predictions.")
