---
name: market-data-warm
description: Run TradingView screener scans and pre-warm the shared market.db cache, OR query previously-warmed scan results without re-fetching. Use this skill whenever the user mentions "warm cache", "warm watchlist", "update market data", "weekly scan", "run my screener", "refresh prices", "scan my TW/US watchlist", or asks to scan/analyze a list of stocks that came from a saved TradingView screen. Also use when the user asks "what tickers are in my latest scan?" or "show me last week's scan results". This skill is the bridge between TradingView screener filters and the local market.db that minervini-screener / forward-rdcf / bubble-watch / company-deep-dive all read from. It runs as pure Python (no API calls during Claude's reply) — invoke it whenever the user wants fresh tickers fed into any downstream analysis skill.
---

# Market Data Warm

Pre-fills the shared `market.db` (at `~/.config/market_data/`) with prices, quarterly financials, and metadata for tickers coming from saved TradingView screener queries. Designed so the heavy data-fetching runs **outside** Claude conversations — via launchd cron — and Claude only does the analysis on cache-warm data.

## When to invoke

Run this skill (or just read its cached results) when:

- User says any variant of: "warm cache", "warm my watchlist", "update market data", "refresh prices", "run my weekly scan", "scan my TW watchlist", "scan my US watchlist"
- User asks to analyze stocks from their TradingView screener output (instead of providing tickers manually)
- User says "what's in my latest scan?" or "show me last week's TW candidates"
- Before running any downstream skill (`minervini-screener`, `forward-rdcf`, `bubble-watch`) on a large universe — verify the warm is fresh first

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│ Saturday 09:00 HKT (Friday after US close)                   │
│   launchd → warm_watchlist.py                                │
│   1. Run TradingView scans (vcp_tw, vcp_us, …)               │
│   2. For each ticker: MarketDataClient.get_prices /          │
│      get_quarterly / get_info                                │
│   3. Save ticker lists → ~/.config/market_data/scans/        │
│      vcp_tw.tickers.json, vcp_us.tickers.json                │
│   4. Append summary → ~/.config/market_data/warm.log         │
│   ⚠ ZERO Claude tokens spent — pure Python                   │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│ Any time during the week                                     │
│   User asks Claude "run Minervini on my TW screen"           │
│   → Claude reads vcp_tw.tickers.json                         │
│   → Pipes ticker list into minervini-screener                │
│   → screen.py hits warm market.db (no API calls)             │
│   → Verdicts in ~5 seconds, ~6k tokens total                 │
└──────────────────────────────────────────────────────────────┘
```

## Available scans

Scans live at `~/.config/market_data/scans/*.py`. Each module exports a `query()` function (a `tradingview-screener` `Query` object). Currently configured:

| Scan | Market | Filter |
|---|---|---|
| `vcp_tw` | Taiwan | beta_1y > 1, mcap > 2B TWD, close > SMA200, AvgValue.Traded_10d > 900M, common stock, primary listing |
| `vcp_us` | US | beta_1y > 1, mcap > 2B USD, close > SMA200, AvgValue.Traded_10d > 50M, common stock, primary listing |

To list all available scans:

```bash
~/.config/market_data/venv/bin/python \
  ~/.config/market_data/warm_watchlist.py --list
```

## Workflow — when user asks to "run my weekly scan" or similar

### Step 1: Check the freshness of the cache

Read the metadata of the relevant tickers file:

```bash
# For TW
python3 -c "import json; d=json.load(open('$HOME/.config/market_data/scans/vcp_tw.tickers.json')); print(f'Last scan: {d[\"generated_at\"]}  ({d[\"count\"]} tickers)')"
```

If the timestamp is within the last 7 days → **use the cached list** (no fetch needed).
If older → **offer to re-run** the warm.

### Step 2a: If cache is fresh — read and act

```python
import json
data = json.load(open('~/.config/market_data/scans/vcp_tw.tickers.json'))
tickers = data['tickers']  # ['2330.TW', '2454.TW', ...]
```

Then pipe into the downstream skill. Example for minervini-screener:

```bash
TICKERS=$(python3 -c "import json; d=json.load(open('$HOME/.config/market_data/scans/vcp_tw.tickers.json')); print(','.join(d['tickers'][:30]))")
~/.config/minervini-screener/venv/bin/python \
  ~/.claude/skills/minervini-screener/screen.py "$TICKERS"
```

### Step 2b: If cache is stale — offer to warm

Tell the user clearly: "Your last `vcp_tw` scan was N days ago. Refreshing now will take about 30-90 seconds for 100+ tickers. Run it?"

If yes:

```bash
~/.config/market_data/venv/bin/python \
  ~/.config/market_data/warm_watchlist.py --scan vcp_tw
```

Then proceed with the analysis.

## Inspecting the warm log

```bash
tail -50 ~/.config/market_data/warm.log
```

Each cron run produces a structured summary block with `INFO`/`WARN`/`ERROR` lines and a `FINAL SUMMARY` at the end. Look for:
- Total candidates returned by TradingView (sanity check the filter still works)
- `warmed` count (how many got data populated)
- `failed` count (tickers where yfinance/FMP couldn't return data — often delisted / illiquid)

## Running a one-off manual warm

```bash
# All scans
~/.config/market_data/venv/bin/python ~/.config/market_data/warm_watchlist.py

# Only one scan
~/.config/market_data/venv/bin/python ~/.config/market_data/warm_watchlist.py --scan vcp_tw

# Dry-run (TV query + save tickers, but skip the price fetches)
~/.config/market_data/venv/bin/python ~/.config/market_data/warm_watchlist.py --dry-run

# Test with a small slice
~/.config/market_data/venv/bin/python ~/.config/market_data/warm_watchlist.py --scan vcp_tw --max-tickers 10
```

## Setting up the launchd cron (one-time)

The plist lives at `~/.config/market_data/com.gary.market-data.warm.plist`. To activate:

```bash
# 1. Copy to LaunchAgents (or symlink)
cp ~/.config/market_data/com.gary.market-data.warm.plist ~/Library/LaunchAgents/

# 2. Load the job
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.gary.market-data.warm.plist

# 3. Verify it's loaded
launchctl list | grep market-data

# 4. (Optional) Fire it immediately to test
launchctl kickstart -k gui/$(id -u)/com.gary.market-data.warm

# 5. Tail the log to watch it run
tail -f ~/.config/market_data/warm.log
```

To unload:

```bash
launchctl bootout gui/$(id -u)/com.gary.market-data.warm
```

The default schedule is **Saturday 09:00 HKT** (= Friday 18:00 PT in winter, 17:00 PT in summer — i.e. right after the US market closes for the week). Edit the `StartCalendarInterval` block in the plist to change this. Reload with steps 2-3 after edits.

## Enabling FMP for the cron job

If FMP_API_KEY is in your shell env, launchd jobs **don't** inherit it. Two options:

### Option A — `.env` file (recommended, cleaner)

```bash
cat > ~/.config/market_data/.env <<'EOF'
FMP_API_KEY=your_key_here
EOF
chmod 600 ~/.config/market_data/.env
```

`warm_watchlist.py` calls `_load_dotenv()` at startup and picks this up automatically.

### Option B — Edit the plist

Uncomment the `<key>FMP_API_KEY</key>` block in `com.gary.market-data.warm.plist` and reload the job.

Without FMP, the warm job uses yfinance for everything (5 quarters of EPS instead of 20; no quarterly ROE/margin trend). Still useful — just less depth.

## Adding a new scan

1. Create `~/.config/market_data/scans/<name>.py` modeled on `vcp_tw.py`:

```python
from tradingview_screener import Query, Column

MARKET = "america"  # or 'taiwan', 'hongkong', etc.
DESCRIPTION = "Short human-readable description"

def query() -> Query:
    return (Query()
            .select("name", "close", "market_cap_basic", ...)
            .where(
                Column("market_cap_basic") > 1_000_000_000,
                ...
            )
            .set_markets(MARKET)
            .limit(300))

def to_yfinance(tv_ticker: str) -> str:
    """Convert TradingView 'NASDAQ:NVDA' → yfinance 'NVDA' (or suffix-required equivalent)."""
    return tv_ticker.split(":")[-1]
```

2. Test it:

```bash
~/.config/market_data/venv/bin/python \
  ~/.config/market_data/warm_watchlist.py --scan <name> --dry-run
```

3. Next cron run picks it up automatically — no plist edit needed.

## Common pitfalls

- **TradingView UI labels lie about field names.** "Beta 5Y" can be `beta_1_year` internally; "Price × avg vol 30D" can be `AvgValue.Traded_10d`. Always copy the actual request payload from your browser devtools (Network tab → POST scan request → Payload) and match field names exactly. See `references/tradingview_fields.md` for a catalog.
- **FMP free is US-only** — Taiwan tickers always go to yfinance, even with FMP key set. The client handles this transparently; you'll see `source=yfinance` in the `fetch_log` table for TW rows.
- **Token cost when re-scanning mid-week**: zero if cache is fresh (Claude just reads the JSON tickers file + the DB). Each `screen.py` invocation cache-hits = ~500-2000 tokens for 30 tickers.
- **`force_refresh=True` is expensive on FMP free**. The cron uses it only for prices (always fresh). Quarterly/info/metrics rely on the 144h TTL.
- **A 200+ ticker US scan may exceed FMP's 250 calls/day budget**. The client falls back to yfinance for any FMP rate-limit error. Look for `fmp ... error` lines in the fetch_log to see when this happened.

## Reference

- Full TradingView field catalog: `references/tradingview_fields.md`
- Sample plist install + troubleshooting: `references/launchd_install.md`
