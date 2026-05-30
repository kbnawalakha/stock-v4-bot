# Stock V4 Bot

Daily stock signal research bot that runs on GitHub Actions and emails a report.

Features:
- Multi-strategy ensemble model
- Strategy comparison vs SPY and QQQ
- Email report
- Daily prediction logging
- Optional Alpaca paper-trading support, disabled by default

Required GitHub Secrets:
- EMAIL_USER
- EMAIL_PASS
- EMAIL_TO

For Gmail, EMAIL_PASS must be a Google App Password.

Optional:
- ALPACA_KEY
- ALPACA_SECRET
- ALPACA_BASE_URL=https://paper-api.alpaca.markets
- ENABLE_PAPER_TRADING=false
