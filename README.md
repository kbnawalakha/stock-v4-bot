# Stock V4 Bot

Daily GitHub Actions stock signal bot.

Features:
- Multi-strategy ensemble model
- Strategy comparison vs SPY and QQQ
- Email report
- Optional Alpaca paper-trading hooks
- Daily 7 AM PT workflow

## Setup

1. Push this repo to GitHub.
2. Add GitHub Actions secrets:
   - EMAIL_USER
   - EMAIL_PASS
   - EMAIL_TO
   - ALPACA_KEY optional
   - ALPACA_SECRET optional
   - ALPACA_BASE_URL optional, use https://paper-api.alpaca.markets
3. Go to Actions and run the workflow manually once.
