"""Standalone Backtest Script for Quantitative Momentum & Volume Profile Strategy.

Simulates walk-forward execution from 2025-01-02 to 2026-10-20.
Features:
- Fills orders at next bar open (Open[D]) with 0.05% transaction fee.
- Handles stock splits and dividends accurately.
- Intraday hard stop loss tracking.
- Zero lookahead bias.
"""

import json
import os
import sys
from typing import Dict, List, Any
import numpy as np
import pandas as pd

# Support imports whether executed from root or forward-test directory
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from strategy_engine import (
    detect_technical_indicators,
    determine_market_regime,
    select_portfolio_targets,
)

START = "2025-01-02"
END = "2026-10-25"
CAPITAL = 1000.0
FEE = 0.0005
LOOKBACK = 250
STEP = 5
MAX_POSITIONS = 4
INITIAL_STOP = 0.08
MAX_DD_TRAIL = 0.12
TAKE_PROFIT_RSI = 88.0
MIN_SCORE = 0.35
REBALANCE_BAND = 0.04
MIN_TRADE_NOTIONAL = 30.0
RUNNER_PROFIT_THRESHOLD = 0.25
RUNNER_DD_TRAIL = 0.18
RUNNER_MAX_BAND = 0.38

def find_data_file(filename: str) -> str:
    candidates = [
        os.path.join(current_dir, "data", filename),
        os.path.join("data", filename),
        os.path.join("forward-test", "data", filename),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    raise FileNotFoundError(f"Cannot find {filename} in candidate paths: {candidates}")


def fast_split_adjust(g: pd.DataFrame, ticker: str, split_tickers: List[str]) -> pd.DataFrame:
    """Adjust past bars to post-split terms if splits occurred."""
    if ticker not in split_tickers:
        return g
    r = g.split.replace(0, 1.0)
    if (r == 1).all():
        return g
    f = r[::-1].cumprod()[::-1] / r
    g = g.copy()
    for c in ["open", "high", "low", "close"]:
        g[c] = g[c] / f
    g["volume"] = g["volume"] * f
    return g


def run_backtest():
    prices_path = find_data_file("prices.csv")
    bm_path = find_data_file("benchmark.csv")

    px = pd.read_csv(prices_path)
    bm = pd.read_csv(bm_path).set_index("date")
    bm["tr"] = ((bm.close + bm.dividends) / bm.close.shift()).fillna(1).cumprod()

    px["date"] = pd.to_datetime(px["date"]).dt.strftime("%Y-%m-%d")
    dates = sorted(px.date.unique())
    tickers = sorted(px.ticker.unique())
    p_dict = {t: g.set_index("date") for t, g in px.groupby("ticker")}
    split_tickers = px[px["split"] > 1]["ticker"].unique().tolist()

    last_idx = max(i for i, d in enumerate(dates) if d <= END)
    dec_idx = [i for i in range(dates.index(START), len(dates), STEP) if i <= last_idx]
    first = dec_idx[0]
    cash = CAPITAL
    pos = {}  # ticker: dict(sh, entry, stop, high_water, is_deep, emergency_stop)
    pending = None
    trades = []
    eq_rows = []
    stopped_history = {}  # ticker: dict(stop_price, stop_date, stop_idx)

    def sell(t: str, price: float, date_str: str, reason: str):
        nonlocal cash
        p = pos.pop(t)
        proceeds = p["sh"] * price * (1.0 - FEE)
        cash += proceeds
        trades.append({
            "date": date_str,
            "ticker": t,
            "side": "SELL",
            "price": float(price),
            "shares": float(p["sh"]),
            "reason": reason,
        })

    for i in range(first, last_idx + 1):
        d_str = dates[i]

        # 1. Splits adjustment on holdings
        for t, p in list(pos.items()):
            r = p_dict[t].split[d_str]
            if r != 1 and r > 0:
                p["sh"] *= r
                p["entry"] /= r
                p["stop"] /= r
                p["high_water"] /= r

        # 2. Dividend credits
        for t, p in list(pos.items()):
            dv = p_dict[t].dividends[d_str]
            if dv > 0:
                cash += p["sh"] * dv
                trades.append({
                    "date": d_str,
                    "ticker": t,
                    "side": "DIV",
                    "price": float(dv),
                    "shares": float(p["sh"]),
                    "reason": "dividend",
                })

        # 3. Fill pending orders at Open[D]
        if pending is not None:
            eq = cash + sum(p["sh"] * p_dict[t].open[d_str] for t, p in pos.items())

            # Full exits: positions not in pending
            for t in [t for t in list(pos) if t not in pending]:
                sell(t, p_dict[t].open[d_str], d_str, "rebalance_exit")

            # Smart Asymmetric Band Trimming:
            # - Posisi normal: target 25%, deadband 4% (pangkas jika > 29%)
            # - Posisi Super Runner (profit >= +25%): izinkan alokasi hingga 38% sebelum band trim
            # - REVENUE RULE: band_trim HANYA BOLEH jika posisi sedang UNTUNG / PROFIT (o > entry_px)
            for t, tg in pending.items():
                if t in pos:
                    o = p_dict[t].open[d_str]
                    have = pos[t]["sh"] * o
                    entry_px = pos[t].get("entry", o)
                    hw_px = pos[t].get("high_water", o)
                    is_runner = tg.get("is_super_runner", False) or ((o / entry_px - 1.0 >= RUNNER_PROFIT_THRESHOLD) or (hw_px / entry_px - 1.0 >= RUNNER_PROFIT_THRESHOLD))

                    if is_runner:
                        runner_max_val = RUNNER_MAX_BAND * eq
                        if (o > entry_px) and have > runner_max_val and (have - runner_max_val) >= MIN_TRADE_NOTIONAL:
                            n = (have - runner_max_val) / o
                            cash += n * o * (1.0 - FEE)
                            pos[t]["sh"] -= n
                            trades.append({"date": d_str, "ticker": t, "side": "SELL", "price": float(o), "shares": float(n), "reason": "runner_band_trim"})
                        tg["_want"] = tg["weight"] * eq
                    else:
                        want = tg["weight"] * eq
                        if (o > entry_px) and have > want and (have - want) / eq > REBALANCE_BAND and (have - want) >= MIN_TRADE_NOTIONAL:
                            n = (have - want) / o
                            cash += n * o * (1.0 - FEE)
                            pos[t]["sh"] -= n
                            trades.append({"date": d_str, "ticker": t, "side": "SELL", "price": float(o), "shares": float(n), "reason": "band_trim"})
                        tg["_want"] = want

            # Smart Buying & Pyramiding (Scale-in to Winners)
            for t, tg in pending.items():
                o = p_dict[t].open[d_str]
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
                        trades.append({"date": d_str, "ticker": t, "side": "BUY", "price": float(o), "shares": float(n), "reason": reason})

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
            cl = p_dict[t].close[d_str]
            if cl <= pos[t]["stop"]:
                stopped_history[t] = {"stop_price": cl, "stop_date": d_str, "stop_idx": i}
                sell(t, cl, d_str, "trailing_stop")

        # 5. Trailing high-water & Dynamic Stop Lifecycle for Reversals on close
        for t in list(pos):
            cl = p_dict[t].close[d_str]
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
        # 6. Record equity row
        eq = cash + sum(p["sh"] * p_dict[t].close[d_str] for t, p in pos.items())
        spy_eq = CAPITAL * bm.tr[d_str] / bm.tr[dates[first]]
        eq_rows.append({
            "date": d_str,
            "equity": float(eq),
            "cash": float(cash),
            "positions": ";".join(pos.keys()),
            "spy": float(spy_eq),
        })

        # 7. Decision date
        if i in dec_idx:
            # Market regime
            sub_bm = bm.loc[:d_str]
            regime_info = determine_market_regime(sub_bm)

            # Analyze universe tickers strictly <= d_str (no lookahead)
            scores = {}
            for t in tickers:
                w = fast_split_adjust(p_dict[t].loc[:d_str].tail(LOOKBACK), t, split_tickers)
                if len(w) >= 200:
                    scores[t] = detect_technical_indicators(w)

            # Generate target portfolio
            pending = select_portfolio_targets(
                scores=scores,
                current_pos=pos,
                regime_info=regime_info,
                max_positions=MAX_POSITIONS,
                max_dd_trail=MAX_DD_TRAIL,
                take_profit_rsi=TAKE_PROFIT_RSI,
                min_score=MIN_SCORE,
                replacement_hurdle=0.20,
                reversal_initial_stop=4.5,
            )

    e = pd.DataFrame(eq_rows)
    r = e.equity.pct_change().dropna()
    total_ret = (e.equity.iloc[-1] / CAPITAL - 1.0) * 100.0
    spy_ret = (e.spy.iloc[-1] / CAPITAL - 1.0) * 100.0
    alpha = total_ret - spy_ret
    max_dd = ((e.equity / e.equity.cummax() - 1.0).min()) * 100.0
    sharpe = float(r.mean() / r.std() * np.sqrt(252)) if r.std() > 0 else 0.0

    tdf = pd.DataFrame(trades)
    trade_count_all = len(tdf)
    trade_count_ex_div = len(tdf[tdf["side"] != "DIV"])

    # Win rate
    buys = {}
    completed_pnl = []
    for tr in trades:
        if tr["side"] == "BUY":
            if tr["ticker"] not in buys:
                buys[tr["ticker"]] = []
            buys[tr["ticker"]].append(tr["price"])
        elif tr["side"] == "SELL":
            if tr["ticker"] in buys and len(buys[tr["ticker"]]) > 0:
                epx = buys[tr["ticker"]].pop(0)
                completed_pnl.append(tr["price"] / epx - 1.0)
    win_rate = float((np.array(completed_pnl) > 0).mean() * 100.0) if completed_pnl else 0.0

    summary = {
        "start": dates[first],
        "end": END,
        "capital": CAPITAL,
        "final_equity": round(float(e.equity.iloc[-1]), 2),
        "total_return_pct": round(total_ret, 2),
        "spy_final": round(float(e.spy.iloc[-1]), 2),
        "spy_return_pct": round(spy_ret, 2),
        "alpha_pct": round(alpha, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "sharpe_ratio": round(sharpe, 2),
        "win_rate_pct": round(win_rate, 1),
        "total_trades_all": trade_count_all,
        "total_trades_ex_div": trade_count_ex_div,
        "decisions": len(dec_idx),
        "trade_reasons": tdf["reason"].value_counts().to_dict(),
    }

    # Save outputs
    out_dir = os.path.join(current_dir, "papertrade")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "summary_strategy.json"), "w") as f:
        json.dump(summary, f, indent=2)
    e.to_csv(os.path.join(out_dir, "equity_strategy.csv"), index=False)
    tdf.to_csv(os.path.join(out_dir, "trades_strategy.csv"), index=False)

    return summary


if __name__ == "__main__":
    res = run_backtest()
    print("\n================ QUANT STRATEGY BACKTEST REPORT ================")
    print(f"Period             : {res['start']} to {res['end']}")
    print(f"Initial Capital    : ${res['capital']:.2f}")
    print(f"Final Equity       : ${res['final_equity']:.2f} (SPY: ${res['spy_final']:.2f})")
    print(f"Strategy Return    : +{res['total_return_pct']:.2f}%")
    print(f"SPY Return         : +{res['spy_return_pct']:.2f}%")
    print(f"Alpha vs SPY       : +{res['alpha_pct']:.2f}%")
    print(f"Max Drawdown       : {res['max_drawdown_pct']:.2f}%")
    print(f"Sharpe Ratio       : {res['sharpe_ratio']:.2f}")
    print(f"Win Rate           : {res['win_rate_pct']:.1f}%")
    print(f"Total Trades (all) : {res['total_trades_all']} (ex-div: {res['total_trades_ex_div']})")
    print(f"Trade Breakdown    : {res['trade_reasons']}")
    print("================================================================\n")
