"""US Stage-2 + tight-base candidates — same filter shape as vcp_tw.

Tightened thresholds for US market liquidity (different scale than TWD):
  beta_1_year > 1
  market_cap_basic >= 2B USD
  close >= SMA200
  AvgValue.Traded_10d > 50M USD   (US dollar volume — much lower threshold than TWD)
  is_primary = true
"""
from tradingview_screener import Query, Column

MARKET = "america"
DESCRIPTION = "US Stage-2 candidates (beta>1, mcap>2B, above 200d MA, liquid)"


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
                Column("AvgValue.Traded_10d") > 50_000_000,
                Column("is_primary") == True,
                Column("type") == "stock",
                Column("typespecs").has(["common"]),
                Column("typespecs").has_none_of(["pre-ipo"]),
            )
            .set_markets(MARKET)
            .order_by("market_cap_basic", ascending=False)
            .limit(300))


def to_yfinance(tv_ticker: str) -> str:
    """US tickers don't need a suffix in yfinance."""
    if ":" not in tv_ticker:
        return tv_ticker
    _, sym = tv_ticker.split(":", 1)
    return sym
