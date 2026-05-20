#!/usr/bin/env python3
"""
Fetch historical quarterly data for a ticker — backed by shared MarketDataClient.

Outputs (unchanged from v1):
  - CSV to stdout (paste into visualize.html "Custom CSV" box)
  - JSON to ~/.config/forward-rdcf/cache/{ticker}.json (for programmatic use)

Migration note (Phase 3, 2026-05-20):
  Previously called yfinance directly; now delegates to the shared
  MarketDataClient at ~/.config/market_data/. This means RDCF, the Minervini
  screener, and any future skill all share one cache. Output format is
  preserved so visualize.html and compute.py continue to work unchanged.

Usage:
  ~/.config/forward-rdcf/venv/bin/python \
    ~/.claude/skills/forward-rdcf/fetch_history.py NVDA
  ~/.config/forward-rdcf/venv/bin/python \
    ~/.claude/skills/forward-rdcf/fetch_history.py NVDA --quarters 16
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Shared market-data library
_MARKET_DATA_DIR = Path.home() / ".config" / "market_data"
if str(_MARKET_DATA_DIR) not in sys.path:
    sys.path.insert(0, str(_MARKET_DATA_DIR))

try:
    import pandas as pd
    from marketdata import MarketDataClient
except ImportError as e:
    print(
        "Missing deps. Install:  ~/.config/forward-rdcf/venv/bin/pip "
        "install yfinance pandas\n"
        f"  also requires shared market_data lib at {_MARKET_DATA_DIR}\n"
        f"  underlying error: {e}",
        file=sys.stderr,
    )
    sys.exit(2)

CACHE_DIR = Path.home() / ".config" / "forward-rdcf" / "cache"


def get_filing_date(period_end: "pd.Timestamp") -> "pd.Timestamp":
    """Approximate filing date as ~30 days after period end (10-Q window)."""
    return period_end + pd.Timedelta(days=30)


def get_close_price_on_or_before(prices_df: "pd.DataFrame",
                                  target_date: "pd.Timestamp") -> float:
    """Find closing price on target_date or nearest trading day before."""
    if prices_df is None or prices_df.empty:
        return float("nan")
    mask = prices_df.index <= target_date
    if not mask.any():
        return float("nan")
    return float(prices_df.loc[mask, "close"].iloc[-1])


def quarter_label_calendar(date: "pd.Timestamp") -> str:
    q = (date.month - 1) // 3 + 1
    return f"Q{q} {date.year}"


def build_dataset(ticker: str, n_quarters: int) -> list[dict]:
    with MarketDataClient(skill_name="forward-rdcf") as c:
        # Pull more price history than minervini does — we need prices going
        # back ~4-5 years for older quarters' filing dates.
        prices_df = c.get_prices(ticker, days=1500)
        qfin_df = c.get_quarterly(ticker, quarters=n_quarters)

    if prices_df.empty or qfin_df.empty:
        return []

    # qfin_df is sorted ascending by period_end (oldest first) — same order
    # as the old fetch_history output.
    rows: list[dict] = []
    for _, q in qfin_df.iterrows():
        eps = q.get("eps_diluted")
        if pd.isna(eps):
            continue
        period_end = q["period_end"]
        filing_date = get_filing_date(period_end)
        price = get_close_price_on_or_before(prices_df, filing_date)
        consensus = q.get("eps_estimate")
        consensus_val = (round(float(consensus), 4)
                         if pd.notna(consensus) and consensus is not None
                         else None)
        rows.append({
            "q": quarter_label_calendar(period_end),
            "date": filing_date.strftime("%Y-%m-%d"),
            "price": round(price, 2) if price == price else None,  # NaN-safe
            "eps": round(float(eps), 4),
            "consensus_eps": consensus_val,
            "fiscal_period_end": period_end.strftime("%Y-%m-%d"),
        })
    return rows


def to_csv(rows: list[dict]) -> str:
    has_consensus = any(r.get("consensus_eps") is not None for r in rows)
    if has_consensus:
        lines = ["q,date,price,eps,consensus_eps"]
        for r in rows:
            if r["price"] is None or r["eps"] is None:
                continue
            cons = r.get("consensus_eps")
            cons_str = f"{cons}" if cons is not None else ""
            lines.append(f'{r["q"]},{r["date"]},{r["price"]},{r["eps"]},{cons_str}')
    else:
        lines = ["q,date,price,eps"]
        for r in rows:
            if r["price"] is None or r["eps"] is None:
                continue
            lines.append(f'{r["q"]},{r["date"]},{r["price"]},{r["eps"]}')
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description="Fetch quarterly history via MarketDataClient")
    p.add_argument("ticker", help="Ticker symbol, e.g. NVDA")
    p.add_argument("--quarters", type=int, default=20,
                   help="How many quarters back (default 20). "
                        "Note: yfinance free tier currently returns ~4-5; "
                        "FMP integration (Phase 4) lifts this to 20.")
    p.add_argument("--cache-only", action="store_true",
                   help="Only write JSON cache, no CSV to stdout")
    args = p.parse_args()

    ticker = args.ticker.upper()
    rows = build_dataset(ticker, args.quarters)

    if not rows:
        print(f"No data for {ticker}", file=sys.stderr)
        return 1

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"{ticker}.json"
    cache_file.write_text(json.dumps(rows, indent=2))
    print(f"Cache written: {cache_file} ({len(rows)} rows)", file=sys.stderr)

    if not args.cache_only:
        print(to_csv(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
