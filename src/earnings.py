from datetime import datetime, timezone
import pandas as pd
from market_data import get_ticker_obj


def days_until_earnings(ticker: str) -> int | None:
    try:
        obj = get_ticker_obj(ticker)
        dates = obj.earnings_dates
        if dates is None or len(dates) == 0:
            return None

        idx = dates.index
        now = pd.Timestamp(datetime.now(timezone.utc))

        future_dates = []
        for d in idx:
            ts = pd.Timestamp(d)
            if ts.tzinfo is None:
                ts = ts.tz_localize("UTC")
            if ts >= now:
                future_dates.append(ts)

        if not future_dates:
            return None

        next_date = min(future_dates)
        return int((next_date - now).days)
    except Exception:
        return None


def earnings_proximity_score(days: int | None) -> float:
    if days is None:
        return 0.0
    if days < 0 or days > 21:
        return 0.0
    if days <= 3:
        return 100.0
    if days <= 7:
        return 80.0
    if days <= 14:
        return 60.0
    return 40.0
