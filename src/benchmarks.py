from market_data import get_history


def benchmark_returns() -> dict:
    out = {}
    for ticker in ["SPY", "QQQ"]:
        df = get_history(ticker, period="1mo")
        if df.empty or len(df) < 6:
            out[ticker] = {"1d": 0.0, "5d": 0.0, "20d": 0.0}
            continue
        close = df["Close"]
        out[ticker] = {
            "1d": float((close.iloc[-1] / close.iloc[-2] - 1) * 100),
            "5d": float((close.iloc[-1] / close.iloc[-6] - 1) * 100),
            "20d": float((close.iloc[-1] / close.iloc[0] - 1) * 100),
        }
    return out
