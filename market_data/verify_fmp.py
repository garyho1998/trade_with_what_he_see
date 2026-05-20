"""Phase 4 verification — set FMP_API_KEY in your env, then run this.

Tests that FMP backend is actually being used (not just falling back to yfinance)
and that we get the expected upgrade: ~20 quarters of EPS, ROE/margins per quarter.

Usage:
  export FMP_API_KEY=...    # set your key
  ~/.config/market_data/venv/bin/python ~/.config/market_data/verify_fmp.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".config" / "market_data"))

from marketdata import MarketDataClient


def main() -> int:
    key = os.environ.get("FMP_API_KEY")
    if not key:
        print("✗ FMP_API_KEY is NOT set in your env.")
        print("  To activate FMP backend:")
        print("    export FMP_API_KEY=your_key_here")
        print("    ~/.config/market_data/venv/bin/python "
              "~/.config/market_data/verify_fmp.py")
        return 1

    print(f"✓ FMP_API_KEY is set (length: {len(key)} chars)")
    print()

    # Use a clean test DB to force fresh fetches
    test_db = Path("/tmp/fmp_verify.db")
    if test_db.exists():
        test_db.unlink()

    ticker = "NVDA"
    all_pass = True

    with MarketDataClient(db_path=test_db, skill_name="fmp-verify") as c:
        # Force fresh fetch to exercise FMP path
        print(f"Fetching {ticker} via FMP (force_refresh)…")
        prices = c.get_prices(ticker, days=400, force_refresh=True)
        quarterly = c.get_quarterly(ticker, force_refresh=True)
        km = c.get_key_metrics(ticker, force_refresh=True)
        info = c.get_info(ticker, force_refresh=True)

        # Check sources in DB
        import sqlite3
        conn = sqlite3.connect(test_db)
        print()
        print("Source breakdown:")
        for r in conn.execute("SELECT source, COUNT(*) FROM prices "
                              f"WHERE ticker='{ticker}' GROUP BY source"):
            mark = "✓" if r[0] == "fmp" else "⚠"
            print(f"  {mark} prices: {r[1]} rows from {r[0]}")
            if r[0] != "fmp":
                all_pass = False
        for r in conn.execute("SELECT source, COUNT(*) FROM quarterly_financials "
                              f"WHERE ticker='{ticker}' GROUP BY source"):
            mark = "✓" if r[0] == "fmp" else "⚠"
            print(f"  {mark} quarterly: {r[1]} rows from {r[0]}")
            if r[0] != "fmp":
                all_pass = False
        for r in conn.execute("SELECT source, COUNT(*) FROM key_metrics_quarterly "
                              f"WHERE ticker='{ticker}' GROUP BY source"):
            print(f"  ✓ key_metrics: {r[1]} rows from {r[0]}")

        # Volume / depth checks
        print()
        print("Data depth:")
        n_q = len(quarterly)
        mark = "✓" if n_q >= 15 else "⚠"
        print(f"  {mark} quarterly rows: {n_q} (expect ≥15 for FMP; yfinance gives 5)")
        if n_q < 15:
            all_pass = False

        n_km = len(km)
        mark = "✓" if n_km >= 15 else "⚠"
        print(f"  {mark} key_metrics rows: {n_km} (FMP-only; yfinance gives 0)")
        if n_km < 15:
            all_pass = False

        n_px = len(prices)
        mark = "✓" if n_px >= 350 else "⚠"
        print(f"  {mark} price rows: {n_px} (expect ≥350)")
        if n_px < 350:
            all_pass = False

        # Show actual content snippets
        print()
        print("Sample quarterly EPS (oldest → newest):")
        print(quarterly[["period_end", "eps_diluted", "revenue",
                         "eps_estimate", "eps_surprise_pct"]]
              .to_string(index=False, max_rows=25))

        if not km.empty:
            print()
            print("Sample key metrics (ROE / margins per quarter):")
            print(km[["period_end", "roe", "gross_margin",
                     "operating_margin", "net_margin"]]
                  .to_string(index=False, max_rows=25))

        print()
        print("Fetch log (newest first):")
        for r in conn.execute(
                "SELECT timestamp, source, ticker, endpoint, status, "
                "duration_ms, rows FROM fetch_log ORDER BY id DESC LIMIT 10"):
            print(f"  {r[0]}  {r[1]:8s}  {r[3]:30s}  "
                  f"{r[4]:6s}  {r[5]:>5}ms  rows={r[6]}")

    print()
    print("=" * 70)
    print(f"OVERALL: {'✓ FMP BACKEND ACTIVE' if all_pass else '✗ ISSUES — see warnings above'}")
    print("=" * 70)
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
