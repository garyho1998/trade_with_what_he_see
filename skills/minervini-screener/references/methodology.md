# Minervini SEPA — Full Methodology Reference

This is the long-form reference for the screener. The main `SKILL.md` is the
"command surface"; this file expands the rules with the context behind them.
Read on demand.

Sources: Mark Minervini, *Trade Like a Stock Market Wizard* (2013) and
*Think & Trade Like a Champion* (2017); Stan Weinstein, *Secrets for Profiting
in Bull and Bear Markets* (1988).

---

## 1. SEPA — Specific Entry Point Analysis

SEPA is a 5-pillar framework. Passing any one pillar in isolation is not
enough. **All five must align** for an actual entry.

| # | Pillar | What it checks | Where the screener helps |
|---|--------|---------------|--------------------------|
| 1 | **Trend** | Is the stock in a Stage 2 uptrend? | 8 Trend Template criteria + Weinstein stage |
| 2 | **Fundamentals** | Accelerating earnings/sales/margins? | EPS/sales YoY for last 4 quarters, ROE, 3y CAGR |
| 3 | **Catalyst** | Is there a real reason to move? | NOT in screener — user must supply (new product, regime shift, mgmt change, etc.) |
| 4 | **Entry Point** | Is there a low-risk pivot? | VCP detection — pivot price + breakout-ready flag |
| 5 | **Exit Point** | What's the stop? Where do you sell? | NOT in screener — user discipline (7-8% stop, 3:1 W/L ratio) |

The screener mechanizes pillars 1, 2, and 4. Pillars 3 (catalyst) and 5
(risk plan) are human judgment.

---

## 2. The 8 Trend Template criteria (verbatim)

From *Trade Like a Stock Market Wizard*, Chapter 5. Minervini requires
**all 8** for a stock to qualify as a Stage 2 leader.

1. The current stock price is above both the 150-day and the 200-day moving averages.
2. The 150-day MA is above the 200-day MA.
3. The 200-day MA line is trending up for at least 1 month (preferably 4–5 months minimum).
4. The 50-day MA is above both the 150-day and the 200-day moving averages.
5. The current stock price is trading above the 50-day MA.
6. The current stock price is at least 30 percent above its 52-week low.
   (Stocks well off their lows are often setting up before a big advance.)
7. The current stock price is within at least 25 percent of its 52-week high
   (the closer to a new high the better).
8. The relative strength ranking (as reported in *Investor's Business Daily*)
   is no less than 70, and preferably in the 80s or 90s.

**Why each one matters** (Minervini's reasoning):
- **C1, C5**: Multiple MA confirmations filter out chop and noise.
- **C2, C4**: The MA stack (50 > 150 > 200) is the structural signature of a
  multi-quarter uptrend.
- **C3**: A flat or declining 200-day means the stock isn't actually trending
  up over the medium term — it's just had a recent bounce.
- **C6**: Stocks within 30% of their 52-week low are likely still basing or
  bouncing dead-cat style.
- **C7**: Stocks more than 25% off their highs are showing distribution.
  Leaders break out from within striking distance of new highs.
- **C8**: Without relative strength, the stock isn't a leader. Minervini
  buys leaders, not laggards.

### About RS Rating

IBD's RS Rating is proprietary. The IBD formula approximates:

```
RS = 0.4 * (close_today / close_~63d_ago)
   + 0.2 * (close_~63d_ago / close_~126d_ago)
   + 0.2 * (close_~126d_ago / close_~189d_ago)
   + 0.2 * (close_~189d_ago / close_~252d_ago)
```

Then ranked as percentile across ~7000-8000 US-listed equities. We can't
replicate the universe at zero cost, so the screener uses the same weighted
return formula and:
- For batch mode (≥5 tickers): percentile within the submitted universe.
- For single ticker: scaled excess vs SPY benchmark (50 = SPY's return,
  99 = SPY return + 50pp, 1 = SPY return − 50pp), via tanh squashing.

This is directionally correct but **not** identical to IBD. Use the value
as ordinal ("higher is better"), not cardinal ("75 means the 75th
percentile of the US market").

---

## 3. VCP — Volatility Contraction Pattern

The VCP is Minervini's signature entry pattern. It's a sequence of
progressively tighter pullbacks inside a base. Each successive contraction
shrinks in depth as supply gets absorbed.

### Geometry of a textbook VCP

```
        peak1
         /\
        /  \         peak2
       /    \         /\
      /      \       /  \      peak3
     /        \     /    \      /\
    /          \___/      \____/  \___pivot (current)
   /                                    └── breakout level
  /
basing
```

Pullback sequence (from peak to next trough):
- T1 = 25-30%
- T2 = 12-18%
- T3 = 5-10%

Each successive contraction is roughly half the prior. **Volume must dry up**
on each pullback — that's the key tell that supply has been absorbed.

### What the screener detects

- Finds local price highs in the last ~60 trading days (peaks where `high[i]`
  is the max over ±5 bars).
- For each peak, finds the subsequent trough (low between this peak and the
  next one).
- Computes pullback% from each peak to its trough.
- Flags a candidate when the last 2-3 contractions are tightening AND at least
  one is ≥30% tighter than its predecessor.
- Also checks: volume on the most recent pullback < 50-day avg volume (dry up).
- **Pivot** = the most recent swing high.
- **`BREAKOUT_READY`** = today's close > pivot × 0.97 AND today's volume >
  1.4 × 50-day avg.

### Limitations

- 60-day window may miss long bases (e.g. 6-month consolidations after big
  runs).
- The W=5 peak-detection window will smooth over very tight bases. Tune in
  `screen.py:detect_vcp` if needed.
- Doesn't distinguish VCP from cup-with-handle, flat base, or double-bottom
  — Minervini accepts all of these; the screener treats any tightening
  sequence as a candidate.

---

## 4. Weinstein Stage analysis

Stan Weinstein's 4-stage framework. Minervini buys only Stage 2.

### Stage 1 — Basing

- Price oscillates around a flat 30-week MA.
- Both price and MA have been ranging for weeks/months.
- Volume typically low; institutions are accumulating quietly.
- **Action**: watch, don't buy. Wait for breakout into Stage 2.

### Stage 2 — Advancing

- Price breaks above the 30-week MA on heavy volume.
- 30-week MA itself starts sloping up.
- 10-week MA crosses above 30-week MA.
- Price makes higher highs and higher lows.
- **This is the buy zone.** All of Minervini's entries are Stage 2.

### Stage 3 — Topping

- Price stops making higher highs.
- 30-week MA flattens.
- Distribution days (down on heavier-than-usual volume) start appearing.
- Often a final "blow-off" pop precedes the breakdown.
- **Action**: trim, tighten stops, no new entries.

### Stage 4 — Declining

- Price drops below the 30-week MA.
- 30-week MA slopes down.
- Lower highs and lower lows.
- **Avoid.** Cheap-looking Stage 4 stocks can drop another 50-80%.

### How the screener classifies

Inputs: 30-week SMA (`smas['sma30w']`), its slope (% per week, computed over
last 5 weeks), 10-week SMA, current close.

| Condition | Stage |
|-----------|-------|
| close > 30W AND slope > +0.1%/wk AND 10W > 30W | Stage 2 |
| close < 30W AND slope < −0.1%/wk | Stage 4 |
| \|close − 30W\| / 30W ≤ 5% AND \|slope\| ≤ 0.1%/wk | Stage 1 |
| close > 30W BUT slope flat (|slope| ≤ 0.1) OR slope < +0.2 | Stage 3 |
| Anything else, above 30W | Stage 3? (mixed) |
| Anything else, below 30W | Stage 4? (mixed) |

---

## 5. Fundamentals (Minervini's CAN SLIM-adjacent rules)

Minervini doesn't dogmatically follow CAN SLIM but his fundamentals filter
overlaps heavily. He looks for:

| Metric | Minervini's preferred level |
|--------|-----------------------------|
| Most recent quarter EPS YoY growth | ≥ 25% |
| Two-quarter EPS trend | accelerating (Q1 > Q2 > Q3...) |
| Most recent quarter sales YoY growth | ≥ 25% |
| Annual EPS growth (3-5y CAGR) | ≥ 20% |
| ROE | ≥ 17% |
| Margin trend | expanding |
| Earnings surprises | positive, especially with raised guidance |

### What the screener captures

- **`eps_yoy_last4q`**: 4 most recent quarterly EPS YoY growth rates (newest first).
- **`sales_yoy_last4q`**: same for revenue.
- **`eps_accelerating` / `sales_accelerating`**: True when (Q1 + Q2) / 2 > (Q3 + Q4) / 2.
- **`roe_pct`**: from `yfinance.info['returnOnEquity']`.
- **`eps_cagr_3y_pct`**: ratio of trailing TTM to 3y-prior TTM, geometric.

### What the screener does NOT capture (acknowledge in the output)

- Margin trend over time (need quarterly margin series).
- Earnings surprise vs consensus (yfinance has `earnings_history` but it's
  unreliable).
- Forward EPS consensus and revision direction (covered by `forward-rdcf`).
- Institutional sponsorship (number of mutual funds holding) — not in
  yfinance.

These gaps mean the fundamentals score is **directional, not authoritative**.
For high-conviction names, supplement with manual checks on the latest 10-Q
and earnings call transcript.

---

## 6. The M-rule — market context

Minervini does not buy in a bear market, period. His check:

> If the broader market is in correction (S&P below its 50-day, or making
> lower highs and lower lows), I don't add new long exposure regardless of
> individual setups.

The screener does **not** apply this filter automatically — that's a
deliberate choice. The output is "what are the candidates assuming the
market gives a green light," and the user is responsible for the meta-call
on whether the green light is on.

Cross-reference: `bubble-watch` is Gary's market-context dashboard.
If `bubble-watch` is flashing high Level + accelerating ROC, don't act on
a `BUY-READY` from this skill.

---

## 7. Risk management (out of scope, listed for completeness)

These rules are Minervini's, not implemented by the screener. The user is
expected to apply them on their own:

1. **7-8% maximum stop loss.** Sometimes tighter (5%) if the entry is
   well-defined. Never wider.
2. **3:1 average win/loss ratio.** If your average winner is +21% and your
   average loser is −7%, the math works. If your average winner is +10%
   and loser is −9%, you're break-even-to-losing even if your hit rate is good.
3. **Average UP on winners, never DOWN on losers.** Add to positions that
   are working; never throw good money after bad.
4. **Hard rule: cut losers within the first 1-2 days if they violate.**
   Don't "give them time to work."
5. **Position size by conviction**, not by alphabetical order. Best ideas
   get 10-25% of capital; lesser ideas get 5%; speculations get 2-3%.

---

## 8. When to read this file vs the SKILL.md

- **SKILL.md**: "How do I run it? What's the verdict logic? What are the
  caveats?" — the operational surface.
- **methodology.md** (this file): "Why is criterion C3 a 1-month vs 4-month
  trend check? What's the geometry of a textbook VCP? Why does Minervini
  not buy in Stage 4?" — the conceptual depth.

Reading the methodology helps when:
- Tuning the screener's thresholds (e.g. should W=5 in peak detection? Should
  the VCP tightening ratio be 30% or 50%?).
- Debugging unexpected verdicts (why did NVDA show Stage 3? when I thought
  it was Stage 2?).
- Pitching a setup that came out of the screen — knowing the "why" makes
  the pitch much stronger.

---

## 9. Quick reference card

| Concept | Symbol | Threshold |
|---------|--------|-----------|
| 8 Trend Template criteria | TT | All 8 pass |
| Stage 2 (Weinstein) | S2 | Above 30W SMA, 30W rising, 10W > 30W |
| VCP candidate | VCP | ≥2 tightening contractions, vol drying up |
| Breakout-ready | BR | Close > pivot × 0.97, volume > 1.4× avg |
| RS proxy | RS | ≥ 70 (preferably 80+) |
| EPS QoQ growth | EPS | Most recent quarter ≥ 25% |
| Sales QoQ growth | REV | Most recent quarter ≥ 25% |
| ROE | ROE | ≥ 17% |
| Stop loss | SL | Max 7-8%, tighter if possible |
| W/L ratio | RR | Average winner / average loser ≥ 3 |

**Buy zone**: TT 8/8 AND S2 AND VCP+BR AND ≥2 of {EPS, REV, ROE} AND M-rule
(market green light).

---

## 10. Advanced entry concepts — beyond the textbook breakout

The screener detects the publicly-documented VCP/breakout pattern. Every top
trader who teaches publicly acknowledges that this pattern has decayed in
edge through over-adoption. This section covers the variations top traders
developed in response. **None of these are auto-detected by the screener** —
they're the conceptual layer for INTERPRETING screener output and timing
entries more precisely.

### 10.1 "深度創造優勢" — Depth creates advantage (Pradeep Bonde)

Pradeep Bonde (StockBee, Episodic Pivots framework) frames the meta-problem:

> Most traders blindly follow O'Neil's CAN SLIM or Minervini's classical VCP
> breakout without questioning whether the elements still work in current
> market structure. The patterns are too well-known. If everyone is watching
> the same pivot, where does YOUR alpha come from?

Market-structure reality (2020s):
- Textbook patterns are pre-emptively front-run by HFTs, ML systems, and
  pattern-watching retail.
- Breakouts have higher failure rates today than in the 1990s when O'Neil's
  *How to Make Money in Stocks* data was collected.
- Even when breakouts work, post-breakout follow-through is shorter — the
  early move is often given back by close.

"Depth" here means **going deeper into the mechanics of the pattern** —
understanding *why* the base forms, *where* supply gets absorbed, *when*
institutions actually buy — rather than mechanically running through the
public checklist. The crowd reads the checklist; the depth-aware trader
reads the structure underneath.

The response: find entry points the crowd is NOT watching:
- Earlier in the base (Minervini's cheat / low cheat)
- On pullbacks to dynamic support (Shannon's AVWAP)
- During the contraction itself (priming pattern)

### 10.2 Cheat / Low Cheat — Minervini

Described in *Think & Trade Like a Champion* (2017), Chapter 7.

Geometry:

```
   Stage-2 high                          textbook classical pivot
        \                                          ↓
         \________base top__________________________
          \                                          \
           \      __cheat plateau__                   \
            \    /                  \                  \
             \__/                    \__________________\  ← cheat entry
            shakeout
            (undercut)
```

The pattern:
1. Stage-2 leader makes a base after a sustained advance.
2. Base develops a shakeout — undercut of prior support, washing out weak
   hands and creating an emotional low.
3. After the shakeout, price recovers and forms a tight horizontal plateau
   (3-10 days, contracting ATR).
4. The breakout of THAT plateau is the **cheat entry** — not the right-side
   base pivot.

Three sub-types by plateau location:

| Sub-type   | Plateau location           | Distance below classical pivot | Stop size | Patience |
|------------|----------------------------|-------------------------------|-----------|----------|
| Low cheat  | Lower third of base        | 10-20%                        | 1-3%      | Most     |
| Mid cheat  | Middle of base             | 5-12%                         | 2-4%      | Moderate |
| High cheat | Upper third, near pivot    | 0-5%                          | 3-5%      | Least    |

Why it works:
- **Tighter stop**: the cheat plateau is small (3-5% range), so a stop just
  below the plateau = 3-5% risk, vs 7-8% on the full base.
- **Beats front-runners**: by the time the textbook pivot triggers, you're
  already up 5-15% with a stop you can move to breakeven.
- **Filters failures cheaply**: if the plateau breaks DOWN, you exit on a
  small loss instead of chasing a failed textbook breakout.

What to confirm before taking a cheat entry:
- Volume drying up during the plateau (supply absorbed).
- Plateau forms above a key support level (50-day MA, prior base low + 5%).
- Distribution days inside the plateau ≤ 2 (institutional accumulation,
  not distribution).
- The shakeout BEFORE the plateau was real — undercutting a prior swing low
  on heavy volume, with quick recovery.

### 10.3 AVWAP pullback — Brian Shannon

Reference: *Maximum Trading Gains with Anchored VWAP* (Shannon, 2022).

**AVWAP definition**: standard VWAP (Volume-Weighted Average Price) with the
starting anchor moved from session-open to a chosen historical event.

Common anchors:

| Anchor type                    | When to use                                                   |
|--------------------------------|---------------------------------------------------------------|
| Earnings gap-up day            | Post-earnings trend; AVWAP = avg buyer since the catalyst    |
| IPO day                        | New issues; AVWAP = avg buyer since trading began            |
| Major news catalyst day        | After M&A announcement, FDA approval, regulatory change      |
| Prior swing low                | After significant correction in an established uptrend       |
| Day of breakout from a base    | Tracking buyers from the most recent breakout                |

The AVWAP from a chosen anchor = the volume-weighted average price PAID by
everyone who's bought since that anchor. Practically: "where is the average
buyer since this event?"

Entry rules:
1. AVWAP must be **rising** (slope positive). A falling AVWAP means the
   trend is broken — do not buy.
2. Buy on a pullback that touches or slightly undercuts the AVWAP.
3. Confirm with rejection candle, volume on the bounce, or AVWAP holding
   as intraday support.
4. Stop just below AVWAP (typically 1-3% risk, depending on stock's ATR).

Why it works:
- **Institutional behavior**: large funds use VWAP as their benchmark for
  execution quality. AVWAP from a meaningful anchor is where they have an
  incentive to defend the level — being filled above their AVWAP is "good
  execution" on the books.
- **Clean invalidation**: if AVWAP breaks decisively, the thesis is wrong
  — exit fast on a small loss.
- **Multi-timeframe**: useful on daily for swing traders, weekly for
  position traders, intraday for day traders.

How it relates to the screener:
- A stock flagged `BUY-READY` has already made at least one significant
  move (otherwise it wouldn't be Stage 2).
- Drawing AVWAP from the most recent significant low or breakout gives you
  a non-breakout entry option.
- Particularly useful when the screener flags Stage-2 + VCP candidate but
  `BREAKOUT_READY` hasn't triggered yet — AVWAP pullback can get you in
  earlier with a smaller stop.

### 10.4 Priming pattern — pre-expansion contraction

Popularised by Kristjan Kullamägi (Qullamaggie) and the swing-trader
community influenced by him. The pattern:

- Stock is in a Stage-2 advance with a recent meaningful move (often a
  "Stage-2 episode" of 30-100% in 1-3 months).
- Price enters a tight consolidation; ATR contracts for 3-10 sessions.
- Volume dries up.
- Price coils near a significant level: prior breakout, AVWAP from prior
  anchor, round number, horizontal resistance.
- Contraction often ends with an **NR7** (narrowest range of last 7 days)
  or **inside-day** (high < prior high AND low > prior low).
- The **range-expansion day** (large bullish candle on heavy volume) is the
  actual trade trigger.

Conceptually, the priming pattern is a **mini-VCP at the daily-bar level**.
The screener's VCP detection works at the weekly/swing-pivot level (looking
for 12-25% contractions over weeks); the priming pattern is the same logic
at the day-to-day level, with much tighter ranges.

How it relates to the screener:
- The screener's `VCP candidate` flag captures multi-week tightening
  sequences.
- A priming pattern is a tightening over DAYS, often within a single VCP
  contraction.
- Workflow: use the screener to identify the broader VCP, then watch daily
  charts for the priming pattern that signals the actual range expansion
  is imminent.

What to look for:
- ATR(14) < 50% of its 60-day average — true volatility contraction.
- Volume on coiling days < 70% of 50-day average — supply absorbed.
- NR7 or inside-day in the last 3 sessions — terminal compression signal.
- The level being coiled near has prior significance (was support or
  resistance before, OR is an AVWAP from a meaningful anchor).

### 10.5 Tighter stops — Martin Luk's daily-chart insight

The classical 7-8% stop comes from O'Neil's *How to Make Money in Stocks*,
calibrated for:
- Weekly-chart entries on the right side of a base.
- Pivot points that span 5-10% of price.
- Holding periods measured in weeks-to-months.

Daily-chart entries (cheat, AVWAP, priming) have different geometry — the
entry point is much more precisely defined. Martin Luk's discovery after
reviewing his own trade journal:

> Across hundreds of profitable trades, none had more than ~2% adverse
> excursion from entry. Many had less than 1%. So why am I giving the
> trade 7%?

The math comparison:

| Strategy                                       | Avg win | Avg loss | Win rate | EV/trade | Trades/yr | Yearly EV |
|------------------------------------------------|---------|----------|----------|----------|-----------|-----------|
| O'Neil-style (7% stop, 21% target)             | 21%     | 7%       | 40%      | +4.2%    | ~30       | +126%     |
| Daily-chart tight (2% stop, 10% target)        | 10%     | 2%       | 50%      | +4.0%    | ~80       | +320%     |
| Daily-chart tight (2% stop, 15% target)        | 15%     | 2%       | 45%      | +5.65%   | ~80       | +452%     |

The yearly EV difference is massive — the daily-chart approach trades more
frequently with similar per-trade EV but fits more cycles per year.

Other benefits of tighter stops:
- **Smaller drawdowns**: a losing streak of 5 trades is −10% vs −35%.
- **Faster feedback**: you find out within 1-2 days if the setup was wrong,
  vs holding a deteriorating position for weeks waiting for the 7% stop.
- **Forces entry discipline**: a 2% stop punishes sloppy entries
  immediately. You learn to enter only at high-quality pivots.

David Ryan's encapsulation (from his *Market Wizards* interview and later
teaching): *"The right stock should be profitable from day 1."*

If your entry is correct and the stock immediately goes 1-2% against you,
the setup is probably wrong — exit fast and re-evaluate rather than
"giving it time to work."

**Critical caveat**: the tighter stop is EARNED by a precise entry, not by
bravery. Stop tightness must match entry quality:

| Entry quality                                    | Appropriate stop |
|--------------------------------------------------|------------------|
| Low cheat (near base lows after shakeout)        | 1-3%             |
| AVWAP pullback with rejection                    | 1-2%             |
| Priming pattern range-expansion entry            | 2-4%             |
| Mid cheat                                        | 2-4%             |
| High cheat                                       | 3-5%             |
| Classical textbook pivot breakout                | 5-8% (O'Neil's)  |
| Late chase of already-extended breakout          | DO NOT TRADE     |

Using a 2% stop on a sloppy textbook-pivot chase will just stop you out
repeatedly. Doing it backwards (wide stop on precise entry, tight stop on
sloppy entry) is the worst of both worlds.

### 10.6 How to use this section with the screener

The screener catches Stage-2 leaders with textbook VCP characteristics.
That's necessary but not optimal. Layer these advanced concepts on top:

1. **Filter** for Stage 2 + good fundamentals using the screener.
2. **Read the daily chart** for cheat / AVWAP / priming setups — these tell
   you WHERE to enter and HOW TIGHT your stop can be.
3. **Reserve `BREAKOUT_READY` as a LATE entry option** — if you haven't
   caught a better setup by then, the textbook pivot is acceptable but
   expect lower win rate and use a wider stop.
4. **Match your stop to your entry quality** (table in §10.5).

The screener is the **filter**. These concepts are the **entry refinement**.
Both layers are required for a high-edge swing trade — and the second
layer is where the alpha lives once everyone is running the first layer
mechanically.
