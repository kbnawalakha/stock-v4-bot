import os
import requests


def paper_buy(ticker: str, qty: int) -> dict:
    enabled = os.getenv("ENABLE_PAPER_TRADING", "false").lower() == "true"

    if not enabled:
        print(f"Paper trade skipped for {ticker}: ENABLE_PAPER_TRADING is not true.")
        return {"skipped": True, "reason": "paper_trading_disabled"}

    base = os.getenv("ALPACA_BASE_URL")
    key = os.getenv("ALPACA_KEY")
    secret = os.getenv("ALPACA_SECRET")

    if not base or not key or not secret:
        print(f"Paper trade skipped for {ticker}: Alpaca credentials missing.")
        return {"skipped": True, "reason": "missing_credentials"}

    if qty <= 0:
        return {"skipped": True, "reason": "qty_zero"}

    headers = {
        "APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": secret,
    }

    payload = {
        "symbol": ticker,
        "qty": qty,
        "side": "buy",
        "type": "market",
        "time_in_force": "day",
    }

    response = requests.post(f"{base}/v2/orders", json=payload, headers=headers, timeout=20)
    print(f"Alpaca order response for {ticker}: {response.status_code}")
    try:
        return response.json()
    except Exception:
        return {"status_code": response.status_code, "text": response.text}
