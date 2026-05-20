#!/usr/bin/env python3
"""
Forward-based Reverse DCF calculator.

Computes the EPS CAGR implicitly required by today's stock price,
given target IRR, holding period, and exit P/E assumption.

Two comparison modes:
  1. Historical (preferred): pass --historical-eps "E_n,E_n-1,...,E_1" (oldest first).
     Compares implied CAGR to the company's own 5y CAGR + recent acceleration —
     better at spotting turning points than a generic industry baseline.
  2. Industry baseline (fallback): pass --industry <key> for a sector-typical CAGR.
"""
import argparse
import sys


def implied_cagr(stock: float, forward_eps: float, irr: float, n: int, exit_pe: float) -> float:
    if forward_eps <= 0:
        return float("nan")
    forward_pe = stock / forward_eps
    multiplier = forward_pe * (1 + irr) ** n / exit_pe
    if multiplier <= 0:
        return float("-inf")
    return multiplier ** (1.0 / n) - 1


def safe_growth(prev: float, curr: float) -> float:
    """YoY growth with sane handling of zero/negative bases."""
    if prev <= 0:
        return float("nan")
    return (curr - prev) / prev


def safe_cagr(start: float, end: float, n_years: int) -> float:
    if start <= 0 or end <= 0 or n_years <= 0:
        return float("nan")
    return (end / start) ** (1.0 / n_years) - 1


def analyze_history(historical_eps: list, forward_eps: float) -> dict:
    """Compute YoY growths, rolling CAGRs, and growth acceleration.

    historical_eps: list of past annual EPS values, OLDEST first, not including
    the forward year. e.g. [E_-5, E_-4, E_-3, E_-2, E_-1].
    forward_eps: the next-12-month EPS (treated as "year 0").
    """
    all_eps = list(historical_eps) + [forward_eps]
    n = len(all_eps) - 1  # number of growth periods

    yoy = []
    for i in range(1, len(all_eps)):
        yoy.append(safe_growth(all_eps[i - 1], all_eps[i]))

    # Trailing CAGRs at different windows ending at forward
    trailing_cagrs = {}
    for window in (1, 2, 3, 5):
        if window <= n:
            trailing_cagrs[window] = safe_cagr(all_eps[-1 - window], all_eps[-1], window)

    # Growth acceleration: change in YoY growth across last two periods
    accel = float("nan")
    if len(yoy) >= 2:
        last = yoy[-1]
        prior = yoy[-2]
        if last == last and prior == prior:  # neither NaN
            accel = last - prior

    # Average of last 5 YoY growth rates (arithmetic) — closer to "recent typical pace"
    last_n_yoy = [g for g in yoy[-5:] if g == g]  # filter NaN
    avg_yoy_5 = sum(last_n_yoy) / len(last_n_yoy) if last_n_yoy else float("nan")

    return {
        "yoy_growth": yoy,
        "trailing_cagrs": trailing_cagrs,
        "acceleration": accel,
        "avg_yoy_5": avg_yoy_5,
        "all_eps": all_eps,
    }


INDUSTRY_BASELINES = {
    "utilities": 0.05,
    "energy": 0.05,
    "consumer_staples": 0.06,
    "industrials": 0.08,
    "financials": 0.08,
    "healthcare": 0.10,
    "tech_mature": 0.12,
    "tech_growth": 0.18,
    "ai_hypergrowth": 0.25,
}


def fmt_pct(x: float, signed: bool = True) -> str:
    if x != x:  # NaN
        return "  n/a"
    sign = "+" if signed and x >= 0 else ""
    return f"{sign}{x*100:.1f}%"


def main() -> int:
    p = argparse.ArgumentParser(description="Forward-based Reverse DCF")
    p.add_argument("--price", type=float, required=True)
    p.add_argument("--forward-eps", type=float, required=True)
    p.add_argument("--irr", type=float, default=0.10)
    p.add_argument("--years", type=int, default=5)
    p.add_argument("--exit-pe", type=float, default=25.0)
    p.add_argument("--industry", type=str, default=None,
                   choices=list(INDUSTRY_BASELINES.keys()),
                   help="Industry baseline (fallback if no --historical-eps).")
    p.add_argument("--historical-eps", type=str, default=None,
                   help="Comma-separated past annual EPS, OLDEST first. "
                        "E.g. '0.41,0.27,0.50,0.99,0.17' = FY-5 to FY-1.")
    p.add_argument("--ticker", type=str, default="")
    args = p.parse_args()

    if args.forward_eps <= 0:
        print("Error: forward EPS must be positive (RDCF breaks at <= 0)", file=sys.stderr)
        return 1

    fpe = args.price / args.forward_eps
    icagr = implied_cagr(args.price, args.forward_eps, args.irr, args.years, args.exit_pe)

    label = f"{args.ticker} " if args.ticker else ""
    print(f"\n=== {label}Forward-based Reverse DCF ===")
    print(f"Price:           ${args.price:.2f}")
    print(f"Forward EPS:     ${args.forward_eps:.2f}")
    print(f"Forward P/E:     {fpe:.1f}x")
    print(f"Assumptions:     {args.irr*100:.0f}% IRR, {args.years}y horizon, exit {args.exit_pe:.0f}x")
    print(f"Implied CAGR:    {fmt_pct(icagr)}")

    # --- Historical comparison (preferred) ---
    if args.historical_eps:
        try:
            hist = [float(x.strip()) for x in args.historical_eps.split(",") if x.strip()]
        except ValueError:
            print("Error: --historical-eps must be comma-separated numbers", file=sys.stderr)
            return 1
        if len(hist) < 2:
            print("Error: need at least 2 historical EPS values", file=sys.stderr)
            return 1

        h = analyze_history(hist, args.forward_eps)

        print(f"\n--- Historical Growth ({label.strip() or 'company'}) ---")
        # EPS series with arrows
        series = " → ".join(f"${e:.2f}" for e in h["all_eps"][:-1])
        series += f" → ${h['all_eps'][-1]:.2f} (fwd)"
        print(f"EPS series:      {series}")

        # YoY growth series
        print(f"YoY growth:")
        for i, g in enumerate(h["yoy_growth"]):
            year_idx = i + 1 - len(h["yoy_growth"])
            if year_idx == 0:
                lbl = "  Y-1 → Forward "
            else:
                lbl = f"  Y{year_idx-1} → Y{year_idx}      "
            print(f"{lbl} {fmt_pct(g):>8}")

        # Trailing CAGRs
        print(f"Trailing CAGRs:")
        for window, c in sorted(h["trailing_cagrs"].items()):
            print(f"  {window}y CAGR:        {fmt_pct(c):>8}")

        # Acceleration
        accel = h["acceleration"]
        if accel == accel:
            if accel > 0.05:
                accel_tag = "ACCELERATING ↑"
            elif accel < -0.05:
                accel_tag = "DECELERATING ↓"
            else:
                accel_tag = "stable ~"
            print(f"Growth ΔΔ (last vs prior YoY): {fmt_pct(accel):>8}  [{accel_tag}]")

        # Composite signal: implied vs avg recent YoY + acceleration
        bench = h["avg_yoy_5"]
        if bench == bench:
            delta = icagr - bench
            print(f"\nImplied CAGR vs avg recent YoY growth ({fmt_pct(bench)}):")
            print(f"  Delta:         {fmt_pct(delta):>8} pp")

            # Composite signal — 2x2 matrix of (under/over vs bench) and (accel/decel)
            under = delta < -0.03
            over = delta > 0.03
            accelerating = accel == accel and accel > 0.05
            decelerating = accel == accel and accel < -0.05

            if under and accelerating:
                sig = "STRONG UNDERVALUED   (priced below historical, growth accelerating)"
            elif under and decelerating:
                sig = "MILD UNDERVALUED     (priced below historical, but growth slowing — could be justified)"
            elif under:
                sig = "UNDERVALUED          (priced below historical, growth stable)"
            elif over and accelerating:
                sig = "MILD OVERVALUED      (priced above historical, but growth accelerating could justify)"
            elif over and decelerating:
                sig = "STRONG OVERVALUED    (priced above historical, growth decelerating — turning point risk)"
            elif over:
                sig = "OVERVALUED           (priced above historical, growth stable)"
            else:
                sig = "FAIR                 (implied matches historical pace)"
            print(f"  Signal:        {sig}")

    # --- Industry fallback ---
    elif args.industry:
        baseline = INDUSTRY_BASELINES[args.industry]
        delta = icagr - baseline
        if delta < -0.03:
            signal = "UNDERVALUED candidate"
        elif delta > 0.03:
            signal = "OVERVALUED candidate"
        else:
            signal = "FAIR"
        print(f"\n--- Industry baseline: {args.industry} ---")
        print(f"Baseline CAGR:   {fmt_pct(baseline)}")
        print(f"Delta:           {fmt_pct(delta)} pp")
        print(f"Signal:          {signal}")
        print(f"(Tip: pass --historical-eps for company-specific comparison + turning-point detection.)")

    # --- Exit P/E sensitivity ---
    print(f"\n--- Exit P/E Sensitivity ---")
    print(f"{'Exit P/E':<10}{'Implied CAGR':<15}")
    print("-" * 28)
    for pe in [15, 18, 20, 25, 30, 35, 40, 50]:
        c = implied_cagr(args.price, args.forward_eps, args.irr, args.years, pe)
        marker = "  <-- baseline" if abs(pe - args.exit_pe) < 0.5 else ""
        print(f"{pe}x{'':<8}{fmt_pct(c):>8}{marker}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
