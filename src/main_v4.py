from emailer import send_email
from market_data import get_history
from strategies import score_all_strategies
from ensemble import ensemble_score
from benchmarks import benchmark_returns
from performance import log_predictions
from risk import suggested_qty
from portfolio import load_portfolio

UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AMD", "AMZN", "META", "TSLA", "AVGO", "MU", "PLTR",
    "GOOGL", "NFLX", "CRM", "ORCL", "ADBE", "COST", "LLY", "JPM", "BAC", "UNH"
]


def analyze_ticker(ticker: str) -> dict | None:
    df = get_history(ticker)
    if df.empty or len(df) < 60:
        print(f"Skipping {ticker}: not enough data.")
        return None

    strategy_scores = score_all_strategies(df)
    score = ensemble_score(strategy_scores)
    price = float(df["Close"].iloc[-1])

    return {
        "ticker": ticker,
        "price": price,
        "score": score,
        **strategy_scores,
    }


def build_report(results: list[dict], benchmarks: dict) -> str:
    lines = []
    lines.append("Daily Stock Signal Report")
    lines.append("")
    lines.append("Top 10 ensemble rankings:")
    lines.append("")

    for i, row in enumerate(results[:10], start=1):
        lines.append(
            f"{i}. {row['ticker']} | Score: {row['score']:.2f} | "
            f"Momentum: {row['momentum']:.1f}, Trend: {row['trend']:.1f}, "
            f"Anomaly: {row['anomaly']:.1f}, MeanRev: {row['mean_reversion']:.1f}"
        )

    lines.append("")
    lines.append("Benchmark comparison:")
    for ticker, ret in benchmarks.items():
        lines.append(f"{ticker}: 1D {ret['1d']:.2f}% | 5D {ret['5d']:.2f}% | 20D {ret['20d']:.2f}%")

    lines.append("")
    lines.append("Note: This is a signal-ranking system for research, not financial advice.")
    return "\n".join(lines)


def main():
    portfolio = load_portfolio()
    cash = float(portfolio.get("cash", 100000))

    results = []
    for ticker in UNIVERSE:
        row = analyze_ticker(ticker)
        if row:
            row["suggested_qty"] = suggested_qty(row["price"], row["score"], cash)
            results.append(row)

    results.sort(key=lambda x: x["score"], reverse=True)

    benchmarks = benchmark_returns()
    report = build_report(results, benchmarks)

    print(report)
    log_predictions(results[:10])

    send_email("Daily Stock Alpha Report", report)


if __name__ == "__main__":
    main()
