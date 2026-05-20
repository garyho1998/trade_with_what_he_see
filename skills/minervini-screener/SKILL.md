---
name: minervini-screener
description: Run Martin Minervini's SEPA stock screen on one ticker or a watchlist. Checks all 8 Trend Template criteria, computes RS proxy vs SPY, detects Weinstein stage (1-4), flags VCP-candidate bases, snapshots EPS/sales acceleration. Also documents advanced entry concepts (Minervini's cheat/low cheat, Brian Shannon's AVWAP pullback, priming patterns, tight-stop discipline) that layer on top of screener output. Use when asked to apply Minervini's method, run SEPA, check Trend Template, screen for stage-2 leaders, find VCP setups, or evaluate a stock by IBD/Minervini-style criteria. Triggers on keywords like Minervini, SEPA, Trend Template, VCP, stage 2, stage analysis, relative strength, RS rating, leader stock, breakout setup, cheat pattern, low cheat, AVWAP, anchored VWAP, priming pattern, range expansion, tight stop.
---

# Minervini Screener

Mechanical implementation of Martin Minervini's **SEPA** (Specific Entry Point Analysis) screen — the same checklist he uses in *Trade Like a Stock Market Wizard* and *Think & Trade Like a Champion*.

## What this does

Given a ticker (or comma-separated watchlist), the skill:

1. Pulls 400 trading days of OHLCV via `yfinance` (free, no key).
2. Computes 50/150/200-day SMAs + 30-week SMA.
3. Runs all **8 Trend Template criteria** mechanically, showing actual numbers.
4. Classifies the Weinstein **Stage (1/2/3/4)** — Minervini only buys Stage 2.
5. Detects **VCP (Volatility Contraction Pattern)** candidates from the last ~12 weeks.
6. Computes an **RS Rating proxy** (12-month total return percentile vs benchmark).
7. Snapshots **fundamentals** — EPS/sales QoQ acceleration, ROE, 3y EPS CAGR, next earnings date.
8. Emits a verdict: `BUY-READY` / `WATCH` / `BASE-BUILDING` / `AVOID` + the reason.

For watchlists, results are ranked by `(Trend Template score, RS proxy)`.

## ⚠️ Mandatory pre-flight checks

1. **Trend Template is necessary but not sufficient.** 8/8 ≠ buy. You still need a VCP entry, a catalyst, and a market-context green light (M-rule).
2. **RS Rating here is a PROXY.** IBD's RS Rating uses a proprietary multi-window formula. This skill uses 12-month total return percentile vs the submitted universe + SPY benchmark. Directionally correct, not identical.
3. **Don't enter near earnings.** Minervini avoids opening positions within ~1-2 weeks of earnings. The skill reports the next earnings date when yfinance has it.
4. **Position sizing & stops are out of scope.** Minervini's 7-8% stop and 3:1 win/loss are discipline rules you apply yourself. The skill flags candidates only.
5. **Market context overrides the signal.** Minervini won't buy in a bear/Stage-4 market regardless of how clean the individual chart looks. Cross-check with `bubble-watch` before acting on a `BUY-READY`.

## How to invoke

Venv lives at `~/.config/minervini-screener/venv/`. Always invoke through it.

```bash
# Single ticker — full scorecard
~/.config/minervini-screener/venv/bin/python \
  ~/.claude/skills/minervini-screener/screen.py NVDA

# Watchlist — ranked Markdown table
~/.config/minervini-screener/venv/bin/python \
  ~/.claude/skills/minervini-screener/screen.py NVDA,META,AVGO,CRWD,PLTR

# From file (one ticker per line)
~/.config/minervini-screener/venv/bin/python \
  ~/.claude/skills/minervini-screener/screen.py --file ~/watchlist.txt

# JSON for programmatic use
~/.config/minervini-screener/venv/bin/python \
  ~/.claude/skills/minervini-screener/screen.py NVDA --json
```

Flags:
- `--rs-benchmark SPY` (default) — benchmark for RS computation.
- `--no-cache` — bypass the 24h fetch cache.
- `--json` — machine-readable output.
- `--verbose` — show all intermediate numbers (debug).

## The 8 Trend Template criteria

| # | Criterion | Formula |
|---|-----------|---------|
| 1 | Price > 150-day SMA AND > 200-day SMA | `close > sma150 and close > sma200` |
| 2 | 150-day SMA > 200-day SMA | `sma150 > sma200` |
| 3 | 200-day SMA trending up ≥ 1 month | `sma200_today > sma200_21_trading_days_ago` (Minervini prefers 4-5 months — flagged separately) |
| 4 | 50-day SMA > 150-day AND > 200-day | `sma50 > sma150 and sma50 > sma200` |
| 5 | Price > 50-day SMA | `close > sma50` |
| 6 | Price ≥ 30% above 52-week low | `close >= 1.30 * low_52w` |
| 7 | Price within 25% of 52-week high | `close >= 0.75 * high_52w` |
| 8 | RS Rating ≥ 70 (proxy) | percentile rank of 12-month total return vs benchmark universe |

A ticker passing all 8 is in a "stage 2 advance" by Minervini's definition.

## VCP detection (heuristic)

Walks the last ~12 weeks of daily highs/lows and identifies a sequence of swing-high pivots and the pullback depth from each.

- **VCP candidate** if there are ≥ 2 contractions AND each contraction is at least 30% tighter than the prior one AND volume on the most recent pullback is below the 50-day average.
- **Pivot point** = most recent swing high (the breakout level).
- **`BREAKOUT_READY`** if `close > pivot × 0.97` AND `volume_today > 1.4 × 50-day avg volume`.

Output example:
```
VCP: candidate
  Contractions: -18% → -9% → -4%  (3 tightenings)
  Pivot: $145.20
  Status: BREAKOUT_READY (today 146.10, vol +62% vs avg)
```

## Weinstein Stage classification

Uses the 30-week SMA (Minervini & Weinstein's preferred timeframe).

| Stage | Definition | Action |
|-------|-----------|--------|
| **Stage 1** (basing) | Price within ±5% of 30W SMA, 30W flat (\|slope\| < 0.5%/wk) | Watch — too early |
| **Stage 2** (advancing) | Price > 30W SMA, 30W slope > 0, 10W > 30W | **Buy zone** |
| **Stage 3** (topping) | Price flat, 30W flattening, distribution signs | Trim / no new entries |
| **Stage 4** (declining) | Price < 30W SMA, 30W slope < 0 | Avoid / short candidate |

## Fundamentals snapshot

- **EPS QoQ YoY growth** for the last 4 quarters. Flag `accelerating` when the last 2 quarters' YoY growth exceeds the prior 2 quarters'.
- **Sales QoQ YoY growth** — same logic on revenue.
- **ROE** (latest annual, when available).
- **3y EPS CAGR** (annual EPS).
- **Next earnings date** (from `ticker.calendar`) — for the "don't enter near earnings" rule.

Minervini's preferred thresholds:
- Recent EPS growth ≥ 25%
- Recent sales growth ≥ 25%
- ROE ≥ 17%

These are scored individually — fundamentals don't gate the verdict but inform it.

## Verdict logic

### Hard gates (rejection short-circuits everything else)

These are evaluated BEFORE the verdict table and force `AVOID` regardless of other factors:

1. **Stage 4 / Stage 4?** — Minervini doesn't buy in distribution. `detect_vcp()` is skipped.
2. **CAN SLIM fundamentals gate** — `fund.score < FUND_GATE_THRESHOLD` (default = 2 of 3).
   The 3 criteria are: most-recent quarter EPS YoY ≥ 25%, sales YoY ≥ 25%, ROE ≥ 17%.
   To revert to pure Minervini behaviour (fundamentals inform but don't gate),
   edit `screen.py` and set `FUND_GATE_THRESHOLD = 0`.

When either gate fires, `detect_vcp()` is skipped (saves ~200-500ms per ticker),
and the VCP section of the scorecard shows `Tightening: skipped` + reason.

### Verdict table (applied only after both gates pass)

| Verdict | Conditions |
|---------|-----------|
| `BUY-READY` | 8/8 Trend Template **AND** Stage 2 **AND** VCP `BREAKOUT_READY` **AND** fundamentals score ≥ 2/3 |
| `WATCH` | 7-8/8 Trend Template **AND** Stage 2 **AND** (VCP forming OR near pivot but not breakout yet) |
| `BASE-BUILDING` | Stage 1 **AND** RS proxy ≥ 70 (early — improving relative strength while basing) |
| `AVOID` | Stage 3/4 **OR** < 6/8 Trend Template **OR** RS proxy < 70 **OR** fund < gate |

The verdict is a **filter**, not advice. The skill never recommends sizing or commits to a direction.

## Workflow — when Claude invokes this skill

1. Parse ticker(s) from the user's request (single, comma-list, or file).
2. Run `screen.py` against them.
3. Read the stdout scorecard (or `--json` if multiple tickers + programmatic chain).
4. For each ticker, report:
   - Trend Template: `X/8` with the failing criteria called out.
   - Stage classification.
   - VCP status (candidate / forming / none).
   - RS proxy.
   - Fundamentals one-liner.
   - Verdict + 1-sentence "why".
5. For batch mode: rank by `(TT score desc, RS proxy desc)` and present as a Markdown table.
6. **Always remind the user**: "This is a filter, not a signal. Cross-check market context (`bubble-watch`) and confirm you have a VCP entry + risk plan before acting."

## Common mistakes — guard against these

1. **Buying Stage 4 because it's "cheap".** Minervini's whole point: a downtrending stock can always go lower. Wait for Stage 1 → Stage 2 transition.
2. **Ignoring the M-rule.** Even a perfect 8/8 + VCP breakout fails when the broader market is in correction. Always check market context first.
3. **Skipping the VCP and chasing.** Trend Template alone identifies *trending* stocks — VCP identifies the *entry point*. Without a tight base, you're buying extended price.
4. **Using EPS surprise as a thesis.** A beat is a signal, not a thesis. Minervini wants the *acceleration* — last 2 quarters faster than prior 2 — not just one good print.
5. **Treating RS proxy as IBD RS Rating.** They're correlated but not identical. Use the value directionally; for absolute IBD-style filtering, consult MarketSmith.
6. **Holding through earnings.** Earnings inside a base = uncertainty. Minervini's discipline: don't open positions within 1-2 weeks of an earnings event.
7. **Averaging down on losers.** Minervini averages **up** on winners. A 7-8% stop is non-negotiable — the skill assumes the user enforces it.

## Advanced entry concepts — beyond the textbook breakout

The screener detects the **publicly-documented VCP/breakout pattern** that Minervini popularised in *Trade Like a Stock Market Wizard*. Every top trader who teaches openly stresses the same caveat: **patterns the crowd watches have lost most of their edge**. Pradeep Bonde (StockBee, Episodic Pivots) frames it as:

> 深度創造優勢 — *Depth creates advantage.*

If everyone blindly follows CAN SLIM/SEPA without questioning the elements, where does YOUR alpha come from? Textbook breakouts are (a) rare in their pure form and (b) frequently fail when they do appear, because too many participants front-run the obvious pivot.

These are the variations top traders developed in response. The screener does NOT auto-detect any of them — they're the conceptual layer to apply when reading screener output.

### Cheat / Low Cheat (Minervini, *Think & Trade Like a Champion*)

An **earlier** buying point INSIDE a Stage-2 base, before the right-side classical pivot:

1. Stock makes a base after a Stage-2 advance.
2. A shakeout/undercut drops price toward the base lows (washing out weak hands).
3. Price recovers and forms a tight 3-10 day plateau ("the cheat").
4. Breakout of THAT plateau = the entry — well below the textbook pivot, with a tighter stop.

Sub-types by location in the base:
- **Low cheat**: plateau near base lows. Earliest entry, lowest risk, most patience required.
- **Mid cheat**: plateau in the middle.
- **High cheat**: plateau just below the classical pivot.

Edge: tighter stop relative to the eventual move; avoids the breakout-failure trap when supply hits at the obvious well-watched level.

### AVWAP pullback (Brian Shannon, *Maximum Trading Gains with Anchored VWAP*)

**AVWAP** = Anchored Volume-Weighted Average Price. Anchor at a meaningful event (earnings gap, IPO day, prior swing low, breakout day). The line shows the average price paid by everyone since that anchor.

Entry: buy pullbacks to a **rising** AVWAP. Stop just below it. If price rejects AVWAP, you're aligned with the average institutional buyer; if AVWAP breaks, the thesis is cleanly invalidated.

Complementary to VCP breakouts — same trend filter, different (often earlier) timing.

### Priming pattern (pre-range-expansion contraction)

Popularised by Kristjan Kullamägi (Qullamaggie) and the swing-trader community influenced by him:

- Daily ranges contract for 3-10 sessions (ATR shrinks).
- Volume dries up.
- Price coils near a meaningful level (prior breakout, resistance, AVWAP, round number).
- Often ends with an **NR7** (narrowest range of 7 days) or **inside-day**.

The expansion day (large green candle on heavy volume) is the **trigger**; the priming was the **setup**. By the time the expansion is obvious, 30-50% of the move is already done — alpha is in catching the priming first.

### Tighter stops — Martin Luk's daily-chart insight

O'Neil's classic **7-8% stop** is calibrated for **weekly-chart** entries with looser pivots. Martin Luk reviewed his own daily-chart trades and found:

> No profitable trade ever showed more than ~2% adverse excursion from entry. Often less than 1%.

If your winners never go more than 2% against you, why use a 7% stop? David Ryan's encapsulation: *"The right stock should be profitable from day 1."*

**Critical caveat**: tighter stops are EARNED by precise entries, not by being braver. A clean cheat/AVWAP/priming entry can use 1-3% stops. A late chase of the textbook pivot still needs the full 7-8% — because you're entering with worse timing on a more front-run pattern. Doing it backwards (wide stop on precise entry, tight stop on sloppy entry) is the worst of both worlds.

### How this changes your reading of the screener output

The screener's `BREAKOUT_READY` flag = the **textbook classical-pivot entry**. Treat it as the **latest acceptable entry**, not the optimal one.

- If you spot a cheat / AVWAP pullback / priming pattern at the same name **before** the screener flags `BREAKOUT_READY`, you have a higher-edge entry with a tighter stop.
- If you only catch the name when `BREAKOUT_READY` triggers, accept the wider stop and lower hit rate.
- The screener catches the obvious; the alpha is in finding the setup earlier.

Full depth (charts, math, anchor-selection rules) lives in `references/methodology.md` §10.

## Data sources

- **Price/volume**: `yfinance` daily OHLCV (post-adjustment) — 400 trading days.
- **Quarterly EPS/revenue**: `yfinance` `quarterly_income_stmt`.
- **ROE**: `yfinance` `info` field (`returnOnEquity`).
- **Next earnings date**: `yfinance` `ticker.calendar`.

If `yfinance` fails for a ticker (delisted, illiquid, foreign), the skill reports `DATA_UNAVAILABLE` for that row rather than crashing.

## Reference

Full methodology — SEPA framework, VCP geometry, stage transitions, M-rule, risk discipline — is in `references/methodology.md`. Read it on demand; the main SKILL.md stays scannable.

## When NOT to use this skill

- Stocks under $10 / very illiquid (Minervini's method assumes institutional participation).
- IPOs with < 6 months of history (no 200-day SMA possible).
- ADRs / OTC pink sheets (yfinance data quality is poor).
- ETFs (Trend Template is designed for individual equities; an ETF "passing" doesn't mean the same thing).
- Pre-earnings / event-driven setups (use `stock-pitch` for those).
