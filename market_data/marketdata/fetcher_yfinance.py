"""yfinance backend for MarketDataClient.

Pure fetch functions — no DB writes here. The client owns persistence.
Each function returns normalized dicts/DataFrames ready to insert.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import yfinance as yf


def fetch_prices(ticker: str, days: int = 400) -> pd.DataFrame:
    """Return OHLCV DataFrame indexed by date.

    Columns: open, high, low, close, volume.
    Uses auto-adjusted prices (splits + dividends applied retroactively).
    """
    end = datetime.today() + timedelta(days=1)
    # Pull extra calendar days to cover weekends/holidays — ~1.5x trading days.
    start = end - timedelta(days=int(days * 1.5))
    t = yf.Ticker(ticker)
    hist = t.history(start=start.strftime("%Y-%m-%d"),
                     end=end.strftime("%Y-%m-%d"),
                     auto_adjust=True)
    if hist is None or hist.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    if hist.index.tz is not None:
        hist.index = hist.index.tz_localize(None)
    df = hist.rename(columns={
        "Open": "open", "High": "high", "Low": "low",
        "Close": "close", "Volume": "volume",
    })[["open", "high", "low", "close", "volume"]]
    df = df.dropna(subset=["close"])
    if days and len(df) > days:
        df = df.tail(days)
    return df


def fetch_quarterly_financials(ticker: str) -> list[dict[str, Any]]:
    """Return list of dicts (one per quarter) with eps_diluted, revenue, etc.

    yfinance gives ~4-5 quarters on free tier. Also merges in consensus EPS
    from `earnings_history` (when available — yfinance's history can be
    spotty for older quarters or international tickers).
    Returned sorted by period_end ascending.
    """
    t = yf.Ticker(ticker)
    inc = t.quarterly_income_stmt
    if inc is None or inc.empty:
        return []

    def _find_row(*candidates: str) -> pd.Series | None:
        for name in candidates:
            if name in inc.index:
                return inc.loc[name]
        return None

    eps_row = _find_row("Diluted EPS", "DilutedEPS", "Basic EPS", "BasicEPS")
    rev_row = _find_row("Total Revenue", "TotalRevenue", "Revenue",
                        "Operating Revenue")
    ni_row = _find_row("Net Income", "NetIncome", "Net Income Common Stockholders")
    gross_row = _find_row("Gross Profit", "GrossProfit")
    op_row = _find_row("Operating Income", "OperatingIncome")
    shares_row = _find_row("Diluted Average Shares", "DilutedAverageShares",
                           "Basic Average Shares")

    # Optional: consensus EPS at the time, keyed by year-month of period_end.
    # earnings_history is best-effort — many tickers/quarters won't have it.
    consensus_by_ym: dict[str, dict[str, float | None]] = {}
    try:
        eh = t.earnings_history
        if eh is not None and not eh.empty:
            eh.index = pd.to_datetime(eh.index)
            for idx, row in eh.iterrows():
                ym = idx.strftime("%Y-%m")
                est = row.get("epsEstimate")
                surp = row.get("surprisePercent")
                consensus_by_ym[ym] = {
                    "estimate": float(est) if pd.notna(est) else None,
                    "surprise_pct": float(surp) if pd.notna(surp) else None,
                }
    except Exception:
        pass  # earnings_history unavailable — leave eps_estimate as None

    columns = list(inc.columns)  # period-end dates
    rows: list[dict[str, Any]] = []
    for col in columns:
        period_end_dt = pd.to_datetime(col)
        period_end = period_end_dt.strftime("%Y-%m-%d")
        cons = consensus_by_ym.get(period_end_dt.strftime("%Y-%m"), {})
        rows.append({
            "period_end": period_end,
            "eps_diluted": _val(eps_row, col),
            "revenue": _val(rev_row, col),
            "net_income": _val(ni_row, col),
            "gross_profit": _val(gross_row, col),
            "operating_income": _val(op_row, col),
            "free_cash_flow": None,  # FCF needs cashflow stmt — defer to FMP
            "shares_diluted": _val(shares_row, col),
            "eps_estimate": cons.get("estimate"),
            "eps_surprise_pct": cons.get("surprise_pct"),
        })
    rows.sort(key=lambda r: r["period_end"])
    return rows


def fetch_info(ticker: str) -> dict[str, Any]:
    """Return latest metadata snapshot. Tolerant of missing fields."""
    t = yf.Ticker(ticker)
    try:
        raw = t.info or {}
    except Exception:
        raw = {}

    next_earnings = _next_earnings_date(t)

    return {
        "long_name": raw.get("longName"),
        "short_name": raw.get("shortName"),
        "sector": raw.get("sector"),
        "industry": raw.get("industry"),
        "market_cap": _float(raw.get("marketCap")),
        "trailing_eps": _float(raw.get("trailingEps")),
        "forward_eps": _float(raw.get("forwardEps")),
        "roe": _float(raw.get("returnOnEquity")),  # stored as fraction (0.32 = 32%)
        "next_earnings_date": next_earnings,
    }


def _next_earnings_date(t: "yf.Ticker") -> str | None:
    try:
        cal = t.calendar
    except Exception:
        return None
    if cal is None:
        return None
    try:
        if isinstance(cal, dict):
            d = cal.get("Earnings Date")
            if isinstance(d, list) and d:
                return pd.to_datetime(d[0]).strftime("%Y-%m-%d")
            if d is not None:
                return pd.to_datetime(d).strftime("%Y-%m-%d")
        elif hasattr(cal, "loc") and "Earnings Date" in cal.index:
            d = cal.loc["Earnings Date"].iloc[0]
            return pd.to_datetime(d).strftime("%Y-%m-%d")
    except Exception:
        pass
    return None


def _val(row: pd.Series | None, col) -> float | None:
    if row is None or col not in row.index:
        return None
    v = row.loc[col]
    if pd.isna(v):
        return None
    return float(v)


def _float(v) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        return f if not (f != f) else None  # filter NaN
    except (TypeError, ValueError):
        return None
