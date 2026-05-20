#!/usr/bin/env python3
"""warm_watchlist — runs configured TradingView scans, pre-fills market.db.

This is the weekly cache-warming worker. Designed to run via launchd (or
manually) with no Claude involvement → zero AI tokens for data fetching.

Workflow:
  1. Discover all `scans/<name>.py` modules
  2. For each scan, run the TradingView query to get a fresh ticker list
  3. For every ticker, hit MarketDataClient.get_prices / get_quarterly /
     get_info — these write to ~/.config/market_data/market.db
  4. Write a per-run summary to ~/.config/market_data/warm.log
  5. Save the ticker list as JSON at ~/.config/market_data/scans/<name>.tickers.json
     so Claude can re-use it during the week without re-querying TradingView.

Usage:
  ~/.config/market_data/venv/bin/python ~/.config/market_data/warm_watchlist.py
  ~/.config/market_data/venv/bin/python ~/.config/market_data/warm_watchlist.py --scan vcp_tw
  ~/.config/market_data/venv/bin/python ~/.config/market_data/warm_watchlist.py --dry-run
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

# Wire up the shared library path
_BASE = Path.home() / ".config" / "market_data"
if str(_BASE) not in sys.path:
    sys.path.insert(0, str(_BASE))


# ── Optional: load .env file for FMP_API_KEY without exposing it ─────────
def _load_dotenv() -> None:
    """Read KEY=value pairs from ~/.config/market_data/.env if it exists.

    Convenient way to supply FMP_API_KEY to launchd-run jobs without baking
    the key into the plist. File should be chmod 600.
    """
    env_file = _BASE / ".env"
    if not env_file.exists():
        return
    try:
        for raw in env_file.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip().strip("\"'")
            # Only set if not already in env (env takes precedence)
            os.environ.setdefault(k, v)
    except Exception as e:
        print(f"[warn] failed to read .env: {type(e).__name__}", file=sys.stderr)


_load_dotenv()

try:
    from marketdata import MarketDataClient
except ImportError as e:
    print(f"FATAL: marketdata lib not importable: {e}", file=sys.stderr)
    print(f"  expected at {_BASE / 'marketdata'}", file=sys.stderr)
    sys.exit(2)


SCANS_DIR = _BASE / "scans"
LOG_FILE = _BASE / "warm.log"
TICKERS_DIR = SCANS_DIR  # save tickers next to the scan modules


# ── Logging — append-only, structured one-line entries ──────────────────
class Logger:
    def __init__(self, log_file: Path = LOG_FILE) -> None:
        self.f = open(log_file, "a", buffering=1)  # line-buffered
        self.console = sys.stdout
        self._start = time.monotonic()

    def log(self, level: str, msg: str) -> None:
        ts = datetime.now().isoformat(timespec="seconds")
        line = f"{ts} [{level}] {msg}\n"
        self.f.write(line)
        self.console.write(line)

    def close(self) -> None:
        self.f.close()


# ── Discover available scans ────────────────────────────────────────────
def discover_scans() -> list[str]:
    if not SCANS_DIR.exists():
        return []
    out = []
    for p in sorted(SCANS_DIR.glob("*.py")):
        if p.name.startswith("_"):
            continue
        out.append(p.stem)
    return out


def load_scan(name: str):
    return importlib.import_module(f"scans.{name}")


# ── Run a single scan + warm the cache ───────────────────────────────────
def run_scan(name: str, log: Logger, dry_run: bool = False,
             max_tickers: int | None = None) -> dict[str, Any]:
    """Returns a summary dict. Does NOT raise — failures are captured."""
    summary: dict[str, Any] = {
        "scan": name,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "candidates": 0,
        "warmed": 0,
        "failed": 0,
        "duration_s": 0.0,
        "tickers": [],
    }
    t0 = time.monotonic()

    try:
        mod = load_scan(name)
    except Exception as e:
        log.log("ERROR", f"scan={name} load failed: {e}")
        summary["error"] = f"import: {e}"
        return summary

    log.log("INFO", f"scan={name} — {getattr(mod, 'DESCRIPTION', '(no desc)')}")

    # Run the TradingView query
    try:
        q = mod.query()
        count, df = q.get_scanner_data()
        summary["candidates"] = int(count)
        log.log("INFO", f"scan={name} TV returned {count} candidates "
                        f"(market={getattr(mod, 'MARKET', '?')})")
    except Exception as e:
        log.log("ERROR", f"scan={name} TV query failed: {e}")
        summary["error"] = f"tv: {e}"
        return summary

    if df.empty:
        log.log("WARN", f"scan={name} produced 0 tickers — nothing to warm")
        return summary

    # Convert TV ticker → yfinance suffix using the scan's own helper
    to_yf = getattr(mod, "to_yfinance", lambda t: t.split(":")[-1])
    yf_tickers = [to_yf(t) for t in df["ticker"]]
    summary["tickers"] = yf_tickers

    if max_tickers:
        yf_tickers = yf_tickers[:max_tickers]
        log.log("INFO", f"scan={name} truncated to {len(yf_tickers)} tickers "
                        f"(--max-tickers)")

    # Save ticker list for re-use during the week
    tickers_file = TICKERS_DIR / f"{name}.tickers.json"
    if not dry_run:
        tickers_file.write_text(json.dumps({
            "scan": name,
            "market": getattr(mod, "MARKET", None),
            "generated_at": summary["started_at"],
            "count": len(yf_tickers),
            "tickers": yf_tickers,
        }, indent=2))
        log.log("INFO", f"scan={name} wrote {tickers_file.name}")

    if dry_run:
        log.log("INFO", f"scan={name} DRY-RUN — skipping cache warm")
        summary["duration_s"] = round(time.monotonic() - t0, 1)
        return summary

    # Warm the cache. Strategy:
    #   prices       → always refetch (need daily-fresh OHLCV for VCP detection)
    #   quarterly    → refetch only if > 144h old (financials only update at earnings)
    #   info         → refetch only if > 144h old (sector/mcap don't move daily)
    #   key_metrics  → refetch only if > 144h old (FMP-only)
    # The 144h (6-day) threshold means a Saturday cron always finds the data
    # stale enough to refresh, but mid-week manual runs don't burn the API.
    warmed = 0
    failed = 0
    with MarketDataClient(skill_name="warm_watchlist") as c:
        for i, tk in enumerate(yf_tickers, 1):
            try:
                prices = c.get_prices(tk, days=400, force_refresh=True)
                if prices.empty:
                    log.log("WARN", f"  {tk}: no price data — skipping rest")
                    failed += 1
                    continue
                c.get_quarterly(tk, quarters=20, max_age_hours=144)
                c.get_info(tk, max_age_hours=144)
                if os.environ.get("FMP_API_KEY"):
                    c.get_key_metrics(tk, max_age_hours=144)
                warmed += 1
                if i % 20 == 0:
                    log.log("INFO", f"  …{i}/{len(yf_tickers)} warmed "
                                    f"({warmed} ok, {failed} fail)")
            except Exception as e:
                failed += 1
                log.log("WARN", f"  {tk}: {type(e).__name__}: {str(e)[:120]}")

    summary["warmed"] = warmed
    summary["failed"] = failed
    summary["duration_s"] = round(time.monotonic() - t0, 1)
    log.log("INFO", f"scan={name} done: {warmed} warmed / {failed} failed "
                    f"in {summary['duration_s']:.1f}s")
    return summary


# ── Main entrypoint ─────────────────────────────────────────────────────
def main() -> int:
    p = argparse.ArgumentParser(description="Warm shared market-data cache from "
                                            "TradingView screener results.")
    p.add_argument("--scan", help="Run only this scan (default: all)")
    p.add_argument("--list", action="store_true", help="List available scans and exit")
    p.add_argument("--dry-run", action="store_true",
                   help="Run scans + save ticker lists, but skip cache warm")
    p.add_argument("--max-tickers", type=int, default=None,
                   help="Cap tickers per scan (for testing)")
    args = p.parse_args()

    all_scans = discover_scans()
    if args.list:
        print(f"Available scans (in {SCANS_DIR}):")
        for s in all_scans:
            try:
                m = load_scan(s)
                desc = getattr(m, "DESCRIPTION", "(no description)")
                mkt = getattr(m, "MARKET", "?")
            except Exception as e:
                desc = f"<failed to load: {e}>"
                mkt = "?"
            print(f"  {s:20s}  market={mkt:10s}  {desc}")
        return 0

    if args.scan:
        scans_to_run = [args.scan] if args.scan in all_scans else []
        if not scans_to_run:
            print(f"Unknown scan: {args.scan}", file=sys.stderr)
            print(f"Available: {all_scans}", file=sys.stderr)
            return 2
    else:
        scans_to_run = all_scans

    if not scans_to_run:
        print("No scans found in", SCANS_DIR, file=sys.stderr)
        return 2

    log = Logger()
    log.log("INFO", "═" * 70)
    log.log("INFO", f"warm_watchlist start — scans: {scans_to_run}")
    log.log("INFO", f"FMP_API_KEY: {'set' if os.environ.get('FMP_API_KEY') else 'not set (yfinance fallback)'}")

    summaries: list[dict[str, Any]] = []
    overall_t0 = time.monotonic()

    for scan_name in scans_to_run:
        try:
            s = run_scan(scan_name, log, dry_run=args.dry_run,
                         max_tickers=args.max_tickers)
            summaries.append(s)
        except KeyboardInterrupt:
            log.log("WARN", "Interrupted")
            return 130
        except Exception as e:
            log.log("ERROR", f"scan={scan_name} unexpected: {e}")
            log.log("ERROR", traceback.format_exc())

    total_t = time.monotonic() - overall_t0
    log.log("INFO", "─" * 70)
    log.log("INFO", f"FINAL SUMMARY (total {total_t:.1f}s):")
    for s in summaries:
        log.log("INFO", f"  {s['scan']:15s}  candidates={s['candidates']:>4}  "
                        f"warmed={s['warmed']:>4}  failed={s['failed']:>3}  "
                        f"time={s['duration_s']:.1f}s")
    log.log("INFO", "═" * 70)
    log.close()

    # Exit non-zero if any scan had > 20% failures (signal for cron alerting)
    for s in summaries:
        total = s["warmed"] + s["failed"]
        if total > 5 and s["failed"] / total > 0.20:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
