from datetime import datetime
from zoneinfo import ZoneInfo

from config import UNIVERSE, TOP_N, UNDER_30_N, EARNINGS_N, SECTOR_ETF_MAP
from market_data import get_history
from indicators import (
    pct_return,
    trend_score,
    relative_strength_score,
    sector_strength_score,
    breakout_score,
    risk_quality_score,
)
from news_catalyst import news_catalyst_score
from earnings import days_until_earnings, earnings_proximity_score
from scoring import final_score, earnings_setup_score
from reasons import why_buy
from performance import log_predictions
from emailer import send_email


def analyze_universe():
    spy_df = get_history("SPY")
    qqq_df = get_history("QQQ")

    sector_cache = {}
    results = []

    for ticker in UNIVERSE:
        df = get_history(ticker)
        if df.empty or len(df) < 120:
            print(f"Skipping {ticker}: not enough data.")
            continue

        sector_ticker = SECTOR_ETF_MAP.get(ticker, "SPY")
        if sector_ticker not in sector_cache:
            sector_cache[sector_ticker] = get_history(sector_ticker)

        news_score, catalysts = news_catalyst_score(ticker)
        dte = days_until_earnings(ticker)

        features = {
            "trend": trend_score(df),
            "relative_strength": relative_strength_score(df, spy_df, qqq_df),
            "sector_strength": sector_strength_score(sector_cache[sector_ticker], spy_df),
            "breakout": breakout_score(df),
            "news_catalyst": news_score,
            "risk_quality": risk_quality_score(df),
            "earnings_proximity": earnings_proximity_score(dte),
        }

        score = final_score(features)

        row = {
            "ticker": ticker,
            "price": float(df["Close"].iloc[-1]),
            "score": score,
            "days_to_earnings": dte,
            "catalysts": catalysts,
            **features,
        }
        row["earnings_score"] = earnings_setup_score(row)
        results.append(row)

    return sorted(results, key=lambda x: x["score"], reverse=True), spy_df, qqq_df


def html_table(title, rows, earnings=False):
    html = f"""
    <h2 style="margin-top:28px;border-bottom:2px solid #222;padding-bottom:6px;">{title}</h2>
    <table width="100%" cellpadding="8" cellspacing="0" style="border-collapse:collapse;font-family:Arial,sans-serif;font-size:14px;">
      <tr style="background:#f2f2f2;">
        <th align="left" style="border:1px solid #ddd;">Ticker</th>
        <th align="left" style="border:1px solid #ddd;">Why buy this?</th>
      </tr>
    """
    if not rows:
        html += '<tr><td style="border:1px solid #ddd;">None</td><td style="border:1px solid #ddd;">No matching setups today.</td></tr>'
    for r in rows:
        ticker_cell = f"<b>{r['ticker']}</b><br><span style='color:#666;'>${r['price']:.2f} | Score {r['score']:.1f}</span>"
        if earnings:
            ticker_cell = f"<b>{r['ticker']}</b><br><span style='color:#666;'>${r['price']:.2f} | Earnings score {r['earnings_score']:.1f}</span>"
        html += f"""
        <tr>
          <td style="border:1px solid #ddd;vertical-align:top;width:28%;">{ticker_cell}</td>
          <td style="border:1px solid #ddd;vertical-align:top;">{why_buy(r, is_earnings=earnings)}</td>
        </tr>
        """
    html += "</table>"
    return html


def build_email(results, spy_df, qqq_df):
    now_pt = datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d %I:%M %p %Z")
    spy_20 = pct_return(spy_df, 20)
    qqq_20 = pct_return(qqq_df, 20)

    top_10 = results[:TOP_N]
    under_30 = [r for r in results if r["price"] < 30][:UNDER_30_N]
    earnings = sorted(
        [r for r in results if r.get("days_to_earnings") is not None and 0 <= r["days_to_earnings"] <= 21],
        key=lambda x: x["earnings_score"],
        reverse=True,
    )[:EARNINGS_N]

    html = f"""
    <html>
    <body style="font-family:Arial,sans-serif;color:#111;line-height:1.4;">
      <h1 style="margin-bottom:4px;">Daily Stock Alpha Report</h1>
      <p style="margin-top:0;color:#666;">Generated: {now_pt}</p>

      <div style="background:#f7f7f7;border:1px solid #ddd;padding:12px;margin:16px 0;">
        <b>Market snapshot:</b><br>
        SPY 20D: {spy_20:.2f}% &nbsp; | &nbsp; QQQ 20D: {qqq_20:.2f}%
      </div>

      {html_table("Top 10 Stocks", top_10)}
      {html_table("Top 5 Under $30", under_30)}
      {html_table("Top 5 Earnings Setups", earnings, earnings=True)}

      <p style="color:#777;font-size:12px;margin-top:28px;">
        Research only. Not financial advice. These rankings are based on relative strength, sector strength,
        breakout potential, news/catalysts, and risk quality.
      </p>
    </body>
    </html>
    """

    text = "Daily Stock Alpha Report\n\n"
    for title, rows in [("Top 10 Stocks", top_10), ("Top 5 Under $30", under_30), ("Top 5 Earnings Setups", earnings)]:
        text += f"\n{title}\n"
        for r in rows:
            text += f"{r['ticker']}: {why_buy(r, title.endswith('Setups'))}\n"

    return html, text, top_10


def main():
    results, spy_df, qqq_df = analyze_universe()
    html, text, top_10 = build_email(results, spy_df, qqq_df)

    print(text)
    log_predictions(top_10)
    send_email("Daily Stock Alpha Report", html, text)


if __name__ == "__main__":
    main()
