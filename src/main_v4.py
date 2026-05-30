from datetime import datetime
from zoneinfo import ZoneInfo

from config import UNIVERSE, TOP_N
from market_data import get_history
from strategies import score_all_strategies
from ensemble import ensemble_score
from benchmarks import benchmark_returns
from performance import log_predictions
from portfolio import load_portfolio
from risk import suggested_qty
from emailer import send_email


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


def market_regime(benchmarks: dict) -> str:
    qqq_20 = benchmarks.get("QQQ", {}).get("20d", 0)
    spy_20 = benchmarks.get("SPY", {}).get("20d", 0)
    avg = (qqq_20 + spy_20) / 2

    if avg > 3:
        return "Risk-on"
    if avg < -3:
        return "Risk-off"
    return "Neutral"


def build_report(results: list[dict], benchmarks: dict) -> str:
    now_pt = datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d %I:%M %p %Z")

    lines = []
    lines.append("Daily Stock Signal Report")
    lines.append(f"Generated: {now_pt}")
    lines.append("")
    lines.append(f"Market Regime: {market_regime(benchmarks)}")
    lines.append("")
    lines.append("Benchmark comparison:")
    for ticker, ret in benchmarks.items():
        lines.append(f"- {ticker}: 1D {ret['1d']:.2f}% | 5D {ret['5d']:.2f}% | 20D {ret['20d']:.2f}%")

    lines.append("")
    lines.append(f"Top {TOP_N} ensemble rankings:")
    lines.append("")

    for i, row in enumerate(results[:TOP_N], start=1):
        lines.append(f"{i}. {row['ticker']} | Score {row['score']:.2f} | Price ${row['price']:.2f}")
        lines.append(
            f"   Momentum {row['momentum']:.1f} | Trend {row['trend']:.1f} | "
            f"Anomaly {row['anomaly']:.1f} | MeanRev {row['mean_reversion']:.1f}"
        )
        lines.append(f"   Suggested paper qty: {row['suggested_qty']}")
        lines.append("")

    lines.append("Important: This is a research signal-ranking system, not financial advice.")
    return "\n".join(lines)


def main():
    portfolio = load_portfolio()
    cash = float(portfolio.get("cash", 100000))

    results = []
    for ticker in UNIVERSE:
        row = analyze_ticker(ticker)
        if row is None:
            continue
        row["suggested_qty"] = suggested_qty(row["price"], row["score"], cash)
        results.append(row)

    results.sort(key=lambda x: x["score"], reverse=True)

    benchmarks = benchmark_returns()
    report = build_report(results, benchmarks)

    print(report)
    log_predictions(results[:TOP_N])
    send_email("Daily Stock Alpha Report", report)


if __name__ == "__main__":
    main()
