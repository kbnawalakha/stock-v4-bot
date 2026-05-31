from datetime import datetime
import json
import logging
import os
from html import escape
from zoneinfo import ZoneInfo

from config import (
    UNIVERSE,
    TOP_N,
    UNDER_30_N,
    EARNINGS_N,
    CATALYST_N,
    POLITICAL_N,
    MIN_PRICE,
    MIN_AVG_DAILY_VOLUME,
    SECTOR_ETF_MAP,
    SECTOR_LABELS,
)
from analyst_revisions import analyst_revision_score
from etf_flow import etf_flow_exposure_score
from finnhub_client import get_finnhub_client
from fundamentals_momentum import fundamental_momentum_score
from insider_buying import insider_buying_score
from institutional_change import institutional_change_score
from market_data import get_history
from market_breadth import market_breadth_regime
from indicators import (
    pct_return,
    trend_score,
    relative_strength_score,
    sector_strength_score,
    breakout_score,
    risk_quality_score,
)
from news_catalyst import news_catalyst_score, get_recent_headlines
from gemini_sentiment import analyze_reddit_plays, score_overnight_sentiments
from reddit_client import extract_reddit_candidates, fetch_reddit_posts
from opening_activity import opening_activity_score
from options_flow import options_flow_score
from institutional import institutional_ownership_score
from pattern_trading import pattern_trading_score
from political_geo import political_geo_score
from politician_trades import politician_trade_score
from earnings import earnings_proximity_score, earnings_score
from market_regime import classify_market_regime
from scoring import (
    apply_reddit_blend,
    catalyst_watch_score,
    earnings_setup_score,
    regime_adjusted_weights,
    staged_final_score,
)
from short_squeeze import short_squeeze_score
from signal_utils import signed_to_percent
from volatility_setup import volatility_setup_score
from volume_accumulation import volume_accumulation_score
from universe_builder import build_daily_universe, universe_config, update_universe_stages
from learning import refresh_learning_state
from performance import log_predictions
from emailer import send_email

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

OPTIONAL_API_ENVS = ["FMP_API_KEY", "ALPHA_VANTAGE_API_KEY", "SEC_USER_AGENT", "FINNHUB_API_KEY", "GEMINI_API_KEY"]


def log_event(event: str, **payload):
    logger.info(json.dumps({"event": event, **payload}, default=str))


def upside_reason(row: dict, reason_mode: str = "normal") -> str:
    drivers = []
    if row.get("opening_activity", 0) >= 70:
        drivers.append("buyers showed up early with strong opening activity")
    elif row.get("opening_activity", 0) >= 55:
        drivers.append("opening activity is supportive")

    if row.get("news_sentiment", 0) >= 70:
        drivers.append("overnight news sentiment is bullish")
    if row.get("options_flow", 0) >= 70:
        drivers.append("options flow is leaning bullish")
    if row.get("pattern_trading", 0) >= 70:
        patterns = row.get("pattern_details", {}).get("patterns", [])
        if patterns:
            drivers.append(patterns[0])
        else:
            drivers.append("daily and weekly trading patterns are constructive")
    if row.get("institutional_ownership", 0) >= 70:
        drivers.append(row.get("institutional_details", {}).get("reason", "institutional ownership is supportive"))
    if row.get("etf_flow_exposure", 50) >= 70:
        drivers.append(row.get("etf_flow_details", {}).get("reason", "sector ETF flow exposure is supportive"))
    if row.get("trend", 0) >= 75:
        drivers.append("the stock remains in a strong trend")
    if row.get("sector_strength", 0) >= 20:
        drivers.append("its sector is acting well")
    if row.get("breakout", 0) >= 55:
        drivers.append("the chart has a breakout setup")
    if row.get("earnings", 0) >= 70:
        drivers.append("earnings data is supportive")
    if row.get("political_geo", 0) >= 20:
        drivers.append("there is a political or geopolitical tailwind")
    if row.get("politician_trade", 0) >= 10:
        drivers.append("politician-trade activity is supportive")

    if reason_mode in ["catalyst", "political"] and row.get("catalysts"):
        catalyst = row["catalysts"][0]
        drivers.insert(0, f'a fresh catalyst is in play: "{catalyst}"')
    elif reason_mode == "earnings" and row.get("days_to_earnings") is not None:
        drivers.insert(0, f"earnings are coming in {row['days_to_earnings']} days")

    if not drivers:
        drivers.append("it has one of the best combined setups in today's model")

    reason = f"{row['ticker']} has upside potential because " + ", ".join(drivers[:3]) + "."
    sentiment_reason = row.get("sentiment_reasoning")
    if sentiment_reason and row.get("sentiment_confidence", 0) > 0:
        reason += f" Gemini sentiment note: {sentiment_reason}"
    return reason


def top_drivers(row: dict) -> list[str]:
    candidates = []
    checks = [
        ("opening_activity", "strong opening activity"),
        ("news_sentiment", "bullish news sentiment"),
        ("options_flow", "bullish options flow"),
        ("volume_accumulation", "accumulation on volume"),
        ("volatility_setup", "constructive volatility setup"),
        ("earnings_quality", "supportive earnings quality"),
        ("analyst_revisions", "positive analyst revisions"),
        ("fundamental_momentum", "improving fundamentals"),
        ("insider_buying", "insider buying signal"),
        ("institutional_ownership", "institutional support"),
        ("pattern_trading", "constructive trading pattern"),
        ("etf_flow_exposure", "supportive sector ETF flow proxy"),
    ]
    for key, label in checks:
        value = float(row.get(key, 50.0))
        if value >= 65:
            candidates.append((value, label))
    return [label for _, label in sorted(candidates, reverse=True)[:3]] or ["balanced multi-factor setup"]


def top_risks(row: dict) -> list[str]:
    risks = []
    if row.get("liquidity_score", 100) < 60:
        risks.append("liquidity is thinner than preferred")
    if row.get("risk_quality", 100) < 45:
        risks.append("volatility/risk quality is weak")
    if row.get("earnings_quality", 50) < 40:
        risks.append("earnings quality is soft")
    if row.get("analyst_revisions", 50) < 40:
        risks.append("analyst revisions are negative")
    if row.get("news_sentiment", 50) < 45:
        risks.append("news sentiment is not supportive")
    return risks[:2] or ["no major model risk flagged"]


def sector_extreme_signals(spy_df, qqq_df) -> list[dict]:
    sectors = sorted(set(SECTOR_ETF_MAP.values()) - {"SPY", "QQQ"})
    signals = []
    for etf in sectors:
        try:
            df = get_history(etf)
            if df.empty or len(df) < 80:
                continue

            trend = trend_score(df)
            five_day = pct_return(df, 5)
            twenty_day = pct_return(df, 20)
            rel_spy = twenty_day - pct_return(spy_df, 20)
            pattern = pattern_trading_score(df)
            close = df["Close"]
            price = float(close.iloc[-1])
            ma20 = float(close.rolling(20).mean().iloc[-1])
            ma50 = float(close.rolling(50).mean().iloc[-1])
            prior_20_low = float(df["Low"].iloc[-21:-1].min())

            bullish_points = 0
            bullish_reasons = []
            if trend >= 80:
                bullish_points += 30
                bullish_reasons.append("trend is strongly bullish")
            if twenty_day >= 5:
                bullish_points += 20
                bullish_reasons.append(f"20-day return is {twenty_day:.1f}%")
            if rel_spy >= 3:
                bullish_points += 20
                bullish_reasons.append(f"outperforming SPY by {rel_spy:.1f}% over 20 days")
            if pattern["score"] >= 75:
                bullish_points += 20
                bullish_reasons.append(pattern["patterns"][0])
            if price > ma20 > ma50:
                bullish_points += 10
                bullish_reasons.append("price is above rising short-term support")

            bearish_points = 0
            bearish_reasons = []
            if trend <= 20:
                bearish_points += 25
                bearish_reasons.append("trend is weak")
            if twenty_day <= -5:
                bearish_points += 25
                bearish_reasons.append(f"20-day return is {twenty_day:.1f}%")
            if rel_spy <= -3:
                bearish_points += 20
                bearish_reasons.append(f"underperforming SPY by {abs(rel_spy):.1f}% over 20 days")
            if price < ma20 < ma50:
                bearish_points += 15
                bearish_reasons.append("price is below declining short-term support")
            if price < prior_20_low:
                bearish_points += 15
                bearish_reasons.append("price is breaking below a 20-day range")

            if bullish_points >= 75 or bearish_points >= 75:
                signal_type = "BULL" if bullish_points >= bearish_points else "BEAR"
                score = bullish_points if signal_type == "BULL" else bearish_points
                reasons = bullish_reasons if signal_type == "BULL" else bearish_reasons
                signal = {
                    "sector": SECTOR_LABELS.get(etf, etf),
                    "etf": etf,
                    "signal": signal_type,
                    "score": min(100.0, float(score)),
                    "five_day": five_day,
                    "twenty_day": twenty_day,
                    "relative_to_spy": rel_spy,
                    "reason": "; ".join(reasons[:3]) + ".",
                }
                signals.append(signal)
                log_event("sector_extreme_signal", **signal)
        except Exception as exc:
            log_event("sector_extreme_failed", etf=etf, error=str(exc))

    return sorted(signals, key=lambda x: x["score"], reverse=True)[:5]


def reddit_related_plays() -> list[dict]:
    posts = fetch_reddit_posts()
    candidates = extract_reddit_candidates(posts, universe=set(UNIVERSE), limit=12)
    plays = analyze_reddit_plays(candidates, limit=10)
    plays = [play for play in plays if play.get("score", 0) >= 35][:5]
    log_event(
        "reddit_related_plays",
        candidate_count=len(candidates),
        play_count=len(plays),
        tickers=[play["ticker"] for play in plays],
    )
    return plays


def quality_liquidity_filter(ticker: str, df) -> tuple[bool, dict]:
    include_high_risk = os.getenv("INCLUDE_HIGH_RISK_MICROCAPS", "false").lower() == "true"
    if df.empty or len(df) < 120:
        return False, {"reason": "not enough price history", "liquidity_score": 0.0}

    price = float(df["Close"].iloc[-1])
    avg_volume = float(df["Volume"].tail(30).mean())
    min_price = env_float("MIN_STOCK_PRICE", MIN_PRICE)
    min_volume = env_float("MIN_AVG_DAILY_VOLUME", MIN_AVG_DAILY_VOLUME)
    price_ok = price > min_price
    volume_ok = avg_volume > min_volume
    extreme_penny = price < 2 or avg_volume < 150_000
    passed = (price_ok and volume_ok and not extreme_penny) or include_high_risk
    price_score = min(100.0, max(0.0, price / min_price * 50)) if min_price > 0 else 50.0
    volume_score = min(100.0, max(0.0, avg_volume / min_volume * 50)) if min_volume > 0 else 50.0
    liquidity_score = price_score * 0.35 + volume_score * 0.65
    reason = "passed quality/liquidity filter" if passed else f"filtered: price ${price:.2f}, avg volume {avg_volume:.0f}"
    return passed, {
        "price": price,
        "avg_daily_volume": avg_volume,
        "liquidity_score": liquidity_score,
        "passed_quality_filter": passed,
        "quality_filter_reason": reason,
    }


def env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return float(default)
    try:
        return float(raw)
    except (TypeError, ValueError):
        log_event("invalid_float_env", name=name, value=raw, default=default)
        return float(default)


def analyze_universe(base_weights: dict[str, float] | None = None):
    spy_df = get_history("SPY")
    qqq_df = get_history("QQQ")
    sector_cache = {}
    universe_price_data = {}
    stage2_rows = []
    missing_api_warnings = [name for name in OPTIONAL_API_ENVS if not os.getenv(name)]
    cfg = universe_config()
    try:
        universe_summary = build_daily_universe(cfg)
        candidate_universe = universe_summary.get("stage1_quality_universe") or UNIVERSE
    except Exception as exc:
        log_event("universe_builder_failed", error=str(exc), fallback_count=len(UNIVERSE))
        universe_summary = {
            "raw_universe": list(UNIVERSE),
            "filtered_universe": list(UNIVERSE),
            "stage1_quality_universe": list(UNIVERSE),
            "stage2_opportunity_candidates": [],
            "stage3_deep_analysis_candidates": [],
            "final_top_10": [],
            "sources_used": {"manual_seed_fallback": len(UNIVERSE)},
            "removed": {},
            "errors": [{"source": "universe_builder", "error": str(exc)}],
        }
        candidate_universe = UNIVERSE

    log_event(
        "universe_stage1_ready",
        raw_count=len(universe_summary.get("raw_universe", [])),
        filtered_count=len(universe_summary.get("filtered_universe", [])),
        stage1_count=len(candidate_universe),
        sources_used=universe_summary.get("sources_used", {}),
        removed=universe_summary.get("removed", {}),
    )

    for ticker in candidate_universe:
        try:
            df = get_history(ticker)
            universe_price_data[ticker] = df
            passed_quality, quality_details = quality_liquidity_filter(ticker, df)
            if not passed_quality:
                log_event("quality_filter_excluded", ticker=ticker, **quality_details)
                continue

            sector_ticker = SECTOR_ETF_MAP.get(ticker, "SPY")
            if sector_ticker not in sector_cache:
                sector_cache[sector_ticker] = get_history(sector_ticker)
            sector_df = sector_cache[sector_ticker]

            opening = opening_activity_score(ticker)
            patterns = pattern_trading_score(df)
            volume = volume_accumulation_score(ticker, df)
            volatility = volatility_setup_score(ticker, df)
            etf_flow = etf_flow_exposure_score(ticker, sector_ticker, sector_df)
            log_event("opening_activity_score", ticker=ticker, **opening)
            log_event("pattern_trading_score", ticker=ticker, **patterns)
            log_event("volume_accumulation_score", ticker=ticker, **volume)
            log_event("volatility_setup_score", ticker=ticker, **volatility)
            log_event("etf_flow_exposure_score", ticker=ticker, **etf_flow)

            features = {
                "trend": trend_score(df),
                "relative_strength": relative_strength_score(df, spy_df, qqq_df),
                "sector_strength": sector_strength_score(sector_df, spy_df),
                "breakout": breakout_score(df),
                "news_catalyst": 0.0,
                "news_sentiment": 50.0,
                "political_geo": 0.0,
                "politician_trade": 0.0,
                "risk_quality": risk_quality_score(df),
                "opening_activity": opening["score"],
                "earnings": 50.0,
                "earnings_quality": 50.0,
                "options_flow": 50.0,
                "institutional_ownership": 50.0,
                "pattern_trading": patterns["score"],
                "earnings_proximity": 0.0,
                "analyst_revisions": 50.0,
                "fundamental_momentum": 50.0,
                "volume_accumulation": volume["score"],
                "short_squeeze": 50.0,
                "insider_buying": 50.0,
                "volatility_setup": volatility["score"],
                "etf_flow_exposure": etf_flow["score"],
                "liquidity_score": quality_details["liquidity_score"],
            }

            row = {
                "ticker": ticker,
                "days_to_earnings": None,
                "catalysts": [],
                "headlines": [],
                "has_catalyst": False,
                "political_reasons": [],
                "politician_reasons": [],
                "opening_details": opening,
                "earnings_details": {},
                "options_details": {},
                "institutional_details": {},
                "pattern_details": patterns,
                "analyst_details": {},
                "fundamental_details": {},
                "volume_details": volume,
                "short_squeeze_details": {},
                "insider_details": {},
                "volatility_details": volatility,
                "etf_flow_details": etf_flow,
                "sentiment_confidence": 0.0,
                "sentiment_reasoning": "Gemini overnight sentiment not evaluated before deep-analysis filtering.",
                "data_freshness": datetime.now(ZoneInfo("America/Los_Angeles")).isoformat(),
                "missing_data_warning": ", ".join(missing_api_warnings) if missing_api_warnings else "",
                **quality_details,
                **features,
            }
            row["score"] = staged_final_score(row, weights=base_weights)
            row["earnings_score"] = earnings_setup_score(row)
            row["catalyst_watch_score"] = catalyst_watch_score(row)
            stage2_rows.append(row)
            log_event(
                "stage2_candidate_score",
                ticker=ticker,
                score=row["score"],
                opening=row["opening_activity"],
                trend=row["trend"],
                relative_strength=row["relative_strength"],
                sector_strength=row["sector_strength"],
                breakout=row["breakout"],
                pattern=row["pattern_trading"],
                opportunity=row["opportunity_score"],
                quality=row["quality_score"],
            )
        except Exception as exc:
            log_event("ticker_failed", ticker=ticker, error=str(exc))
            continue

    stage2_ranked = sorted(stage2_rows, key=lambda x: x["score"], reverse=True)[: cfg.target_stage2_size]
    update_universe_stages(universe_summary, stage2=[r["ticker"] for r in stage2_ranked])
    log_event(
        "stage2_opportunity_candidates",
        count=len(stage2_ranked),
        target=cfg.target_stage2_size,
        tickers=[r["ticker"] for r in stage2_ranked],
    )

    stage3_rows = []
    for row in stage2_ranked:
        ticker = row["ticker"]
        try:
            headlines = get_recent_headlines(ticker)
            news_score, catalysts, has_catalyst = news_catalyst_score(ticker)
            pg_score, pg_reasons = political_geo_score(ticker, headlines)
            pol_score, pol_reasons = politician_trade_score(ticker)
            earnings = earnings_score(ticker)
            options = options_flow_score(ticker)
            institutional = institutional_change_score(ticker)
            analyst = analyst_revision_score(ticker)
            fundamentals = fundamental_momentum_score(ticker)
            squeeze = short_squeeze_score(ticker)
            insider = insider_buying_score(ticker)

            row.update({
                "headlines": headlines,
                "news_catalyst": news_score,
                "news_sentiment": max(0.0, min(100.0, 50.0 + news_score / 2)),
                "catalysts": catalysts,
                "has_catalyst": has_catalyst,
                "political_geo": pg_score,
                "politician_trade": pol_score,
                "political_reasons": pg_reasons,
                "politician_reasons": pol_reasons,
                "days_to_earnings": earnings.get("days_to_earnings"),
                "earnings": earnings["score"],
                "earnings_quality": earnings["score"],
                "earnings_proximity": earnings_proximity_score(earnings.get("days_to_earnings")),
                "options_flow": options["score"],
                "institutional_ownership": institutional["score"],
                "analyst_revisions": signed_to_percent(analyst["score"]),
                "fundamental_momentum": signed_to_percent(fundamentals["score"]),
                "short_squeeze": squeeze["score"],
                "insider_buying": signed_to_percent(insider["score"]),
                "earnings_details": earnings,
                "options_details": options,
                "institutional_details": institutional,
                "analyst_details": analyst,
                "fundamental_details": fundamentals,
                "short_squeeze_details": squeeze,
                "insider_details": insider,
            })
            row["score"] = staged_final_score(row, weights=base_weights)
            row["earnings_score"] = earnings_setup_score(row)
            row["catalyst_watch_score"] = catalyst_watch_score(row)
            stage3_rows.append(row)

            log_event("earnings_score", ticker=ticker, **earnings)
            log_event("options_score", ticker=ticker, **options)
            log_event("institutional_score", ticker=ticker, **institutional)
            log_event("analyst_revision_score", ticker=ticker, **analyst)
            log_event("fundamental_momentum_score", ticker=ticker, **fundamentals)
            log_event("short_squeeze_score", ticker=ticker, **squeeze)
            log_event("insider_buying_score", ticker=ticker, **insider)
            log_event(
                "stage3_candidate_score",
                ticker=ticker,
                score=row["score"],
                options=row["options_flow"],
                earnings=row["earnings"],
                analyst=row["analyst_revisions"],
                institutional=row["institutional_ownership"],
                catalyst=row["catalyst_score"],
            )
        except Exception as exc:
            log_event("stage3_ticker_failed", ticker=ticker, error=str(exc))
            stage3_rows.append(row)
            continue

    preliminary = sorted(stage3_rows, key=lambda x: x["score"], reverse=True)
    top_20 = preliminary[: cfg.target_deep_analysis_size]
    update_universe_stages(universe_summary, stage3=[r["ticker"] for r in top_20])
    log_event("top_20_candidates", count=len(top_20), tickers=[r["ticker"] for r in top_20])

    finnhub_client = get_finnhub_client()
    for row in top_20:
        try:
            finnhub_headlines = finnhub_client.overnight_headlines(row["ticker"])
            if finnhub_headlines:
                row["headlines"] = finnhub_headlines
            log_event(
                "finnhub_news_enrichment",
                ticker=row["ticker"],
                headline_count=len(finnhub_headlines),
                calls_made=finnhub_client.calls_made,
                max_calls_per_minute=finnhub_client.max_calls_per_minute,
            )
        except Exception as exc:
            log_event("finnhub_news_enrichment_failed", ticker=row["ticker"], error=str(exc))

    sentiment_results = score_overnight_sentiments(top_20)
    log_event("gemini_sentiment_batch", tickers=list(sentiment_results.keys()), calls_made=1)
    for row in top_20:
        sentiment = sentiment_results.get(row["ticker"], {
            "sentiment": 50.0,
            "confidence": 0.0,
            "reasoning": "Gemini sentiment result missing; sentiment score neutral.",
        })
        row["news_sentiment"] = sentiment["sentiment"]
        row["sentiment_confidence"] = sentiment["confidence"]
        row["sentiment_reasoning"] = sentiment["reasoning"]
        log_event("sentiment_score", ticker=row["ticker"], **sentiment)

    breadth = market_breadth_regime(universe_price_data)
    regime = classify_market_regime(breadth)
    weights = regime_adjusted_weights(str(regime["regime"]), base_weights)
    reddit_plays = reddit_related_plays()
    reddit_by_ticker = {play["ticker"]: play for play in reddit_plays}
    blend_reddit = os.getenv("BLEND_REDDIT_IN_MAIN_SCORE", "false").lower() == "true"
    log_event("market_breadth", **breadth)
    log_event("regime", **regime, learned_base_weights=base_weights, weights=weights)

    for row in top_20:
        row["regime"] = regime["regime"]
        row["regime_confidence"] = regime["confidence"]
        row["market_breadth_regime"] = breadth["regime"]
        row["market_breadth_score"] = breadth["breadth_score"]
        row["score"] = staged_final_score(row, regime, breadth, weights)
        row["score"] = apply_reddit_blend(row["score"], row, reddit_by_ticker, blend_reddit)
        row["earnings_score"] = earnings_setup_score(row)
        row["catalyst_watch_score"] = catalyst_watch_score(row)
        row["top_drivers"] = top_drivers(row)
        row["top_risks"] = top_risks(row)

    final_results = sorted(top_20, key=lambda x: x["score"], reverse=True)
    update_universe_stages(universe_summary, final_top_10=[r["ticker"] for r in final_results[:TOP_N]])
    log_event("final_top_10", tickers=[r["ticker"] for r in final_results[:TOP_N]])
    sectors = sector_extreme_signals(spy_df, qqq_df)
    return final_results, spy_df, qqq_df, regime, sectors, reddit_plays, universe_summary


def html_table(title, rows, reason_mode="normal"):
    html = f"""
    <h2 style="margin-top:28px;border-bottom:2px solid #222;padding-bottom:6px;">{title}</h2>
    <table width="100%" cellpadding="8" cellspacing="0" style="border-collapse:collapse;font-family:Arial,sans-serif;font-size:14px;">
      <tr style="background:#f2f2f2;">
        <th align="left" style="border:1px solid #ddd;">Ticker</th>
        <th align="right" style="border:1px solid #ddd;">Opening</th>
        <th align="left" style="border:1px solid #ddd;">Reason</th>
      </tr>
    """
    if not rows:
        html += '<tr><td colspan="3" style="border:1px solid #ddd;">No matching setups today.</td></tr>'

    for r in rows:
        ticker_cell = f"<b>{r['ticker']}</b><br><span style='color:#666;'>${r['price']:.2f}</span>"
        reason = escape(upside_reason(r, reason_mode))

        html += f"""
        <tr>
          <td style="border:1px solid #ddd;vertical-align:top;width:18%;">{ticker_cell}</td>
          <td align="right" style="border:1px solid #ddd;vertical-align:top;width:12%;">{r.get('opening_activity', 0):.0f}</td>
          <td style="border:1px solid #ddd;vertical-align:top;">{reason}</td>
        </tr>
        """
    html += "</table>"
    return html


def html_top10_table(rows):
    html = """
    <h2 style="margin-top:28px;border-bottom:2px solid #222;padding-bottom:6px;">Top 10 Stocks</h2>
    <table width="100%" cellpadding="8" cellspacing="0" style="border-collapse:collapse;font-family:Arial,sans-serif;font-size:14px;">
      <tr style="background:#f2f2f2;">
        <th align="left" style="border:1px solid #ddd;">Ticker</th>
        <th align="right" style="border:1px solid #ddd;">Score</th>
        <th align="right" style="border:1px solid #ddd;">Opportunity</th>
        <th align="right" style="border:1px solid #ddd;">Catalyst</th>
        <th align="right" style="border:1px solid #ddd;">Quality</th>
        <th align="left" style="border:1px solid #ddd;">Drivers / Risks</th>
      </tr>
    """
    if not rows:
        html += '<tr><td colspan="6" style="border:1px solid #ddd;">No matching setups today.</td></tr>'

    for row in rows:
        drivers = "<br>".join(escape(item) for item in row.get("top_drivers", top_drivers(row))[:3])
        risks = "<br>".join(escape(item) for item in row.get("top_risks", top_risks(row))[:2])
        warning = escape(row.get("missing_data_warning", "") or "none")
        freshness = escape(str(row.get("data_freshness", ""))[:19])
        html += f"""
        <tr>
          <td style="border:1px solid #ddd;vertical-align:top;"><b>{escape(row["ticker"])}</b><br><span style="color:#666;">${row["price"]:.2f}</span></td>
          <td align="right" style="border:1px solid #ddd;vertical-align:top;">{row.get("score", 0):.0f}</td>
          <td align="right" style="border:1px solid #ddd;vertical-align:top;">{row.get("opportunity_score", 0):.0f}</td>
          <td align="right" style="border:1px solid #ddd;vertical-align:top;">{row.get("catalyst_score", 0):.0f}</td>
          <td align="right" style="border:1px solid #ddd;vertical-align:top;">{row.get("quality_score", 0):.0f}</td>
          <td style="border:1px solid #ddd;vertical-align:top;">
            <b>Drivers</b><br>{drivers}<br>
            <b>Risks</b><br>{risks}<br>
            <span style="color:#666;">Freshness: {freshness}</span><br>
            <span style="color:#999;">Missing data: {warning}</span>
          </td>
        </tr>
        """
    html += "</table>"
    return html


def html_sector_extremes(rows):
    html = """
    <h2 style="margin-top:28px;border-bottom:2px solid #222;padding-bottom:6px;">Extreme Sector Signals</h2>
    <table width="100%" cellpadding="8" cellspacing="0" style="border-collapse:collapse;font-family:Arial,sans-serif;font-size:14px;">
      <tr style="background:#f2f2f2;">
        <th align="left" style="border:1px solid #ddd;">Sector</th>
        <th align="left" style="border:1px solid #ddd;">Signal</th>
        <th align="right" style="border:1px solid #ddd;">Strength</th>
        <th align="left" style="border:1px solid #ddd;">Reason</th>
      </tr>
    """
    if not rows:
        html += '<tr><td colspan="4" style="border:1px solid #ddd;">No extreme sector bull or bear signal today.</td></tr>'

    for row in rows:
        html += f"""
        <tr>
          <td style="border:1px solid #ddd;vertical-align:top;"><b>{escape(row["sector"])}</b><br><span style="color:#666;">{row["etf"]}</span></td>
          <td style="border:1px solid #ddd;vertical-align:top;">{row["signal"]}</td>
          <td align="right" style="border:1px solid #ddd;vertical-align:top;">{row["score"]:.0f}</td>
          <td style="border:1px solid #ddd;vertical-align:top;">{escape(row["reason"])}</td>
        </tr>
        """
    html += "</table>"
    return html


def html_reddit_plays(rows):
    html = """
    <h2 style="margin-top:28px;border-bottom:2px solid #222;padding-bottom:6px;">Reddit Related Stocks</h2>
    <table width="100%" cellpadding="8" cellspacing="0" style="border-collapse:collapse;font-family:Arial,sans-serif;font-size:14px;">
      <tr style="background:#f2f2f2;">
        <th align="left" style="border:1px solid #ddd;">Ticker</th>
        <th align="left" style="border:1px solid #ddd;">Signal</th>
        <th align="right" style="border:1px solid #ddd;">Strength</th>
        <th align="left" style="border:1px solid #ddd;">Reason</th>
      </tr>
    """
    if not rows:
        html += '<tr><td colspan="4" style="border:1px solid #ddd;">No strong Reddit-related stock plays today.</td></tr>'

    for row in rows:
        subreddits = ", ".join(row.get("subreddits", [])[:3])
        context = f"<br><span style='color:#666;'>{escape(subreddits)}</span>" if subreddits else ""
        html += f"""
        <tr>
          <td style="border:1px solid #ddd;vertical-align:top;"><b>{escape(row["ticker"])}</b>{context}</td>
          <td style="border:1px solid #ddd;vertical-align:top;">{escape(row.get("signal", "MIXED"))}</td>
          <td align="right" style="border:1px solid #ddd;vertical-align:top;">{float(row.get("score", 0)):.0f}</td>
          <td style="border:1px solid #ddd;vertical-align:top;">{escape(row.get("reasoning", ""))}</td>
        </tr>
        """
    html += "</table>"
    return html


def html_universe_summary(summary):
    summary = summary or {}
    sources = summary.get("sources_used", {})
    removed = summary.get("removed", {})
    html = """
    <h2 style="margin-top:28px;border-bottom:2px solid #222;padding-bottom:6px;">Universe Summary</h2>
    <table width="100%" cellpadding="8" cellspacing="0" style="border-collapse:collapse;font-family:Arial,sans-serif;font-size:14px;">
      <tr style="background:#f2f2f2;">
        <th align="left" style="border:1px solid #ddd;">Stage</th>
        <th align="right" style="border:1px solid #ddd;">Count</th>
        <th align="left" style="border:1px solid #ddd;">Details</th>
      </tr>
    """
    rows = [
        ("Raw universe", len(summary.get("raw_universe", [])), ", ".join(f"{escape(str(k))}: {v}" for k, v in sources.items()) or "manual seed only"),
        ("Quality universe", len(summary.get("stage1_quality_universe", [])), ", ".join(f"{escape(str(k))}: {v}" for k, v in removed.items() if v) or "no removals recorded"),
        ("Opportunity candidates", len(summary.get("stage2_opportunity_candidates", [])), ", ".join(summary.get("stage2_opportunity_candidates", [])[:12])),
        ("Deep analysis candidates", len(summary.get("stage3_deep_analysis_candidates", [])), ", ".join(summary.get("stage3_deep_analysis_candidates", [])[:12])),
        ("Final top 10", len(summary.get("final_top_10", [])), ", ".join(summary.get("final_top_10", []))),
    ]
    for label, count, details in rows:
        html += f"""
        <tr>
          <td style="border:1px solid #ddd;vertical-align:top;"><b>{label}</b></td>
          <td align="right" style="border:1px solid #ddd;vertical-align:top;">{count}</td>
          <td style="border:1px solid #ddd;vertical-align:top;">{escape(str(details))}</td>
        </tr>
        """
    if summary.get("errors"):
        html += f"""
        <tr>
          <td style="border:1px solid #ddd;vertical-align:top;"><b>Warnings</b></td>
          <td align="right" style="border:1px solid #ddd;vertical-align:top;">{len(summary.get("errors", []))}</td>
          <td style="border:1px solid #ddd;vertical-align:top;">Some universe sources or lookups failed and were skipped; processing continued.</td>
        </tr>
        """
    html += "</table>"
    return html


def universe_summary_text(summary):
    summary = summary or {}
    lines = [
        "Universe Summary",
        f"Raw universe: {len(summary.get('raw_universe', []))}",
        f"Quality universe: {len(summary.get('stage1_quality_universe', []))}",
        f"Opportunity candidates: {len(summary.get('stage2_opportunity_candidates', []))}",
        f"Deep analysis candidates: {len(summary.get('stage3_deep_analysis_candidates', []))}",
        f"Final top 10: {', '.join(summary.get('final_top_10', []))}",
        f"Sources: {summary.get('sources_used', {})}",
        f"Removed: {summary.get('removed', {})}",
        f"Warnings: {len(summary.get('errors', []))}",
    ]
    return "\n".join(lines) + "\n"


def build_email(results, spy_df, qqq_df, regime, sector_extremes, reddit_plays, universe_summary=None):
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

      {html_sector_extremes(sector_extremes)}
      {html_reddit_plays(reddit_plays)}
      {html_universe_summary(universe_summary)}
      {html_top10_table(top_10)}
      {html_table("Top 5 Under $30", under_30)}
      {html_table("Top 5 Earnings Setups", earnings, reason_mode="earnings")}
      {html_table("Catalyst Watch", catalyst_watch, reason_mode="catalyst")}
      {html_table("Political / Geopolitical Watch", political_watch, reason_mode="political")}

      <p style="color:#777;font-size:12px;margin-top:28px;">
        Not financial advice. For research only. Verify data before trading.
        Congressional trade disclosures can be delayed, so politician-trade signals are secondary indicators.
      </p>
    </body>
    </html>
    """

    text = "Daily Stock Alpha Report\n\n"
    text += universe_summary_text(universe_summary)
    text += "\nExtreme Sector Signals\n"
    if sector_extremes:
        for sector in sector_extremes:
            text += (
                f"{sector['sector']} ({sector['etf']}) | {sector['signal']} | Strength {sector['score']:.0f}\n"
                f"Reason: {sector['reason']}\n"
            )
    else:
        text += "No extreme sector bull or bear signal today.\n"

    text += "\nReddit Related Stocks\n"
    if reddit_plays:
        for play in reddit_plays:
            text += (
                f"{play['ticker']} | {play.get('signal', 'MIXED')} | Strength {float(play.get('score', 0)):.0f}\n"
                f"Reason: {play.get('reasoning', '')}\n"
            )
    else:
        text += "No strong Reddit-related stock plays today.\n"

    text += "\nTop 10 Stocks\n"
    for r in top_10:
        text += (
            f"{r['ticker']} | Score {r.get('score', 0):.0f} | Opportunity {r.get('opportunity_score', 0):.0f} | "
            f"Catalyst {r.get('catalyst_score', 0):.0f} | Quality {r.get('quality_score', 0):.0f}\n"
            f"Drivers: {', '.join(r.get('top_drivers', top_drivers(r))[:3])}\n"
            f"Risks: {', '.join(r.get('top_risks', top_risks(r))[:2])}\n"
            f"Freshness: {str(r.get('data_freshness', ''))[:19]} | Missing data: {r.get('missing_data_warning') or 'none'}\n"
        )

    sections = [
        ("Top 5 Under $30", under_30, "normal"),
        ("Top 5 Earnings Setups", earnings, "earnings"),
        ("Catalyst Watch", catalyst_watch, "catalyst"),
        ("Political / Geopolitical Watch", political_watch, "political"),
    ]
    for title, rows, mode in sections:
        text += f"\n{title}\n"
        for r in rows:
            text += (
                f"{r['ticker']} | Opening {r.get('opening_activity', 0):.0f}\n"
                f"Reason: {upside_reason(r, mode)}\n"
            )

    return html, text, top_10


def main():
    learned_weights = refresh_learning_state()
    log_event("learned_weights", weights=learned_weights)
    results, spy_df, qqq_df, regime, sector_extremes, reddit_plays, universe_summary = analyze_universe(learned_weights)
    html, text, top_10 = build_email(results, spy_df, qqq_df, regime, sector_extremes, reddit_plays, universe_summary)

    print(text)
    log_predictions(top_10)
    send_email("Daily Stock Alpha Report", html, text)


if __name__ == "__main__":
    main()
