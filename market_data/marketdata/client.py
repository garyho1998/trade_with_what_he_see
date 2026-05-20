"""MarketDataClient — shared cache + fetch facade for personal finance skills.

Usage:
    from marketdata import MarketDataClient
    c = MarketDataClient()
    df_prices = c.get_prices("NVDA", days=400)
    quarterly = c.get_quarterly("NVDA")
    info = c.get_info("NVDA")

All public methods are cache-first: they read from SQLite if fresh, fetch
otherwise. Writes are idempotent (INSERT OR REPLACE).
"""
from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from . import fetcher_yfinance as yf_fetch
from . import fetcher_fmp as fmp_fetch
from .fetcher_fmp import FmpError

DEFAULT_DB_PATH = Path.home() / ".config" / "market_data" / "market.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"

# Default TTLs (hours). Override per call.
TTL_PRICES = 24
TTL_QUARTERLY = 168    # 7 days — financials don't update intra-quarter
TTL_ANNUAL = 720       # 30 days
TTL_METRICS = 168
TTL_INFO = 24


class MarketDataClient:
    def __init__(self, db_path: str | Path | None = None,
                 skill_name: str | None = None) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.skill_name = skill_name  # logged with each fetch for audit
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA foreign_keys=ON;")
        # FMP key never logged; kept in memory for future fetcher_fmp.
        self._fmp_key = os.environ.get("FMP_API_KEY")
        self._ensure_schema()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "MarketDataClient":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    # ── Schema bootstrap ─────────────────────────────────────
    def _ensure_schema(self) -> None:
        sql = SCHEMA_PATH.read_text()
        self._conn.executescript(sql)
        self._conn.commit()

    # ── Cache state ──────────────────────────────────────────
    def _is_fresh(self, ticker: str, data_type: str) -> bool:
        row = self._conn.execute(
            "SELECT last_fetch, ttl_hours FROM cache_state "
            "WHERE ticker=? AND data_type=?",
            (ticker, data_type),
        ).fetchone()
        if not row:
            return False
        last = datetime.fromisoformat(row["last_fetch"])
        age = (datetime.now() - last).total_seconds() / 3600
        return age < row["ttl_hours"]

    def _mark_fresh(self, ticker: str, data_type: str, ttl_hours: int) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO cache_state (ticker, data_type, last_fetch, ttl_hours) "
            "VALUES (?, ?, ?, ?)",
            (ticker, data_type, datetime.now().isoformat(timespec="seconds"),
             ttl_hours),
        )

    def stale(self, ticker: str, data_type: str) -> bool:
        return not self._is_fresh(ticker, data_type)

    # ── Fetch logging ────────────────────────────────────────
    def _log(self, source: str, ticker: str, endpoint: str, status: str,
             duration_ms: int, rows: int = 0, error: str | None = None) -> None:
        self._conn.execute(
            "INSERT INTO fetch_log (source, ticker, endpoint, status, "
            "duration_ms, rows, skill, error, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (source, ticker, endpoint, status, duration_ms, rows,
             self.skill_name, error,
             datetime.now().isoformat(timespec="seconds")),
        )

    # ── Public API: prices ───────────────────────────────────
    def get_prices(self, ticker: str, days: int = 400,
                   max_age_hours: int = TTL_PRICES,
                   force_refresh: bool = False) -> pd.DataFrame:
        """Return OHLCV DataFrame indexed by date (DatetimeIndex)."""
        ticker = ticker.upper().strip()
        if force_refresh or not self._is_fresh(ticker, "prices"):
            self._refresh_prices(ticker, days, max_age_hours)
        return self._read_prices(ticker, days)

    def _refresh_prices(self, ticker: str, days: int, ttl: int) -> None:
        df, source = self._fetch_prices_layered(ticker, days)
        if df is None or df.empty:
            return
        now = datetime.now().isoformat(timespec="seconds")
        rows = [
            (ticker, idx.strftime("%Y-%m-%d"),
             _to_float(r["open"]), _to_float(r["high"]),
             _to_float(r["low"]), _to_float(r["close"]),
             int(r["volume"]) if pd.notna(r["volume"]) else 0,
             source, now)
            for idx, r in df.iterrows()
        ]
        self._conn.executemany(
            "INSERT OR REPLACE INTO prices "
            "(ticker, date, open, high, low, close, volume, source, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        self._mark_fresh(ticker, "prices", ttl)
        self._conn.commit()

    def _fetch_prices_layered(self, ticker: str, days: int):
        """Try FMP first if key set, else yfinance. Returns (DataFrame, source)."""
        if self._fmp_key:
            t0 = time.monotonic()
            try:
                df = fmp_fetch.fetch_prices(ticker, self._fmp_key, days=days)
                dur = int((time.monotonic() - t0) * 1000)
                self._log("fmp", ticker, "historical-price-full", "ok",
                          dur, len(df))
                return df, "fmp"
            except FmpError as e:
                dur = int((time.monotonic() - t0) * 1000)
                self._log("fmp", ticker, "historical-price-full", "error",
                          dur, 0, str(e)[:200])
                # fall through to yfinance
        t0 = time.monotonic()
        try:
            df = yf_fetch.fetch_prices(ticker, days=days)
            dur = int((time.monotonic() - t0) * 1000)
            if df.empty:
                self._log("yfinance", ticker, "history", "error",
                          dur, 0, "empty result")
                return None, "yfinance"
            self._log("yfinance", ticker, "history", "ok", dur, len(df))
            return df, "yfinance"
        except Exception as e:
            dur = int((time.monotonic() - t0) * 1000)
            self._log("yfinance", ticker, "history", "error",
                      dur, 0, str(e)[:200])
            return None, "yfinance"

    def _read_prices(self, ticker: str, days: int) -> pd.DataFrame:
        rows = self._conn.execute(
            "SELECT date, open, high, low, close, volume FROM prices "
            "WHERE ticker=? ORDER BY date DESC LIMIT ?",
            (ticker, days),
        ).fetchall()
        if not rows:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        df = pd.DataFrame([dict(r) for r in rows])
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        return df

    # ── Public API: quarterly financials ─────────────────────
    def get_quarterly(self, ticker: str, quarters: int = 20,
                      max_age_hours: int = TTL_QUARTERLY,
                      force_refresh: bool = False) -> pd.DataFrame:
        """Return quarterly financials, newest last, up to `quarters` rows."""
        ticker = ticker.upper().strip()
        if force_refresh or not self._is_fresh(ticker, "quarterly"):
            self._refresh_quarterly(ticker, max_age_hours)
        return self._read_quarterly(ticker, quarters)

    def _refresh_quarterly(self, ticker: str, ttl: int) -> None:
        rows, source = self._fetch_quarterly_layered(ticker)
        if not rows:
            return
        now = datetime.now().isoformat(timespec="seconds")
        db_rows = [
            (ticker, r["period_end"], r["eps_diluted"], r["revenue"],
             r["net_income"], r["gross_profit"], r["operating_income"],
             r["free_cash_flow"], r["shares_diluted"],
             r["eps_estimate"], r["eps_surprise_pct"],
             source, now)
            for r in rows
        ]
        self._conn.executemany(
            "INSERT OR REPLACE INTO quarterly_financials "
            "(ticker, period_end, eps_diluted, revenue, net_income, "
            "gross_profit, operating_income, free_cash_flow, shares_diluted, "
            "eps_estimate, eps_surprise_pct, source, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            db_rows,
        )
        self._mark_fresh(ticker, "quarterly", ttl)
        self._conn.commit()

    def _fetch_quarterly_layered(self, ticker: str):
        """Try FMP first if key set (returns up to 20q), else yfinance (4-5q)."""
        if self._fmp_key:
            t0 = time.monotonic()
            try:
                rows = fmp_fetch.fetch_quarterly_financials(
                    ticker, self._fmp_key, limit=20)
                dur = int((time.monotonic() - t0) * 1000)
                self._log("fmp", ticker, "income-statement", "ok",
                          dur, len(rows))
                return rows, "fmp"
            except FmpError as e:
                dur = int((time.monotonic() - t0) * 1000)
                self._log("fmp", ticker, "income-statement", "error",
                          dur, 0, str(e)[:200])
        t0 = time.monotonic()
        try:
            rows = yf_fetch.fetch_quarterly_financials(ticker)
            dur = int((time.monotonic() - t0) * 1000)
            if not rows:
                self._log("yfinance", ticker, "quarterly_income_stmt", "error",
                          dur, 0, "empty result")
                return [], "yfinance"
            self._log("yfinance", ticker, "quarterly_income_stmt", "ok",
                      dur, len(rows))
            return rows, "yfinance"
        except Exception as e:
            dur = int((time.monotonic() - t0) * 1000)
            self._log("yfinance", ticker, "quarterly_income_stmt", "error",
                      dur, 0, str(e)[:200])
            return [], "yfinance"

    # ── Public API: key metrics quarterly (FMP-only) ─────────
    def get_key_metrics(self, ticker: str, quarters: int = 20,
                        max_age_hours: int = TTL_METRICS,
                        force_refresh: bool = False) -> pd.DataFrame:
        """Quarterly ROE, ROA, margins. Requires FMP_API_KEY — empty if not set."""
        ticker = ticker.upper().strip()
        if force_refresh or not self._is_fresh(ticker, "metrics"):
            self._refresh_key_metrics(ticker, max_age_hours)
        return self._read_key_metrics(ticker, quarters)

    def _refresh_key_metrics(self, ticker: str, ttl: int) -> None:
        if not self._fmp_key:
            return  # yfinance can't provide this; silent skip
        t0 = time.monotonic()
        try:
            rows = fmp_fetch.fetch_key_metrics_quarterly(
                ticker, self._fmp_key, limit=20)
            dur = int((time.monotonic() - t0) * 1000)
            if not rows:
                self._log("fmp", ticker, "ratios", "error", dur, 0, "empty")
                return
            now = datetime.now().isoformat(timespec="seconds")
            db_rows = [
                (ticker, r["period_end"], r["roe"], r["roa"],
                 r["gross_margin"], r["operating_margin"],
                 r["net_margin"], r["fcf_margin"], "fmp", now)
                for r in rows
            ]
            self._conn.executemany(
                "INSERT OR REPLACE INTO key_metrics_quarterly "
                "(ticker, period_end, roe, roa, gross_margin, "
                "operating_margin, net_margin, fcf_margin, source, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                db_rows,
            )
            self._mark_fresh(ticker, "metrics", ttl)
            self._log("fmp", ticker, "ratios", "ok", dur, len(db_rows))
            self._conn.commit()
        except FmpError as e:
            dur = int((time.monotonic() - t0) * 1000)
            self._log("fmp", ticker, "ratios", "error", dur, 0, str(e)[:200])
            self._conn.commit()

    def _read_key_metrics(self, ticker: str, quarters: int) -> pd.DataFrame:
        rows = self._conn.execute(
            "SELECT period_end, roe, roa, gross_margin, operating_margin, "
            "net_margin, fcf_margin, source FROM key_metrics_quarterly "
            "WHERE ticker=? ORDER BY period_end DESC LIMIT ?",
            (ticker, quarters),
        ).fetchall()
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame([dict(r) for r in rows])
        df["period_end"] = pd.to_datetime(df["period_end"])
        df = df.sort_values("period_end").reset_index(drop=True)
        return df

    def _read_quarterly(self, ticker: str, quarters: int) -> pd.DataFrame:
        rows = self._conn.execute(
            "SELECT period_end, eps_diluted, revenue, net_income, "
            "gross_profit, operating_income, free_cash_flow, shares_diluted, "
            "eps_estimate, eps_surprise_pct, source FROM quarterly_financials "
            "WHERE ticker=? ORDER BY period_end DESC LIMIT ?",
            (ticker, quarters),
        ).fetchall()
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame([dict(r) for r in rows])
        df["period_end"] = pd.to_datetime(df["period_end"])
        df = df.sort_values("period_end").reset_index(drop=True)
        return df

    # ── Public API: ticker info ──────────────────────────────
    def get_info(self, ticker: str, max_age_hours: int = TTL_INFO,
                 force_refresh: bool = False) -> dict[str, Any]:
        ticker = ticker.upper().strip()
        if force_refresh or not self._is_fresh(ticker, "info"):
            self._refresh_info(ticker, max_age_hours)
        return self._read_info(ticker)

    def _refresh_info(self, ticker: str, ttl: int) -> None:
        t0 = time.monotonic()
        try:
            info = yf_fetch.fetch_info(ticker)
            duration_ms = int((time.monotonic() - t0) * 1000)
            now = datetime.now().isoformat(timespec="seconds")
            self._conn.execute(
                "INSERT OR REPLACE INTO ticker_info "
                "(ticker, long_name, short_name, sector, industry, market_cap, "
                "trailing_eps, forward_eps, roe, next_earnings_date, "
                "source, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ticker, info.get("long_name"), info.get("short_name"),
                 info.get("sector"), info.get("industry"),
                 info.get("market_cap"), info.get("trailing_eps"),
                 info.get("forward_eps"), info.get("roe"),
                 info.get("next_earnings_date"),
                 "yfinance", now),
            )
            self._mark_fresh(ticker, "info", ttl)
            self._log("yfinance", ticker, "info", "ok", duration_ms, 1)
            self._conn.commit()
        except Exception as e:
            duration_ms = int((time.monotonic() - t0) * 1000)
            self._log("yfinance", ticker, "info", "error",
                      duration_ms, 0, str(e)[:200])
            self._conn.commit()

    def _read_info(self, ticker: str) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT long_name, short_name, sector, industry, market_cap, "
            "trailing_eps, forward_eps, roe, next_earnings_date, "
            "source, fetched_at "
            "FROM ticker_info WHERE ticker=?", (ticker,)
        ).fetchone()
        if not row:
            return {}
        return dict(row)

    # ── Diagnostics ──────────────────────────────────────────
    def cache_summary(self, ticker: str | None = None) -> pd.DataFrame:
        """Return cache_state as a DataFrame for inspection."""
        if ticker:
            rows = self._conn.execute(
                "SELECT * FROM cache_state WHERE ticker=?", (ticker,)
            ).fetchall()
        else:
            rows = self._conn.execute("SELECT * FROM cache_state").fetchall()
        return pd.DataFrame([dict(r) for r in rows])

    def fetch_log_tail(self, n: int = 20) -> pd.DataFrame:
        rows = self._conn.execute(
            "SELECT timestamp, source, ticker, endpoint, status, "
            "duration_ms, rows, skill, error FROM fetch_log "
            "ORDER BY id DESC LIMIT ?", (n,)
        ).fetchall()
        return pd.DataFrame([dict(r) for r in rows])


def _to_float(v) -> float | None:
    if v is None or (isinstance(v, float) and v != v):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
