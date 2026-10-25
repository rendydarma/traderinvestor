"""Walk-forward paper trading test. Model sees only bars <= decision date; orders fill at next open.

Supports:
- CLI --quant: Fully automated quantitative Momentum + Volume Profile engine.
- Default: LLM-driven decision engine via OMP.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from typing import Dict, Any
import numpy as np
import pandas as pd

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

def find_file(rel_path: str) -> str:
    candidates = [
        os.path.join(current_dir, rel_path),
        rel_path,
        os.path.join("forward-test", rel_path),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return os.path.join(current_dir, rel_path)

from strategy_engine import (
    compute_volume_profile,
    detect_technical_indicators,
    determine_market_regime,
    select_portfolio_targets,
)

MODEL, THINK = "anthropic/claude-sonnet-5-5", "low"
START, END = "2025-01-02", "2026-10-25"
STEP, LOOKBACK, RECENT = 5, 250, 30  # decide every 5 trading days; 250-bar lookback
CAPITAL, FEE = 1000.0, 0.0005
REBALANCE_BAND = 0.04  # 4% deadband threshold to prevent fee bleed & micro-churn
MIN_TRADE_NOTIONAL = 30.0  # minimum $30 trade delta to avoid micro-trims
OMP = shutil.which("omp")

px = pd.read_csv(find_file("data/prices.csv"), parse_dates=["date"])
px["date"] = px["date"].dt.strftime("%Y-%m-%d")
TICKERS = sorted(px.ticker.unique())
dates = sorted(px.date.unique())
P = {t: g.set_index("date") for t, g in px.groupby("ticker")}
BM = pd.read_csv(find_file("data/benchmark.csv")).set_index("date")  # SPY, benchmark only
BM["tr"] = ((BM.close + BM.dividends) / BM.close.shift()).fillna(1).cumprod()
split_tickers = px[px["split"] > 1]["ticker"].unique().tolist()

TPL = open(find_file("prompts/template.md"), encoding="utf-8").read()
SYS = open(find_file("prompts/system.md"), encoding="utf-8").read().strip()

def split_adjust(g: pd.DataFrame) -> pd.DataFrame:
    """Express a raw price window in today's post-split terms so MAs/support are continuous."""
    r = g.split.replace(0, 1.0)
    if (r == 1).all():
        return g
    f = r[::-1].cumprod()[::-1] / r
    g = g.copy()
    for c in ["open", "high", "low", "close"]:
        g[c] = g[c] / f
    g["volume"] = g["volume"] * f
    return g


def fast_split_adjust(g: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Optimized split adjustment: bypass for tickers without splits."""
    if ticker not in split_tickers:
        return g
    return split_adjust(g)


def trend_state(close: float, sma50: float, sma200: float, swing_low20: float) -> str:
    if not np.isfinite([close, sma50, sma200, swing_low20]).all():
        return "UNKNOWN"
    if close < sma200 or close < swing_low20:
        return "BREAKDOWN"
    if close < sma50:
        return "DOWNTREND"
    return "UPTREND"


def setup_flags(g: pd.DataFrame, close: float, sma20: float, sma50: float, rsi: float, trend: str, vp: Dict[str, Any]) -> Dict[str, Any]:
    vol_sma20 = float(g.volume.rolling(20).mean().iloc[-1])
    vol_ratio = float(g.volume.iloc[-1] / vol_sma20) if vol_sma20 > 0 else np.nan
    high20 = float(g.high.tail(20).max())
    o, h, l = float(g.open.iloc[-1]), float(g.high.iloc[-1]), float(g.low.iloc[-1])

    poc = vp["poc"]
    hvns = vp["hvns"]
    sup_nodes = [node for node in hvns if node <= close * 1.02]
    hvn_sup = max(sup_nodes) if sup_nodes else poc
    sup_dist = close / hvn_sup - 1.0 if hvn_sup > 0 else np.nan

    bounce = (close > o) and (close > l + 0.3 * (h - l + 1e-9))
    dist_sma20 = abs(close / sma20 - 1.0)
    dist_sma50 = abs(close / sma50 - 1.0)
    dist_hvn = abs(close / hvn_sup - 1.0)
    near_support = (dist_sma20 <= 0.025) or (dist_sma50 <= 0.035) or (dist_hvn <= 0.025)

    continuation = bool(trend == "UPTREND" and (close >= high20 * 0.97) and (vol_ratio >= 1.25) and (close >= o))
    pullback = bool(trend == "UPTREND" and near_support and (vol_ratio <= 1.15) and bounce)
    sup60 = float(g.low.tail(60).min())
    reversal = bool((abs(close / poc - 1.0) <= 0.03 or abs(close / sup60 - 1.0) <= 0.03) and (vol_ratio >= 1.4) and bounce)

    return dict(
        poc=poc,
        hvn_sup=hvn_sup,
        sup_dist=sup_dist,
        vol_ratio=vol_ratio,
        continuation=continuation,
        pullback=pullback,
        reversal=reversal,
    )


def indicators(g: pd.DataFrame) -> Dict[str, Any]:
    c = g.close
    d = c.diff()
    rsi = 100 - 100 / (1 + d.clip(lower=0).rolling(14).mean() / (-d.clip(upper=0)).rolling(14).mean())
    tr = pd.concat([g.high - g.low, (g.high - c.shift()).abs(), (g.low - c.shift()).abs()], axis=1).max(axis=1)
    sma20, sma50, sma200 = float(c.rolling(20).mean().iloc[-1]), float(c.rolling(50).mean().iloc[-1]), float(c.rolling(200).mean().iloc[-1])
    swing_low20 = float(g.low.iloc[-21:-1].min())
    last_c = float(c.iloc[-1])
    trend = trend_state(last_c, sma50, sma200, swing_low20)

    # Calculate Volume Profile
    vp = compute_volume_profile(g.low.tail(60).values, g.high.tail(60).values, g.volume.tail(60).values, n_bins=30)

    out = dict(
        close=last_c,
        r5=last_c / float(c.iloc[-6]) - 1 if len(c) >= 6 else 0.0,
        r20=last_c / float(c.iloc[-21]) - 1 if len(c) >= 21 else 0.0,
        r60=last_c / float(c.iloc[-61]) - 1 if len(c) >= 61 else 0.0,
        sma20=sma20,
        sma50=sma50,
        sma200=sma200,
        rsi14=float(rsi.iloc[-1]),
        atr_pct=float(tr.rolling(14).mean().iloc[-1]) / last_c * 100.0,
        from_high=last_c / float(g.high.max()) - 1.0,
        trend=trend,
    )
    out.update(setup_flags(g, last_c, sma20, sma50, float(rsi.iloc[-1]), trend, vp))
    return out


def build_prompt(D: str, cash: float, pos: Dict[str, Any], equity: float):
    win = {t: fast_split_adjust(P[t].loc[:D].tail(LOOKBACK), t) for t in TICKERS}
    assert all(w.index[-1] == D for w in win.values())
    snap = pd.DataFrame({t: indicators(w) for t, w in win.items()}).T

    flags = [("continuation", "CONT"), ("pullback", "PULLBACK"), ("reversal", "REV")]
    groups = {lab: [t for t in snap.index if bool(snap.loc[t, col])] for col, lab in flags}
    by_trend = {s: [t for t in snap.index if snap.loc[t, "trend"] == s] for s in ["UPTREND", "DOWNTREND", "BREAKDOWN"]}
    trends = snap.trend.value_counts().to_dict()

    setups = "\n".join([
        f"- BREAKDOWN (below SMA200 or swing low): {', '.join(by_trend['BREAKDOWN']) or 'none'}",
        f"- DOWNTREND (below SMA50 but above SMA200): {', '.join(by_trend['DOWNTREND']) or 'none'}",
        f"- CONTINUATION (Uptrend breakout near 20d high + volume surge): {', '.join(groups['CONT']) or 'none'}",
        f"- PULLBACK (Uptrend pullback to SMA20/50 or HVN support + dry volume): {', '.join(groups['PULLBACK']) or 'none'}",
        f"- REVERSAL (Volume Profile POC / support absorption with volume spike): {', '.join(groups['REV']) or 'none'}",
        f"- Market Breadth: {trends.get('UPTREND', 0)} UPTREND, {trends.get('DOWNTREND', 0)} DOWNTREND, "
        f"{trends.get('BREAKDOWN', 0)} BREAKDOWN",
    ])

    for c in ["r5", "r20", "r60", "from_high", "sup_dist"]:
        snap[c] = (snap[c] * 100).round(1).astype(str) + "%"
    for c in ["close", "sma20", "sma50", "sma200", "poc", "hvn_sup", "vol_ratio"]:
        snap[c] = snap[c].round(2)
    snap["rsi14"], snap["atr_pct"] = snap["rsi14"].round(1), snap["atr_pct"].round(1)
    for col, lab in flags:
        snap[lab] = snap[col].map({True: "Y", False: ""})

    cols = [
        "close", "r5", "r20", "r60", "sma20", "sma50", "sma200", "rsi14", "atr_pct", "from_high",
        "poc", "hvn_sup", "sup_dist", "vol_ratio", "trend", "CONT", "PULLBACK", "REV"
    ]
    snap = snap[cols].reset_index().rename(columns={"index": "ticker"})
    rec = "\n".join(f"{t}: " + " ".join(f"{v:.2f}" for v in w.close.tail(RECENT)) for t, w in win.items())
    ptxt = "\n".join(
        f"{t}: {p['sh']:.4f} sh, entry ${p['entry']:.2f}, stop ${p['stop']:.2f}, high ${p.get('high_water', p['entry']):.2f}, value ${p['sh']*win[t].close.iloc[-1]:.2f}"
        for t, p in pos.items()
    ) or "(none, 100% cash)"

    prompt = TPL.format(
        date=D, equity=equity, cash=cash, step=STEP, positions=ptxt, lookback=LOOKBACK, recent=RECENT,
        snapshot=snap.to_markdown(index=False), recent_closes=rec, tickers=", ".join(TICKERS), setups=setups
    )
    return prompt, pd.concat(win.values()).reset_index()


def parse(text: str) -> Dict[str, Any]:
    m = re.search(r"\{.*\}", text, re.S)
    j = json.loads(m.group(0))
    tg = {t: v for t, v in j["targets"].items() if t in TICKERS and float(v.get("weight", 0)) > 0}
    s = sum(float(v["weight"]) for v in tg.values())
    k = 1.0 / s if s > 1.0 else 1.0
    j["parsed"] = {
        t: {"weight": float(v["weight"]) * k, "stop_pct": min(30.0, max(1.0, float(v.get("stop_pct", 8.0))))}
        for t, v in tg.items()
    }
    return j


def decide_llm(D: str, cash: float, pos: Dict[str, Any], equity: float) -> Dict[str, Any]:
    d = f"runs/{D}"
    os.makedirs(d, exist_ok=True)
    if os.path.exists(f"{d}/parsed.json"):
        return json.load(open(f"{d}/parsed.json"))["parsed"]
    prompt, data = build_prompt(D, cash, pos, equity)
    data.to_csv(f"{d}/data.csv", index=False)
    open(f"{d}/prompt.md", "w", encoding="utf-8").write(prompt)
    for attempt in range(3):
        r = subprocess.run(
            [OMP, "-p", "--no-session", "--no-tools", "--no-rules", "--no-skills", "--no-extensions", "--no-lsp", "--no-title",
             "--model", MODEL, "--thinking", THINK, "--system-prompt", SYS, f"@{d}/prompt.md"],
            capture_output=True, text=True, encoding="utf-8", timeout=600
        )
        open(f"{d}/response.md", "w", encoding="utf-8").write(r.stdout)
        try:
            j = parse(r.stdout)
            break
        except Exception as e:
            print(f"  {D} attempt {attempt+1} parse fail: {e}", flush=True)
    else:
        j = {
            "error": "parse failed, kept prior holdings",
            "parsed": {t: {"weight": p["sh"] * P[t].close[D] / equity, "stop_pct": 8.0} for t, p in pos.items()}
        }
    json.dump(j, open(f"{d}/parsed.json", "w"), indent=1)
    return j["parsed"]


def decide_quant(D: str, pos: Dict[str, Any]) -> Dict[str, Any]:
    """Automated Quantitative Momentum + Volume Profile Decision."""
    sub_bm = BM.loc[:D]
    regime_info = determine_market_regime(sub_bm)

    scores = {}
    for t in TICKERS:
        w = fast_split_adjust(P[t].loc[:D].tail(LOOKBACK), t)
        if len(w) >= 200:
            scores[t] = detect_technical_indicators(w)

    targets = select_portfolio_targets(
        scores=scores,
        current_pos=pos,
        regime_info=regime_info,
        max_positions=4,
        max_dd_trail=0.12,
        take_profit_rsi=88.0,
        min_score=0.35,
        replacement_hurdle=0.20,
        reversal_initial_stop=4.5,
    )

    for t, tg in targets.items():
        if "stop_pct" not in tg:
            s = scores.get(t, {})
            atr_pct = s.get("atr_pct", 4.0)
            tg["stop_pct"] = max(5.0, min(10.0, atr_pct * 2.0))

    return targets


def main():
    out_dir = os.path.join(current_dir, "papertrade")
    os.makedirs(out_dir, exist_ok=True)
    use_quant = "--quant" in sys.argv or "-q" in sys.argv

    last_idx = max(i for i, d in enumerate(dates) if d <= END)
    dec_idx = [i for i in range(dates.index(START), len(dates), STEP) if i <= last_idx]
    cash, pos, pending, eq_rows, trades = CAPITAL, {}, None, [], []
    stopped_history = {}

    def sell(t: str, price: float, D: str, why: str):
        nonlocal cash
        p = pos.pop(t)
        cash += p["sh"] * price * (1.0 - FEE)
        trades.append(dict(date=D, ticker=t, side="SELL", price=float(price), shares=float(p["sh"]), reason=why))

    first = dec_idx[0]
    for i in range(first, last_idx + 1):
        D = dates[i]

        # 1. Splits: scale holdings and update entry, stop, high_water
        for t, p in pos.items():
            r = P[t].split[D]
            if r != 1 and r > 0:
                p["sh"] *= r
                p["entry"] /= r
                p["stop"] /= r
                if "high_water" in p:
                    p["high_water"] /= r

        # 2. Dividends credited as cash on ex-date
        for t, p in pos.items():
            dv = P[t].dividends[D]
            if dv > 0:
                cash += p["sh"] * dv
                trades.append(dict(date=D, ticker=t, side="DIV", price=float(dv), shares=float(p["sh"]), reason="dividend"))

        # 3. Fill pending orders at Open[D]
        if pending is not None:
            eq = cash + sum(p["sh"] * P[t].open[D] for t, p in pos.items())

            # Full exits: positions not in pending
            for t in [t for t in list(pos) if t not in pending]:
                sell(t, P[t].open[D], D, "rebalance_exit")

            # Smart Asymmetric Band Trimming:
            # - Posisi normal: target 25%, deadband 4% (pangkas jika > 29%)
            # - Posisi Super Runner (profit >= +25%): izinkan alokasi bertumbuh hingga 35%-40% (38%) sebelum trim
            # - REVENUE RULE: band_trim HANYA BOLEH jika posisi sedang UNTUNG / PROFIT (o > entry_px)
            for t, tg in pending.items():
                if t in pos:
                    o = P[t].open[D]
                    have = pos[t]["sh"] * o
                    entry_px = pos[t].get("entry", o)
                    hw_px = pos[t].get("high_water", o)
                    is_runner = tg.get("is_super_runner", False) or ((o / entry_px - 1.0 >= 0.25) or (hw_px / entry_px - 1.0 >= 0.25))

                    if is_runner:
                        runner_max_val = 0.38 * eq
                        if (o > entry_px) and have > runner_max_val and (have - runner_max_val) >= MIN_TRADE_NOTIONAL:
                            n = (have - runner_max_val) / o
                            cash += n * o * (1.0 - FEE)
                            pos[t]["sh"] -= n
                            trades.append(dict(date=D, ticker=t, side="SELL", price=float(o), shares=float(n), reason="runner_band_trim"))
                        tg["_want"] = tg["weight"] * eq
                    else:
                        want = tg["weight"] * eq
                        if (o > entry_px) and have > want and (have - want) / eq > REBALANCE_BAND and (have - want) >= MIN_TRADE_NOTIONAL:
                            n = (have - want) / o
                            cash += n * o * (1.0 - FEE)
                            pos[t]["sh"] -= n
                            trades.append(dict(date=D, ticker=t, side="SELL", price=float(o), shares=float(n), reason="band_trim"))
                        tg["_want"] = want

            # Smart Buying & Pyramiding (Scale-in to Winners)
            for t, tg in pending.items():
                o = P[t].open[D]
                have = pos[t]["sh"] * o if t in pos else 0.0
                want = tg.get("_want", tg["weight"] * eq)

                # Cooldown Re-entry filter: max 1 interval (~5-6 trading days), cancelled if price breaks out above SMA20 or confirmed above stop
                if t not in pos and t in stopped_history:
                    last_stop = stopped_history[t]
                    bars_since = i - last_stop["stop_idx"]
                    if bars_since <= 6:
                        is_breakout_ma20 = o > tg.get("sma20", 0)
                        confirmed_above = o > last_stop["stop_price"] * 1.01
                        if not (is_breakout_ma20 or confirmed_above):
                            continue
                is_pyramid = (t in pos) and (want > have)
                if t not in pos or ((want - have) / eq > REBALANCE_BAND and (want - have) >= MIN_TRADE_NOTIONAL):
                    spend = min(want - have, cash / (1.0 + FEE))
                    if spend >= MIN_TRADE_NOTIONAL or (t not in pos and spend > 10.0):
                        n = spend / o
                        cash -= spend * (1.0 + FEE)
                        entry = ((pos[t]["entry"] * pos[t]["sh"]) + spend) / (pos[t]["sh"] + n) if t in pos else o
                        hw = max(pos[t].get("high_water", o), o) if t in pos else o
                        is_deep = tg.get("is_deep", False)
                        stop_p = tg.get("stop_pct", 5.0 if is_deep else 12.0)
                        stop = o * (1.0 - stop_p / 100.0)
                        pos[t] = {
                            "sh": (pos[t]["sh"] if t in pos else 0.0) + n,
                            "entry": entry,
                            "stop": stop,
                            "high_water": hw,
                            "is_deep": is_deep,
                            "stop_pct": stop_p,
                        }
                        reason = "pyramid_add" if is_pyramid else "rebalance_buy"
                        trades.append(dict(date=D, ticker=t, side="BUY", price=float(o), shares=float(n), reason=reason))
                # Ratchet adaptive trailing stop from high-water mark: NEVER re-anchor downward
                if t in pos:
                    if "high_water" not in pos[t]:
                        pos[t]["high_water"] = pos[t]["entry"]
                    stop_pct = tg.get("stop_pct", 12.0)
                    new_stop = pos[t]["high_water"] * (1.0 - stop_pct / 100.0)
                    pos[t]["stop"] = max(pos[t].get("stop", 0.0), new_stop)
            pending = None

        # 4. Trend Holding: Close-based Trailing Stop check (immune to intraday needle wicks)
        for t in list(pos):
            cl = P[t].close[D]
            if cl <= pos[t]["stop"]:
                stopped_history[t] = {"stop_price": cl, "stop_date": D, "stop_idx": i}
                sell(t, cl, D, "trailing_stop")

        # 5. Trailing high-water & Dynamic Stop Lifecycle for Reversals on close
        for t in list(pos):
            cl = P[t].close[D]
            if "high_water" not in pos[t]:
                pos[t]["high_water"] = pos[t]["entry"]
            if cl > pos[t]["high_water"]:
                pos[t]["high_water"] = cl

            entry = pos[t]["entry"]
            hw = pos[t]["high_water"]
            gain = hw / entry - 1.0
            is_deep = pos[t].get("is_deep", False)

            if is_deep:
                # Dynamic stop lifecycle for deep support reversals:
                # - Initial stop: ~4.5% - 5.0%
                # - Breakeven lock: once gain >= +8%, move stop to entry price
                # - Runner trailing stop: once gain >= +20%, trail by 12-15% from high water mark
                if gain >= 0.20:
                    new_stop = hw * (1.0 - 0.12)
                elif gain >= 0.08:
                    new_stop = entry
                else:
                    stop_p = pos[t].get("stop_pct", 5.0)
                    new_stop = entry * (1.0 - stop_p / 100.0)
                pos[t]["stop"] = max(pos[t].get("stop", 0.0), new_stop)
        eq = cash + sum(p["sh"] * P[t].close[D] for t, p in pos.items())
        eq_rows.append(dict(date=D, equity=float(eq), cash=float(cash), positions=";".join(pos), spy=float(CAPITAL * BM.tr[D] / BM.tr[dates[first]])))

        # 7. Decision date
        if i in dec_idx:
            if use_quant:
                pending = decide_quant(D, pos)
                print(f"{D} equity ${eq:.2f} (SPY ${eq_rows[-1]['spy']:.2f}) -> quant targets: {list(pending.keys())}", flush=True)
            else:
                print(f"{D} equity ${eq:.2f} (SPY ${eq_rows[-1]['spy']:.2f}) -> asking model", flush=True)
                pending = {t: dict(v) for t, v in decide_llm(D, cash, pos, eq).items()}
                print("   targets:", {t: round(v["weight"], 2) for t, v in pending.items()}, flush=True)

        pd.DataFrame(eq_rows).to_csv(os.path.join(out_dir, "equity.csv"), index=False)
        pd.DataFrame(trades).to_csv(os.path.join(out_dir, "trades.csv"), index=False)

    e = pd.DataFrame(eq_rows)
    r = e.equity.pct_change().dropna()
    s = dict(
        start=dates[first],
        end=END,
        final_equity=round(float(e.equity.iloc[-1]), 2),
        ret_pct=round(float((e.equity.iloc[-1] / CAPITAL - 1.0) * 100.0), 2),
        spy_final=round(float(e.spy.iloc[-1]), 2),
        spy_ret_pct=round(float((e.spy.iloc[-1] / CAPITAL - 1.0) * 100.0), 2),
        alpha_pct=round(float((e.equity.iloc[-1] / CAPITAL - 1.0) * 100.0) - float((e.spy.iloc[-1] / CAPITAL - 1.0) * 100.0), 2),
        max_dd_pct=round(float(((e.equity / e.equity.cummax() - 1.0).min()) * 100.0), 2),
        sharpe=round(float(r.mean() / r.std() * np.sqrt(252)), 2) if r.std() > 0 else 0.0,
        trades=len(trades),
        trades_ex_div=len([tr for tr in trades if tr["side"] != "DIV"]),
        decisions=len(dec_idx),
    )
    json.dump(s, open(os.path.join(out_dir, "summary.json"), "w"), indent=2)
    print("\nFINAL SUMMARY:")
    print(s)


if __name__ == "__main__":
    if "--limit" in sys.argv:
        END = sys.argv[sys.argv.index("--limit") + 1]
    main()
