import json
from pathlib import Path

PORTFOLIO_FILE = Path("portfolio.json")


def load_portfolio() -> dict:
    if not PORTFOLIO_FILE.exists():
        return {"cash": 100000, "positions": {}}
    try:
        return json.loads(PORTFOLIO_FILE.read_text())
    except Exception:
        return {"cash": 100000, "positions": {}}
