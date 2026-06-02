# Stock V4.2 Bot - Multi-Signal Catalyst Edition

Daily stock signal bot with regime-aware ranking, overnight Gemini sentiment,
pre-market activity, post-market activity, opening activity, swing setup quality, options flow, earnings, catalyst, institutional ownership,
institutional ownership change, analyst revisions, fundamentals momentum,
volume accumulation, insider buying, short squeeze potential, volatility setup,
ETF flow exposure proxy, daily/weekly trading patterns, Reddit watchlists, and political/geopolitical signals.
The bot stores recommendations in `predictions.csv`, evaluates prior picks against
SPY, and updates `learning_state.json` so signal weights can adapt over time.

Email sections:
- Universe Summary
- Recommendations
- Strong Bear Cases
- Top 5 Under $30
- Top 5 Earnings Setups
- Reddit Related Stocks
- Catalyst Watch
- Swing Recommendations
- Political / Geopolitical Watch

GitHub Actions sends reports on weekday mornings at 7:15 AM Pacific and on
Sunday at 10:00 PM Pacific, using a Pacific-time guard for daylight-saving shifts.

Required GitHub Secrets:
- GEMINI_API_KEY
- FINNHUB_API_KEY
- EMAIL_USER
- EMAIL_PASS
- EMAIL_TO, one or more recipients separated by commas or semicolons

Optional:
- FMP_API_KEY enables analyst revisions, FMP fundamentals, and insider fallback data
- ALPHA_VANTAGE_API_KEY enables insider transactions and optional earnings/fundamental data
- SEC_USER_AGENT enables SEC EDGAR public API checks; use a real contact string
- POLITICIAN_TRADE_API_URL
- POLITICIAN_TRADE_API_KEY
- FINNHUB_MAX_CALLS_PER_MINUTE defaults to 60
- CAPITOLTRADES_BASE_URL overrides the Capitol Trades public source URL
- REDDIT_SUBREDDITS overrides the default subreddit list
- REDDIT_POST_LIMIT defaults to 30 posts per subreddit
- BLEND_REDDIT_IN_MAIN_SCORE defaults to false and caps Reddit impact at 5 points
- INCLUDE_HIGH_RISK_MICROCAPS defaults to false
- USE_DYNAMIC_UNIVERSE defaults to true
- MAX_RAW_UNIVERSE_SIZE defaults to 2000
- TARGET_STAGE1_SIZE defaults to 500
- TARGET_STAGE2_SIZE defaults to 100
- TARGET_DEEP_ANALYSIS_SIZE defaults to 20
- HIGH_MOMENTUM_SCAN_LIMIT defaults to 300
- MIN_RECOMMENDATION_CONFIDENCE defaults to 55
- MAX_RECOMMENDATIONS defaults to 15
- MIN_STOCK_PRICE defaults to 10
- MIN_PRICE defaults to 10 for the dynamic universe quality filter
- MIN_AVG_DAILY_VOLUME defaults to 500000
- MIN_MARKET_CAP defaults to 1000000000
- INCLUDE_MICROCAPS defaults to false
- INCLUDE_REDDIT_IN_UNIVERSE defaults to true
- INCLUDE_ETF_HOLDINGS defaults to true
- INCLUDE_RUSSELL_3000 defaults to true
- INCLUDE_SP500 defaults to true
- INCLUDE_NASDAQ_100 defaults to true
- GEMINI_MODEL defaults to gemini-2.5-flash
- GEMINI_TIMEOUT_SECONDS defaults to 120
- GEMINI_MAX_ATTEMPTS defaults to 2
- GEMINI_BATCH_SIZE defaults to 5
- GEMINI_REDDIT_BATCH_SIZE defaults to 5

The ranking funnel is:
1. Dynamic universe from manual seed, indexes, ETF holdings, Reddit, earnings, and momentum sources
2. Quality/liquidity filter
3. Stage 2 opportunity score from technical, swing setup quality, pre-market, post-market, opening, volume, volatility, ETF flow, and pattern signals
4. Stage 3 medium-depth score from options, earnings, analyst, insider, institutional, squeeze, and political signals
5. Stage 4 deep analysis using Finnhub overnight news and Gemini sentiment on the final deep-analysis candidates
6. Market-regime weight adjustment, confidence filtering, and dynamic recommendation count

Swing setup scoring includes pullback buys, moving-average crossover confirmation, support/resistance bounces,
volume-confirmed breakouts, Fibonacci retracement zones, anchored-VWAP-style pullbacks, and earnings-momentum style continuation.

The politician-trade module has safe fallback behavior. If no API is configured, it checks the free Capitol Trades public site and keyword-based geopolitical catalysts.
Not financial advice. For research only. Verify data before trading.
