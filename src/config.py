UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AMD", "AMZN", "META", "TSLA", "AVGO", "MU", "PLTR",
    "GOOGL", "NFLX", "CRM", "ORCL", "ADBE", "COST", "LLY", "JPM", "BAC", "UNH",
    "SMCI", "ARM", "INTC", "QCOM", "NOW", "PANW", "CRWD", "SHOP", "UBER", "COIN",
    "SOFI", "RIVN", "LCID", "HOOD", "SNAP", "F", "T", "WBD", "NIO", "OPEN",
    "RKLB", "IONQ", "ACHR", "JOBY", "AFRM", "CHPT", "QS", "ENVX"
]

TOP_N = 10
UNDER_30_N = 5
EARNINGS_N = 5

STRATEGY_WEIGHTS = {
    "trend": 0.25,
    "relative_strength": 0.20,
    "sector_strength": 0.15,
    "breakout": 0.15,
    "news_catalyst": 0.15,
    "risk_quality": 0.10,
}

BENCHMARKS = ["SPY", "QQQ"]

SECTOR_ETF_MAP = {
    "NVDA": "SOXX", "AMD": "SOXX", "MU": "SOXX", "AVGO": "SOXX", "INTC": "SOXX", "QCOM": "SOXX", "ARM": "SOXX",
    "AAPL": "XLK", "MSFT": "XLK", "ORCL": "XLK", "ADBE": "XLK", "NOW": "XLK", "PANW": "XLK", "CRWD": "XLK",
    "JPM": "XLF", "BAC": "XLF", "SOFI": "XLF", "HOOD": "XLF",
    "LLY": "XLV", "UNH": "XLV",
    "AMZN": "XLY", "TSLA": "XLY", "NFLX": "XLC", "META": "XLC", "GOOGL": "XLC", "SNAP": "XLC", "WBD": "XLC",
    "F": "XLY", "RIVN": "XLY", "LCID": "XLY",
    "RKLB": "ITA", "ACHR": "ITA", "JOBY": "ITA",
}
