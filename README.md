# Stock V4.1 Bot - Catalyst + Politics Edition

Daily stock signal bot with regime-aware ranking, overnight OpenAI sentiment,
opening activity, options flow, earnings, catalyst, and political/geopolitical signals.

Email sections:
- Top 10 Stocks
- Top 5 Under $30
- Top 5 Earnings Setups
- Catalyst Watch
- Political / Geopolitical Watch

GitHub Actions sends reports on weekday mornings at 7:05 AM Pacific during
daylight time and on Sunday at 10:00 PM Pacific during daylight time.

Required GitHub Secrets:
- OPENAI_API_KEY
- FINNHUB_API_KEY
- EMAIL_USER
- EMAIL_PASS
- EMAIL_TO

Optional:
- POLITICIAN_TRADE_API_URL
- POLITICIAN_TRADE_API_KEY

The politician-trade module has safe fallback behavior. If no API is configured, it still checks public web sources and keyword-based geopolitical catalysts.
