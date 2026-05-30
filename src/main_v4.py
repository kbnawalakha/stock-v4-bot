from datetime import datetime
import json
import logging
from html import escape
from zoneinfo import ZoneInfo

from config import UNIVERSE, TOP_N, UNDER_30_N, EARNINGS_N, CATALYST_N, POLITICAL_N, SECTOR_ETF_MAP
from finnhub_client import get_finnhub_client
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
from openai_sentiment import score_overnight_sentiment
from opening_activity import opening_activity_score
from options_flow import options_flow_score
from political_geo import political_geo_score
from politician_trades import politician_trade_score
from earnings import earnings_proximity_score, earnings_score
from market_regime import classify_market_regime
from scoring import final_score, earnings_setup_score, catalyst_watch_score, regime_adjusted_weights
from reasons import why_buy
from performance import log_predictions
from emailer import send_email

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def log_event(event: str, **payload):
    logger.info(json.dumps({"event": event, **payload}, default=str))


INDICATOR_COLUMNS = [
    ("Opening", "opening_activity"),
    ("News", "news_sentiment"),
    ("Catalyst", "news_catalyst"),
    ("Trend", "trend"),
    ("RS", "relative_strength"),
    ("Sector", "sector_strength"),
    ("Breakout", "breakout"),
    ("Options", "options_flow"),
    ("Earnings", "earnings"),
    ("Political", "political_geo"),
    ("Trade", "politician_trade"),
    ("Risk", "risk_quality"),
]


def indicator_text(row: dict) -> str:
    return " | ".join(f"{label} {row.get(key, 0):.0f}" for label, key in INDICATOR_COLUMNS)


def analyze_universe():
    spy_df = get_history("SPY")
    qqq_df = get_history("QQQ")
    sector_cache = {}
    results = []

    for ticker in UNIVERSE:
        try:
            df = get_history(ticker)
            if df.empty or len(df) < 120:
                print(f"Skipping {ticker}: not enough data.")
                continue

            sector_ticker = SECTOR_ETF_MAP.get(ticker, "SPY")
            if sector_ticker not in sector_cache:
                sector_cache[sector_ticker] = get_history(sector_ticker)

            news_score, catalysts, has_catalyst = news_catalyst_score(ticker)
            finnhub_headlines = get_finnhub_client().overnight_headlines(ticker)
            headlines = finnhub_headlines or get_recent_headlines(ticker)
            pg_score, pg_reasons = political_geo_score(ticker, headlines)
            pol_score, pol_reasons = politician_trade_score(ticker)
            opening = opening_activity_score(ticker)
            earnings = earnings_score(ticker)
            options = options_flow_score(ticker)
            log_event("opening_activity_score", ticker=ticker, **opening)
            log_event("earnings_score", ticker=ticker, **earnings)
            log_event("options_score", ticker=ticker, **options)

            features = {
                "trend": trend_score(df),
                "relative_strength": relative_strength_score(df, spy_df, qqq_df),
                "sector_strength": sector_strength_score(sector_cache[sector_ticker], spy_df),
                "breakout": breakout_score(df),
                "news_catalyst": news_score,
                "news_sentiment": max(0.0, min(100.0, 50.0 + news_score / 2)),
                "political_geo": pg_score,
                "politician_trade": pol_score,
                "risk_quality": risk_quality_score(df),
                "opening_activity": opening["score"],
                "earnings": earnings["score"],
                "options_flow": options["score"],
                "earnings_proximity": earnings_proximity_score(earnings.get("days_to_earnings")),
            }

            row = {
                "ticker": ticker,
                "price": float(df["Close"].iloc[-1]),
                "days_to_earnings": earnings.get("days_to_earnings"),
                "catalysts": catalysts,
                "headlines": headlines,
                "has_catalyst": has_catalyst,
                "political_reasons": pg_reasons,
                "politician_reasons": pol_reasons,
                "opening_details": opening,
                "earnings_details": earnings,
                "options_details": options,
                "sentiment_confidence": 0.0,
                "sentiment_reasoning": "OpenAI overnight sentiment not evaluated before top-20 filtering.",
                **features,
            }
            row["score"] = final_score(row)
            row["earnings_score"] = earnings_setup_score(row)
            row["catalyst_watch_score"] = catalyst_watch_score(row)
            results.append(row)
            log_event(
                "candidate_scores",
                ticker=ticker,
                score=row["score"],
                opening=row["opening_activity"],
                options=row["options_flow"],
                earnings=row["earnings"],
            )
        except Exception as exc:
            log_event("ticker_failed", ticker=ticker, error=str(exc))
            continue

    preliminary = sorted(results, key=lambda x: x["score"], reverse=True)
    top_20 = preliminary[:20]
    log_event("top_20_candidates", tickers=[r["ticker"] for r in top_20])

    for row in top_20:
        sentiment = score_overnight_sentiment(row["ticker"], row.get("headlines", []))
        row["news_sentiment"] = sentiment["sentiment"]
        row["sentiment_confidence"] = sentiment["confidence"]
        row["sentiment_reasoning"] = sentiment["reasoning"]
        log_event("sentiment_score", ticker=row["ticker"], **sentiment)

    regime = classify_market_regime()
    weights = regime_adjusted_weights(str(regime["regime"]))
    log_event("regime", **regime, weights=weights)

    for row in preliminary:
        row["regime"] = regime["regime"]
        row["regime_confidence"] = regime["confidence"]
        row["score"] = final_score(row, weights)
        row["earnings_score"] = earnings_setup_score(row)
        row["catalyst_watch_score"] = catalyst_watch_score(row)

    return sorted(preliminary, key=lambda x: x["score"], reverse=True), spy_df, qqq_df, regime


def html_table(title, rows, reason_mode="normal"):
    indicator_headers = "\n".join(
        f'<th align="right" style="border:1px solid #ddd;">{label}</th>'
        for label, _ in INDICATOR_COLUMNS
    )
    html = f"""
    <h2 style="margin-top:28px;border-bottom:2px solid #222;padding-bottom:6px;">{title}</h2>
    <table width="100%" cellpadding="6" cellspacing="0" style="border-collapse:collapse;font-family:Arial,sans-serif;font-size:12px;">
      <tr style="background:#f2f2f2;">
        <th align="left" style="border:1px solid #ddd;">Ticker</th>
        {indicator_headers}
        <th align="left" style="border:1px solid #ddd;">Regime</th>
        <th align="left" style="border:1px solid #ddd;">Why buy this?</th>
      </tr>
    """
    if not rows:
        colspan = len(INDICATOR_COLUMNS) + 3
        html += f'<tr><td colspan="{colspan}" style="border:1px solid #ddd;">No matching setups today.</td></tr>'

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
        sentiment_reason = r.get("sentiment_reasoning")
        if sentiment_reason and reason_mode == "normal":
            why += f"<br><span style='color:#555;'>OpenAI: {escape(sentiment_reason)}</span>"
        indicator_cells = "\n".join(
            f'<td align="right" style="border:1px solid #ddd;vertical-align:top;">{r.get(key, 0):.0f}</td>'
            for _, key in INDICATOR_COLUMNS
        )

        html += f"""
        <tr>
          <td style="border:1px solid #ddd;vertical-align:top;width:16%;">{ticker_cell}</td>
          {indicator_cells}
          <td style="border:1px solid #ddd;vertical-align:top;">{r.get('regime', 'NEUTRAL')}</td>
          <td style="border:1px solid #ddd;vertical-align:top;">{why}</td>
        </tr>
        """
    html += "</table>"
    return html


def build_email(results, spy_df, qqq_df, regime):
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
        SPY 20D: {spy_20:.2f}% &nbsp; | &nbsp; QQQ 20D: {qqq_20:.2f}%<br>
        Regime: {regime.get("regime", "NEUTRAL")} ({float(regime.get("confidence", 0)):.0%} confidence)
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
            text += (
                f"{r['ticker']} Score: {r['score']:.1f} | {indicator_text(r)} | Regime {r.get('regime', 'NEUTRAL')}\n"
                f"Drivers: {why_buy(r, mode == 'earnings', mode in ['catalyst', 'political'])}\n"
            )
            if mode == "normal" and r.get("sentiment_reasoning"):
                text += f"OpenAI: {r['sentiment_reasoning']}\n"

    return html, text, top_10


def main():
    results, spy_df, qqq_df, regime = analyze_universe()
    html, text, top_10 = build_email(results, spy_df, qqq_df, regime)

    print(text)
    log_predictions(top_10)
    send_email("Daily Stock Alpha Report", html, text)


if __name__ == "__main__":
    main()
