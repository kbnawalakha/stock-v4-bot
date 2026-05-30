from market_data import get_history
from config import BENCHMARKS


def benchmark_returns() -> dict:
    output = {}
    for ticker in BENCHMARKS:
        df = get_history(ticker, period="3mo")
        if df.empty or len(df) < 22:
            output[ticker] = {"1d": 0.0, "5d": 0.0, "20d": 0.0}
            continue
        close = df["Close"]
        output[ticker] = {
            "1d": float((close.iloc[-1] / close.iloc[-2] - 1) * 100),
            "5d": float((close.iloc[-1] / close.iloc[-6] - 1) * 100),
            "20d": float((close.iloc[-1] / close.iloc[-21] - 1) * 100),
        }
    return output
