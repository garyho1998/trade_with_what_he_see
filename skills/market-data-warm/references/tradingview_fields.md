# TradingView Scanner — Field Name Reference

The unofficial scanner endpoint at `https://scanner.tradingview.com/{market}/scan`
uses internal field names that don't always match the UI labels. **The single
most reliable way** to discover the right field is to open your screener in
the browser, open devtools → Network tab, trigger a refresh, and inspect the
POST request body. That gives you the exact field name TradingView uses.

This file catalogs the most common ones for Minervini-style screening.

## Filters Gary's `vcp` saved screen actually uses

| UI label | API field |
|---|---|
| Beta 1Y | `beta_1_year` (NOT `beta_5_year`) |
| Mkt cap > 2B TWD | `market_cap_basic` (in local currency) |
| Price > SMA(200) | `close` > `"SMA200"` (string literal, not a column) |
| Price × avg vol 10D | `AvgValue.Traded_10d` (single field — NOT `close * volume`) |
| Primary listing | `is_primary` == true |
| Common stock only | `type` == "stock" AND `typespecs` has `["common"]` |

## Common dollar-volume fields

UI labels are inconsistent. Use the time window you actually want:

| Window | API field |
|---|---|
| 3-day | `AvgValue.Traded_3d` |
| 5-day | `AvgValue.Traded_5d` |
| 10-day | `AvgValue.Traded_10d` |
| 30-day | `AvgValue.Traded_30d` |
| 60-day | `AvgValue.Traded_60d` |
| 90-day | `AvgValue.Traded_90d` |

`Value.Traded` (no suffix) = today's dollar volume (close × today's volume). Useful for "biggest movers today" filters, not for liquidity screens.

## Volume fields (share count, not $)

| UI label | API field |
|---|---|
| Volume | `volume` (today's) |
| Avg volume 10D | `average_volume_10d_calc` |
| Avg volume 30D | `average_volume_30d_calc` |
| Avg volume 60D | `average_volume_60d_calc` |
| Avg volume 90D | `average_volume_90d_calc` |
| Relative volume 10D | `relative_volume_10d_calc` |

## Fundamentals

| UI label | API field |
|---|---|
| Market cap | `market_cap_basic` (local currency) |
| Market cap USD | `market_cap_basic_usd` |
| P/E | `price_earnings_ttm` |
| Forward P/E | `price_earnings_current_fy` |
| EPS dil growth (YoY) | `earnings_per_share_diluted_yoy_growth_ttm` |
| Revenue growth | `total_revenue_yoy_growth_ttm` |
| ROE | `return_on_equity` |
| Dividend yield | `dividends_yield_current` |
| PEG | `price_earnings_growth_ttm` |

## Technical / price

| UI label | API field |
|---|---|
| Close | `close` |
| Change % (1D) | `change` |
| Perf 1W | `Perf.W` |
| Perf 1M | `Perf.1M` |
| Perf 3M | `Perf.3M` |
| Perf YTD | `Perf.YTD` |
| Perf 1Y | `Perf.Y` |
| Perf 5Y | `Perf.5Y` |
| SMA 50 | `SMA50` (use as right-side of comparison) |
| SMA 100 | `SMA100` |
| SMA 200 | `SMA200` |
| EMA 50 | `EMA50` |
| RSI (14) | `RSI` |

## Type filters (the boolean filter2 tree)

To replicate TradingView's "All stocks" default (common stocks + preferred + DRs + active funds, excluding pre-IPO/ETF/mutual):

```json
"filter2": {
  "operator": "and",
  "operands": [
    {"operation": {"operator": "or", "operands": [
      {"operation": {"operator": "and", "operands": [
        {"expression": {"left": "type", "operation": "equal", "right": "stock"}},
        {"expression": {"left": "typespecs", "operation": "has", "right": ["common"]}}
      ]}},
      {"operation": {"operator": "and", "operands": [
        {"expression": {"left": "type", "operation": "equal", "right": "stock"}},
        {"expression": {"left": "typespecs", "operation": "has", "right": ["preferred"]}}
      ]}},
      {"operation": {"operator": "and", "operands": [
        {"expression": {"left": "type", "operation": "equal", "right": "dr"}}
      ]}},
      {"operation": {"operator": "and", "operands": [
        {"expression": {"left": "type", "operation": "equal", "right": "fund"}},
        {"expression": {"left": "typespecs", "operation": "has_none_of", "right": ["etf", "mutual"]}}
      ]}}
    ]}},
    {"expression": {"left": "typespecs", "operation": "has_none_of", "right": ["pre-ipo"]}}
  ]
}
```

`typespecs` values include: `common`, `preferred`, `etf`, `mutual`, `pre-ipo`,
`reit`, `adr`, etc.

`type` values include: `stock`, `dr` (depositary receipt), `fund`, `bond`,
`structured`, `index`, `economic`, `crypto`, `forex`.

## Operators

| Operator | Meaning |
|---|---|
| `equal` | == |
| `not_equal` | != |
| `greater` | > (strict) |
| `egreater` | >= (extended/equal greater) |
| `less` | < |
| `eless` | <= |
| `in_range` | value in array |
| `nin_range` | value NOT in array |
| `has` | array field contains value |
| `has_none_of` | array field contains NONE of the values |
| `crosses` | technical: cross-over event |
| `crosses_above` / `crosses_below` | directional crosses |

## Markets

| `markets` value | Coverage |
|---|---|
| `america` | US (NYSE, NASDAQ, AMEX, OTC) |
| `taiwan` | TWSE + TPEX |
| `hongkong` | HKEX |
| `japan` | TSE (1ST/2ND) + JASDAQ |
| `korea` | KOSPI + KOSDAQ |
| `singapore` | SGX |
| `india` | NSE + BSE |
| `china` | SSE + SZSE |
| `crypto` | Cryptocurrencies (uses different field set!) |
| `forex` | FX pairs |
| `cfd` | CFD instruments |

## The "is_primary" gotcha (US only)

For US stocks, `is_primary == true` excludes secondary listings of foreign
companies — e.g. without it you'll see Toyota's NYSE listing AND its Tokyo
listing as duplicates. Always include this filter for US scans. Other markets
typically don't need it.

## How to discover a field name you don't know

1. Open TradingView, set up the filter you want via the UI
2. Open browser devtools → Network tab
3. Trigger a refresh (or just move a filter slightly)
4. Find the POST request to `scanner.tradingview.com/{market}/scan`
5. Click "Payload" → copy the JSON body
6. The `filter` array has the field name TradingView uses internally
7. Now use that exact field name in your `tradingview-screener` Query

This is the single highest-leverage skill for working with the unofficial API.
