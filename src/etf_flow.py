import pandas as pd

from signal_utils import clamp
from volume_accumulation import volume_accumulation_score


def etf_flow_exposure_score(ticker: str, sector_etf: str, sector_df: pd.DataFrame) -> dict[str, float | str]:
    if not sector_etf or sector_df is None or sector_df.empty:
        return {
            "score": 50.0,
            "sector_etf": sector_etf or "",
            "relative_volume": 1.0,
            "reason": "ETF flow exposure unavailable",
        }

    proxy = volume_accumulation_score(sector_etf, sector_df)
    score = clamp(proxy.get("score", 50.0), 0, 100)
    reason = (
        f"{sector_etf} shows supportive ETF accumulation proxy"
        if score >= 65 else
        f"{sector_etf} shows weak ETF accumulation proxy"
        if score <= 40 else
        f"{sector_etf} ETF accumulation proxy is neutral"
    )
    return {
        "score": score,
        "sector_etf": sector_etf,
        "relative_volume": float(proxy.get("relative_volume", 1.0)),
        "reason": reason,
    }
