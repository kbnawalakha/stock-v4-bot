from typing import Any

import pandas as pd

from fmp_client import get_fmp_client
from market_data import get_ticker_obj
from signal_utils import clamp, pct_change, safe_float


def fundamental_momentum_score(ticker: str) -> dict[str, float | None | str]:
    fmp = _from_fmp(ticker)
    if fmp["data_available"]:
        return fmp
    return _from_yfinance(ticker)


def _from_fmp(ticker: str) -> dict[str, float | None | str | bool]:
    client = get_fmp_client()
    if not client.available:
        return {**_neutral("FMP_API_KEY missing; using yfinance fallback if available."), "data_available": False}

    income = _as_list(client.get(f"/v3/income-statement/{ticker}", {"period": "quarter", "limit": 8}))
    balance = _as_list(client.get(f"/v3/balance-sheet-statement/{ticker}", {"period": "quarter", "limit": 4}))
    cash = _as_list(client.get(f"/v3/cash-flow-statement/{ticker}", {"period": "quarter", "limit": 8}))
    if len(income) < 5:
        return {**_neutral("FMP fundamentals unavailable."), "data_available": False}

    revenue_growth = pct_change(_num(income[0], "revenue"), _num(income[4], "revenue"))
    eps_growth = pct_change(_num(income[0], "epsdiluted", "eps"), _num(income[4], "epsdiluted", "eps"))
    gross_margin_trend = _margin_delta(income, "grossProfit", "revenue")
    operating_margin_trend = _margin_delta(income, "operatingIncome", "revenue")
    fcf_trend = None
    if len(cash) >= 5:
        fcf_trend = pct_change(_num(cash[0], "freeCashFlow"), _num(cash[4], "freeCashFlow"))
    debt_equity = _debt_equity(balance[0]) if balance else None
    return _score(revenue_growth, eps_growth, gross_margin_trend, operating_margin_trend, fcf_trend, debt_equity, "FMP")


def _from_yfinance(ticker: str) -> dict[str, float | None | str]:
    try:
        obj = get_ticker_obj(ticker)
        financials = _safe_frame(getattr(obj, "quarterly_financials", None))
        balance = _safe_frame(getattr(obj, "quarterly_balance_sheet", None))
        cashflow = _safe_frame(getattr(obj, "quarterly_cashflow", None))
        if financials.empty or financials.shape[1] < 5:
            return _neutral("fundamental data unavailable")

        revenue = _row(financials, ["Total Revenue", "Operating Revenue"])
        eps = _row(financials, ["Diluted EPS", "Basic EPS", "Net Income"])
        gross_profit = _row(financials, ["Gross Profit"])
        operating_income = _row(financials, ["Operating Income"])
        free_cash_flow = _row(cashflow, ["Free Cash Flow"]) if not cashflow.empty else pd.Series(dtype=float)

        revenue_growth = _series_growth(revenue, 4)
        eps_growth = _series_growth(eps, 4)
        gross_margin_trend = _series_margin_delta(gross_profit, revenue)
        operating_margin_trend = _series_margin_delta(operating_income, revenue)
        fcf_trend = _series_growth(free_cash_flow, 4)
        debt_equity = _yf_debt_equity(balance)
        return _score(revenue_growth, eps_growth, gross_margin_trend, operating_margin_trend, fcf_trend, debt_equity, "yfinance")
    except Exception:
        return _neutral("fundamental data unavailable")


def _score(revenue_growth, eps_growth, gross_margin_trend, operating_margin_trend, fcf_trend, debt_equity, source) -> dict[str, float | None | str | bool]:
    components = []
    if revenue_growth is not None:
        components.append(clamp(revenue_growth * 2, -100, 100))
    if eps_growth is not None:
        components.append(clamp(eps_growth * 1.5, -100, 100))
    if gross_margin_trend is not None:
        components.append(clamp(gross_margin_trend * 8, -100, 100))
    if operating_margin_trend is not None:
        components.append(clamp(operating_margin_trend * 8, -100, 100))
    if fcf_trend is not None:
        components.append(clamp(fcf_trend, -100, 100))
    score = sum(components) / len(components) if components else 0.0
    if debt_equity is not None and debt_equity > 2:
        score -= min(35.0, (debt_equity - 2) * 10)
    score = clamp(score, -100, 100)
    return {
        "score": score,
        "revenue_growth_yoy": revenue_growth,
        "eps_growth_yoy": eps_growth,
        "gross_margin_trend": gross_margin_trend,
        "operating_margin_trend": operating_margin_trend,
        "free_cash_flow_trend": fcf_trend,
        "debt_equity": debt_equity,
        "reason": f"Fundamental momentum from {source} is {'positive' if score > 15 else 'negative' if score < -15 else 'neutral'}.",
        "data_available": True,
    }


def _neutral(reason: str) -> dict[str, float | None | str]:
    return {
        "score": 0.0,
        "revenue_growth_yoy": None,
        "eps_growth_yoy": None,
        "gross_margin_trend": None,
        "operating_margin_trend": None,
        "free_cash_flow_trend": None,
        "debt_equity": None,
        "reason": reason,
    }


def _as_list(value: Any) -> list[dict[str, Any]]:
    return value if isinstance(value, list) else []


def _num(row: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = safe_float(row.get(key))
        if value is not None:
            return value
    return None


def _margin_delta(rows: list[dict[str, Any]], numerator: str, denominator: str) -> float | None:
    if len(rows) < 5:
        return None
    latest_den = _num(rows[0], denominator)
    prior_den = _num(rows[4], denominator)
    latest_num = _num(rows[0], numerator)
    prior_num = _num(rows[4], numerator)
    if latest_den in (None, 0) or prior_den in (None, 0) or latest_num is None or prior_num is None:
        return None
    return (latest_num / latest_den - prior_num / prior_den) * 100


def _debt_equity(row: dict[str, Any]) -> float | None:
    debt = _num(row, "totalDebt", "shortTermDebt")
    equity = _num(row, "totalStockholdersEquity", "totalEquity")
    if debt is None or equity in (None, 0):
        return None
    return debt / abs(equity)


def _safe_frame(value) -> pd.DataFrame:
    return value if isinstance(value, pd.DataFrame) else pd.DataFrame()


def _row(df: pd.DataFrame, names: list[str]) -> pd.Series:
    for name in names:
        if name in df.index:
            return pd.to_numeric(df.loc[name], errors="coerce")
    return pd.Series(dtype=float)


def _series_growth(series: pd.Series, periods: int) -> float | None:
    if series.empty or len(series.dropna()) <= periods:
        return None
    values = list(series.dropna())
    return pct_change(safe_float(values[0]), safe_float(values[periods]))


def _series_margin_delta(num: pd.Series, den: pd.Series) -> float | None:
    if num.empty or den.empty:
        return None
    latest_den = safe_float(den.iloc[0])
    prior_den = safe_float(den.iloc[min(4, len(den) - 1)])
    latest_num = safe_float(num.iloc[0])
    prior_num = safe_float(num.iloc[min(4, len(num) - 1)])
    if latest_den in (None, 0) or prior_den in (None, 0) or latest_num is None or prior_num is None:
        return None
    return (latest_num / latest_den - prior_num / prior_den) * 100


def _yf_debt_equity(balance: pd.DataFrame) -> float | None:
    if balance.empty:
        return None
    debt = _row(balance, ["Total Debt", "Long Term Debt"]).iloc[0] if not _row(balance, ["Total Debt", "Long Term Debt"]).empty else None
    equity_series = _row(balance, ["Stockholders Equity", "Total Equity Gross Minority Interest"])
    equity = equity_series.iloc[0] if not equity_series.empty else None
    debt = safe_float(debt)
    equity = safe_float(equity)
    if debt is None or equity in (None, 0):
        return None
    return debt / abs(equity)
