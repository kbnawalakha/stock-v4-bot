from pathlib import Path
from datetime import datetime
import pandas as pd

LOG_FILE = Path("predictions.csv")


def log_predictions(rows: list[dict]) -> None:
    df = pd.DataFrame(rows)
    df.insert(0, "date", datetime.utcnow().strftime("%Y-%m-%d"))
    header = not LOG_FILE.exists()
    df.to_csv(LOG_FILE, mode="a", header=header, index=False)
    print(f"Logged {len(rows)} predictions to {LOG_FILE}")
