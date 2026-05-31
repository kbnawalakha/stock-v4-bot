import yfinance as yf
import pandas as pd

_HISTORY_CACHE: dict[tuple[str, str], pd.DataFrame] = {}
_FAILED_HISTORY: set[tuple[str, str]] = set()


def get_history(ticker: str, period: str = "1y") -> pd.DataFrame:
    key = (ticker.upper(), period)
    if key in _HISTORY_CACHE:
        return _HISTORY_CACHE[key].copy()
    if key in _FAILED_HISTORY:
        return pd.DataFrame()

    df = yf.download(ticker, period=period, interval="1d", auto_adjust=True, progress=False, threads=False)
    if df is None or df.empty:
        _FAILED_HISTORY.add(key)
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    required = {"Open", "High", "Low", "Close", "Volume"}
    if not required.issubset(set(df.columns)):
        _FAILED_HISTORY.add(key)
        return pd.DataFrame()
    cleaned = df.dropna()
    if cleaned.empty:
        _FAILED_HISTORY.add(key)
        return pd.DataFrame()
    _HISTORY_CACHE[key] = cleaned
    return cleaned.copy()


def get_ticker_obj(ticker: str):
    return yf.Ticker(ticker)


def clear_market_data_cache() -> None:
    _HISTORY_CACHE.clear()
    _FAILED_HISTORY.clear()
