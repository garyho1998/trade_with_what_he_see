#!/usr/bin/env python3
"""
Minervini SEPA Screener.

Mechanical implementation of Mark Minervini's Trend Template + VCP + Stage + RS
proxy + fundamentals snapshot.

Usage:
  ~/.config/minervini-screener/venv/bin/python \
    ~/.claude/skills/minervini-screener/screen.py NVDA
  ~/.config/minervini-screener/venv/bin/python \
    ~/.claude/skills/minervini-screener/screen.py NVDA,META,AVGO --json
  ~/.config/minervini-screener/venv/bin/python \
    ~/.claude/skills/minervini-screener/screen.py --file ~/watchlist.txt

Requires venv at ~/.config/minervini-screener/venv with yfinance, pandas, numpy.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# Shared market-data library (Phase 2 migration — replaces JSON cache).
_MARKET_DATA_DIR = Path.home() / ".config" / "market_data"
if str(_MARKET_DATA_DIR) not in sys.path:
    sys.path.insert(0, str(_MARKET_DATA_DIR))

try:
    import numpy as np
    import pandas as pd
    from marketdata import MarketDataClient
except ImportError as e:
    print(
        "Missing deps. Install:  ~/.config/minervini-screener/venv/bin/pip "
        "install yfinance pandas numpy\n"
        f"  also requires shared market_data lib at {_MARKET_DATA_DIR}\n"
        f"  underlying error: {e}",
        file=sys.stderr,
    )
    sys.exit(2)

TRADING_DAYS_YEAR = 252
TRADING_DAYS_MONTH = 21
TRADING_DAYS_QUARTER = 63

# Minervini fundamentals thresholds
EPS_GROWTH_THRESHOLD = 25.0  # %
SALES_GROWTH_THRESHOLD = 25.0  # %
ROE_THRESHOLD = 17.0  # %

# CAN SLIM-style hard gate (Option B). When fund.score < this threshold,
# the verdict is forced to AVOID regardless of trend/VCP quality, and the
# expensive detect_vcp() step is skipped to save compute. Set to 0 to disable
# the gate (pure Minervini behaviour — fundamentals only inform, never block).
FUND_GATE_THRESHOLD = 2  # out of 3 (EPS growth ≥25%, sales ≥25%, ROE ≥17%)


# ---------------------------------------------------------------------------
# Data fetch — backed by shared MarketDataClient (Phase 2)
# ---------------------------------------------------------------------------


def fetch_data(ticker: str, use_cache: bool = True) -> dict[str, Any] | None:
    """Pull OHLCV + quarterly + info via the shared MarketDataClient.

    Returns dict with keys:
      ticker, fetched_at, prices_df (pd.DataFrame), quarterly_eps (list),
      quarterly_revenue (list), info (dict), next_earnings (str or None).
    Returns None if data is unusable.

    The shared client handles SQLite caching (24h TTL for prices/info,
    168h for quarterly). use_cache=False forces a refresh.
    """
    ticker = ticker.upper().strip()
    force = not use_cache
    try:
        with MarketDataClient(skill_name="minervini-screener") as c:
            prices_df = c.get_prices(ticker, days=400, force_refresh=force)
            if prices_df.empty or len(prices_df) < 50:
                return None
            qfin_df = c.get_quarterly(ticker, quarters=20, force_refresh=force)
            info_row = c.get_info(ticker, force_refresh=force)
    except Exception as e:
        print(f"  [error] {ticker}: market_data fetch failed: {e}",
              file=sys.stderr)
        return None

    # Convert quarterly DataFrame → old list-of-dicts shape consumed by fundamentals()
    quarterly_eps: list[dict[str, Any]] = []
    quarterly_revenue: list[dict[str, Any]] = []
    if not qfin_df.empty:
        for _, row in qfin_df.iterrows():
            pe = row["period_end"].strftime("%Y-%m-%d")
            eps = row.get("eps_diluted")
            rev = row.get("revenue")
            if pd.notna(eps):
                quarterly_eps.append({"period_end": pe, "eps": float(eps)})
            if pd.notna(rev):
                quarterly_revenue.append({"period_end": pe, "revenue": float(rev)})

    # Re-shape info to match old yfinance-style keys (so downstream code unchanged)
    info: dict[str, Any] = {}
    if info_row:
        if info_row.get("long_name"):
            info["longName"] = info_row["long_name"]
        if info_row.get("short_name"):
            info["shortName"] = info_row["short_name"]
        if info_row.get("sector"):
            info["sector"] = info_row["sector"]
        if info_row.get("industry"):
            info["industry"] = info_row["industry"]
        if info_row.get("market_cap") is not None:
            info["marketCap"] = info_row["market_cap"]
        if info_row.get("trailing_eps") is not None:
            info["trailingEps"] = info_row["trailing_eps"]
        if info_row.get("forward_eps") is not None:
            info["forwardEps"] = info_row["forward_eps"]
        if info_row.get("roe") is not None:
            info["returnOnEquity"] = info_row["roe"]  # fraction (e.g. 0.32)

    return {
        "ticker": ticker,
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "prices_df": prices_df,
        "quarterly_eps": quarterly_eps,
        "quarterly_revenue": quarterly_revenue,
        "info": info,
        "next_earnings": (info_row.get("next_earnings_date")
                          if info_row else None),
    }


def prices_to_df(prices) -> pd.DataFrame:
    """Backward-compat: accepts either a DataFrame (new) or list-of-dicts (legacy)."""
    if isinstance(prices, pd.DataFrame):
        return prices
    df = pd.DataFrame(prices)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    return df


# ---------------------------------------------------------------------------
# SMAs + Trend Template
# ---------------------------------------------------------------------------


def compute_smas(df: pd.DataFrame) -> dict[str, Any]:
    close = df["close"]
    smas = {
        "sma50": float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else None,
        "sma150": float(close.rolling(150).mean().iloc[-1]) if len(close) >= 150 else None,
        "sma200": float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else None,
        "sma200_21d_ago": (
            float(close.rolling(200).mean().iloc[-1 - TRADING_DAYS_MONTH])
            if len(close) >= 200 + TRADING_DAYS_MONTH
            else None
        ),
        "sma200_4mo_ago": (
            float(close.rolling(200).mean().iloc[-1 - 4 * TRADING_DAYS_MONTH])
            if len(close) >= 200 + 4 * TRADING_DAYS_MONTH
            else None
        ),
    }
    # 30-week SMA on weekly closes (Fri close convention)
    weekly = close.resample("W-FRI").last().dropna()
    if len(weekly) >= 30:
        sma30w = weekly.rolling(30).mean()
        smas["sma30w"] = float(sma30w.iloc[-1])
        # slope: % change of 30W SMA per week, averaged over last 5 weeks
        if len(sma30w.dropna()) >= 6:
            recent = sma30w.dropna().iloc[-6:]
            pct_per_week = ((recent.iloc[-1] / recent.iloc[0]) ** (1 / 5) - 1) * 100
            smas["sma30w_slope_pct_per_week"] = float(pct_per_week)
        else:
            smas["sma30w_slope_pct_per_week"] = None
        # 10W SMA on weekly close
        if len(weekly) >= 10:
            smas["sma10w"] = float(weekly.rolling(10).mean().iloc[-1])
        else:
            smas["sma10w"] = None
    else:
        smas["sma30w"] = None
        smas["sma30w_slope_pct_per_week"] = None
        smas["sma10w"] = None

    return smas


def trend_template(df: pd.DataFrame, smas: dict[str, Any], rs_rank: int | None
                   ) -> dict[str, Any]:
    """Run the 8 Trend Template criteria. Returns per-criterion bool + detail."""
    close = float(df["close"].iloc[-1])
    high_52w = float(df["high"].tail(TRADING_DAYS_YEAR).max())
    low_52w = float(df["low"].tail(TRADING_DAYS_YEAR).min())

    s50, s150, s200 = smas.get("sma50"), smas.get("sma150"), smas.get("sma200")
    s200_21 = smas.get("sma200_21d_ago")
    s200_4mo = smas.get("sma200_4mo_ago")

    def fmt(v):
        return f"{v:.2f}" if v is not None else "n/a"

    # C1: close > sma150 and close > sma200
    c1 = (s150 is not None and s200 is not None and close > s150 and close > s200)
    c1_detail = f"close {fmt(close)} > sma150 {fmt(s150)} > sma200 {fmt(s200)}"

    # C2: sma150 > sma200
    c2 = (s150 is not None and s200 is not None and s150 > s200)
    c2_detail = f"sma150 {fmt(s150)} {'>' if c2 else '<='} sma200 {fmt(s200)}"

    # C3: sma200 trending up >= 1 month
    c3 = (s200 is not None and s200_21 is not None and s200 > s200_21)
    c3_detail = f"sma200 {fmt(s200)} vs 21d ago {fmt(s200_21)} ({'rising' if c3 else 'flat/falling'})"
    c3_preferred = (s200 is not None and s200_4mo is not None and s200 > s200_4mo)

    # C4: sma50 > sma150 and sma50 > sma200
    c4 = (s50 is not None and s150 is not None and s200 is not None
          and s50 > s150 and s50 > s200)
    c4_detail = f"sma50 {fmt(s50)} > sma150 {fmt(s150)} > sma200 {fmt(s200)}"

    # C5: close > sma50
    c5 = (s50 is not None and close > s50)
    c5_detail = f"close {fmt(close)} {'>' if c5 else '<='} sma50 {fmt(s50)}"

    # C6: close >= 1.30 * low_52w
    pct_above_low = (close / low_52w - 1) * 100 if low_52w else 0
    c6 = pct_above_low >= 30.0
    c6_detail = f"close {fmt(close)} is +{pct_above_low:.1f}% above 52W low {fmt(low_52w)}"

    # C7: close >= 0.75 * high_52w
    pct_below_high = (1 - close / high_52w) * 100 if high_52w else 0
    c7 = close >= 0.75 * high_52w
    c7_detail = f"close {fmt(close)} is -{pct_below_high:.1f}% below 52W high {fmt(high_52w)}"

    # C8: RS rank >= 70
    c8 = rs_rank is not None and rs_rank >= 70
    c8_detail = f"RS proxy = {rs_rank}" if rs_rank is not None else "RS proxy n/a"

    crit = [
        ("c1_price_above_150_200", c1, c1_detail),
        ("c2_sma150_above_sma200", c2, c2_detail),
        ("c3_sma200_trending_up_1mo", c3, c3_detail),
        ("c4_sma50_above_150_200", c4, c4_detail),
        ("c5_price_above_sma50", c5, c5_detail),
        ("c6_30pct_above_52w_low", c6, c6_detail),
        ("c7_within_25pct_of_52w_high", c7, c7_detail),
        ("c8_rs_rank_70_plus", c8, c8_detail),
    ]
    score = sum(1 for _, ok, _ in crit if ok)
    return {
        "score": score,
        "max_score": 8,
        "criteria": [
            {"id": cid, "pass": ok, "detail": d} for cid, ok, d in crit
        ],
        "c3_preferred_long_uptrend": c3_preferred,  # 200 > 4mo ago — Minervini's preference
        "high_52w": high_52w,
        "low_52w": low_52w,
        "close": close,
    }


# ---------------------------------------------------------------------------
# Stage classification (Weinstein 1-4)
# ---------------------------------------------------------------------------


def detect_stage(df: pd.DataFrame, smas: dict[str, Any]) -> dict[str, Any]:
    sma30w = smas.get("sma30w")
    slope = smas.get("sma30w_slope_pct_per_week")
    sma10w = smas.get("sma10w")
    close = float(df["close"].iloc[-1])

    if sma30w is None or slope is None:
        return {"stage": "UNKNOWN", "reason": "insufficient history for 30W SMA"}

    pct_from_30w = (close / sma30w - 1) * 100
    above_30w = close > sma30w
    rising = slope > 0.1   # > +0.1% per week (10-week proj ~ +1%)
    falling = slope < -0.1
    flat = abs(slope) <= 0.1

    # Stage 2: above and rising, 10W > 30W
    if above_30w and rising and (sma10w is not None and sma10w > sma30w):
        stage, reason = ("Stage 2", f"close +{pct_from_30w:.1f}% above 30W, 30W rising "
                                    f"+{slope:.2f}%/wk, 10W>30W — advancing")
    # Stage 4: below and falling
    elif (not above_30w) and falling:
        stage, reason = ("Stage 4", f"close {pct_from_30w:.1f}% below 30W, "
                                    f"30W falling {slope:.2f}%/wk — declining")
    # Stage 1: near 30W and flat
    elif abs(pct_from_30w) <= 5 and flat:
        stage, reason = ("Stage 1", f"close within ±5% of 30W, 30W flat ({slope:.2f}%/wk) — basing")
    # Stage 3: above 30W but flat, or rising slowed dramatically
    elif above_30w and (flat or slope < 0.2):
        stage, reason = ("Stage 3", f"close +{pct_from_30w:.1f}% above 30W but 30W flat "
                                    f"({slope:.2f}%/wk) — topping/distributing")
    # Fallback "mixed" — call it Stage 1 or Stage 4 lean
    elif above_30w:
        stage, reason = ("Stage 3?", f"above 30W ({pct_from_30w:.1f}%) but trend unclear "
                                     f"(slope {slope:.2f}%/wk)")
    else:
        stage, reason = ("Stage 4?", f"below 30W ({pct_from_30w:.1f}%), slope {slope:.2f}%/wk")

    return {"stage": stage, "reason": reason, "pct_from_30w": pct_from_30w,
            "slope_pct_per_week": slope}


# ---------------------------------------------------------------------------
# VCP detection (v2 — layered: zigzag swings + tightening + independent confirm)
# ---------------------------------------------------------------------------


def percentage_zigzag(df: pd.DataFrame, threshold_pct: float = 4.0
                      ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Confirmed swings via percentage-reversal zigzag.

    A candidate extremum becomes a confirmed swing only after price reverses
    ≥ threshold_pct from it in the opposite direction. This filters out
    micro-wiggles and gives a clean alternating H/L sequence.

    Returns (confirmed_swings, pending_candidate).
    Each swing dict = {type: 'H'|'L', idx, date, price}.
    """
    if len(df) < 5:
        return [], None
    thr = threshold_pct / 100.0
    high = df["high"].values.astype(float)
    low = df["low"].values.astype(float)
    dates = df.index

    # Bootstrap: scan first ~20 bars to pick initial direction
    init_n = min(20, len(df))
    init_high_idx = int(np.argmax(high[:init_n]))
    init_low_idx = int(np.argmin(low[:init_n]))

    confirmed: list[dict[str, Any]] = []
    if init_high_idx < init_low_idx:
        # Up first, then down — anchor a high, then look for a low
        confirmed.append({"type": "H", "idx": init_high_idx,
                          "date": dates[init_high_idx].strftime("%Y-%m-%d"),
                          "price": float(high[init_high_idx])})
        state = "looking_for_low"
        cand_idx, cand_price = init_low_idx, float(low[init_low_idx])
        start_idx = init_low_idx + 1
    else:
        confirmed.append({"type": "L", "idx": init_low_idx,
                          "date": dates[init_low_idx].strftime("%Y-%m-%d"),
                          "price": float(low[init_low_idx])})
        state = "looking_for_high"
        cand_idx, cand_price = init_high_idx, float(high[init_high_idx])
        start_idx = init_high_idx + 1

    for i in range(start_idx, len(df)):
        h, l = float(high[i]), float(low[i])
        if state == "looking_for_high":
            if h > cand_price:
                cand_idx, cand_price = i, h
            elif l <= cand_price * (1 - thr):
                confirmed.append({"type": "H", "idx": cand_idx,
                                  "date": dates[cand_idx].strftime("%Y-%m-%d"),
                                  "price": cand_price})
                state = "looking_for_low"
                cand_idx, cand_price = i, l
        else:  # looking_for_low
            if l < cand_price:
                cand_idx, cand_price = i, l
            elif h >= cand_price * (1 + thr):
                confirmed.append({"type": "L", "idx": cand_idx,
                                  "date": dates[cand_idx].strftime("%Y-%m-%d"),
                                  "price": cand_price})
                state = "looking_for_high"
                cand_idx, cand_price = i, h

    pending = {
        "type": "H" if state == "looking_for_low" else "L",
        "idx": cand_idx,
        "date": dates[cand_idx].strftime("%Y-%m-%d"),
        "price": cand_price,
    }
    return confirmed, pending


def _compute_atr(df: pd.DataFrame, window: int = 20) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(window).mean()


def atr_contracting(df: pd.DataFrame, lookback: int = 63, ratio_threshold: float = 0.70
                    ) -> tuple[bool, float | None]:
    """Is ATR(today) < ratio_threshold × ATR(lookback bars ago)?"""
    if len(df) < lookback + 25:
        return False, None
    atr = _compute_atr(df, window=20)
    cur, prior = atr.iloc[-1], atr.iloc[-lookback]
    if pd.isna(cur) or pd.isna(prior) or prior <= 0:
        return False, None
    ratio = float(cur) / float(prior)
    return ratio < ratio_threshold, ratio


def bb_squeeze(df: pd.DataFrame, window: int = 20, lookback: int = 120,
               quantile: float = 0.10) -> tuple[bool, float | None]:
    """Bollinger Band width in bottom `quantile` of last `lookback` days = squeeze."""
    if len(df) < lookback + window:
        return False, None
    mid = df["close"].rolling(window).mean()
    std = df["close"].rolling(window).std()
    width = (4 * std) / mid  # (upper − lower) / mid, with upper = mid + 2σ
    cur = width.iloc[-1]
    if pd.isna(cur):
        return False, None
    window_data = width.dropna().tail(lookback)
    if len(window_data) < 30:
        return False, None
    threshold = float(window_data.quantile(quantile))
    return float(cur) <= threshold, float(cur)


def volume_dryup_check(df: pd.DataFrame, recent_window: int = 10, base_window: int = 60,
                       ratio_threshold: float = 0.70, climax_multiplier: float = 2.5
                       ) -> tuple[bool, float | None, bool]:
    """Is recent avg volume < ratio_threshold × base avg volume?

    Uses a CLIMAX-RESISTANT baseline. If the base window contains ≥2 climax
    days (volume > climax_multiplier × median), those days are excluded from
    the baseline. Without this, a recent climax spike inflates the baseline,
    making post-climax exhaustion look like "supply absorbed" dry-up.

    Trigger case: Visual Photonics 2455 May 2026 — 4/27-5/5 had 28-33M climax
    volume; recent 3M avg vs raw 14M baseline looked like 0.21 dry-up (great),
    but vs climax-cleaned 5M baseline ratio is 0.60 (mediocre — no real
    accumulation, just post-climax cool-down).

    Returns (is_dryup, ratio, climax_detected).
    """
    if len(df) < base_window + 5:
        return False, None, False
    v = df["volume"].astype(float)
    recent = v.tail(recent_window).mean()

    base_series = v.tail(base_window)
    median_vol = base_series.median()
    climax_mask = base_series > climax_multiplier * median_vol
    n_climax_days = int(climax_mask.sum())
    climax_detected = n_climax_days >= 2

    if climax_detected:
        clean_series = base_series[~climax_mask]
        clean_base = clean_series.mean() if len(clean_series) > 0 else base_series.mean()
    else:
        clean_base = base_series.mean()

    if clean_base <= 0 or pd.isna(recent) or pd.isna(clean_base):
        return False, None, climax_detected

    ratio = float(recent) / float(clean_base)
    return ratio < ratio_threshold, ratio, climax_detected


def up_down_volume_ratio(df: pd.DataFrame, window: int = 20
                         ) -> tuple[float | None, bool]:
    """Volume on UP days / Volume on DOWN days over `window` sessions.

    Direct measure of institutional behaviour:
      UDR ≥ 1.5  → bullish accumulation (funds buying on up-days)
      UDR ~ 1.0  → neutral
      UDR ≤ 0.7  → distribution (funds dumping on down-days)

    Much harder to fake than raw "dry-up" — a stock under distribution can
    show declining absolute volume while UDR collapses, and a real base in
    accumulation shows UDR > 1.5 even if absolute volume isn't impressive.

    Returns (udr_value, is_accumulation).
    """
    if len(df) < window + 1:
        return None, False
    recent = df.tail(window).copy()
    recent = recent.assign(change=recent["close"].diff())
    up_vol = float(recent.loc[recent["change"] > 0, "volume"].sum())
    down_vol = float(recent.loc[recent["change"] < 0, "volume"].sum())
    if down_vol <= 0:
        return None, False  # all up days; can't compute ratio meaningfully
    udr = up_vol / down_vol
    return udr, udr >= 1.5


def check_tightening(pairs: list[tuple[dict, dict]], max_t: int = 5
                     ) -> dict[str, Any]:
    """Run the 5 tightening criteria on the last 2..max_t (high, low) pairs.

    Each pair = (peak swing dict, trough swing dict) — one contraction.
    """
    if len(pairs) < 2:
        return {"is_pattern": False, "t_count": len(pairs), "score": 0,
                "max_score": 5, "depths_pct": [], "durations_bars": [],
                "lows": [], "highs": [], "base_depth_pct": None,
                "details": {"reason": f"only {len(pairs)} contraction(s)"}}

    sel = pairs[-max_t:]
    n = len(sel)
    depths = [(h["price"] - l["price"]) / h["price"] * 100 for h, l in sel]
    durations = [l["idx"] - h["idx"] for h, l in sel]
    lows = [l["price"] for _, l in sel]
    highs = [h["price"] for h, _ in sel]
    max_high = max(highs)
    min_low = min(lows)
    min_high = min(highs)

    # 1. Depth tightening (each ≤ 0.70 × prior — Minervini's "halve" rule, loosened)
    depth_tightening = all(depths[i + 1] <= 0.70 * depths[i] for i in range(n - 1))
    depth_monotonic = all(depths[i + 1] < depths[i] for i in range(n - 1))
    # 2. Time tightening (each ≤ prior duration)
    time_tightening = all(durations[i + 1] <= durations[i] for i in range(n - 1))
    # 3. Higher lows (rising support shelf)
    higher_lows = all(lows[i + 1] >= lows[i] for i in range(n - 1))
    # 4. Base depth from absolute peak ≤ 35%
    base_depth_pct = (max_high - min_low) / max_high * 100 if max_high > 0 else 0
    base_depth_ok = base_depth_pct <= 35.0
    # 5. Final contraction tight (< 10%)
    final_tight = depths[-1] < 10.0

    # 6. flat_highs: peaks form a recognisable resistance shelf. Pass if EITHER
    #    (a) very flat — peaks within ±10% range, OR
    #    (b) has resistance test — at least one peak gave back ≥3% from prior
    #        peak AND overall range ≤25% (peaks wobbled around a level).
    # Pure rising channels have peaks strictly monotonically increasing —
    # both conditions fail → flat_highs=False. Real bases (even noisy ones
    # like TSLA Q2 2020, META Q4 2023) wobble at the resistance line.
    high_range_pct = (max_high - min_high) / min_high * 100 if min_high > 0 else 0
    peak_givebacks = sum(
        1 for i in range(1, n)
        if highs[i - 1] > 0 and (highs[i - 1] - highs[i]) / highs[i - 1] >= 0.03
    )
    has_resistance_test = peak_givebacks >= 1 and high_range_pct <= 25.0
    flat_highs = (high_range_pct <= 10.0) or has_resistance_test

    # 7. base_long_enough: swing peaks span ≥15 bars (≈3 weeks). Real VCP
    # needs time to absorb supply; vertical movers cluster swings in days.
    first_high_idx = sel[0][0]["idx"]
    last_high_idx = sel[-1][0]["idx"]
    base_duration_bars = last_high_idx - first_high_idx
    base_long_enough = base_duration_bars >= 15

    # 8. all_tight: every contraction in the base ≤10% (uniformly tight base).
    # 9. tight_end_geometry: Minervini's canonical VCP geometry — final ≤10%,
    #    second-last ≤15%, third-last ≤20%. Each contraction at most 1.5× the
    #    next, so progressive tightening as base completes. Allows EARLIER
    #    contractions to be bigger (the prior advance's volatility).
    all_tight = max(depths) <= 10.0 if depths else False
    tight_end_geometry = (
        n >= 3
        and depths[-1] <= 10.0
        and depths[-2] <= 15.0
        and depths[-3] <= 20.0
    )

    score = sum([depth_tightening, time_tightening, higher_lows,
                 base_depth_ok, final_tight])

    # Two paths to is_pattern:
    #   Path A (classic progressive VCP):  score≥4 AND (depth_tightening OR depth_monotonic)
    #   Path B (tight-base pattern):        n≥3 AND (all_tight OR tight_end) AND
    #                                       base_depth_ok AND final_tight
    # Both paths require flat_highs + base_long_enough (HARD — define a base).
    #
    # Backtest validation:
    #   NVDA Apr-May 2023:  contractions 4-7% (all small) → path_b via all_tight ✓
    #   PLTR Sep-Oct 2024:  contractions [10,8,4,4,5] (last 3 tight) → path_b via tight_end ✓
    #   APP  Jun-Jul 2024:  contractions [8,4,17,6,9] (deep pullback in middle) → both fail ✗
    path_a = score >= 4 and (depth_tightening or depth_monotonic)
    path_b = (n >= 3 and (all_tight or tight_end_geometry)
              and base_depth_ok and final_tight)
    structural_ok = flat_highs and base_long_enough
    is_pattern = (path_a or path_b) and structural_ok

    # Type A vs Type B classification — both valid VCPs, different geometry:
    #   Type A — "Progressive VCP": contractions roughly halve each time.
    #            Classic Minervini textbook (e.g. -25% → -12% → -5%).
    #            Detected via depth_tightening or depth_monotonic.
    #   Type B — "Long Tight Base": contractions uniformly tight (all ≤ 8-10%)
    #            OR follow Minervini geometry on last 3 (final≤10, 2nd≤15, 3rd≤20).
    #            NVDA Apr-May 2023 is canonical (contractions 4-7%).
    # If BOTH paths fire (textbook + tight end), prefer Type A label (more specific).
    if not is_pattern:
        vcp_type = None
    elif path_a:
        vcp_type = "progressive"
    else:
        vcp_type = "long_tight_base"

    return {
        "is_pattern": is_pattern,
        "vcp_type": vcp_type,
        "path_a_matched": bool(path_a and structural_ok),
        "path_b_matched": bool(path_b and structural_ok),
        "t_count": n,
        "score": score,
        "max_score": 5,
        "depths_pct": [round(d, 1) for d in depths],
        "durations_bars": durations,
        "lows": [round(x, 2) for x in lows],
        "highs": [round(x, 2) for x in highs],
        "base_depth_pct": round(base_depth_pct, 1),
        "high_range_pct": round(high_range_pct, 1),
        "base_duration_bars": base_duration_bars,
        "details": {
            "depth_tightening": depth_tightening,
            "depth_monotonic": depth_monotonic,
            "time_tightening": time_tightening,
            "higher_lows": higher_lows,
            "base_depth_ok": base_depth_ok,
            "final_tight": final_tight,
            "flat_highs": flat_highs,
            "base_long_enough": base_long_enough,
            "all_tight": all_tight,
            "tight_end_geometry": tight_end_geometry,
        },
    }


def _empty_vcp_result(skip_reason: str) -> dict[str, Any]:
    """Default-shaped result for screen_one early-exits.

    All fields render_scorecard expects are populated with safe defaults so
    downstream code doesn't need to special-case skipped runs.
    """
    return {
        "is_candidate": False,
        "contractions": [],
        "all_contractions": [],
        "pivot": None,
        "breakout_ready": False,
        "reason": skip_reason,
        "volume_avg_50d": 0.0,
        "volume_today": 0.0,
        "t_count": 0,
        "tightening_score": "skipped",
        "tightening_details": {},
        "provisional_pivot": False,
        "provisional_pivot_reason": None,
        "volatility_contracting": False,
        "volatility_atr_ratio": None,
        "bb_squeeze": False,
        "volume_dryup": False,
        "volume_dryup_ratio": None,
        "durations_bars": [],
        "base_depth_pct": None,
        "higher_lows": False,
        "swings": [],
        "_skipped": True,
    }


def detect_vcp(df: pd.DataFrame, zigzag_pct: float = 4.0,
               lookback_days: int = 120) -> dict[str, Any]:
    """v2 — Minervini VCP detector.

    Layer 1: percentage zigzag → clean confirmed swings
    Layer 2: tightening checks (5 criteria) on last 2-5 contractions → T-count
    Layer 3: independent confirmation via ATR, BB squeeze, volume dry-up
    Layer 4: pivot identification (with fresh-high / pending-swing handling)
    Layer 5: breakout-ready trigger

    Backward-compatible: all old fields (is_candidate, contractions,
    all_contractions, pivot, breakout_ready, volume_avg_50d, volume_today,
    reason) are preserved. New v2 fields are added alongside.
    """
    vol_50d = float(df["volume"].tail(50).mean()) if len(df) >= 50 else 0.0
    vol_today = float(df["volume"].iloc[-1]) if len(df) else 0.0
    result: dict[str, Any] = {
        # backward-compatible keys
        "is_candidate": False,
        "contractions": [],
        "all_contractions": [],
        "pivot": None,
        "breakout_ready": False,
        "reason": "",
        "volume_avg_50d": vol_50d,
        "volume_today": vol_today,
        # v2 new keys
        "t_count": 0,
        "tightening_score": "0/5",
        "tightening_details": {},
        "provisional_pivot": False,
        "provisional_pivot_reason": None,
        "volatility_contracting": False,
        "volatility_atr_ratio": None,
        "bb_squeeze": False,
        "volume_dryup": False,
        "volume_dryup_ratio": None,
        "durations_bars": [],
        "base_depth_pct": None,
        "higher_lows": False,
        "swings": [],
    }
    if len(df) < 40:
        result["reason"] = "insufficient history"
        return result

    # ── Layer 1: percentage zigzag on the recent window ──────────
    recent = df.tail(lookback_days + 30).copy()
    confirmed, pending = percentage_zigzag(recent, threshold_pct=zigzag_pct)
    result["swings"] = [
        {"type": s["type"], "date": s["date"], "price": round(s["price"], 2)}
        for s in confirmed[-10:]
    ]
    if pending is not None:
        result["pending_swing"] = {
            "type": pending["type"], "date": pending["date"],
            "price": round(pending["price"], 2),
        }

    # Build (peak, trough) pairs from consecutive (H, L)
    all_pairs: list[tuple[dict, dict]] = []
    last_h: dict | None = None
    for s in confirmed:
        if s["type"] == "H":
            last_h = s
        elif s["type"] == "L" and last_h is not None:
            all_pairs.append((last_h, s))
            last_h = None

    # Identify the base — start from the FIRST peak in the upper 15% band
    # of the max peak (the "resistance zone" / left side of the base).
    # Old logic used max peak itself, which collapsed multi-peak bases into
    # a single contraction when the max peak was recent. Backtest case:
    # NVDA 2023-05-15 had max 29.03 with 6 peaks ≥ 24.68; old algo saw 1T,
    # new algo correctly captures all 6 contractions of the tight base.
    if all_pairs:
        max_high_price = max(h["price"] for h, _ in all_pairs)
        base_band_threshold = max_high_price * 0.85  # peaks within 15% = base
        base_start_idx = next(
            (i for i, (h, _) in enumerate(all_pairs)
             if h["price"] >= base_band_threshold),
            0,
        )
        pairs = all_pairs[base_start_idx:]
    else:
        pairs = all_pairs

    # Also drop any micro-pullbacks (< 3% — noise leakage past the zigzag threshold)
    pairs = [(h, l) for h, l in pairs
             if (h["price"] - l["price"]) / h["price"] * 100 >= 3.0]
    result["pairs_total"] = len(all_pairs)
    result["pairs_in_base"] = len(pairs)

    # ── Layer 2: tightening checks ───────────────────────────────
    tight = check_tightening(pairs)
    result["t_count"] = tight["t_count"]
    result["tightening_score"] = f"{tight['score']}/{tight['max_score']}"
    result["tightening_details"] = tight.get("details", {})
    result["contractions"] = tight.get("depths_pct", [])
    result["all_contractions"] = [
        round((h["price"] - l["price"]) / h["price"] * 100, 1) for h, l in all_pairs
    ]
    result["durations_bars"] = tight.get("durations_bars", [])
    result["base_depth_pct"] = tight.get("base_depth_pct")
    result["higher_lows"] = tight.get("details", {}).get("higher_lows", False)
    result["high_range_pct"] = tight.get("high_range_pct")
    result["base_duration_bars"] = tight.get("base_duration_bars")
    result["vcp_type"] = tight.get("vcp_type")
    result["path_a_matched"] = tight.get("path_a_matched", False)
    result["path_b_matched"] = tight.get("path_b_matched", False)

    # ── Layer 3: independent confirmation ────────────────────────
    # Thresholds loosened after backtesting against documented examples
    # (SHOP 2016, NVDA 2023, TSLA 2020). 0.70 → 0.85 because post-event
    # bases (e.g. NVDA post-AI-earnings) have lookback windows contaminated
    # by the event itself, so a 30% drop is too strict.
    atr_ok, atr_ratio = atr_contracting(df, lookback=63, ratio_threshold=0.85)
    bb_ok, bb_width_val = bb_squeeze(df, window=20, lookback=120, quantile=0.20)
    vol_ok, vol_ratio, climax_in_base = volume_dryup_check(
        df, recent_window=10, base_window=60, ratio_threshold=0.85)
    udr, udr_ok = up_down_volume_ratio(df, window=20)
    result["volatility_contracting"] = atr_ok
    result["volatility_atr_ratio"] = round(atr_ratio, 2) if atr_ratio is not None else None
    result["bb_squeeze"] = bb_ok
    result["volume_dryup"] = vol_ok
    result["volume_dryup_ratio"] = round(vol_ratio, 2) if vol_ratio is not None else None
    result["climax_in_baseline"] = climax_in_base
    result["udr"] = round(udr, 2) if udr is not None else None
    result["udr_accumulation"] = udr_ok

    # ── Layer 4: pivot identification ────────────────────────────
    last_close = float(df["close"].iloc[-1])
    confirmed_highs = [s for s in confirmed if s["type"] == "H"]
    max_confirmed_high_val = (max(s["price"] for s in confirmed_highs)
                              if confirmed_highs else None)
    last_confirmed_high = confirmed_highs[-1] if confirmed_highs else None
    pending_high = pending if (pending and pending["type"] == "H") else None

    # Case A: at fresh high — current bar is provisional pivot
    if max_confirmed_high_val is not None and last_close > max_confirmed_high_val * 1.02:
        result["pivot"] = round(last_close, 2)
        result["provisional_pivot"] = True
        result["provisional_pivot_reason"] = (
            "at fresh high — no confirmed swing above current price"
        )
    # Case B: pending swing high is the latest peak (above confirmed)
    elif pending_high is not None and (
        max_confirmed_high_val is None
        or pending_high["price"] >= max_confirmed_high_val
    ):
        result["pivot"] = round(pending_high["price"], 2)
        result["provisional_pivot"] = True
        result["provisional_pivot_reason"] = (
            "pending swing high — awaiting reversal to confirm"
        )
    # Case C: latest confirmed swing high
    elif last_confirmed_high is not None:
        result["pivot"] = round(last_confirmed_high["price"], 2)

    # ── Layer 5: breakout-ready trigger ──────────────────────────
    breakout_ready = (
        result["pivot"] is not None
        and not result["provisional_pivot"]
        and last_close > result["pivot"] * 0.97
        and vol_today > 1.4 * vol_50d
    )
    result["breakout_ready"] = breakout_ready

    # ── Final verdict ────────────────────────────────────────────
    # 4 confirmations now: ATR, BB, vol_dryup (climax-cleaned), UDR (accumulation).
    confirmation_count = sum([atr_ok, bb_ok, vol_ok, udr_ok])
    # Require ≥2 of 4 confirmations OR breakout-ready firing.
    # Tightened from "≥1 of 3" because climax-cleaned volume + UDR catches
    # post-climax false dry-ups that the old 1-of-3 logic accepted.
    is_candidate = tight["is_pattern"] and (confirmation_count >= 2 or breakout_ready)

    if is_candidate:
        confs = []
        if atr_ok:
            confs.append("ATR↓")
        if bb_ok:
            confs.append("BB squeeze")
        if vol_ok:
            confs.append("vol dry-up")
        if udr_ok:
            confs.append(f"UDR {udr:.1f}x")
        vtype = tight.get("vcp_type") or "?"
        type_label = {
            "progressive": "Type A (progressive)",
            "long_tight_base": "Type B (long tight base)",
        }.get(vtype, vtype)
        result["reason"] = (f"{tight['t_count']}T VCP — {type_label}, "
                            f"score {tight['score']}/5, "
                            f"confirmations: {' + '.join(confs) if confs else 'breakout only'}")
    elif tight["is_pattern"]:
        result["reason"] = (f"{tight['t_count']}T sequence {tight['score']}/5 — but only "
                            f"{confirmation_count}/3 independent confirmations")
    elif tight["t_count"] >= 2:
        failed = [k for k, v in tight.get("details", {}).items()
                  if not v and k != "depth_monotonic"]
        result["reason"] = (f"{tight['t_count']}T detected but "
                            f"{', '.join(failed) if failed else 'pattern incomplete'}")
    else:
        result["reason"] = f"only {tight['t_count']} contraction(s) detected"

    result["is_candidate"] = is_candidate
    return result


# ---------------------------------------------------------------------------
# RS Rating proxy
# ---------------------------------------------------------------------------


def weighted_4q_return(df: pd.DataFrame) -> float | None:
    """Approximate IBD RS: 0.4*Q1 + 0.2*Q2 + 0.2*Q3 + 0.2*Q4 where Q1=most recent ~63d."""
    if len(df) < TRADING_DAYS_YEAR:
        if len(df) < TRADING_DAYS_QUARTER:
            return None
        # fallback: just use available trailing return
        c = df["close"].values
        return float((c[-1] / c[0] - 1) * 100)
    c = df["close"].values
    q1 = c[-1] / c[-TRADING_DAYS_QUARTER] - 1
    q2 = c[-TRADING_DAYS_QUARTER] / c[-2 * TRADING_DAYS_QUARTER] - 1
    q3 = c[-2 * TRADING_DAYS_QUARTER] / c[-3 * TRADING_DAYS_QUARTER] - 1
    q4 = c[-3 * TRADING_DAYS_QUARTER] / c[-4 * TRADING_DAYS_QUARTER] - 1
    return float((0.4 * q1 + 0.2 * q2 + 0.2 * q3 + 0.2 * q4) * 100)


def rs_rank_proxy(ticker_w4q: float | None, universe_w4q: list[float],
                  benchmark_w4q: float | None) -> int | None:
    """Map ticker's weighted-4q-return to 1-99 RS rank.

    If universe has >= 5 valid values, use cross-sectional percentile.
    Else fall back to formula vs benchmark: 50 + tanh-scaled excess.
    """
    if ticker_w4q is None:
        return None
    universe = [x for x in universe_w4q if x is not None]
    if len(universe) >= 5:
        # percentile of ticker within universe (including itself)
        sorted_u = sorted(universe)
        below = sum(1 for x in sorted_u if x < ticker_w4q)
        pct = below / len(sorted_u) * 100
        return max(1, min(99, int(round(pct))))
    # benchmark fallback
    if benchmark_w4q is None:
        return None
    excess = ticker_w4q - benchmark_w4q  # in %
    # tanh maps ±50pp to roughly ±48 around 50
    scaled = 50 + 50 * math.tanh(excess / 50)
    return max(1, min(99, int(round(scaled))))


# ---------------------------------------------------------------------------
# Fundamentals snapshot
# ---------------------------------------------------------------------------


def fundamentals(data: dict[str, Any]) -> dict[str, Any]:
    qeps = data.get("quarterly_eps", [])
    qrev = data.get("quarterly_revenue", [])

    def yoy_growths(quarters: list[dict], key: str) -> list[float]:
        """YoY % growth for the last 4 quarters where Q[-1] vs Q[-5], etc."""
        out = []
        if len(quarters) < 5:
            return out
        for i in range(-1, -5, -1):  # last 4 quarters
            cur = quarters[i][key]
            prior_idx = i - 4
            if abs(prior_idx) > len(quarters):
                break
            prior = quarters[prior_idx][key]
            if prior == 0 or (prior < 0 and cur > 0):
                # negative→positive: report a flag rather than a misleading number
                out.append(float("inf") if cur > 0 else float("nan"))
            else:
                out.append((cur / prior - 1) * 100)
        return out

    eps_yoy = yoy_growths(qeps, "eps")
    rev_yoy = yoy_growths(qrev, "revenue")

    def is_accelerating(g: list[float]) -> bool | None:
        # g[0] = most recent. Recent 2 avg > prior 2 avg.
        if len(g) < 4:
            return None
        g_clean = [x for x in g if math.isfinite(x)]
        if len(g_clean) < 4:
            return None
        recent = (g[0] + g[1]) / 2
        prior = (g[2] + g[3]) / 2
        return recent > prior

    info = data.get("info", {})
    roe = info.get("returnOnEquity")
    if roe is not None:
        roe = roe * 100  # yfinance gives as fraction

    # 3y EPS CAGR (annual approx — use trailing TTM vs 3y prior TTM)
    eps_cagr_3y = None
    if len(qeps) >= 16:
        ttm = sum(q["eps"] for q in qeps[-4:])
        prior_ttm = sum(q["eps"] for q in qeps[-16:-12])
        if prior_ttm > 0 and ttm > 0:
            eps_cagr_3y = ((ttm / prior_ttm) ** (1 / 3) - 1) * 100

    # Scoring (0-3): EPS growth thr, sales growth thr, ROE thr
    score = 0
    flags = {}
    most_recent_eps = eps_yoy[0] if eps_yoy and math.isfinite(eps_yoy[0]) else None
    most_recent_rev = rev_yoy[0] if rev_yoy and math.isfinite(rev_yoy[0]) else None
    flags["eps_growth_high"] = (most_recent_eps is not None
                                and most_recent_eps >= EPS_GROWTH_THRESHOLD)
    flags["sales_growth_high"] = (most_recent_rev is not None
                                  and most_recent_rev >= SALES_GROWTH_THRESHOLD)
    flags["roe_high"] = roe is not None and roe >= ROE_THRESHOLD
    score = sum(1 for v in flags.values() if v)

    return {
        "score": score,
        "max_score": 3,
        "eps_yoy_last4q": [round(x, 1) if math.isfinite(x) else None for x in eps_yoy],
        "sales_yoy_last4q": [round(x, 1) if math.isfinite(x) else None for x in rev_yoy],
        "eps_accelerating": is_accelerating(eps_yoy),
        "sales_accelerating": is_accelerating(rev_yoy),
        "roe_pct": round(roe, 1) if roe is not None else None,
        "eps_cagr_3y_pct": round(eps_cagr_3y, 1) if eps_cagr_3y is not None else None,
        "next_earnings": data.get("next_earnings"),
        "flags": flags,
    }


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------


def verdict(tt: dict[str, Any], stage: dict[str, Any], vcp: dict[str, Any],
            fund: dict[str, Any], rs_rank: int | None) -> dict[str, str]:
    tt_score = tt.get("score", 0)
    stg = stage.get("stage", "UNKNOWN")
    rs = rs_rank if rs_rank is not None else 0
    fund_score = fund.get("score", 0)

    # CAN SLIM-style hard fundamentals gate (Option B). If FUND_GATE_THRESHOLD
    # is set and fundamentals fall short, the stock is rejected regardless of
    # technical setup. Set FUND_GATE_THRESHOLD = 0 to disable and recover
    # pure Minervini behaviour (fundamentals inform but don't gate).
    if FUND_GATE_THRESHOLD > 0 and fund_score < FUND_GATE_THRESHOLD:
        return {
            "label": "AVOID",
            "why": f"Fundamentals {fund_score}/3 < gate {FUND_GATE_THRESHOLD}/3 "
                   f"(CAN SLIM-style hard gate — needs EPS/sales growth ≥ 25% "
                   f"and/or ROE ≥ 17%)",
        }

    is_candidate = vcp.get("is_candidate", False)
    is_breakout = vcp.get("breakout_ready", False)
    has_pivot = vcp.get("pivot") is not None

    # Strong BUY-READY: 8/8 + Stage 2 + VCP candidate CONFIRMED + breakout + good fundamentals
    if (tt_score == 8 and stg == "Stage 2"
            and is_candidate and is_breakout
            and fund.get("score", 0) >= 2):
        return {"label": "BUY-READY",
                "why": "8/8 TT + Stage 2 + VCP confirmed + breakout-ready + fundamentals strong"}

    # Weaker BUY-READY: 7-8/8 + Stage 2 + VCP candidate CONFIRMED + breakout
    if tt_score >= 7 and stg == "Stage 2" and is_candidate and is_breakout:
        return {"label": "BUY-READY",
                "why": f"{tt_score}/8 TT + Stage 2 + VCP confirmed + breakout-ready"}

    # FALSE POSITIVE GUARD: price at new high (breakout_ready) but NO proper VCP base
    # = vertical Stage-2 mark-up, not a real low-risk pivot.
    # Demoted to WATCH with explicit warning (Chipbond 6147 May 2026 was the trigger case).
    if tt_score >= 7 and stg == "Stage 2" and is_breakout and not is_candidate:
        return {"label": "WATCH",
                "why": f"{tt_score}/8 TT + Stage 2; at new high BUT no VCP base — "
                       f"vertical mark-up, wait for proper consolidation"}

    # Regular WATCH: VCP forming, or near pivot but not breaking out
    if tt_score >= 7 and stg == "Stage 2" and (is_candidate or has_pivot):
        pivot_str = f"${vcp.get('pivot'):.2f}" if vcp.get('pivot') is not None else "n/a"
        return {"label": "WATCH",
                "why": f"{tt_score}/8 TT + Stage 2; "
                       f"{'VCP forming' if is_candidate else 'near pivot ' + pivot_str}, "
                       f"not yet breakout"}

    if stg == "Stage 1" and rs >= 70:
        return {"label": "BASE-BUILDING",
                "why": f"Stage 1 base with RS {rs} — improving relative strength, watch for breakout"}

    if stg in ("Stage 3", "Stage 3?", "Stage 4", "Stage 4?"):
        return {"label": "AVOID", "why": f"{stg} — Minervini does not buy in distribution/decline"}
    if tt_score < 6:
        return {"label": "AVOID", "why": f"Only {tt_score}/8 Trend Template — fails the screen"}
    if rs < 70 and rs_rank is not None:
        return {"label": "AVOID", "why": f"RS proxy {rs} < 70 — not a relative leader"}

    return {"label": "WATCH", "why": "Borderline — see scorecard"}


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_scorecard(result: dict[str, Any]) -> str:
    if result.get("error"):
        return f"\n{result['ticker']}: ERROR — {result['error']}\n"

    t = result["ticker"]
    tt = result["trend_template"]
    stg = result["stage"]
    vcp = result["vcp"]
    fund = result["fundamentals"]
    v = result["verdict"]
    rs = result.get("rs_rank")
    info = result.get("info", {})
    name = info.get("longName") or info.get("shortName") or t

    lines: list[str] = []
    lines.append("=" * 72)
    lines.append(f"{t}  ({name})")
    lines.append("=" * 72)
    lines.append(f"Close: ${tt['close']:.2f}  |  52W: ${tt['low_52w']:.2f} – ${tt['high_52w']:.2f}")
    lines.append(f"RS proxy: {rs if rs is not None else 'n/a'}    "
                 f"Stage: {stg['stage']}    "
                 f"Verdict: {v['label']}")
    lines.append("")
    lines.append(f"Trend Template: {tt['score']}/8")
    for i, c in enumerate(tt["criteria"], 1):
        mark = "✓" if c["pass"] else "✗"
        lines.append(f"  {mark} C{i}: {c['detail']}")
    if not tt.get("c3_preferred_long_uptrend"):
        lines.append("  (note: C3 passes 1-month threshold; Minervini prefers 4-5 mo — "
                     "200d not above its level from 4 months ago)")
    lines.append("")
    lines.append(f"Stage: {stg['stage']}  —  {stg.get('reason', '')}")
    lines.append("")
    t_count = vcp.get("t_count", 0)
    vcp_type = vcp.get("vcp_type")
    type_descr = {
        "progressive": "Type A — Progressive (textbook: contractions halve)",
        "long_tight_base": "Type B — Long Tight Base (uniformly tight ≤ 8-10%)",
    }.get(vcp_type, "— (no pattern matched)")
    lines.append(f"VCP (v2 — zigzag + tightening + 3-layer confirm):")
    lines.append(f"  Pattern type: {type_descr}")
    lines.append(f"  T-count: {t_count}T    "
                 f"Tightening: {vcp.get('tightening_score', '0/5')}    "
                 f"Base depth: "
                 f"{vcp.get('base_depth_pct', 'n/a')}{'%' if vcp.get('base_depth_pct') is not None else ''}")
    # Show which path(s) matched — useful for debugging type classification
    pa = vcp.get("path_a_matched", False)
    pb = vcp.get("path_b_matched", False)
    if pa or pb:
        matched = []
        if pa: matched.append("Path A (progressive)")
        if pb: matched.append("Path B (long-tight)")
        lines.append(f"  Paths matched: {' + '.join(matched)}")
    if vcp.get("contractions"):
        depths = " → ".join(f"-{p}%" for p in vcp["contractions"])
        durations = vcp.get("durations_bars") or []
        if durations:
            dur_str = " → ".join(f"{d}b" for d in durations)
            lines.append(f"  Contractions (depth): {depths}")
            lines.append(f"  Contractions (time):  {dur_str}")
        else:
            lines.append(f"  Last contractions: {depths}")
    if (vcp.get("all_contractions")
            and len(vcp["all_contractions"]) > len(vcp.get("contractions", []))):
        lines.append(f"  All recent: {' → '.join(f'-{p}%' for p in vcp['all_contractions'])}")
    # Layer 3 confirmations
    atr_status = "✓" if vcp.get("volatility_contracting") else "✗"
    bb_status = "✓" if vcp.get("bb_squeeze") else "✗"
    vol_status = "✓" if vcp.get("volume_dryup") else "✗"
    udr_status = "✓" if vcp.get("udr_accumulation") else "✗"
    atr_ratio = vcp.get("volatility_atr_ratio")
    vol_ratio = vcp.get("volume_dryup_ratio")
    climax_tag = " [climax-cleaned]" if vcp.get("climax_in_baseline") else ""
    udr_val = vcp.get("udr")
    lines.append(f"  Confirmations: {atr_status} ATR contracting"
                 f"{f' (ratio {atr_ratio})' if atr_ratio is not None else ''}    "
                 f"{bb_status} BB squeeze    "
                 f"{vol_status} Vol dry-up"
                 f"{f' (ratio {vol_ratio}{climax_tag})' if vol_ratio is not None else ''}    "
                 f"{udr_status} UDR ≥1.5"
                 f"{f' ({udr_val:.2f}x)' if udr_val is not None else ''}")
    # Higher-lows + tightening details
    td = vcp.get("tightening_details") or {}
    if td:
        flag = lambda b: "✓" if b else "✗"
        lines.append(f"  Tightening checks: "
                     f"{flag(td.get('depth_tightening'))} depth halve  "
                     f"{flag(td.get('time_tightening'))} time tightening  "
                     f"{flag(td.get('higher_lows'))} higher lows  "
                     f"{flag(td.get('base_depth_ok'))} base ≤35%  "
                     f"{flag(td.get('final_tight'))} final <10%")
        high_range = vcp.get("high_range_pct")
        base_dur = vcp.get("base_duration_bars")
        lines.append(f"  Base structure: "
                     f"{flag(td.get('flat_highs'))} flat highs"
                     f"{f' (range {high_range}%)' if high_range is not None else ''}  "
                     f"{flag(td.get('base_long_enough'))} base ≥15 bars"
                     f"{f' ({base_dur} bars)' if base_dur is not None else ''}")
    if vcp.get("pivot"):
        prov = vcp.get("provisional_pivot")
        prov_tag = " (provisional)" if prov else ""
        lines.append(f"  Pivot: ${vcp['pivot']:.2f}{prov_tag}    "
                     f"vol today: {vcp.get('volume_today', 0):,.0f} "
                     f"(50d avg {vcp.get('volume_avg_50d', 0):,.0f})")
        if prov and vcp.get("provisional_pivot_reason"):
            lines.append(f"    └─ {vcp['provisional_pivot_reason']}")
    lines.append(f"  Candidate: {vcp.get('is_candidate', False)} "
                 f"— {vcp.get('reason', '')}")
    lines.append(f"  Breakout-ready: {vcp.get('breakout_ready', False)}")
    lines.append("")
    lines.append(f"Fundamentals: {fund['score']}/3 thresholds met")
    lines.append(f"  EPS YoY (last 4q, most-recent first): {fund.get('eps_yoy_last4q')}")
    lines.append(f"    accelerating: {fund.get('eps_accelerating')}")
    lines.append(f"  Sales YoY (last 4q): {fund.get('sales_yoy_last4q')}")
    lines.append(f"    accelerating: {fund.get('sales_accelerating')}")
    lines.append(f"  ROE: {fund.get('roe_pct')}%    "
                 f"3y EPS CAGR: {fund.get('eps_cagr_3y_pct')}%")
    lines.append(f"  Next earnings: {fund.get('next_earnings') or 'n/a'}")
    lines.append("")
    lines.append(f"VERDICT: {v['label']}")
    lines.append(f"  {v['why']}")
    lines.append("=" * 72)
    return "\n".join(lines)


def render_batch_table(results: list[dict[str, Any]]) -> str:
    rows: list[dict[str, Any]] = []
    for r in results:
        if r.get("error"):
            rows.append({"ticker": r["ticker"], "tt": "ERR", "stage": "-", "vcp": "-",
                         "rs": "-", "fund": "-", "verdict": "DATA_UNAVAILABLE",
                         "_sort_tt": -1, "_sort_rs": -1})
            continue
        tt = r["trend_template"]
        stg = r["stage"]
        vcp = r["vcp"]
        fund = r["fundamentals"]
        v = r["verdict"]
        rs = r.get("rs_rank")
        t_count = vcp.get("t_count", 0)
        flat = vcp.get("tightening_details", {}).get("flat_highs", True)
        long_enough = vcp.get("tightening_details", {}).get("base_long_enough", True)
        vcp_type = vcp.get("vcp_type")
        type_tag = ""
        if vcp_type == "progressive":
            type_tag = " [A]"
        elif vcp_type == "long_tight_base":
            type_tag = " [B]"
        if vcp.get("breakout_ready"):
            vcp_label = f"BREAKOUT ({t_count}T){type_tag}"
        elif vcp.get("is_candidate"):
            vcp_label = f"{t_count}T candidate{type_tag}"
        elif t_count >= 2 and not flat:
            vcp_label = f"{t_count}T rising channel"
        elif t_count >= 2 and not long_enough:
            vcp_label = f"{t_count}T too short"
        elif t_count >= 2:
            vcp_label = f"{t_count}T forming"
        else:
            vcp_label = "—"
        rows.append({
            "ticker": r["ticker"],
            "tt": f"{tt['score']}/8",
            "stage": stg["stage"],
            "vcp": vcp_label,
            "rs": str(rs) if rs is not None else "-",
            "fund": f"{fund['score']}/3",
            "verdict": v["label"],
            "_sort_tt": tt["score"],
            "_sort_rs": rs if rs is not None else -1,
        })

    rows.sort(key=lambda r: (r["_sort_tt"], r["_sort_rs"]), reverse=True)

    out = ["| Ticker | TT | Stage | VCP | RS | Fund | Verdict |",
           "|--------|-----|-------|-----|----|----|---------|"]
    for r in rows:
        out.append(f"| {r['ticker']} | {r['tt']} | {r['stage']} | {r['vcp']} | "
                   f"{r['rs']} | {r['fund']} | {r['verdict']} |")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Main driver
# ---------------------------------------------------------------------------


def screen_one(ticker: str, use_cache: bool, universe_w4q: list[float],
               benchmark_w4q: float | None) -> dict[str, Any]:
    data = fetch_data(ticker, use_cache=use_cache)
    if data is None:
        return {"ticker": ticker, "error": "DATA_UNAVAILABLE"}
    try:
        df = prices_to_df(data["prices_df"])  # already a DataFrame from MarketDataClient
        if len(df) < 200:
            return {"ticker": ticker, "error": f"only {len(df)} trading days — need 200+"}

        smas = compute_smas(df)
        ticker_w4q = weighted_4q_return(df)
        rs = rs_rank_proxy(ticker_w4q, universe_w4q, benchmark_w4q)
        tt = trend_template(df, smas, rs)
        stg = detect_stage(df, smas)
        # Compute fundamentals BEFORE the expensive VCP detector so we can
        # short-circuit on hard rejections (Stage 4 or CAN SLIM gate failure).
        # This saves ~200-500ms per ticker on stocks that would AVOID anyway.
        fund = fundamentals(data)
        fund_score = fund.get("score", 0)
        if stg["stage"] in ("Stage 4", "Stage 4?"):
            vcp = _empty_vcp_result(f"skipped: {stg['stage']} (don't buy in distribution)")
        elif FUND_GATE_THRESHOLD > 0 and fund_score < FUND_GATE_THRESHOLD:
            vcp = _empty_vcp_result(
                f"skipped: fundamentals {fund_score}/3 < gate {FUND_GATE_THRESHOLD}/3"
            )
        else:
            vcp = detect_vcp(df)
        v = verdict(tt, stg, vcp, fund, rs)

        return {
            "ticker": ticker,
            "fetched_at": data["fetched_at"],
            "info": data.get("info", {}),
            "smas": smas,
            "trend_template": tt,
            "stage": stg,
            "vcp": vcp,
            "fundamentals": fund,
            "rs_rank": rs,
            "weighted_4q_return_pct": ticker_w4q,
            "verdict": v,
        }
    except Exception as e:
        return {"ticker": ticker, "error": f"compute failed: {e}"}


def main() -> int:
    p = argparse.ArgumentParser(description="Minervini SEPA stock screener")
    p.add_argument("tickers", nargs="?", default=None,
                   help="Comma-separated tickers, e.g. NVDA,META,AVGO")
    p.add_argument("--file", help="Path to a file with one ticker per line")
    p.add_argument("--rs-benchmark", default="SPY", help="RS benchmark ticker (default SPY)")
    p.add_argument("--no-cache", action="store_true", help="Bypass fetch cache")
    p.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    p.add_argument("--verbose", action="store_true", help="Verbose diagnostics")
    args = p.parse_args()

    # Resolve ticker list
    tickers: list[str] = []
    if args.file:
        path = Path(args.file).expanduser()
        if not path.exists():
            print(f"File not found: {path}", file=sys.stderr)
            return 2
        tickers.extend([line.strip().upper() for line in path.read_text().splitlines()
                        if line.strip() and not line.strip().startswith("#")])
    if args.tickers:
        tickers.extend([t.strip().upper() for t in args.tickers.split(",") if t.strip()])
    if not tickers:
        print("No tickers provided. Pass tickers as positional arg or via --file.",
              file=sys.stderr)
        return 2

    # Dedupe preserving order
    seen = set()
    tickers = [t for t in tickers if not (t in seen or seen.add(t))]

    use_cache = not args.no_cache

    # First pass: fetch all + compute weighted-4q-return for universe (incl. SPY)
    universe_tickers = list(tickers)
    bench = args.rs_benchmark.upper()
    if bench not in universe_tickers:
        universe_tickers.append(bench)

    if args.verbose:
        print(f"Fetching {len(universe_tickers)} tickers ({tickers} + benchmark {bench})…",
              file=sys.stderr)

    fetched: dict[str, dict[str, Any] | None] = {}
    for t in universe_tickers:
        fetched[t] = fetch_data(t, use_cache=use_cache)

    # Build universe weighted-4q-returns
    universe_w4q: list[float] = []
    for t in tickers:
        d = fetched.get(t)
        if d is None:
            continue
        try:
            df = prices_to_df(d["prices_df"])
            w = weighted_4q_return(df)
            if w is not None:
                universe_w4q.append(w)
        except Exception:
            pass

    bench_w4q: float | None = None
    bd = fetched.get(bench)
    if bd is not None:
        try:
            bench_w4q = weighted_4q_return(prices_to_df(bd["prices_df"]))
        except Exception:
            pass

    # Now run the screen on each requested ticker (skip benchmark unless requested)
    results: list[dict[str, Any]] = []
    for t in tickers:
        # We already fetched; pass cache=True so screen_one hits cache
        r = screen_one(t, use_cache=True, universe_w4q=universe_w4q,
                       benchmark_w4q=bench_w4q)
        results.append(r)

    if args.json:
        print(json.dumps(results, indent=2, default=str))
        return 0

    if len(results) == 1:
        print(render_scorecard(results[0]))
    else:
        # Print ranked table first, then per-ticker scorecards
        print("RANKED RESULTS (sorted by Trend Template score then RS proxy)\n")
        print(render_batch_table(results))
        print()
        for r in results:
            print(render_scorecard(r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
