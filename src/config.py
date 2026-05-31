UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AMD", "AMZN", "META", "TSLA", "AVGO", "MU", "PLTR",
    "GOOGL", "NFLX", "CRM", "ORCL", "ADBE", "COST", "LLY", "JPM", "BAC", "UNH",
    "SMCI", "ARM", "INTC", "QCOM", "NOW", "PANW", "CRWD", "SHOP", "UBER", "COIN",
    "SOFI", "RIVN", "LCID", "HOOD", "SNAP", "F", "T", "WBD", "NIO", "OPEN",
    "RKLB", "IONQ", "ACHR", "JOBY", "AFRM", "CHPT", "QS", "ENVX",
    "LMT", "RTX", "NOC", "GD", "BA", "HII", "XOM", "CVX", "LNG", "URA"
]

TOP_N = 10
UNDER_30_N = 5
EARNINGS_N = 5
CATALYST_N = 5
POLITICAL_N = 5

STRATEGY_WEIGHTS = {
    "opening_activity": 0.12,
    "news_sentiment": 0.13,
    "trend": 0.10,
    "relative_strength": 0.08,
    "sector_strength": 0.06,
    "options_flow": 0.08,
    "earnings_quality": 0.08,
    "analyst_revisions": 0.10,
    "fundamental_momentum": 0.10,
    "volume_accumulation": 0.08,
    "insider_buying": 0.07,
    "volatility_setup": 0.06,
    "short_squeeze": 0.04,
    "institutional_ownership": 0.05,
    "pattern_trading": 0.05,
    "political_geo": 0.01,
    "politician_trade": 0.01,
}

MIN_PRICE = 10.0
MIN_AVG_DAILY_VOLUME = 500_000

BENCHMARKS = ["SPY", "QQQ"]

SECTOR_ETF_MAP = {
    "NVDA": "SOXX", "AMD": "SOXX", "MU": "SOXX", "AVGO": "SOXX", "INTC": "SOXX", "QCOM": "SOXX", "ARM": "SOXX",
    "AAPL": "XLK", "MSFT": "XLK", "ORCL": "XLK", "ADBE": "XLK", "NOW": "XLK", "PANW": "XLK", "CRWD": "XLK",
    "JPM": "XLF", "BAC": "XLF", "SOFI": "XLF", "HOOD": "XLF",
    "LLY": "XLV", "UNH": "XLV",
    "AMZN": "XLY", "TSLA": "XLY", "NFLX": "XLC", "META": "XLC", "GOOGL": "XLC", "SNAP": "XLC", "WBD": "XLC",
    "F": "XLY", "RIVN": "XLY", "LCID": "XLY",
    "RKLB": "ITA", "ACHR": "ITA", "JOBY": "ITA",
    "LMT": "ITA", "RTX": "ITA", "NOC": "ITA", "GD": "ITA", "BA": "ITA", "HII": "ITA",
    "XOM": "XLE", "CVX": "XLE", "LNG": "XLE",
    "URA": "URA"
}

SECTOR_LABELS = {
    "SOXX": "Semiconductors",
    "XLK": "Technology",
    "XLF": "Financials",
    "XLV": "Healthcare",
    "XLY": "Consumer Discretionary",
    "XLC": "Communication Services",
    "ITA": "Aerospace & Defense",
    "XLE": "Energy",
    "URA": "Uranium",
    "SPY": "Broad Market",
}

GEOPOLITICAL_SECTOR_BOOSTS = {
    "defense": ["LMT", "RTX", "NOC", "GD", "BA", "HII", "RKLB"],
    "energy": ["XOM", "CVX", "LNG"],
    "semiconductors": ["NVDA", "AMD", "MU", "AVGO", "INTC", "QCOM", "ARM"],
    "cybersecurity": ["PANW", "CRWD"],
    "uranium": ["URA"],
}
