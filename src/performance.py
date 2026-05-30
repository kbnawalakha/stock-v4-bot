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
        "date", "ticker", "price", "score", "relative_strength", "sector_strength",
        "breakout", "news_catalyst", "political_geo", "politician_trade",
        "risk_quality", "days_to_earnings", "catalyst_watch_score"
    ]
    df = df[[c for c in cols if c in df.columns]]

    header = not LOG_FILE.exists()
    df.to_csv(LOG_FILE, mode="a", header=header, index=False)
    print(f"Logged {len(rows)} predictions.")
