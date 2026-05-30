from config import GEOPOLITICAL_SECTOR_BOOSTS

GEOPOLITICAL_KEYWORDS = {
    "defense": ["war", "missile", "defense", "military", "drone", "geopolitical", "nato", "pentagon"],
    "energy": ["oil", "gas", "lng", "opec", "sanctions", "middle east", "pipeline", "energy security"],
    "semiconductors": ["china", "taiwan", "chips", "semiconductor", "export controls", "ai chips"],
    "cybersecurity": ["cyberattack", "hack", "breach", "ransomware", "cybersecurity"],
    "uranium": ["nuclear", "uranium", "reactor", "energy security"],
}


def political_geo_score(ticker: str, headlines: list[str]) -> tuple[float, list[str]]:
    if not headlines:
        return 0.0, []

    joined = " ".join(headlines).lower()
    score = 0.0
    reasons = []

    for theme, words in GEOPOLITICAL_KEYWORDS.items():
        ticker_list = GEOPOLITICAL_SECTOR_BOOSTS.get(theme, [])
        if ticker not in ticker_list:
            continue

        hits = [w for w in words if w in joined]
        if hits:
            score += min(len(hits) * 20, 60)
            reasons.append(f"{theme} news sensitivity")

    return min(score, 100.0), reasons[:2]
