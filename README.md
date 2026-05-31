# Stock V4.2 Bot - Multi-Signal Catalyst Edition

Daily stock signal bot with regime-aware ranking, overnight Gemini sentiment,
opening activity, options flow, earnings, catalyst, institutional ownership,
institutional ownership change, analyst revisions, fundamentals momentum,
volume accumulation, insider buying, short squeeze potential, volatility setup,
ETF flow exposure proxy, daily/weekly trading patterns, Reddit watchlists, and political/geopolitical signals.
The bot stores recommendations in `predictions.csv`, evaluates prior picks against
SPY, and updates `learning_state.json` so signal weights can adapt over time.

Email sections:
- Top 10 Stocks
- Top 5 Under $30
- Top 5 Earnings Setups
- Reddit Related Stocks
- Catalyst Watch
- Political / Geopolitical Watch

GitHub Actions sends reports on weekday mornings at 7:05 AM Pacific during
daylight time and on Sunday at 10:00 PM Pacific during daylight time.

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
- MIN_STOCK_PRICE defaults to 5
- MIN_AVG_DAILY_VOLUME defaults to 500000
- GEMINI_MODEL defaults to gemini-2.5-flash
- GEMINI_TIMEOUT_SECONDS defaults to 120
- GEMINI_MAX_ATTEMPTS defaults to 2
- GEMINI_BATCH_SIZE defaults to 5
- GEMINI_REDDIT_BATCH_SIZE defaults to 5

The ranking funnel is:
1. Quality/liquidity filter
2. Opportunity score from technical, opening, volume, volatility, and options signals
3. Catalyst score from news, analyst, earnings, insider, squeeze, and political signals
4. Quality score from risk, fundamentals, institutional, pattern, and liquidity inputs

The politician-trade module has safe fallback behavior. If no API is configured, it checks the free Capitol Trades public site and keyword-based geopolitical catalysts.
Not financial advice. For research only. Verify data before trading.
