"""FMP (Financial Modeling Prep) backend for MarketDataClient.

Returns data in the SAME normalized shape as fetcher_yfinance, so the client
can swap backends without callers caring. Raises FmpError on any unusable
response — the client catches that and falls back to yfinance.

SECURITY NOTE
  • The API key is passed in as a function argument, never read globally.
  • URLs contain the API key as a query parameter and MUST NEVER be logged.
  • Errors only surface the HTTP code / FMP error message — never the URL.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

FMP_BASE = "https://financialmodelingprep.com/api"


class FmpError(Exception):
    """Raised when FMP returns an unusable response."""


def _get(path: str, api_key: str, timeout: int = 30) -> Any:
    """GET FMP_BASE + path with apikey appended.

    Never logs the URL or the key. Raises FmpError on any non-OK condition.
    """
    sep = "&" if "?" in path else "?"
    url = f"{FMP_BASE}{path}{sep}apikey={api_key}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        # Don't include the URL in the message (contains key).
        raise FmpError(f"HTTP {e.code}") from None
    except urllib.error.URLError as e:
        raise FmpError(f"network: {type(e.reason).__name__}") from None
    except Exception as e:
        raise FmpError(f"transport: {type(e).__name__}") from None

    if isinstance(data, dict):
        if "Error Message" in data:
            raise FmpError(f"api: {str(data['Error Message'])[:100]}")
        if "error" in data and not data.get("historical"):
            raise FmpError(f"api: {str(data['error'])[:100]}")
    if data == [] or data is None:
        raise FmpError("empty response")
    return data


# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------


def fetch_prices(ticker: str, api_key: str, days: int = 400) -> pd.DataFrame:
    """Daily OHLCV. Adjusts open/high/low using adjClose/close ratio."""
    end = datetime.today()
    start = end - timedelta(days=int(days * 1.5))
    path = (f"/v3/historical-price-full/{ticker}"
            f"?from={start.strftime('%Y-%m-%d')}&to={end.strftime('%Y-%m-%d')}")
    data = _get(path, api_key)
    if not isinstance(data, dict) or "historical" not in data:
        raise FmpError("unexpected price shape")
    rows = data["historical"]
    if not rows:
        raise FmpError("no price history")
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    # FMP returns unadjusted OHLC + separate adjClose. Apply split-adjustment
    # ratio so all four columns are consistently adjusted (like yfinance auto_adjust).
    if "adjClose" in df.columns and "close" in df.columns:
        ratio = (df["adjClose"] / df["close"]).fillna(1.0)
        df["close"] = df["adjClose"]
        df["open"] = df["open"] * ratio
        df["high"] = df["high"] * ratio
        df["low"] = df["low"] * ratio
    keep = [c for c in ("open", "high", "low", "close", "volume") if c in df.columns]
    df = df[keep]
    if "volume" in df.columns:
        df["volume"] = df["volume"].fillna(0).astype("int64")
    if days and len(df) > days:
        df = df.tail(days)
    return df


# ---------------------------------------------------------------------------
# Quarterly financials (income statement + earnings surprises)
# ---------------------------------------------------------------------------


def fetch_quarterly_financials(ticker: str, api_key: str,
                                limit: int = 20) -> list[dict[str, Any]]:
    """Up to `limit` quarterly income-statement rows + consensus EPS from /earnings-surprises.

    Returned sorted by period_end ascending (oldest first).
    """
    inc_path = f"/v3/income-statement/{ticker}?period=quarter&limit={limit}"
    inc_data = _get(inc_path, api_key)
    if not isinstance(inc_data, list):
        raise FmpError("unexpected income stmt shape")

    # Earnings surprises is best-effort — failure here is non-fatal.
    surprises_by_date: dict[str, dict[str, float | None]] = {}
    try:
        surp_data = _get(f"/v3/earnings-surprises/{ticker}", api_key)
        if isinstance(surp_data, list):
            for s in surp_data:
                d = s.get("date")
                if d:
                    surprises_by_date[d] = {
                        "estimate": _f(s.get("estimatedEarning")),
                        "actual": _f(s.get("actualEarningResult")),
                    }
    except FmpError:
        pass

    rows: list[dict[str, Any]] = []
    for q in inc_data:
        period_end = q.get("date")
        if not period_end:
            continue
        eps = _f(q.get("epsdiluted")) or _f(q.get("eps"))
        if eps is None:
            continue
        surp = surprises_by_date.get(period_end, {})
        eps_est = surp.get("estimate")
        surprise_pct = None
        if eps_est is not None and eps is not None and eps_est != 0:
            surprise_pct = (eps - eps_est) / abs(eps_est) * 100
        rows.append({
            "period_end": period_end,
            "eps_diluted": eps,
            "revenue": _f(q.get("revenue")),
            "net_income": _f(q.get("netIncome")),
            "gross_profit": _f(q.get("grossProfit")),
            "operating_income": _f(q.get("operatingIncome")),
            "free_cash_flow": None,  # needs /v3/cash-flow-statement
            "shares_diluted": _f(q.get("weightedAverageShsOutDil")),
            "eps_estimate": eps_est,
            "eps_surprise_pct": surprise_pct,
        })
    rows.sort(key=lambda r: r["period_end"])
    return rows


# ---------------------------------------------------------------------------
# Key metrics (ROE, margins) per quarter — FMP-exclusive
# ---------------------------------------------------------------------------


def fetch_key_metrics_quarterly(ticker: str, api_key: str,
                                 limit: int = 20) -> list[dict[str, Any]]:
    """ROE, ROA, margins per quarter from /v3/ratios. FMP-exclusive."""
    path = f"/v3/ratios/{ticker}?period=quarter&limit={limit}"
    data = _get(path, api_key)
    if not isinstance(data, list):
        raise FmpError("unexpected ratios shape")
    rows: list[dict[str, Any]] = []
    for r in data:
        period_end = r.get("date")
        if not period_end:
            continue
        rows.append({
            "period_end": period_end,
            "roe": _f(r.get("returnOnEquity")),
            "roa": _f(r.get("returnOnAssets")),
            "gross_margin": _f(r.get("grossProfitMargin")),
            "operating_margin": _f(r.get("operatingProfitMargin")),
            "net_margin": _f(r.get("netProfitMargin")),
            "fcf_margin": None,  # not in /ratios
        })
    rows.sort(key=lambda r: r["period_end"])
    return rows


# ---------------------------------------------------------------------------
# Profile (supplements info; FMP doesn't give next_earnings_date in profile)
# ---------------------------------------------------------------------------


def fetch_info(ticker: str, api_key: str) -> dict[str, Any]:
    """Profile snapshot. Note: next_earnings_date NOT included (use yfinance)."""
    data = _get(f"/v3/profile/{ticker}", api_key)
    if not isinstance(data, list) or not data:
        raise FmpError("unexpected profile shape")
    p = data[0]

    # Try ROE TTM (best-effort)
    roe = None
    try:
        ratios = _get(f"/v3/ratios-ttm/{ticker}", api_key)
        if isinstance(ratios, list) and ratios:
            roe = _f(ratios[0].get("returnOnEquityTTM"))
    except FmpError:
        pass

    return {
        "long_name": p.get("companyName"),
        "short_name": p.get("companyName"),  # FMP doesn't expose a separate short_name
        "sector": p.get("sector"),
        "industry": p.get("industry"),
        "market_cap": _f(p.get("mktCap")),
        "trailing_eps": _f(p.get("lastDiv")),  # not really EPS — FMP profile lacks it
        "forward_eps": None,                   # not in profile
        "roe": roe,
        "next_earnings_date": None,            # not in profile; yfinance handles this
    }


def _f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        return None if f != f else f  # filter NaN
    except (TypeError, ValueError):
        return None
