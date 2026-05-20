# trade_with_what_he_see

Personal Minervini-style stock screening pipeline built as a set of Claude Code skills + a shared local data cache.

The name nods to *Trade Like a Stock Market Wizard* (Mark Minervini, 2013) — the system trades based on what the chart shows, not what the news says.

## What's in here

| Path | Purpose |
|---|---|
| `skills/market-data-warm/` | Claude skill: runs TradingView scans + warms the local cache via launchd cron |
| `skills/minervini-screener/` | Claude skill: 8-criteria Trend Template + Weinstein Stage + VCP detection + CAN SLIM-style fundamentals gate |
| `skills/forward-rdcf/` | Claude skill: forward-based reverse DCF (computes implied EPS CAGR) |
| `market_data/` | Shared Python library — `MarketDataClient` + SQLite cache + yfinance/FMP backends |
| `market_data/scans/` | TradingView screener queries saved as Python code |

## Architecture

```
                ┌────────────────────────────────────────────┐
                │ Saturday 09:00 (launchd cron)              │
                │   warm_watchlist.py                        │
                │   1. Run TradingView scans (vcp_tw, …)     │
                │   2. Fetch prices/quarterly/info per ticker │
                │   3. Write to ~/.config/market_data/        │
                │      market.db (shared SQLite)             │
                │   → ZERO AI tokens spent                   │
                └────────────────────────────────────────────┘
                                  ↓
                ┌────────────────────────────────────────────┐
                │ During the week                            │
                │   You ask Claude "scan my TW watchlist"    │
                │   → minervini-screener hits warm cache     │
                │   → ranked verdicts in ~5 seconds          │
                │   → ~6k tokens (analysis only)             │
                └────────────────────────────────────────────┘
```

## Install

1. Clone this repo. The contents are meant to be copied into your home dir:

   ```bash
   git clone https://github.com/garyho1998/trade_with_what_he_see.git
   cd trade_with_what_he_see

   # Skills go into ~/.claude/skills/
   mkdir -p ~/.claude/skills
   cp -r skills/* ~/.claude/skills/

   # Shared library goes into ~/.config/market_data/
   mkdir -p ~/.config/market_data
   cp -r market_data/* ~/.config/market_data/
   ```

2. Set up a Python venv (or symlink to an existing one with yfinance/pandas/numpy):

   ```bash
   python3 -m venv ~/.config/market_data/venv
   ~/.config/market_data/venv/bin/pip install yfinance pandas numpy tradingview-screener
   ```

3. (Optional) Enable FMP for richer fundamentals data:

   ```bash
   echo 'FMP_API_KEY=your_key_here' > ~/.config/market_data/.env
   chmod 600 ~/.config/market_data/.env
   ```

   Without FMP_API_KEY, the system uses yfinance only (5 quarters of EPS instead of 20; no ROE trend).

4. Run a one-shot test:

   ```bash
   ~/.config/market_data/venv/bin/python ~/.config/market_data/warm_watchlist.py --dry-run
   ```

5. Install the weekly launchd cron (see `skills/market-data-warm/references/launchd_install.md` for full details):

   ```bash
   # IMPORTANT: edit com.user.market-data.warm.plist first to replace
   # /Users/garyho/ with your own home dir paths
   cp market_data/com.user.market-data.warm.plist ~/Library/LaunchAgents/
   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.user.market-data.warm.plist
   ```

## Daily usage

Ask Claude:
- "Scan my TW watchlist" → triggers `market-data-warm` skill, reads warm cache, runs `minervini-screener`
- "Run Minervini on NVDA,GOOGL,AVGO" → direct screener call (still hits warm cache for any prior-warmed ticker)
- "What's in my latest scan?" → reports the last TradingView scan results
- "Forward RDCF on NVDA at $220, EPS $4.90, exit 25x" → triggers `forward-rdcf` skill

The skills are configured to triggering keywords; see each `SKILL.md` for the full list.

## Methodology

The screener follows Mark Minervini's published SEPA (Specific Entry Point Analysis):

1. **Trend** — Stage 2 uptrend + 8 Trend Template criteria (mechanical)
2. **Entry** — VCP (Volatility Contraction Pattern) candidate + breakout-ready trigger
3. **Fundamentals** — Currently configured as a CAN SLIM-style **hard gate** (Option B): rejects if `fund.score < 2/3` (EPS growth ≥ 25%, sales ≥ 25%, ROE ≥ 17%). Set `FUND_GATE_THRESHOLD = 0` in `screen.py` to switch back to pure Minervini behaviour where fundamentals only inform the verdict.
4. **Catalyst** — Out of scope; you supply via your own research
5. **Risk** — Out of scope; the screener flags candidates, you set stops

See `skills/minervini-screener/SKILL.md` and `skills/minervini-screener/references/methodology.md` for the full methodology.

## Sources

- Mark Minervini, *Trade Like a Stock Market Wizard* (2013)
- Mark Minervini, *Think & Trade Like a Champion* (2017)
- Stan Weinstein, *Secrets for Profiting in Bull and Bear Markets* (1988)
- William O'Neil, *How to Make Money in Stocks* (CAN SLIM framework)

## License

Personal use. No warranty. Not investment advice — always verify the math against the underlying sources before risking capital.
