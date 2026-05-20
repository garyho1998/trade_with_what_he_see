"""Smoke test for MarketDataClient.

Exercises get_prices, get_quarterly, get_info on a real ticker.
Verifies: data round-trips through SQLite, cache hits on second call,
fetch_log records both calls correctly.
"""
import sys
import time
from pathlib import Path

# Add lib dir to path
sys.path.insert(0, str(Path.home() / ".config" / "market_data"))

from marketdata import MarketDataClient


def check(label: str, cond: bool, detail: str = "") -> bool:
    mark = "✓ PASS" if cond else "✗ FAIL"
    print(f"  {mark}  {label}  {detail}")
    return cond


def main() -> int:
    # Use a clean test DB so we don't pollute the real one
    test_db = Path("/tmp/market_data_test.db")
    if test_db.exists():
        test_db.unlink()

    all_pass = True
    print("\n[1] First-fetch path — DB empty, all data should come from yfinance")
    print("=" * 70)
    t0 = time.monotonic()
    with MarketDataClient(db_path=test_db, skill_name="smoketest") as c:
        # Prices
        prices = c.get_prices("NVDA", days=400)
        all_pass &= check("prices not empty", not prices.empty,
                          f"got {len(prices)} rows")
        all_pass &= check("prices has OHLCV columns",
                          set(prices.columns) >= {"open", "high", "low", "close", "volume"},
                          f"cols={list(prices.columns)}")
        all_pass &= check("prices index is DatetimeIndex",
                          str(prices.index.dtype).startswith("datetime"),
                          f"dtype={prices.index.dtype}")
        all_pass &= check("prices ≥ 200 rows for 200-day MA",
                          len(prices) >= 200,
                          f"got {len(prices)}")

        # Quarterly
        qfin = c.get_quarterly("NVDA", quarters=20)
        all_pass &= check("quarterly not empty", not qfin.empty,
                          f"got {len(qfin)} quarters")
        all_pass &= check("quarterly has eps_diluted",
                          "eps_diluted" in qfin.columns,
                          f"cols={list(qfin.columns)}")

        # Info
        info = c.get_info("NVDA")
        all_pass &= check("info has long_name", bool(info.get("long_name")),
                          f"name={info.get('long_name')}")
        all_pass &= check("info has sector", bool(info.get("sector")),
                          f"sector={info.get('sector')}")

        first_call_secs = time.monotonic() - t0
        print(f"\n  Total time for first fetch: {first_call_secs:.1f}s")

        # Inspect cache state
        cs = c.cache_summary("NVDA")
        print(f"\n  Cache state for NVDA:")
        print(cs.to_string(index=False) if not cs.empty else "  (empty)")
        all_pass &= check("cache_state has prices+quarterly+info",
                          len(cs) == 3,
                          f"got {len(cs)} rows")

    print("\n[2] Cache-hit path — second client instance, same DB")
    print("=" * 70)
    t1 = time.monotonic()
    with MarketDataClient(db_path=test_db, skill_name="smoketest") as c:
        prices2 = c.get_prices("NVDA", days=400)
        qfin2 = c.get_quarterly("NVDA")
        info2 = c.get_info("NVDA")
        cache_hit_secs = time.monotonic() - t1
        all_pass &= check("cache hit much faster than fetch",
                          cache_hit_secs < first_call_secs / 5,
                          f"cache={cache_hit_secs:.2f}s vs first={first_call_secs:.1f}s")
        all_pass &= check("cached prices same row count",
                          len(prices2) == len(prices),
                          f"{len(prices2)} vs {len(prices)}")
        all_pass &= check("cached qfin same row count",
                          len(qfin2) == len(qfin),
                          f"{len(qfin2)} vs {len(qfin)}")
        all_pass &= check("cached info same long_name",
                          info2.get("long_name") == info.get("long_name"))

    print("\n[3] fetch_log audit")
    print("=" * 70)
    with MarketDataClient(db_path=test_db, skill_name="smoketest") as c:
        log = c.fetch_log_tail(20)
        print(log.to_string(index=False) if not log.empty else "  (empty)")
        ok_calls = log[log["status"] == "ok"] if not log.empty else log
        all_pass &= check("at least 3 successful fetches logged",
                          len(ok_calls) >= 3,
                          f"got {len(ok_calls)}")
        all_pass &= check("skill_name recorded",
                          (log["skill"] == "smoketest").all() if not log.empty else False,
                          "all rows tagged smoketest")

    print("\n[4] Idempotence — force refresh, should INSERT OR REPLACE without error")
    print("=" * 70)
    with MarketDataClient(db_path=test_db, skill_name="smoketest") as c:
        before = len(c.get_prices("NVDA"))
        c.get_prices("NVDA", force_refresh=True)
        after = len(c.get_prices("NVDA"))
        all_pass &= check("row count stable after refresh",
                          abs(before - after) <= 2,  # ±2 for new bars since last fetch
                          f"before={before} after={after}")

    print(f"\n{'=' * 70}")
    print(f"OVERALL: {'✓ ALL TESTS PASS' if all_pass else '✗ SOME FAILED'}")
    print(f"{'=' * 70}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
