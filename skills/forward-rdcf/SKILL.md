---
name: forward-rdcf
description: Compute Forward-based Reverse DCF — calculate the market's implied EPS CAGR at a given price/forward-EPS pair. Tells you the growth rate the market is implicitly pricing in at your target IRR. Use when you want to check if a stock is over/undervalued by reverse-engineering market expectations. Triggers on keywords like reverse DCF, RDCF, implied growth, implied CAGR, valuation check, is X overvalued, is X cheap, what growth does the market expect, forward PE check.
---

# Forward-based Reverse DCF

## What this does

Takes stock price + forward EPS + (IRR target, horizon, exit P/E) and tells you: **"To make this price work at your target IRR, EPS needs to grow at X% CAGR."**

Then compares X% to the industry baseline to flag potentially under/overvalued names.

## When to use

- User asks "is X overvalued?" / "is X a buy?" / "what's priced in?"
- User wants to compare a stock's implied growth to a realistic ceiling
- User wants sensitivity analysis on exit-multiple assumption

## When NOT to use

- Pre-earnings / regime-change companies where forward EPS is wildly being revised
- Companies with negative or near-zero forward EPS (formula breaks)
- Cyclicals at trough where forward EPS understates normalized
- Hyper-growth (>50% CAGR) — RDCF's exit-multiple assumption breaks down

## ⚠️ Mandatory pre-flight checks (DO BEFORE EVERY CALCULATION)

The skill has burned us with silent inconsistencies — these checks are non-negotiable:

1. **State IRR, exit multiple, horizon explicitly** in the output. Never silently default. If you used different assumptions for different rows in the same table, the table is broken.
2. **Use identical assumptions across rows of one table.** Mixing IRR=10% on one row and IRR=12% on another makes Δ comparisons meaningless.
3. **Input consistency check.** If you have multiple metrics from a source (e.g. revenue + burn + burn_ratio), verify they reconcile arithmetically before plugging in. `burn ÷ revenue` must equal `burn_ratio` to within rounding. Mismatch → stop and re-source.
4. **Sanity-check magnitudes.** A claimed ARR figure must be consistent with last reported ARR + plausible growth (e.g. AI lab going from $7B → $43B in 6 months = 36× annualized = implausible without confirmation).
5. **For private companies / AI labs**, default to revenue-based RDCF (see section below), not EPS-based.

## How to invoke

### Interactive webapp (preferred when human is reading the output)

```bash
open /Users/garyho/.claude/skills/forward-rdcf/visualize.html
```

Pure HTML/JS, no dependencies. Type ticker + price + forward EPS + historical EPS,
live-updates: implied CAGR, signal, YoY bar chart, exit-P/E sensitivity.
Includes preset buttons for NVDA Jan 2023, NVDA Aug 2024, CAT now.

### CLI: historical-EPS mode (company-specific, turning-point aware)

```bash
python3 /Users/garyho/.claude/skills/forward-rdcf/compute.py \
  --price 19.50 \
  --forward-eps 1.19 \
  --historical-eps "0.41,0.27,0.50,0.99,0.17" \
  --ticker NVDA
```

`--historical-eps` = comma-separated past annual EPS, **OLDEST first**, not including forward.
e.g. `"FY-5,FY-4,FY-3,FY-2,FY-1"`.

The skill compares implied CAGR to the company's own:
- 5-year geometric CAGR (smoothed)
- Average of last 5 YoY growth rates (recent-typical pace)
- YoY growth series (you see each year)
- Growth acceleration (last YoY − prior YoY) — **turning-point indicator**
- 1y / 2y / 3y / 5y trailing CAGRs

### CLI: industry baseline mode (fallback)

```bash
python3 /Users/garyho/.claude/skills/forward-rdcf/compute.py \
  --price 19.50 \
  --forward-eps 1.19 \
  --industry ai_hypergrowth \
  --ticker NVDA
```

Only used when historical EPS is hard to find. Less informative — no turning-point detection.

### Optional flags
- `--irr 0.10` (default 10%)
- `--years 5` (default horizon)
- `--exit-pe 25` (default terminal P/E)

## Industry baseline CAGR reference (fallback)

| Industry | Typical CAGR |
|---|---|
| utilities | 5% |
| energy | 5% |
| consumer_staples | 6% |
| industrials | 8% |
| financials | 8% |
| healthcare | 10% |
| tech_mature | 12% |
| tech_growth | 18% |
| ai_hypergrowth | 25% |

## Signal logic — historical-EPS mode (preferred)

Combines two dimensions: **valuation vs history** AND **growth direction**:

|  | Accelerating ↑ | Stable ~ | Decelerating ↓ |
|---|---|---|---|
| **Implied < hist − 3pp** | **STRONG UNDERVALUED** (growth bottoming + cheap) | UNDERVALUED | MILD UNDERVALUED (cheap but slowing) |
| **Within ±3pp** | FAIR (accel could push to bull) | FAIR | FAIR (decel may justify) |
| **Implied > hist + 3pp** | MILD OVERVALUED (high price but growth helping) | OVERVALUED | **STRONG OVERVALUED** (priced for growth that's leaving) |

The most actionable signals are the corner cells. The **STRONG OVERVALUED** cell is the classic top — high implied CAGR + growth turning down. The **STRONG UNDERVALUED** cell is the classic bottom — low implied CAGR + growth turning up.

**⚠️ CAVEAT on the "Within ±3pp" row**: The "FAIR" label assumes trailing realized CAGR is a clean signal. If the trailing window includes a base-period anomaly (COVID 2020 depressed earnings, recession 2008-09, one-time sector boom/bust), the FAIR cell **can hide a MILD/STRONG OVERVALUED**. Always run the **5-Point Sanity Check** (below) before declaring "balanced."

## Signal logic — industry mode (fallback)

- Implied CAGR < baseline − 3pp → **UNDERVALUED candidate**
- Implied CAGR within ±3pp of baseline → **FAIR**
- Implied CAGR > baseline + 3pp → **OVERVALUED candidate**

## Workflow

1. Get current stock price (WebSearch or user input)
2. Get forward 12-month EPS consensus (WebSearch: "[ticker] forward EPS consensus" or analyst estimates page)
3. Pick industry baseline
4. Run `compute.py` with inputs
5. Read implied CAGR + sensitivity table
6. Interpret signal but **cross-check qualitatively** (management guidance, backlog, regime change risk)

## Caveats (always communicate these to user)

1. **Forward EPS source matters** — consensus lags reality in regime change. Underestimates upside on inflection plays (NVDA 2023). Wide bull-bear spread = downside revision risk (ISRG May 2026).
2. **Exit P/E is the most sensitive input** — single-stock leaders can permanently trade above industry avg. Default 25x may be too low for top-tier names.
3. **Industry baselines are approximate** — calibrate against the specific company's 5-10 year history.
4. **RDCF is a filter, not an oracle** — low implied CAGR is a candidate signal; verify with thesis qualitatively.
5. **Δ ≈ 0 ≠ fair value** — "balanced" is necessary but not sufficient. Run the 5-Point Sanity Check. Especially watch for: COVID/recession in trailing window inflating realized CAGR; valuation-reset convergence pattern (stock falling, not earnings rising); implied above management's own guidance.

## Backtest validation (NVDA, 2023-2026)

Low implied CAGR points correctly preceded biggest gains:
- Jan 2023: 1.1% implied → +1,059% over 3 years
- Nov 2023: 4.4% implied → +361% over 2.5 years

High implied CAGR points correctly preceded weakest gains:
- Aug 2024: 18.1% implied → +81% over 1.75 years (relatively cooler)
- Nov 2024: 17.5% implied → +56% over 1.5 years

Methodology directionally validated. Use as candidate-screening filter, not absolute timing tool.

## Implied vs Realized CAGR — Convergence Signal

The most powerful turning-point signal in RDCF is **the gap between Implied CAGR (what market requires) and Realized CAGR (what company actually delivered)**.

Compute trailing 5y (or 3y / 2y fallback) TTM-based CAGR alongside Implied CAGR. Track Δ = Implied − Realized over time:

| Δ (Implied − Realized) | What it means | Action signal |
|---|---|---|
| **> +10pp sustained 3+ yr** | Chronic optimism — market pricing >> reality | RED FLAG: prone to multiple compression |
| **+3 to +10pp** | Modest premium — market expects acceleration | Watch closely; common in growth narratives |
| **−3 to +3pp** | Surface-balanced — apparent alignment | ⚠️ **Run 5-Point Sanity Check** — could be fair value, could be a reset trap (see ISRG May 2026) |
| **−3 to −10pp** | Market behind reality — analyst conservatism | Potential undervalued; check forward consensus revisions |
| **< −10pp sustained** | Inflection / regime change | High upside if growth sustains (NVDA 2023 was here) |

### Convergence pattern — DIRECTION matters more than the gap

**When Δ has been chronically positive (+10-35pp) for 3+ years, then converges toward 0 → could be one of two opposite things.** Reading the convergence direction is the difference between a buy and a sell.

#### Convergence Direction Test

| Convergence path | What's really happening | Signal |
|---|---|---|
| **Implied stable, Realized rising** | Company fundamentals catching up to market expectations | ✅ **Bull confirmation** — earnings momentum real |
| **Implied falling, Realized stable** | Stock falling — multiple compression / valuation reset | ⚠️ **Caution** — reset may not be over |
| **Implied falling faster than Realized falling** | Market re-rating ahead of fundamental slowdown | 🔴 **Bearish setup** |
| **Implied stable, Realized falling** | Market hasn't priced in slowdown yet | 🔴🔴 **Strong bearish setup** |

**The test**: Look at 4-6 quarters of the Δ chart in `visualize.html`. Which line is doing the work?
- **Bull convergence**: Realized line moves UP toward stable Implied
- **Reset convergence**: Implied line moves DOWN toward stable Realized — the stock is falling

The Δ column alone hides this. **Always look at the chart, not just the Δ number.**

### Anti-Pattern Case Study: ISRG May 2026

This is the cautionary tale. The naive read of the Δ table screamed "balanced ⭐ — fair value." Five sanity checks reveal it was actually mild-overvalued mid-reset.

**Naive read** (Q1 2026):
- Implied 22.1% vs Realized 20.5% (5y) → Δ +1.6pp 🟡 "almost perfectly balanced"
- Δ history: chronically +13 to +36pp for 4+ years, now converged
- Conclusion if stopped here: "fair value — wishful thinking premium gone"

**What the 5-Point Sanity Check reveals**:

| Check | Finding | Adjusted view |
|---|---|---|
| 1. Base anomaly | FY2020 EPS depressed by COVID elective-surgery shutdown — inflates 5y CAGR by 3-5pp | Normalized realized: **15-18%**, not 20.5% → corrected Δ +4-7pp = MILD OVERVALUED |
| 2. Convergence direction | Implied dropped from 36.5% → 22.1% over 5 quarters (stock fell 19% YTD); Realized stayed ~20% | **Reset, not catchup** — reset may continue |
| 3. vs Mgmt guidance | Mgmt 2026 procedure growth guidance 13.5-15.5% (decelerating from 18%) | To deliver 22% EPS CAGR with sub-16% revenue growth → implied **more optimistic than mgmt** |
| 4. Forward EPS spread | 2026 consensus mean $10.22, low $9.51, high $11.18 = 16% spread | If consensus revised to $9.51, implied jumps to ~25% — **high sensitivity** |
| 5. Forward vs trailing | Hugo (MDT FDA-cleared Dec 2025) + Ottava (J&J pivotal May 2026) + China + Class I recall | Forward 5y realized **likely below** trailing 5y realized |

**Corrected verdict**: ISRG was NOT "balanced" in May 2026 — it was **MILD OVERVALUED with continued reset risk**. The ⭐ in the Δ table was a trap.

**Lesson**: Δ ≈ 0 is **necessary but not sufficient** for "fair value." Run the 5-Point Sanity Check every time before calling balanced.

## 5-Point Sanity Check (run before declaring "balanced")

Before treating Δ within ±3pp as fair value:

1. **Base-period anomaly check**: Does the trailing 5y window include COVID 2020, recession 2008-09, sector boom/bust? If yes, **normalize**:
   - Drop the anomaly year from CAGR calculation
   - Use a longer window (8-10y)
   - Use mid-cycle normalized EPS
   - Anomaly base routinely inflates/deflates realized CAGR by 3-8pp

2. **Convergence direction test**: Use `visualize.html` chart. Is Δ converging because:
   - (a) Realized rising → **bull**, or
   - (b) Implied falling → **valuation reset, may continue**
   - If (b), today's balanced is tomorrow's overvalued.

3. **Implied vs Management Guidance**: Compare Implied CAGR to company's own multi-year guidance:
   - Implied > Mgmt guidance → market more optimistic than mgmt → 🔴 red flag
   - Implied < Mgmt guidance → market discounting executive credibility → ✅ contrarian opportunity if execution validates

4. **Forward EPS spread test**: Pull bull/bear spread for forward EPS:
   - Spread / mean > 10% → high uncertainty → consensus revision risk
   - Stress-test: "If consensus revises ±10%, Implied CAGR moves to X-Y range"
   - Wide spread + decelerating growth = downside leverage

5. **Forward direction overrides backward**: Even if Δ balanced vs 5y trailing, check forward:
   - Management guidance / consensus 2y → is it below or above trailing 5y?
   - If forward < trailing, **backward comparison overstates forward**
   - Cleaner comparison: Implied vs FORWARD expected growth (mgmt + consensus), not just trailing realized

**Implementation**: The webapp `visualize.html` shows the Δ column with color coding. Use the chart to identify convergence direction. Always do steps 1-5 in the analyst's narrative, not just read the auto-signal.

## When to use Δ analysis instead of Industry baseline

- **High-quality compounders** (ISRG, MA, V, COST, MSFT): Δ comparison is much more useful than industry baseline. These stocks always trade premium-to-sector; what matters is whether implied is above or below their OWN realized run-rate.
- **Cyclicals** (CAT, FCX, energy): Δ is tricky because realized swings wildly with the cycle. Use mid-cycle normalized EPS.
- **Inflection plays** (NVDA 2023): Δ is negative (market behind) — the methodology screams "buy."

## Private companies / AI labs — Revenue-based RDCF

EPS-based RDCF breaks for unprofitable hypergrowth (Anthropic, OpenAI, xAI, etc.). Substitute:
- **EPS → Forward annualized revenue ($B)**
- **Exit P/E → Exit revenue multiple**
- Same math:

```
V_today × (1+IRR)^n = Forward_rev × (1+g)^n × Exit_RevMult

g = [V_today × (1+IRR)^n / (Forward_rev × Exit_RevMult)]^(1/n) − 1
```

### Reference exit revenue multiples

| Maturity profile | Exit Rev Mult |
|---|---|
| Mature large-cap tech (META, GOOG, AAPL at peak) | 5–7× |
| Mature high-margin SaaS (MSFT, ADBE, CRM at peak) | 10–12× |
| AI hype current spot (Anthropic, OpenAI now) | 14–40× |
| Telecom 2002 trough analog (multiple-compression bear) | 1–3× |

**The exit multiple is the killer assumption.** It silently determines 70%+ of the output. Use a **sensitivity table by default**, never a point estimate.

### Reference IRR targets

| Capital pool | Required IRR |
|---|---|
| Late-stage growth / public market (cost of equity) | 8–10% |
| Crossover / pre-IPO | 12–15% |
| Growth-stage VC | 15–20% |
| Early-stage VC | 25–35% |

Using IRR=10% for a Series-F private AI lab is **too lenient** — venture investors won't accept that return. Document the IRR you're using and why.

### Mandatory output template for revenue-based RDCF

```
Inputs:
  Valuation:      $XXXBn
  Forward ARR:    $XXBn  (source + date)
  IRR target:     XX%    (justify)
  Exit Rev Mult:  XXx    (justify)
  Horizon:        Xy

Point estimate:   Implied rev CAGR = XX.X%

Sensitivity table:
                Exit Multiple →
IRR ↓     5x      10x      15x      20x
10%       …       …        …        …
15%       …       …        …        …
20%       …       …        …        …

Multiple-compression caveat: at current X× rev multiple, downside to Y× exit would require
Z% implied CAGR to clear IRR hurdle — this is the real bear case, not growth shortfall.
```

### Δ interpretation differs from EPS-based

For hypergrowth labs, recent realized growth is unsustainable (came from ~$0 base):
- **Δ < 0 (implied << realized)** is normal and healthy — market correctly pricing deceleration
- **Δ > 0 (implied > realized)** would be a mania signal (market pricing acceleration above already-explosive growth)
- **The ABSOLUTE implied CAGR vs your S-curve view matters more than Δ.**

### Canonical worked example — OpenAI 2026-05-19

```
Valuation $500B; Forward ARR $35B; IRR 10%; Exit Mult 10x; 5y

Step 1: $500B × (1.10)^5 = $805.3B
Step 2: $805.3B / 10x = $80.5B
Step 3: ($80.5B / $35B)^(1/5) − 1 = 18.1%
```

Then publish the sensitivity table. The 18.1% is meaningless without it.

---

## Exit Multiple by Maturity State — DON'T use 7x as default

The default 7x EV/Revenue (or 25x P/E) is for "still-growing" operators (like EQIX/DLR with 5-10% organic growth, or NVDA-class compounders). **Lazy default of 7x is the #1 silent error** in this skill's history. Apply this discipline:

| Terminal state | Fair Exit EV/Rev | Fair Exit P/E | Examples |
|---|---|---|---|
| **Hyper-growth at exit** (20%+ CAGR continues) | 10-14x | 30-40x | NVDA, top SaaS |
| **Mid-growth at exit** (5-10% CAGR) | 7-9x | 20-25x | EQIX, DLR, mature DC REITs |
| **Mature operator** (2-3% lease escalator only) | **5x** | **15x** | mature DC REIT post-conversion |
| **No-growth + renewal cliff risk** | **2.5-3x** | **7-10x** | "100% MW used" miner pivot, expiring contracts |
| **Commodity / pricing pressure** | 1-2x | 5-8x | telecom carrier, regulated utility at peak |

**Discipline rule**: If your Year-5 ARR / EPS assumes the company has reached its **capacity ceiling** (no new MW / sites / customers / products), use **mature multiple (3-5x EV/Rev, 10-15x P/E)**. Don't apply 7x to a company that ran out of pipeline — that double-counts the growth premium.

**Failure mode this prevents**: Computing fair value with 7x exit on a "full conversion" scenario, then declaring "+200% upside!" — when the math implicitly assumed growth continues past exit despite hitting the capacity ceiling.

---

## Risk-Free Benchmark Check — Sanity test implied yields

After computing implied CAGR + exit multiple, convert to earnings yield and compare to Treasury yield. **If equity yield < Treasury yield, you're paying more for less safety — flag explicitly.**

| Asset | Current yield | P/E equivalent | EV/Revenue (@ 12% net margin) |
|---|---|---|---|
| 10-yr US Treasury | ~4.5% | 22x | 2.6x |
| BBB Corporate bond | ~5.5% | 18x | 2.2x |
| Equity required (no-growth + 6% ERP + 2% renewal risk premium) | 12-14% | 7-8x | **0.96-1.7x** |

**The math**:
- Required equity return = Risk-free + Equity Risk Premium + idiosyncratic risk premium
- = 4.5% + 6% + 2-3% = **12.5-13.5% earnings yield for no-growth, risk-bearing equity**
- = fair P/E 7-8x for no-growth + risk
- × net margin → fair EV/Revenue

**Red flag conditions**:
- Implied EV/Revenue × Net margin → earnings yield **<** Treasury yield → over-paying unless growth catalyst
- Implied P/E **>** Treasury inverse with no growth assumption → unjustified
- Always show: "Implied yield X% vs Treasury Y% → premium of Z pp justified by [explicit growth assumption]"

---

## Capital Structure Sanity Check — Critical for highly-levered infrastructure

For companies funding large CapEx with project debt (DC operators, mining pivots, utilities, manufacturing build-outs):

```
Year-5 Equity Value = Year-5 EV − Year-5 Debt outstanding
                    = (Year-5 Revenue × Exit Mult) − Project debt
```

**At low exit multiples, equity can go NEGATIVE** — the entire scenario is conceptually broken.

**Worked example** (CORZ at $9B Year-5 revenue, $25B debt outstanding):

| Exit Mult | Year-5 EV | − Debt | Year-5 Equity | Status |
|---|---|---|---|---|
| 2.5x | $22.5B | $25B | **−$2.5B** | ❌ insolvent |
| 4x | $36B | $25B | $11B | ✓ marginal |
| 5x | $45B | $25B | $20B | ✓ healthy |
| 7x | $63B | $25B | $38B | ✓ strong |

**Rule**: For levered infrastructure, MINIMUM justifiable exit multiple = **(debt + 1× revenue safety margin) / revenue**. Below that floor, the math breaks regardless of growth assumptions.

**Dilution layer**: Also model equity raised to fund CapEx gap:
- Equity needed = (CapEx required) − (cash on hand) − (debt capacity)
- Dilution % = New shares / Existing shares
- Per-share fair value = Equity FV / Post-dilution shares

Always quote both **enterprise value** and **per-share** outcomes after dilution.

---

## Time-Adjusted Exit Multiple — Is Year-5 still ramping or at ceiling?

The exit multiple should reflect Year-5 **company state**, not company current state:

| Year-5 State | Pipeline status | Exit Mult |
|---|---|---|
| Still ramping (pipeline > Year-5 ARR base) | Growth runway ahead | 5-7x |
| At capacity ceiling (Year-5 ARR ≈ full pipeline) | No more MW/units to add | **3-5x** |
| Post-mature, contract renewals due | Renewal cliff approaching | **2.5-3.5x** |

**Failure mode**: Using 7x exit on a "100% MW used by Year-5" scenario double-counts the growth premium. The 100% used scenario already captured ALL growth from current to ceiling; applying 7x exit assumes growth CONTINUES post-exit — but where would the growth come from when capacity is fully used?

**Discipline check**: Match exit multiple to terminal state:
- If you wrote "Year-5 ARR includes full pipeline conversion" → use 3-5x exit
- If you wrote "Year-5 ARR = currently contracted ramp only" → 7x exit OK because partial conversion still implies pipeline available

---

## Probability-Weighted Expected Return — Always compute

Single-scenario point estimates are dangerous. Always build probability tree before declaring buy/sell:

```
| Path | Probability | Per-share outcome | Probability-weighted |
|---|---|---|---|
| Bear (extreme downside)          | 20-25% | −60 to −80%  | (calc) |
| Mid bear (partial execution miss) | 25-35% | −20 to +10%  | (calc) |
| Base (expected execution)         | 30-40% | +20 to +50%  | (calc) |
| Bull (above-expectation)          | 10-20% | +100 to +300%| (calc) |
| EXPECTED RETURN                   | 100%   |              | Σ      |
```

Then compare expected return to **Treasury 4.5%/yr × horizon** = 25% 5-year baseline.

**Decision framework**:
- Expected return < Treasury baseline → don't take the risk
- Expected return > Treasury but tail downside > 50% → size position to reflect tail
- Expected return > Treasury AND tail downside < 30% → core holding candidate
- Negative expected return → only if as hedge / pair trade short leg

---

## Mathematical Equivalence Trap — Multiple vs Growth Decomposition

These three statements are **mathematically equivalent** for a given market cap:

| Decomposition | Forward ARR | Implied CAGR | Exit Mult |
|---|---|---|---|
| Conservative growth + premium mult | $2B | 16% | 7x |
| Mid growth + mid mult | $4B | 30% | 3.9x |
| Aggressive growth + commodity mult | $7B | 55% | 1.6x |

All three imply the same current market cap — they differ in **how you attribute the expectation** between revenue ramp and multiple maintenance.

**Best practice when analyzing**:
1. State the decomposition you're using explicitly
2. Show all three to let reader pick their lens
3. Different investors weight "growth shortfall risk" vs "multiple compression risk" differently
4. The pair trade thesis often arises from ONE peer pricing in mode A while another prices in mode B

**Failure mode**: Implicitly using one decomposition without stating it, then comparing peers using a DIFFERENT decomposition. Apples-to-oranges error.

---

## Worked Example — Miner-to-AI Sector (CLSK / IREN / CORZ, May 2026)

This is the canonical case study where 7x default broke and required all corrections above.

**Sector context**: Bitcoin miners pivoting to AI/HPC datacenter operators. Heavy CapEx ($10M/MW), long contracts (10-15 yr), hyperscaler tenants (Microsoft, AWS, CoreWeave, Fluidstack/Google).

**Lessons**:

1. **Exit multiple compression**: Miners at "100% MW used" state should trade at 3-5x EV/Rev (mature DC REIT), not 7x (still-growing EQIX/DLR multiple). Applying 7x to full-conversion scenario inflated FV by 40-50%.

2. **Risk-free benchmark**: IREN at $18B implied 3.8% equity yield < 4.5% Treasury. Either growth catalyst exists OR over-paying. Required explicit narrative on which.

3. **Capital structure**: CORZ at 2.5x exit had NEGATIVE equity value due to $25B project debt outstanding. Below 4x exit, math breaks for capital-intensive operators.

4. **Time-adjusted**: CLSK with 1.8 GW pipeline reaching 100% by 2031 (Year-5 = ceiling) → should use 4-5x exit. IREN with 5 GW pipeline maybe 60-80% by Year-5 → 5-7x exit OK.

5. **Probability-weighted**: CLSK base case point estimate "+80% upside" misleading. Probability-weighted expected return was **~0%** because 25% probability of −70% bear case (no anchor signed) dominated.

6. **Mathematical equivalence**: Same IREN $18B mcap could be explained as "16% CAGR + 7x exit" OR "55% CAGR + 1.6x exit" — both true mathematically, but very different bull/bear narratives.

**Bottom line**: For sector with regime change, large CapEx, and pipeline-driven growth, EPS-based RDCF doesn't work. Use **revenue-based RDCF with explicit exit multiple discipline, capital structure check, and probability weighting**.
