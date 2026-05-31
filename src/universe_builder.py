from __future__ import annotations

import csv
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import date, timedelta
from io import StringIO
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import yfinance as yf
from bs4 import BeautifulSoup

from config import MIN_AVG_DAILY_VOLUME, MIN_PRICE, UNIVERSE
from finnhub_client import get_finnhub_client
from market_data import get_history, get_ticker_obj
from reddit_client import extract_reddit_candidates, fetch_reddit_posts

logger = logging.getLogger(__name__)

ETF_HOLDINGS = [
    "QQQ", "VUG", "SOXX", "SMH", "HACK", "CIBR", "ITA", "BOTZ", "ARKQ",
    "ARKK", "URA", "XLE", "XLK", "XLF", "XLV", "XLY", "XLC",
]

ETF_TICKERS = set(ETF_HOLDINGS) | {
    "SPY", "DIA", "IWM", "IWV", "VOO", "VTI", "IVV", "VGT", "VHT", "XLI",
    "XLP", "XLU", "XLRE", "XLB", "TLT", "GLD", "SLV", "USO",
}

INVALID_SUFFIXES = (
    "W", "WS", "WT", "U", "UN", "R", "RT", "PR", "PRA", "PRB", "PRC", "PRD",
)
US_SHARE_CLASS_SUFFIXES = {"A", "B", "C"}

WIKI_HEADERS = {
    "sp500": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
    "nasdaq100": "https://en.wikipedia.org/wiki/Nasdaq-100",
}

ISHARES_IWV_HOLDINGS_URL = (
    "https://www.ishares.com/us/products/239714/ishares-russell-3000-etf/"
    "1467271812596.ajax?fileType=csv&fileName=IWV_holdings&dataType=fund"
)

REQUEST_TIMEOUT_SECONDS = 20
HIGH_MOMENTUM_SCAN_LIMIT = 300
PROGRESS_LOG_INTERVAL = 25


@dataclass(frozen=True)
class UniverseConfig:
    use_dynamic_universe: bool
    max_raw_universe_size: int
    target_stage1_size: int
    target_stage2_size: int
    target_deep_analysis_size: int
    min_price: float
    min_avg_daily_volume: float
    min_market_cap: float
    include_microcaps: bool
    include_reddit_in_universe: bool
    include_etf_holdings: bool
    include_russell_3000: bool
    include_sp500: bool
    include_nasdaq_100: bool
    allow_etfs: bool
    cache_dir: Path


def build_daily_universe(config: UniverseConfig | dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = universe_config(config)
    summary = _empty_summary()
    summary["config"] = {
        "use_dynamic_universe": cfg.use_dynamic_universe,
        "max_raw_universe_size": cfg.max_raw_universe_size,
        "target_stage1_size": cfg.target_stage1_size,
        "target_stage2_size": cfg.target_stage2_size,
        "target_deep_analysis_size": cfg.target_deep_analysis_size,
        "min_price": cfg.min_price,
        "min_avg_daily_volume": cfg.min_avg_daily_volume,
        "min_market_cap": cfg.min_market_cap,
        "include_microcaps": cfg.include_microcaps,
        "allow_etfs": cfg.allow_etfs,
    }

    if not cfg.use_dynamic_universe:
        manual = sorted(set(_normalize_many(UNIVERSE, summary)))
        summary["raw_universe"] = manual
        summary["filtered_universe"] = manual
        summary["stage1_quality_universe"] = manual
        summary["sources_used"]["manual_seed"] = len(manual)
        _write_snapshot(cfg, summary)
        _log_universe_summary(summary)
        return summary

    source_rows: list[tuple[str, str]] = []
    _extend_source(source_rows, "manual_seed", UNIVERSE, summary)
    _log_event("universe_source_loaded", source="manual_seed", count=len(UNIVERSE), total_rows=len(source_rows))

    if cfg.include_sp500:
        _extend_source(source_rows, "sp500", _fetch_wikipedia_tickers("sp500", summary), summary)
        _log_event("universe_source_loaded", source="sp500", count=summary["sources_used"].get("sp500", 0), total_rows=len(source_rows))
    if cfg.include_nasdaq_100:
        _extend_source(source_rows, "nasdaq100", _fetch_wikipedia_tickers("nasdaq100", summary), summary)
        _log_event("universe_source_loaded", source="nasdaq100", count=summary["sources_used"].get("nasdaq100", 0), total_rows=len(source_rows))
    if cfg.include_russell_3000:
        _extend_source(source_rows, "russell3000_iwv", _fetch_iwv_holdings(summary), summary)
        _log_event("universe_source_loaded", source="russell3000_iwv", count=summary["sources_used"].get("russell3000_iwv", 0), total_rows=len(source_rows))
    if cfg.include_etf_holdings:
        _extend_source(source_rows, "etf_holdings", _fetch_all_etf_holdings(summary), summary)
        _log_event("universe_source_loaded", source="etf_holdings", count=summary["sources_used"].get("etf_holdings", 0), total_rows=len(source_rows))
    if cfg.include_reddit_in_universe:
        _extend_source(source_rows, "reddit_social", _fetch_reddit_tickers(source_rows, summary), summary)
        _log_event("universe_source_loaded", source="reddit_social", count=summary["sources_used"].get("reddit_social", 0), total_rows=len(source_rows))
    _extend_source(source_rows, "earnings_calendar", _fetch_earnings_calendar_symbols(summary=summary), summary)
    _log_event("universe_source_loaded", source="earnings_calendar", count=summary["sources_used"].get("earnings_calendar", 0), total_rows=len(source_rows))

    raw = _dedupe_and_filter(source_rows, cfg, summary)
    summary["raw_universe"] = raw[: cfg.max_raw_universe_size]
    summary["filtered_universe"] = list(summary["raw_universe"])
    _log_event(
        "universe_raw_filtered",
        raw_count=len(summary["raw_universe"]),
        removed=summary["removed"],
        max_raw_universe_size=cfg.max_raw_universe_size,
    )

    momentum = _collect_high_momentum_tickers(summary["filtered_universe"], summary)
    if momentum:
        _extend_source(source_rows, "high_momentum_daily_scan", momentum, summary)
        summary["filtered_universe"] = _dedupe_and_filter(source_rows, cfg, summary)[: cfg.max_raw_universe_size]
        summary["raw_universe"] = list(summary["filtered_universe"])
        _log_event("universe_high_momentum_added", count=len(momentum), filtered_count=len(summary["filtered_universe"]))

    stage1 = _stage1_quality_filter(summary["filtered_universe"], cfg, summary)
    summary["stage1_quality_universe"] = stage1
    _write_snapshot(cfg, summary)
    _log_universe_summary(summary)
    return summary


def update_universe_stages(
    summary: dict[str, Any],
    stage2: list[str] | None = None,
    stage3: list[str] | None = None,
    final_top_10: list[str] | None = None,
) -> dict[str, Any]:
    if stage2 is not None:
        summary["stage2_opportunity_candidates"] = stage2
    if stage3 is not None:
        summary["stage3_deep_analysis_candidates"] = stage3
    if final_top_10 is not None:
        summary["final_top_10"] = final_top_10
    return summary


def universe_config(config: UniverseConfig | dict[str, Any] | None = None) -> UniverseConfig:
    if isinstance(config, UniverseConfig):
        return config
    overrides = config or {}
    cache_dir = Path(str(overrides.get("cache_dir") or os.getenv("UNIVERSE_CACHE_DIR") or "data/universe"))
    return UniverseConfig(
        use_dynamic_universe=_env_bool("USE_DYNAMIC_UNIVERSE", bool(overrides.get("use_dynamic_universe", True))),
        max_raw_universe_size=_env_int("MAX_RAW_UNIVERSE_SIZE", int(overrides.get("max_raw_universe_size", 2000))),
        target_stage1_size=_env_int("TARGET_STAGE1_SIZE", int(overrides.get("target_stage1_size", 500))),
        target_stage2_size=_env_int("TARGET_STAGE2_SIZE", int(overrides.get("target_stage2_size", 100))),
        target_deep_analysis_size=_env_int("TARGET_DEEP_ANALYSIS_SIZE", int(overrides.get("target_deep_analysis_size", 20))),
        min_price=_env_float("MIN_PRICE", float(overrides.get("min_price", MIN_PRICE))),
        min_avg_daily_volume=_env_float("MIN_AVG_DAILY_VOLUME", float(overrides.get("min_avg_daily_volume", MIN_AVG_DAILY_VOLUME))),
        min_market_cap=_env_float("MIN_MARKET_CAP", float(overrides.get("min_market_cap", 1_000_000_000))),
        include_microcaps=_env_bool("INCLUDE_MICROCAPS", bool(overrides.get("include_microcaps", False))),
        include_reddit_in_universe=_env_bool("INCLUDE_REDDIT_IN_UNIVERSE", bool(overrides.get("include_reddit_in_universe", True))),
        include_etf_holdings=_env_bool("INCLUDE_ETF_HOLDINGS", bool(overrides.get("include_etf_holdings", True))),
        include_russell_3000=_env_bool("INCLUDE_RUSSELL_3000", bool(overrides.get("include_russell_3000", True))),
        include_sp500=_env_bool("INCLUDE_SP500", bool(overrides.get("include_sp500", True))),
        include_nasdaq_100=_env_bool("INCLUDE_NASDAQ_100", bool(overrides.get("include_nasdaq_100", True))),
        allow_etfs=_env_bool("ALLOW_ETFS_IN_UNIVERSE", bool(overrides.get("allow_etfs", False))),
        cache_dir=cache_dir,
    )


def _empty_summary() -> dict[str, Any]:
    return {
        "raw_universe": [],
        "filtered_universe": [],
        "stage1_quality_universe": [],
        "stage2_opportunity_candidates": [],
        "stage3_deep_analysis_candidates": [],
        "final_top_10": [],
        "sources_used": {},
        "removed": {
            "duplicates": 0,
            "invalid": 0,
            "etfs": 0,
            "quality": 0,
            "insufficient_history": 0,
            "price": 0,
            "volume": 0,
            "market_cap": 0,
        },
        "errors": [],
        "snapshot_path": "",
    }


def _extend_source(
    source_rows: list[tuple[str, str]],
    source_name: str,
    tickers: list[str] | set[str] | tuple[str, ...],
    summary: dict[str, Any],
) -> None:
    cleaned = [ticker for ticker in tickers if ticker]
    summary["sources_used"][source_name] = summary["sources_used"].get(source_name, 0) + len(cleaned)
    source_rows.extend((source_name, ticker) for ticker in cleaned)


def _dedupe_and_filter(source_rows: list[tuple[str, str]], cfg: UniverseConfig, summary: dict[str, Any]) -> list[str]:
    seen: set[str] = set()
    valid: list[str] = []
    removed = _new_removed_counter()
    for source_name, raw_ticker in source_rows:
        ticker = normalize_ticker(raw_ticker)
        if not ticker or not _valid_common_stock_symbol(ticker):
            removed["invalid"] += 1
            summary["errors"].append({"source": source_name, "ticker": raw_ticker, "error": "invalid ticker"})
            continue
        if ticker in seen:
            removed["duplicates"] += 1
            continue
        if not cfg.allow_etfs and ticker in ETF_TICKERS:
            removed["etfs"] += 1
            continue
        seen.add(ticker)
        valid.append(ticker)
        if len(valid) >= cfg.max_raw_universe_size:
            break
    for key, value in removed.items():
        summary["removed"][key] = summary["removed"].get(key, 0) + value
    return valid


def _stage1_quality_filter(tickers: list[str], cfg: UniverseConfig, summary: dict[str, Any]) -> list[str]:
    accepted: list[tuple[float, str]] = []
    _log_event("universe_stage1_quality_start", ticker_count=len(tickers), target_stage1_size=cfg.target_stage1_size)
    for index, ticker in enumerate(tickers, start=1):
        try:
            df = get_history(ticker)
            if df.empty or len(df) < 120:
                summary["removed"]["insufficient_history"] += 1
                continue

            price = float(df["Close"].iloc[-1])
            avg_volume = float(df["Volume"].tail(30).mean())
            if price < cfg.min_price:
                summary["removed"]["price"] += 1
                continue
            if avg_volume < cfg.min_avg_daily_volume:
                summary["removed"]["volume"] += 1
                continue

            market_cap = _market_cap(ticker)
            quote_type = _quote_type(ticker)
            if not cfg.allow_etfs and quote_type in {"ETF", "MUTUALFUND", "INDEX"}:
                summary["removed"]["etfs"] += 1
                continue
            if not cfg.include_microcaps and market_cap is not None and market_cap < cfg.min_market_cap:
                summary["removed"]["market_cap"] += 1
                continue

            liquidity_rank = min(100.0, avg_volume / max(cfg.min_avg_daily_volume, 1) * 30.0)
            cap_rank = 50.0 if market_cap is None else min(100.0, market_cap / max(cfg.min_market_cap, 1) * 20.0)
            price_rank = min(100.0, price / max(cfg.min_price, 1) * 15.0)
            accepted.append((liquidity_rank + cap_rank + price_rank, ticker))
        except Exception as exc:
            summary["errors"].append({"source": "stage1_quality", "ticker": ticker, "error": str(exc)})
            summary["removed"]["quality"] += 1
            continue
        finally:
            if index == 1 or index % PROGRESS_LOG_INTERVAL == 0 or index == len(tickers):
                _log_event(
                    "universe_stage1_quality_progress",
                    processed=index,
                    total=len(tickers),
                    accepted=len(accepted),
                    removed=summary["removed"],
                )

    accepted = sorted(accepted, key=lambda item: item[0], reverse=True)
    stage1 = [ticker for _, ticker in accepted[: cfg.target_stage1_size]]
    summary["removed"]["quality"] += max(0, len(tickers) - len(stage1))
    _log_event("universe_stage1_quality_done", accepted=len(accepted), selected=len(stage1), removed=summary["removed"])
    return stage1


def _fetch_wikipedia_tickers(source: str, summary: dict[str, Any]) -> list[str]:
    url = WIKI_HEADERS[source]
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS, headers={"User-Agent": "stock-v4-bot/1.0"})
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        tickers: list[str] = []
        for table in soup.find_all("table"):
            headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
            if "symbol" not in headers and "ticker" not in headers:
                continue
            column = headers.index("symbol") if "symbol" in headers else headers.index("ticker")
            for row in table.find_all("tr")[1:]:
                cells = row.find_all(["td", "th"])
                if len(cells) > column:
                    tickers.append(cells[column].get_text(strip=True))
            if tickers:
                return tickers
    except Exception as exc:
        summary["errors"].append({"source": source, "error": str(exc)})
    return []


def _fetch_iwv_holdings(summary: dict[str, Any]) -> list[str]:
    try:
        response = requests.get(ISHARES_IWV_HOLDINGS_URL, timeout=REQUEST_TIMEOUT_SECONDS, headers={"User-Agent": "stock-v4-bot/1.0"})
        response.raise_for_status()
        rows = list(csv.reader(StringIO(response.text)))
        header_index = next(
            index for index, row in enumerate(rows)
            if any(cell.strip().lower() == "ticker" for cell in row)
        )
        header = rows[header_index]
        ticker_index = [cell.strip().lower() for cell in header].index("ticker")
        return [row[ticker_index] for row in rows[header_index + 1:] if len(row) > ticker_index]
    except Exception as exc:
        summary["errors"].append({"source": "russell3000_iwv", "error": str(exc)})
        return []


def _fetch_all_etf_holdings(summary: dict[str, Any]) -> list[str]:
    tickers: set[str] = set()
    _log_event("universe_etf_holdings_start", etf_count=len(ETF_HOLDINGS))
    for index, etf in enumerate(ETF_HOLDINGS, start=1):
        holdings = _fetch_yfinance_etf_holdings(etf, summary)
        tickers.update(holdings)
        _log_event("universe_etf_holdings_progress", etf=etf, processed=index, total=len(ETF_HOLDINGS), holdings_count=len(holdings), unique_count=len(tickers))
    return sorted(tickers)


def _fetch_yfinance_etf_holdings(etf: str, summary: dict[str, Any]) -> list[str]:
    try:
        ticker = yf.Ticker(etf)
        funds_data = getattr(ticker, "funds_data", None)
        top_holdings = getattr(funds_data, "top_holdings", None) if funds_data is not None else None
        if isinstance(top_holdings, pd.DataFrame) and not top_holdings.empty:
            if "Symbol" in top_holdings.columns:
                return [str(item) for item in top_holdings["Symbol"].dropna().tolist()]
            return [str(item) for item in top_holdings.index.tolist()]
    except Exception as exc:
        summary["errors"].append({"source": "etf_holdings", "ticker": etf, "error": str(exc)})
    return []


def _fetch_reddit_tickers(source_rows: list[tuple[str, str]], summary: dict[str, Any]) -> list[str]:
    try:
        known = {normalize_ticker(ticker) for _, ticker in source_rows if normalize_ticker(ticker)}
        posts = fetch_reddit_posts()
        candidates = extract_reddit_candidates(posts, universe=known, limit=75)
        return [candidate["ticker"] for candidate in candidates]
    except Exception as exc:
        summary["errors"].append({"source": "reddit_social", "error": str(exc)})
        return []


def _collect_high_momentum_tickers(tickers: list[str], summary: dict[str, Any]) -> list[str]:
    ranked: list[tuple[float, str]] = []
    scan_limit = _env_int("HIGH_MOMENTUM_SCAN_LIMIT", HIGH_MOMENTUM_SCAN_LIMIT)
    scan_tickers = tickers[: max(0, scan_limit)]
    _log_event("universe_high_momentum_scan_start", ticker_count=len(scan_tickers), configured_limit=scan_limit)
    for index, ticker in enumerate(scan_tickers, start=1):
        try:
            df = get_history(ticker)
            if df.empty or len(df) < 60:
                continue
            close = df["Close"]
            ret20 = (float(close.iloc[-1]) / float(close.iloc[-21]) - 1.0) * 100.0
            ret5 = (float(close.iloc[-1]) / float(close.iloc[-6]) - 1.0) * 100.0
            volume_ratio = float(df["Volume"].tail(5).mean()) / max(float(df["Volume"].tail(30).mean()), 1.0)
            score = ret20 * 0.55 + ret5 * 0.30 + min(volume_ratio, 4.0) * 4.0
            if score > 8:
                ranked.append((score, ticker))
        except Exception as exc:
            summary["errors"].append({"source": "high_momentum_daily_scan", "ticker": ticker, "error": str(exc)})
        finally:
            if index == 1 or index % PROGRESS_LOG_INTERVAL == 0 or index == len(scan_tickers):
                _log_event(
                    "universe_high_momentum_scan_progress",
                    processed=index,
                    total=len(scan_tickers),
                    matches=len(ranked),
                )
    result = [ticker for _, ticker in sorted(ranked, reverse=True)[:150]]
    _log_event("universe_high_momentum_scan_done", scanned=len(scan_tickers), selected=len(result))
    return result


def _fetch_earnings_calendar_symbols(summary: dict[str, Any], days_ahead: int = 14) -> list[str]:
    client = get_finnhub_client()
    if not client.available:
        return []
    try:
        today = date.today()
        end = today + timedelta(days=days_ahead)
        data = client._get("/calendar/earnings", {"from": today.isoformat(), "to": end.isoformat()})
        if not isinstance(data, dict):
            return []
        rows = data.get("earningsCalendar")
        if not isinstance(rows, list):
            return []
        return [str(item.get("symbol") or item.get("ticker") or "") for item in rows]
    except Exception as exc:
        summary["errors"].append({"source": "earnings_calendar", "error": str(exc)})
        return []


def normalize_ticker(ticker: str) -> str:
    cleaned = str(ticker or "").strip().upper().replace(".", "-")
    cleaned = cleaned.replace("$", "").replace(" ", "")
    return cleaned


def _normalize_many(tickers: list[str] | tuple[str, ...] | set[str], summary: dict[str, Any]) -> list[str]:
    normalized = []
    for ticker in tickers:
        clean = normalize_ticker(ticker)
        if clean and _valid_common_stock_symbol(clean):
            normalized.append(clean)
        else:
            summary["removed"]["invalid"] += 1
    return normalized


def _valid_common_stock_symbol(ticker: str) -> bool:
    if not re.match(r"^[A-Z][A-Z0-9-]{0,9}$", ticker):
        return False
    if "-" in ticker:
        parts = ticker.split("-")
        if len(parts) != 2:
            return False
        root, suffix = parts
        if suffix not in US_SHARE_CLASS_SUFFIXES:
            return False
        if not 1 <= len(root) <= 5:
            return False
        return True
    if len(ticker) == 5 and ticker[-1] in {"F", "Y"}:
        return False
    return True


def _market_cap(ticker: str) -> float | None:
    try:
        obj = get_ticker_obj(ticker)
        fast_info = getattr(obj, "fast_info", None)
        if fast_info is not None:
            value = _safe_mapping_get(fast_info, "market_cap")
            if value:
                return float(value)
        info = getattr(obj, "info", {}) or {}
        value = info.get("marketCap")
        return float(value) if value else None
    except Exception:
        return None


def _quote_type(ticker: str) -> str:
    try:
        info = getattr(get_ticker_obj(ticker), "info", {}) or {}
        return str(info.get("quoteType") or info.get("typeDisp") or "").upper()
    except Exception:
        return ""


def _safe_mapping_get(obj: Any, key: str) -> Any:
    try:
        return obj.get(key)
    except Exception:
        try:
            return obj[key]
        except Exception:
            return None


def _write_snapshot(cfg: UniverseConfig, summary: dict[str, Any]) -> None:
    try:
        cfg.cache_dir.mkdir(parents=True, exist_ok=True)
        path = cfg.cache_dir / f"{date.today().isoformat()}_universe.json"
        summary["snapshot_path"] = str(path)
        path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    except Exception as exc:
        summary["errors"].append({"source": "snapshot", "error": str(exc)})


def _log_universe_summary(summary: dict[str, Any]) -> None:
    _log_event(
        "universe_summary",
        raw_count=len(summary.get("raw_universe", [])),
        filtered_count=len(summary.get("filtered_universe", [])),
        stage1_count=len(summary.get("stage1_quality_universe", [])),
        sources_used=summary.get("sources_used", {}),
        removed=summary.get("removed", {}),
        snapshot_path=summary.get("snapshot_path", ""),
        error_count=len(summary.get("errors", [])),
    )


def _log_event(event: str, **payload: Any) -> None:
    logger.info(json.dumps({
        "event": event,
        **payload,
    }, default=str))


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return int(default)
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        logger.warning(json.dumps({"event": "invalid_int_env", "name": name, "value": raw, "default": default}))
        return int(default)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return float(default)
    try:
        return float(raw)
    except (TypeError, ValueError):
        logger.warning(json.dumps({"event": "invalid_float_env", "name": name, "value": raw, "default": default}))
        return float(default)


def _new_removed_counter() -> dict[str, int]:
    return {
        "duplicates": 0,
        "invalid": 0,
        "etfs": 0,
        "quality": 0,
        "insufficient_history": 0,
        "price": 0,
        "volume": 0,
        "market_cap": 0,
    }
