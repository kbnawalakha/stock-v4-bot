from datetime import datetime
from zoneinfo import ZoneInfo

from config import UNIVERSE, TOP_N, UNDER_30_N, EARNINGS_N, CATALYST_N, POLITICAL_N, SECTOR_ETF_MAP
from market_data import get_history
from indicators import (
    pct_return,
    trend_score,
    relative_strength_score,
    sector_strength_score,
    breakout_score,
    risk_quality_score,
)
from news_catalyst import news_catalyst_score, get_recent_headlines
from political_geo import political_geo_score
from politician_trades import politician_trade_score
from earnings import days_until_earnings, earnings_proximity_score
from scoring import final_score, earnings_setup_score, catalyst_watch_score
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

        news_score, catalysts, has_catalyst = news_catalyst_score(ticker)
        headlines = get_recent_headlines(ticker)
        pg_score, pg_reasons = political_geo_score(ticker, headlines)
        pol_score, pol_reasons = politician_trade_score(ticker)
        dte = days_until_earnings(ticker)

        features = {
            "trend": trend_score(df),
            "relative_strength": relative_strength_score(df, spy_df, qqq_df),
            "sector_strength": sector_strength_score(sector_cache[sector_ticker], spy_df),
            "breakout": breakout_score(df),
            "news_catalyst": news_score,
            "political_geo": pg_score,
            "politician_trade": pol_score,
            "risk_quality": risk_quality_score(df),
            "earnings_proximity": earnings_proximity_score(dte),
        }

        row = {
            "ticker": ticker,
            "price": float(df["Close"].iloc[-1]),
            "days_to_earnings": dte,
            "catalysts": catalysts,
            "has_catalyst": has_catalyst,
            "political_reasons": pg_reasons,
            "politician_reasons": pol_reasons,
            **features,
        }
        row["score"] = final_score(row)
        row["earnings_score"] = earnings_setup_score(row)
        row["catalyst_watch_score"] = catalyst_watch_score(row)
        results.append(row)

    return sorted(results, key=lambda x: x["score"], reverse=True), spy_df, qqq_df


def html_table(title, rows, reason_mode="normal"):
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
        score_label = f"Score {r['score']:.1f}"
        if reason_mode == "earnings":
            score_label = f"Earnings score {r['earnings_score']:.1f}"
        elif reason_mode in ["catalyst", "political"]:
            score_label = f"Catalyst score {r['catalyst_watch_score']:.1f}"

        ticker_cell = f"<b>{r['ticker']}</b><br><span style='color:#666;'>${r['price']:.2f} | {score_label}</span>"
        why = why_buy(
            r,
            is_earnings=(reason_mode == "earnings"),
            is_catalyst=(reason_mode in ["catalyst", "political"]),
        )

        html += f"""
        <tr>
          <td style="border:1px solid #ddd;vertical-align:top;width:28%;">{ticker_cell}</td>
          <td style="border:1px solid #ddd;vertical-align:top;">{why}</td>
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

    catalyst_watch = sorted(
        [r for r in results if r.get("has_catalyst") or r.get("news_catalyst", 0) >= 30],
        key=lambda x: x["catalyst_watch_score"],
        reverse=True,
    )[:CATALYST_N]

    political_watch = sorted(
        [r for r in results if r.get("political_geo", 0) >= 20 or r.get("politician_trade", 0) >= 10],
        key=lambda x: x["catalyst_watch_score"],
        reverse=True,
    )[:POLITICAL_N]

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
      {html_table("Top 5 Earnings Setups", earnings, reason_mode="earnings")}
      {html_table("Catalyst Watch", catalyst_watch, reason_mode="catalyst")}
      {html_table("Political / Geopolitical Watch", political_watch, reason_mode="political")}

      <p style="color:#777;font-size:12px;margin-top:28px;">
        Research only. Not financial advice. Congressional trade disclosures can be delayed,
        so politician-trade signals are secondary indicators.
      </p>
    </body>
    </html>
    """

    text = "Daily Stock Alpha Report\n\n"
    sections = [
        ("Top 10 Stocks", top_10, "normal"),
        ("Top 5 Under $30", under_30, "normal"),
        ("Top 5 Earnings Setups", earnings, "earnings"),
        ("Catalyst Watch", catalyst_watch, "catalyst"),
        ("Political / Geopolitical Watch", political_watch, "political"),
    ]
    for title, rows, mode in sections:
        text += f"\n{title}\n"
        for r in rows:
            text += f"{r['ticker']}: {why_buy(r, mode == 'earnings', mode in ['catalyst', 'political'])}\n"

    return html, text, top_10


def main():
    results, spy_df, qqq_df = analyze_universe()
    html, text, top_10 = build_email(results, spy_df, qqq_df)

    print(text)
    log_predictions(top_10)
    send_email("Daily Stock Alpha Report", html, text)


if __name__ == "__main__":
    main()
