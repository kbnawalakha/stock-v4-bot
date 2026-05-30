# Stock V4 Bot - Catalyst + Politics Edition

Daily stock signal bot with clean email tables.

Email sections:
- Top 10 Stocks
- Top 5 Under $30
- Top 5 Earnings Setups
- Catalyst Watch
- Political / Geopolitical Watch

Required GitHub Secrets:
- EMAIL_USER
- EMAIL_PASS
- EMAIL_TO

Optional:
- POLITICIAN_TRADE_API_URL
- POLITICIAN_TRADE_API_KEY

The politician-trade module has safe fallback behavior. If no API is configured, it still checks public web sources and keyword-based geopolitical catalysts.
