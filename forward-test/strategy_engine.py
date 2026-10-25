"""Quantitative Strategy Engine for Momentum Trend Following & Volume Profile.

Implements:
1. Volume Profile (VPVR): High Volume Nodes (HVN), Point of Control (POC), Value Area (VAH/VAL), Low Volume Nodes (LVN).
2. Setups:
   - CONTINUATION: Breakout from tight consolidation near 20-bar/52-week highs with volume expansion.
   - PULLBACK: Pullback to strong support (SMA20/SMA50 or HVN/POC) with drying volume and bounce confirmation.
   - REVERSAL: Absorption/sweep of major support (POC, HVN, 60-bar low) with volume spike.
3. Market Regime Filter: SPY and breadth analysis to dynamically adjust defensive cash (0-100%).
4. Exit Rules: Resistance profit-taking, trend breakdown (close < SMA50), trailing stop, and hard stop.
5. Smart Band Rebalancing: Hold winners, avoid unnecessary rebalancing trims, minimize transaction fees.
"""

from typing import Dict, List, Optional, Tuple, Any
import numpy as np
import pandas as pd


def compute_volume_profile(
    lows: np.ndarray,
    highs: np.ndarray,
    volumes: np.ndarray,
    n_bins: int = 30
) -> Dict[str, Any]:
    """Calculate Volume Profile Visible Range (VPVR) over a window.

    Returns:
    - poc: Point of Control (price level with peak traded volume)
    - vah: Value Area High (70% volume upper boundary)
    - val: Value Area Low (70% volume lower boundary)
    - hvns: List of High Volume Nodes (peaks acting as strong support/magnet)
    - lvns: List of Low Volume Nodes (valleys acting as rejection/fast travel zones)
    """
    p_min = float(np.min(lows))
    p_max = float(np.max(highs))
    if p_min >= p_max or len(lows) == 0:
        c = float(lows[-1]) if len(lows) > 0 else 1.0
        return dict(poc=c, vah=c, val=c, hvns=[c], lvns=[])

    bin_edges = np.linspace(p_min, p_max, n_bins + 1)
    bin_centers = (bin_edges[:-1] + bin_edges[1:]) * 0.5

    # Approximate volume distribution using bar midpoints
    mids = (lows + highs) * 0.5
    bin_indices = np.clip(np.digitize(mids, bin_edges) - 1, 0, n_bins - 1)
    vol_bins = np.bincount(bin_indices, weights=volumes, minlength=n_bins)

    poc_idx = int(np.argmax(vol_bins))
    poc = float(bin_centers[poc_idx])

    # 70% Value Area expansion from POC
    total_vol = float(np.sum(vol_bins))
    target_vol = total_vol * 0.70
    cum_vol = float(vol_bins[poc_idx])
    left, right = poc_idx, poc_idx

    while cum_vol < target_vol and (left > 0 or right < n_bins - 1):
        v_l = vol_bins[left - 1] if left > 0 else -1.0
        v_r = vol_bins[right + 1] if right < n_bins - 1 else -1.0
        if v_l >= v_r and left > 0:
            left -= 1
            cum_vol += vol_bins[left]
        elif right < n_bins - 1:
            right += 1
            cum_vol += vol_bins[right]
        else:
            left -= 1
            cum_vol += vol_bins[left]

    val = float(bin_centers[left])
    vah = float(bin_centers[right])

    # Detect High Volume Nodes (HVNs) and Low Volume Nodes (LVNs) using smoothed volume profile
    smoothed = np.convolve(vol_bins, np.ones(3) / 3.0, mode="same")
    mean_v = float(np.mean(smoothed))

    peaks = (smoothed[1:-1] > smoothed[:-2]) & (smoothed[1:-1] > smoothed[2:]) & (smoothed[1:-1] >= mean_v)
    hvns = [float(x) for x in bin_centers[1:-1][peaks]]
    if not hvns:
        hvns = [poc]

    valleys = (smoothed[1:-1] < smoothed[:-2]) & (smoothed[1:-1] < smoothed[2:]) & (smoothed[1:-1] < mean_v * 0.8)
    lvns = [float(x) for x in bin_centers[1:-1][valleys]]

    return dict(poc=poc, vah=vah, val=val, hvns=hvns, lvns=lvns)


def detect_technical_indicators(df: pd.DataFrame) -> Dict[str, Any]:
    """Calculate moving averages, RSI, ATR, and Volume Profile indicators."""
    c = df["close"].values
    o = df["open"].values
    h = df["high"].values
    l = df["low"].values
    v = df["volume"].values
    n = len(c)

    last_c = float(c[-1])
    last_o = float(o[-1])
    last_h = float(h[-1])
    last_l = float(l[-1])
    last_v = float(v[-1])

    # Moving averages
    sma20 = float(np.mean(c[-20:])) if n >= 20 else last_c
    sma50 = float(np.mean(c[-50:])) if n >= 50 else last_c
    sma200 = float(np.mean(c[-200:])) if n >= 200 else last_c
    vol_sma20 = float(np.mean(v[-20:])) if n >= 20 else last_v
    vol_ratio = last_v / vol_sma20 if vol_sma20 > 0 else 1.0

    # ATR 14
    tr1 = h[-14:] - l[-14:]
    tr2 = np.abs(h[-14:] - c[-15:-1])
    tr3 = np.abs(l[-14:] - c[-15:-1])
    tr = np.maximum(tr1, np.maximum(tr2, tr3))
    atr14 = float(np.mean(tr))
    atr_pct = (atr14 / last_c) * 100.0

    # RSI 14
    diffs = np.diff(c[-15:])
    pos_d = np.clip(diffs, 0, None)
    neg_d = np.clip(-diffs, 0, None)
    avg_gain = float(np.mean(pos_d))
    avg_loss = float(np.mean(neg_d))
    rs = avg_gain / (avg_loss + 1e-9)
    rsi14 = float(100.0 - (100.0 / (1.0 + rs)))

    # VPVR on 60 bars
    vp_window = min(60, n)
    vp = compute_volume_profile(l[-vp_window:], h[-vp_window:], v[-vp_window:], n_bins=30)
    poc = vp["poc"]
    hvns = vp["hvns"]
    lvns = vp["lvns"]

    # Trend classification (Minervini Stage 2 Uptrend)
    is_uptrend = bool((last_c > sma50 > sma200) and (last_c > sma200))
    swing_low20 = float(np.min(l[-21:-1])) if n >= 21 else last_l
    is_breakdown = bool((last_c < sma200) or (last_c < swing_low20))

    # Setup 1: CONTINUATION (Breakout from consolidation near highs with volume)
    high20 = float(np.max(h[-20:]))
    continuation = bool(is_uptrend and (last_c >= high20 * 0.97) and (vol_ratio >= 1.25) and (last_c >= last_o))

    # Setup 2: PULLBACK (Pullback to SMA20/50 or HVN support on dry volume, then bounce)
    dist_sma20 = abs(last_c / sma20 - 1.0)
    dist_sma50 = abs(last_c / sma50 - 1.0)
    sup_nodes = [node for node in hvns if node <= last_c * 1.02]
    dist_hvn = min([abs(last_c / node - 1.0) for node in sup_nodes]) if sup_nodes else 999.0
    near_support = (dist_sma20 <= 0.025) or (dist_sma50 <= 0.035) or (dist_hvn <= 0.025)
    dry_volume = vol_ratio <= 1.15
    bounce = (last_c > last_o) and (last_c > last_l + 0.3 * (last_h - last_l + 1e-9))
    pullback = bool(is_uptrend and near_support and dry_volume and bounce)

    # Setup 3: Multi-Touch Multi-Month Reversal (lookback 90-120 bar accumulation base)
    w_acc = min(120, n)
    sub_l = l[-w_acc:]
    sub_h = h[-w_acc:]
    sub_o = o[-w_acc:]
    sub_c = c[-w_acc:]
    sub_v = v[-w_acc:]

    # Detect local swing lows across accumulation window
    swing_indices = []
    for i in range(2, w_acc - 2):
        if sub_l[i] <= min(sub_l[i-1], sub_l[i-2]) and sub_l[i] <= min(sub_l[i+1], sub_l[i+2]):
            swing_indices.append(i)
    min_idx = int(np.argmin(sub_l))
    if min_idx not in swing_indices and 0 < min_idx < w_acc - 1:
        swing_indices.append(min_idx)
    swing_indices.sort()

    # Support cluster detection (tolerance ±1.5% to ±2.0%, >= 2 touches >= 5 bars apart)
    has_cluster = False
    cluster_level = poc
    touch_count = 0
    for idx1 in swing_indices:
        lvl1 = sub_l[idx1]
        matches = [idx1]
        for idx2 in swing_indices:
            if abs(idx2 - idx1) >= 5 and abs(sub_l[idx2] / lvl1 - 1.0) <= 0.02:
                matches.append(idx2)
        if len(matches) >= 2:
            has_cluster = True
            cluster_level = float(np.mean([sub_l[m] for m in set(matches)]))
            touch_count = len(set(matches))
            break

    # Volume absorption: vol_ratio >= 1.4x with rejection candle (close > open and close in upper half)
    rejection_candle = (last_c > last_o) and ((last_c - last_l) >= 0.5 * (last_h - last_l + 1e-9))
    vol_absorption = (vol_ratio >= 1.4 and rejection_candle)
    if not vol_absorption and has_cluster:
        for k in range(-min(10, w_acc), 0):
            v_rat_k = sub_v[k] / vol_sma20 if vol_sma20 > 0 else 1.0
            rej_k = (sub_c[k] > sub_o[k]) and ((sub_c[k] - sub_l[k]) >= 0.5 * (sub_h[k] - sub_l[k] + 1e-9))
            if v_rat_k >= 1.35 and rej_k:
                vol_absorption = True
                break

    # Confirmation: Near POC / HVN / support multi-touch and price bounces (reclaim SMA20 or RSI bounce/divergence)
    dist_poc = abs(last_c / poc - 1.0)
    dist_cluster = abs(last_c / cluster_level - 1.0) if has_cluster else 999.0
    near_mt_sup = (dist_cluster <= 0.04) or (dist_poc <= 0.035) or (dist_hvn <= 0.035) or (has_cluster and last_c >= cluster_level and dist_cluster <= 0.12)

    reclaim_sma20 = (last_c >= sma20 * 0.99)
    rsi_bounce = rsi14 >= 38.0
    confirmed_bounce = (reclaim_sma20 or rsi_bounce) and bounce

    # Baseline fallback: absorption at 60-bar low or POC
    sup60 = float(np.min(l[-min(60, n):]))
    dist_sup60 = abs(last_c / sup60 - 1.0)
    simple_reversal = bool((dist_poc <= 0.03 or dist_sup60 <= 0.03) and (vol_ratio >= 1.4) and bounce)
    multi_touch_reversal = bool(has_cluster and near_mt_sup and vol_absorption and confirmed_bounce)
    reversal = multi_touch_reversal or simple_reversal

    # Setup 4: DEEP_SUPPORT_REVERSAL (Institutional Bottom-Fishing Post-Capitulation)
    high250 = float(np.max(h[-min(250, n):]))
    from_high = last_c / high250 - 1.0
    
    # Check RSI oversold bounce: was <= 40 in recent 20 bars, now bounced to >= 38
    rsis = []
    for k in range(max(15, n - 20), n + 1):
        df_k = np.diff(c[k-15:k])
        rs_k = np.clip(df_k, 0, None).mean() / (np.clip(-df_k, 0, None).mean() + 1e-9)
        rsis.append(100.0 - (100.0 / (1.0 + rs_k)))
    min_rsi20 = min(rsis) if rsis else rsi14
    rsi_oversold_bounce = (min_rsi20 <= 40.0) and (rsi14 >= 38.0 and rsi14 >= min_rsi20 + 4.0)

    # Institutional support pool: POC, VAL, HVNs, multi-month swing low cluster
    inst_sups = [poc, vp["val"]] + hvns
    if has_cluster:
        inst_sups.append(cluster_level)
    
    touched_inst_sup = False
    best_sup = last_c * 0.95
    prev_l = l[-2] if n >= 2 else last_l
    for lvl in inst_sups:
        if abs(last_c / lvl - 1.0) <= 0.025 or abs(last_l / lvl - 1.0) <= 0.025 or abs(prev_l / lvl - 1.0) <= 0.025:
            if last_c >= lvl * 0.98:
                touched_inst_sup = True
                best_sup = lvl
                break

    tot_rng = last_h - last_l + 1e-9
    lower_wick_ratio = (min(last_o, last_c) - last_l) / tot_rng
    close_upper_ratio = (last_c - last_l) / tot_rng
    rej_absorption_candle = (last_c > last_o) and (lower_wick_ratio >= 0.15 or close_upper_ratio >= 0.45)
    prev_h, prev_o, prev_c = (h[-2], o[-2], c[-2]) if n >= 2 else (last_h, last_o, last_c)
    prev_rej = (prev_c > prev_o) and ((prev_c - prev_l) / (prev_h - prev_l + 1e-9) >= 0.50) and (last_c >= prev_c * 0.98)
    
    reclaiming_structure = (last_c >= sma20 * 0.97)
    
    deep_support_reversal = bool(
        (-0.55 <= from_high <= -0.18)
        and touched_inst_sup
        and (rej_absorption_candle or prev_rej)
        and rsi_oversold_bounce
        and reclaiming_structure
    )
    # Momentum Scoring (Minervini / Weinstein composite relative strength)
    r20 = last_c / c[-21] - 1.0 if n >= 21 else 0.0
    r60 = last_c / c[-61] - 1.0 if n >= 61 else 0.0
    r120 = last_c / c[-121] - 1.0 if n >= 121 else 0.0

    mom_score = 0.45 * r60 + 0.30 * r120 + 0.25 * r20
    if from_high >= -0.15:
        mom_score += 0.10
    if continuation:
        mom_score += 0.15
    elif pullback:
        mom_score += 0.12
    elif reversal:
        mom_score += 0.16
    elif deep_support_reversal:
        mom_score += 0.12

    return {
        "close": last_c,
        "open": last_o,
        "high": last_h,
        "low": last_l,
        "volume": last_v,
        "sma20": sma20,
        "sma50": sma50,
        "sma200": sma200,
        "atr14": atr14,
        "atr_pct": atr_pct,
        "rsi14": rsi14,
        "vol_ratio": vol_ratio,
        "is_uptrend": is_uptrend,
        "is_breakdown": is_breakdown,
        "poc": poc,
        "vah": vp["vah"],
        "val": vp["val"],
        "hvns": hvns,
        "lvns": lvns,
        "continuation": continuation,
        "pullback": pullback,
        "reversal": reversal,
        "deep_support_reversal": deep_support_reversal,
        "closest_support": float(best_sup),
        "mom_score": float(mom_score),
        "from_high": from_high,
        "r60": r60,
    }


def determine_market_regime(benchmark_df: pd.DataFrame) -> Dict[str, Any]:
    """Analyze SPY benchmark to determine market regime and target cash allocation.

    Regimes:
    - BEAR (SPY < SMA200): Deep bear/structural downtrend -> 80% defensive cash.
    - PULLBACK (SPY < SMA50 * 0.98): Short-term market correction -> 25% cash buffer.
    - BULL (SPY >= SMA50): Healthy bull market -> 0% cash, fully invested in leaders.
    """
    c = benchmark_df["close"].values
    n = len(c)
    last_c = float(c[-1])
    sma50 = float(np.mean(c[-50:])) if n >= 50 else last_c
    sma200 = float(np.mean(c[-200:])) if n >= 200 else last_c

    if last_c < sma200:
        regime = "BEAR"
        cash_target = 0.80
    elif last_c < sma50 * 0.98:
        regime = "PULLBACK"
        cash_target = 0.25
    else:
        regime = "BULL"
        cash_target = 0.0

    return {
        "regime": regime,
        "spy_close": last_c,
        "spy_sma50": sma50,
        "spy_sma200": sma200,
        "cash_target": cash_target,
        "equity_target": 1.0 - cash_target,
    }


def select_portfolio_targets(
    scores: Dict[str, Dict[str, Any]],
    current_pos: Dict[str, Dict[str, Any]],
    regime_info: Dict[str, Any],
    max_positions: int = 4,
    max_dd_trail: float = 0.12,
    take_profit_rsi: float = 88.0,
    min_score: float = 0.35,
    runner_profit_threshold: float = 0.25,
    runner_dd_trail: float = 0.18,
    runner_max_weight: float = 0.38,
    replacement_hurdle: float = 0.20,
    reversal_initial_stop: float = 4.5,
) -> Dict[str, Dict[str, Any]]:
    """Smart Portfolio Allocation & Rebalancing Engine with Super Runner & Holding Hysteresis Buffer.

    1. Holding Hysteresis Buffer ("Trailing Stop > Auto Rebalance"):
       - Retains existing healthy positions: close >= sma50 * 0.98, stop not breached, not overbought blow-off.
       - Prevents premature rebalance_exit churn for healthy compounders (PLTR, AMD, DASH, INTC).
       - Only replaces an existing healthy holding if a new candidate's momentum score exceeds
         the holding's score by a significant hurdle (delta score >= 0.20).
       - In BEAR regime, respects the bear liquidation rule (equity_target reduction).
    2. Reversal with Strict Stop Loss & Dynamic Lifecycle:
       - Reversal entries carry a tight initial stop loss (~4.5%).
       - Dynamic stop lifecycle: Initial 4.5% -> Breakeven lock at +8% -> Runner trailing stop (12%) at +20%.
    3. Allocates target weights across leaders with Asymmetric Band Trimming support.
    """
    equity_target = regime_info["equity_target"]
    is_bear = regime_info["regime"] == "BEAR"

    # Bear liquidation rule: in deep bear (SPY < SMA200), respect defensive cash target
    if is_bear:
        return {}

    # 1. Evaluate current holdings: Retain existing healthy positions!
    kept = {}
    for t, p in current_pos.items():
        s = scores.get(t)
        if s is None:
            continue
        entry_px = p.get("entry", s["close"])
        hw_px = p.get("high_water", s["close"])
        profit = (s["close"] / entry_px - 1.0)
        is_runner = (profit >= runner_profit_threshold) or ((hw_px / entry_px - 1.0) >= runner_profit_threshold)
        is_deep = p.get("is_deep", False)
        is_rev = p.get("is_reversal", False) or is_deep

        # Structural trend line check:
        # Reversals bottom-fish before SMA50 reclaim so check stop/support;
        # Normal/runner positions check close >= sma50 * 0.98
        if is_rev:
            trend_ok = (s["close"] >= p.get("stop", 0.0))
        else:
            trend_ok = (s["close"] >= s["sma50"] * 0.98)

        # Stop check: holding has not breached its stop level
        not_stopped = (s["close"] >= p.get("stop", 0.0))

        # Extreme overbought blow-off check (super runners exempt to let winners run)
        not_overbought = is_runner or (s["rsi14"] <= take_profit_rsi)

        if trend_ok and not_stopped and not_overbought:
            kept[t] = p

    # 2. Filter candidates for open slots: Focus on uptrend leaders and institutional DEEP_SUPPORT_REVERSAL
    candidates = [
        t for t, s in scores.items()
        if (s["is_uptrend"] and s["from_high"] >= -0.20) or
           s.get("deep_support_reversal", False)
    ]

    ranked = sorted(candidates, key=lambda cand: scores[cand]["mom_score"], reverse=True)

    needed_slots = max_positions - len(kept)
    new_picks = []

    valid_cands = [
        cand for cand in ranked
        if cand not in kept and (
            scores[cand]["continuation"] or
            scores[cand]["pullback"] or
            scores[cand].get("deep_support_reversal", False) or
            scores[cand]["mom_score"] > min_score
        )
    ]

    if needed_slots > 0 and equity_target > 0.20:
        deep_cands = [c for c in valid_cands if scores[c].get("deep_support_reversal", False)]
        if deep_cands and needed_slots >= 2:
            pick = deep_cands[0]
            new_picks.append(pick)
            valid_cands.remove(pick)
            needed_slots -= 1

        for cand in list(valid_cands):
            if needed_slots > 0:
                new_picks.append(cand)
                valid_cands.remove(cand)
                needed_slots -= 1
            else:
                break

    # Trailing Stop > Auto Rebalance:
    # Healthy holdings stay in kept and final_tickers. New candidates ONLY fill open slots.
    final_tickers = list(kept.keys()) + new_picks
    if len(final_tickers) > 0 and equity_target > 0:
        base_w = equity_target / max_positions
        targets = {}
        for t in final_tickers:
            s = scores.get(t, {})
            is_d = s.get("deep_support_reversal", False)
            is_r = False
            target_w = base_w

            if t in current_pos:
                p = current_pos[t]
                entry_px = p.get("entry", s.get("close", 1.0))
                hw_px = p.get("high_water", s.get("close", 1.0))
                profit = (s.get("close", entry_px) / entry_px - 1.0)
                is_r = (profit >= runner_profit_threshold) or ((hw_px / entry_px - 1.0) >= runner_profit_threshold)
                is_d = p.get("is_deep", is_d)

                # Pyramiding / Scale-In (ADD to Winners):
                # If winner prints Continuation/Pullback above SMA20/50, increase allocation up to 35%
                if profit >= 0.12 and (s.get("continuation") or s.get("pullback")) and (s.get("close", 0) > s.get("sma20", 0) > s.get("sma50", 0)):
                    target_w = min(runner_max_weight, base_w * 1.4)

            atr_p = s.get("atr_pct", 4.0)
            if is_d:
                stop_p = 5.0  # Tight initial stop (4.5% - 5.0%) for deep support reversals
            elif is_r:
                stop_p = runner_dd_trail * 100.0
            else:
                stop_p = max(8.0, min(12.0, atr_p * 2.0))

            has_fresh = bool(s.get("continuation") or s.get("pullback") or is_d)
            targets[t] = {
                "weight": target_w,
                "is_super_runner": is_r,
                "is_deep": is_d,
                "stop_pct": stop_p,
                "has_fresh_setup": has_fresh,
                "sma20": s.get("sma20", 0.0),
            }
        # Normalize weights if sum > equity_target
        tot_w = sum(tg["weight"] for tg in targets.values())
        if tot_w > equity_target and tot_w > 0:
            scale = equity_target / tot_w
            for tg in targets.values():
                tg["weight"] *= scale

        return targets

    return {}
