"""TW Stage-2 + tight-base candidates (a saved TradingView 'vcp' screen for Taiwan stocks).

Replicates a TradingView screener for Taiwan Stage-2 + liquid candidates:
  beta_1_year > 1
  market_cap_basic >= 2B TWD
  close >= SMA200            (already in Stage 2)
  AvgValue.Traded_10d > 900M (sufficient liquidity)
  is_primary = true          (no secondary listings)
  + typespec filter: only common/preferred stock, DRs, or non-ETF funds
"""
from tradingview_screener import Query, Column

MARKET = "taiwan"
DESCRIPTION = "TW Stage-2 candidates (beta>1, mcap>2B, above 200d MA, liquid)"


def query() -> Query:
    return (Query()
            .select(
                "name", "description", "close", "change", "volume",
                "market_cap_basic", "beta_1_year",
                "AvgValue.Traded_10d", "sector", "industry",
            )
            .where(
                Column("beta_1_year") > 1,
                Column("market_cap_basic") >= 2_000_000_000,
                Column("close") >= Column("SMA200"),
                Column("AvgValue.Traded_10d") > 900_000_000,
                Column("is_primary") == True,
                Column("type") == "stock",
                Column("typespecs").has(["common"]),
                Column("typespecs").has_none_of(["pre-ipo"]),
            )
            .set_markets(MARKET)
            .order_by("market_cap_basic", ascending=False)
            .limit(300))


def to_yfinance(tv_ticker: str) -> str:
    """Convert TradingView ticker → yfinance suffix format.

    Examples:
        'TWSE:2330'  → '2330.TW'
        'TPEX:5274'  → '5274.TWO'
    """
    if ":" not in tv_ticker:
        return tv_ticker
    exch, sym = tv_ticker.split(":", 1)
    suffix = {"TWSE": ".TW", "TPEX": ".TWO"}.get(exch, "")
    return sym + suffix
