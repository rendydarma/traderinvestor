"""Live / Paper Trading Runner with TradingView MCP Bridge & Strategy Engine.

Executes quantitative Momentum + Volume Profile strategy using live or mock
data from TradingView Desktop:
1. SPY Benchmark Market Regime detection (Cash: 0%, 25%, 80%).
2. Multi-asset Volume Profile (POC, HVN, LVN) & Setup detection (Continuation, Pullback, Reversal).
3. Visual level plotting onto TradingView Desktop chart:
   - Cyan: Point of Control (POC)
   - Green: Strong HVN Support
   - Red: Trailing Stop Level
   - Purple: Target Resistance / LVN
4. Smart Band Papertrade Portfolio rebalancing (deadband threshold, $30 minimum).
5. State persistence in papertrade/live_portfolio.json & papertrade/live_trades.csv.
"""

import argparse
from datetime import datetime
import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd

# Support imports from forward-test directory or root
current_dir = os.path.dirname(os.path.abspath(__file__))
repo_root = os.path.dirname(current_dir)
for p in [current_dir, repo_root]:
    if p not in sys.path:
        sys.path.insert(0, p)

from strategy_engine import (
    compute_volume_profile,
    detect_technical_indicators,
    determine_market_regime,
    select_portfolio_targets,
)
from tv_bridge import TradingViewBridge, TradingViewConnectionError

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("tv_runner")

DEFAULT_WATCHLIST = ["NVDA", "AAPL", "MSFT", "AMD", "MU", "META", "AMZN", "GOOGL"]
DEFAULT_CAPITAL = 1000.0
FEE_RATE = 0.0005
MIN_TRADE_NOTIONAL = 30.0
REBALANCE_BAND = 0.04
MAX_POSITIONS = 4


def clean_ticker(sym: Optional[str]) -> str:
    """Normalize ticker symbol removing exchange prefixes (e.g. NASDAQ:NVDA -> NVDA)."""
    if not sym:
        return ""
    return sym.split(":")[-1].strip().upper()


def resolve_file(rel_path: str) -> str:
    """Resolve file path across current working directory and forward-test folder."""
    candidates = [
        os.path.join(current_dir, rel_path),
        os.path.join(repo_root, rel_path),
        rel_path,
        os.path.join(current_dir, "data", os.path.basename(rel_path)),
    ]
    for c in candidates:
        if os.path.exists(c):
            return os.path.abspath(c)
    return os.path.abspath(candidates[0])


def get_papertrade_dir() -> str:
    """Ensure and return the workspace root papertrade directory."""
    target = os.path.join(repo_root, "papertrade")
    os.makedirs(target, exist_ok=True)
    return target


def format_summary_table(levels_map: Dict[str, Dict[str, Any]]) -> str:
    """Format technical levels and setups into a clean aligned terminal table."""
    headers = ["Ticker", "Price", "RSI", "Setup", "Support HVN", "POC", "Target Res"]
    rows = []
    for ticker, info in levels_map.items():
        price = f"${info.get('close', 0.0):.2f}"
        rsi = f"{info.get('rsi14', 0.0):.1f}"
        setup = info.get("setup", "NONE")
        hvn = f"${info.get('hvn_support', 0.0):.2f}"
        poc = f"${info.get('poc', 0.0):.2f}"
        res = f"${info.get('target_resistance', 0.0):.2f}"
        rows.append([ticker, price, rsi, setup, hvn, poc, res])

    if not rows:
        return "No symbols processed."

    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, val in enumerate(row):
            col_widths[i] = max(col_widths[i], len(val))

    widths = [w + 2 for w in col_widths]

    top = "┌" + "┬".join("─" * w for w in widths) + "┐"
    head_s = "│" + "│".join(f" {h:<{w-1}}" for h, w in zip(headers, widths)) + "│"
    mid = "├" + "┼".join("─" * w for w in widths) + "┤"
    bot = "└" + "┴".join("─" * w for w in widths) + "┘"

    lines = [top, head_s, mid]
    for row in rows:
        formatted_cols = []
        for i, (val, w) in enumerate(zip(row, widths)):
            if i in (0, 3):  # Ticker, Setup left-aligned
                formatted_cols.append(f" {val:<{w-1}}")
            else:  # Numeric values right-aligned
                formatted_cols.append(f"{val:>{w-1}} ")
        lines.append("│" + "│".join(formatted_cols) + "│")
    lines.append(bot)
    return "\n".join(lines)


def generate_decision_rationale(
    portfolio: "PaperTradePortfolio",
    decisions: List[str],
    levels_map: Dict[str, Any],
    current_prices: Dict[str, float],
    equity: float,
    single_mode: bool,
    target_symbol: Optional[str] = None,
) -> str:
    """Generate concise, intuitive Indonesian rationale for HOLD/BUY/SELL decisions."""
    trade_actions = [d for d in decisions if d.startswith(("BUY", "TRIM", "EXIT"))]

    if trade_actions:
        summary_actions = "; ".join(trade_actions)
        cash_pct = (portfolio.cash / equity * 100.0) if equity > 0 else 0.0
        return f"{summary_actions} -> sisa cash ${portfolio.cash:.2f} ({cash_pct:.1f}%) dijaga sebagai dry powder."

    # HOLD Decision - Explain state of holdings, scanned assets, and cash
    holdings_notes = []
    for t, h in portfolio.holdings.items():
        px = current_prices.get(t, h.get("entry_price", 0.0))
        mv = h["shares"] * px
        wt = (mv / equity * 100.0) if equity > 0 else 0.0
        holdings_notes.append(f"{t} bobot sudah pas {wt:.0f}%")

    if holdings_notes:
        holdings_part = ", ".join(holdings_notes)
    else:
        holdings_part = "Belum ada posisi terbuka"

    if single_mode and target_symbol:
        sym_info = levels_map.get(target_symbol, {})
        setup = sym_info.get("setup", "NONE")
        rsi = sym_info.get("rsi14", 0.0)
        if setup == "NONE":
            scan_part = f"{target_symbol} belum mencetak konfirmasi bounce"
        else:
            scan_part = f"{target_symbol} setup {setup} belum memenuhi threshold eksekusi"
    else:
        non_held = [t for t in levels_map if t not in portfolio.holdings]
        no_setup = [t for t in non_held if levels_map[t].get("setup") == "NONE"]
        if len(no_setup) == len(non_held) and non_held:
            scan_part = "saham lain belum mencetak konfirmasi bounce"
        elif no_setup:
            scan_part = f"{len(no_setup)} saham lain belum mencetak konfirmasi bounce"
        else:
            scan_part = "saham lain belum memenuhi kriteria entry"

    return f"{holdings_part}, {scan_part} -> cash ${portfolio.cash:.2f} dijaga sebagai dry powder"


class MockTradingViewBridge:
    """Mock bridge providing offline data from data/prices.csv and data/benchmark.csv."""

    def __init__(self, prices_path: str, benchmark_path: str, initial_symbol: str = "NVDA"):
        self.prices_df = pd.read_csv(prices_path, parse_dates=["date"])
        self.prices_df["date_str"] = self.prices_df["date"].dt.strftime("%Y-%m-%d")
        self.benchmark_df = pd.read_csv(benchmark_path, parse_dates=["date"])
        self.benchmark_df["date_str"] = self.benchmark_df["date"].dt.strftime("%Y-%m-%d")

        self.tickers = sorted(self.prices_df["ticker"].unique())
        self.current_symbol = clean_ticker(initial_symbol) or "NVDA"
        self.drawings = []
        logger.info(f"[MOCK] MockTradingViewBridge initialized with {len(self.tickers)} tickers (active: {self.current_symbol}).")

    def health_check(self) -> Dict[str, Any]:
        return {
            "connected": True,
            "symbol": self.current_symbol,
            "resolution": "1D",
            "chart_type": 1,
            "api_available": True,
            "details": {"source": "mock_engine"},
            "instruction": None,
        }

    def get_symbol(self) -> str:
        return self.current_symbol

    def set_symbol(self, symbol: str) -> Dict[str, Any]:
        clean = clean_ticker(symbol)
        self.current_symbol = clean
        return {"success": True, "symbol": clean}

    def get_quote(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        sym = clean_ticker(symbol or self.current_symbol)
        df = self.prices_df[self.prices_df["ticker"] == sym]
        if df.empty:
            return {"success": False, "error": f"Symbol {sym} not found"}
        last_row = df.iloc[-1]
        return {
            "success": True,
            "symbol": sym,
            "close": float(last_row["close"]),
            "open": float(last_row["open"]),
            "high": float(last_row["high"]),
            "low": float(last_row["low"]),
            "volume": float(last_row["volume"]),
            "last": float(last_row["close"]),
        }

    def get_ohlcv(self, count: int = 100, symbol: Optional[str] = None) -> pd.DataFrame:
        sym = clean_ticker(symbol or self.current_symbol)
        if sym == "SPY":
            df = self.benchmark_df.copy()
            df["volume"] = 50000000.0
            if "open" not in df.columns:
                df["open"] = df["close"]
                df["high"] = df["close"] * 1.005
                df["low"] = df["close"] * 0.995
        else:
            df = self.prices_df[self.prices_df["ticker"] == sym].copy()
            if df.empty:
                raise ValueError(f"No mock data available for {sym}")

        df = df.tail(count).copy()
        df = df[["open", "high", "low", "close", "volume"]]
        return df

    def draw_level(self, price: float, text: str = "", linecolor: str = "#00ffff", linewidth: int = 2) -> Dict[str, Any]:
        shape = {
            "entity_id": f"mock_line_{len(self.drawings)+1}",
            "price": price,
            "text": text,
            "color": linecolor,
        }
        self.drawings.append(shape)
        logger.info(f"[MOCK DRAW] {linecolor} -> {price:.2f} ({text})")
        return {"success": True, "entity_id": shape["entity_id"]}

    def clear_drawings(self) -> Dict[str, Any]:
        cnt = len(self.drawings)
        self.drawings.clear()
        logger.info(f"[MOCK DRAW] Cleared {cnt} drawings.")
        return {"success": True, "action": "all_shapes_removed"}

    def create_alert(self, symbol: str, price: float, condition: str = "crossing", message: str = "") -> Dict[str, Any]:
        logger.info(f"[MOCK ALERT] {symbol} {condition} {price:.2f} -> {message}")
        return {"success": True, "alert_id": "mock_alert_1", "symbol": symbol, "price": price}


class PaperTradePortfolio:
    """Manages paper trading ledger, state persistence, and rebalancing."""

    def __init__(self, portfolio_file: str, trades_file: str, initial_capital: float = DEFAULT_CAPITAL):
        self.portfolio_file = portfolio_file
        self.trades_file = trades_file
        self.initial_capital = initial_capital
        self.saved_levels: Dict[str, Any] = {}
        self.load()

    def load(self):
        self.saved_levels = {}
        if os.path.exists(self.portfolio_file):
            try:
                with open(self.portfolio_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.capital = float(data.get("capital", self.initial_capital))
                self.cash = float(data.get("cash", self.capital))
                self.realized_pnl = float(data.get("realized_pnl", 0.0))
                self.holdings = data.get("holdings", {})
                self.saved_levels = data.get("levels", {})
                logger.info(f"Loaded existing portfolio: Cash=${self.cash:.2f}, Holdings={list(self.holdings.keys())}")
                return
            except Exception as e:
                logger.warning(f"Error loading {self.portfolio_file}, starting fresh: {e}")

        self.capital = self.initial_capital
        self.cash = self.initial_capital
        self.realized_pnl = 0.0
        self.holdings = {}
        self.saved_levels = {}

    def reset(self, initial_capital: float = DEFAULT_CAPITAL):
        """Reset paper trading portfolio back to clean initial cash."""
        self.capital = initial_capital
        self.cash = initial_capital
        self.realized_pnl = 0.0
        self.holdings = {}
        self.saved_levels = {}

        clean_payload = {
            "timestamp": datetime.now().isoformat(),
            "capital": round(self.capital, 2),
            "cash": round(self.cash, 2),
            "equity": round(self.capital, 2),
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "total_pnl": 0.0,
            "total_pnl_pct": 0.0,
            "regime": {},
            "holdings": {},
            "levels": {},
            "decisions": ["Portfolio reset to initial clean cash."],
            "rationale": "Portfolio reset to clean cash.",
        }
        try:
            os.makedirs(os.path.dirname(self.portfolio_file), exist_ok=True)
            with open(self.portfolio_file, "w", encoding="utf-8") as f:
                json.dump(clean_payload, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to reset {self.portfolio_file}: {e}")

        try:
            if os.path.exists(self.trades_file):
                os.remove(self.trades_file)
        except Exception as e:
            logger.error(f"Failed to clear trades file {self.trades_file}: {e}")
        logger.info(f"Portfolio reset complete. Cash=${self.cash:.2f}, Holdings={list(self.holdings.keys())}")

    def save(
        self,
        current_prices: Dict[str, float],
        regime_info: Dict[str, Any],
        levels_map: Dict[str, Any],
        decision_notes: List[str],
        rationale: str = "",
    ):
        holdings_summary = {}
        total_market_val = 0.0
        total_unrealized = 0.0

        for t, h in self.holdings.items():
            px = current_prices.get(t, h.get("entry_price", 0.0))
            mv = h["shares"] * px
            cost = h["shares"] * h["entry_price"]
            u_pnl = mv - cost
            u_pnl_pct = (u_pnl / cost * 100.0) if cost > 0 else 0.0
            total_market_val += mv
            total_unrealized += u_pnl

            holdings_summary[t] = {
                "shares": round(h["shares"], 4),
                "entry_price": round(h["entry_price"], 2),
                "current_price": round(px, 2),
                "market_value": round(mv, 2),
                "stop_loss": round(h.get("stop_loss", 0.0), 2),
                "high_water": round(h.get("high_water", px), 2),
                "unrealized_pnl": round(u_pnl, 2),
                "unrealized_pnl_pct": round(u_pnl_pct, 2),
                "setup": h.get("setup", "N/A"),
            }

        equity = self.cash + total_market_val
        total_pnl = (equity - self.capital)
        total_pnl_pct = (total_pnl / self.capital) * 100.0 if self.capital > 0 else 0.0

        for t in holdings_summary:
            holdings_summary[t]["weight_pct"] = round((holdings_summary[t]["market_value"] / equity) * 100.0, 2) if equity > 0 else 0.0

        # Preserve previously saved levels for other tickers if running in single-symbol mode
        merged_levels = dict(self.saved_levels)
        merged_levels.update(levels_map)
        self.saved_levels = merged_levels

        all_decisions = list(decision_notes)
        if rationale and rationale not in all_decisions:
            all_decisions.insert(0, rationale)

        payload = {
            "timestamp": datetime.now().isoformat(),
            "capital": round(self.capital, 2),
            "cash": round(self.cash, 2),
            "equity": round(equity, 2),
            "realized_pnl": round(self.realized_pnl, 2),
            "unrealized_pnl": round(total_unrealized, 2),
            "total_pnl": round(total_pnl, 2),
            "total_pnl_pct": round(total_pnl_pct, 2),
            "regime": regime_info,
            "holdings": holdings_summary,
            "levels": merged_levels,
            "decisions": all_decisions,
            "rationale": rationale,
        }

        # Save to canonical portfolio file
        try:
            os.makedirs(os.path.dirname(self.portfolio_file), exist_ok=True)
            with open(self.portfolio_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to write portfolio to {self.portfolio_file}: {e}")

        logger.info(f"Portfolio saved: Equity=${equity:.2f} (P&L: ${total_pnl:+.2f} / {total_pnl_pct:+.2f}%)")

    def log_trade(
        self,
        ticker: str,
        side: str,
        price: float,
        shares: float,
        reason: str,
        pnl: float = 0.0,
    ):
        notional = price * shares
        fee = notional * FEE_RATE
        row = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "ticker": ticker,
            "side": side,
            "price": round(price, 2),
            "shares": round(shares, 4),
            "notional": round(notional, 2),
            "fee": round(fee, 2),
            "reason": reason,
            "realized_pnl": round(pnl, 2),
        }

        try:
            os.makedirs(os.path.dirname(self.trades_file), exist_ok=True)
            file_exists = os.path.exists(self.trades_file) and os.path.getsize(self.trades_file) > 0
            df = pd.DataFrame([row])
            df.to_csv(self.trades_file, mode="a" if file_exists else "w", header=not file_exists, index=False)
        except Exception as e:
            logger.error(f"Failed to append trade to {self.trades_file}: {e}")


def execute_papertrade_cycle(
    bridge: Any,
    portfolio: PaperTradePortfolio,
    watchlist: List[str],
    mock_benchmark_path: Optional[str] = None,
    target_symbol: Optional[str] = None,
    initial_sym: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute complete cycle: Regime check, VPVR & Setups, Level Plotting, and Smart Rebalancing."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info(f"=== Starting TV Papertrade Cycle at {now_str} ===")

    # 0. Detect active symbol
    if not initial_sym:
        try:
            initial_sym = bridge.get_symbol()
        except Exception as e:
            logger.warning(f"Could not read initial symbol from bridge: {e}")
            initial_sym = "NVDA"

    initial_clean = clean_ticker(initial_sym)

    # Determine processing scope and primary target
    if target_symbol:
        primary_ticker = clean_ticker(target_symbol)
        symbols_to_process = [primary_ticker]
        single_mode = True
        logger.info(f"Target Symbol Mode: Analyzing only {primary_ticker} (instant execution)")
    else:
        single_mode = False
        # Priority for main level plotting is on initial_sym (not hardcoded fallback to AAPL)
        if initial_clean and initial_clean != "SPY":
            primary_ticker = initial_clean
        else:
            primary_ticker = clean_ticker(watchlist[0]) if watchlist else "NVDA"
        symbols_to_process = list(dict.fromkeys([primary_ticker] + [clean_ticker(w) for w in watchlist]))
        logger.info(f"Full Watchlist Mode: Primary={primary_ticker}, Total {len(symbols_to_process)} assets.")

    # 1. Market Regime Check on SPY
    logger.info("Step 1: Checking SPY Market Regime...")
    spy_df = None
    try:
        if isinstance(bridge, MockTradingViewBridge):
            spy_df = bridge.get_ohlcv(200, symbol="SPY")
        elif single_mode:
            # Optimize single mode for ~2s execution by reading benchmark CSV directly
            bm_file = mock_benchmark_path or resolve_file("data/benchmark.csv")
            if os.path.exists(bm_file):
                bdf = pd.read_csv(bm_file)
                bdf["volume"] = 50000000.0
                bdf["open"] = bdf["close"]
                bdf["high"] = bdf["close"]
                bdf["low"] = bdf["close"]
                spy_df = bdf.tail(200)
            else:
                curr_sym = bridge.get_symbol()
                if clean_ticker(curr_sym) != "SPY":
                    bridge.set_symbol("SPY")
                spy_df = bridge.get_ohlcv(200)
        else:
            # Full mode: live SPY query or benchmark CSV fallback
            try:
                curr_sym = bridge.get_symbol()
                if clean_ticker(curr_sym) != "SPY":
                    bridge.set_symbol("SPY")
                spy_df = bridge.get_ohlcv(200)
            except Exception as e:
                logger.warning(f"Could not fetch live SPY from TradingView: {e}. Using benchmark CSV.")
                bm_file = mock_benchmark_path or resolve_file("data/benchmark.csv")
                if os.path.exists(bm_file):
                    bdf = pd.read_csv(bm_file)
                    bdf["volume"] = 50000000.0
                    bdf["open"] = bdf["close"]
                    bdf["high"] = bdf["close"]
                    bdf["low"] = bdf["close"]
                    spy_df = bdf.tail(200)

        if spy_df is None or len(spy_df) < 50:
            regime_info = {"regime": "BULL", "cash_target": 0.0, "equity_target": 1.0, "spy_close": 500.0}
        else:
            regime_info = determine_market_regime(spy_df)
    except Exception as e:
        logger.error(f"Error determining market regime: {e}. Defaulting to BULL.")
        regime_info = {"regime": "BULL", "cash_target": 0.0, "equity_target": 1.0}

    logger.info(f"Regime: {regime_info['regime']} (Defensive Cash Buffer: {regime_info['cash_target']*100:.0f}%)")

    # 2. Collect Data and Calculate Indicators for Watchlist
    logger.info("Step 2: Processing Watchlist Assets...")
    scores: Dict[str, Dict[str, Any]] = {}
    current_prices: Dict[str, float] = {}
    levels_map: Dict[str, Any] = {}

    for ticker in symbols_to_process:
        try:
            if isinstance(bridge, MockTradingViewBridge):
                df = bridge.get_ohlcv(200, symbol=ticker)
            else:
                curr = bridge.get_symbol()
                if clean_ticker(curr) != ticker:
                    bridge.set_symbol(ticker)
                df = bridge.get_ohlcv(200)

            if len(df) < 30:
                continue

            ind = detect_technical_indicators(df)
            scores[ticker] = ind
            close_px = ind["close"]
            current_prices[ticker] = close_px

            # Execution levels
            poc = ind["poc"]
            sup_candidates = [h for h in ind["hvns"] if h <= close_px * 1.01]
            hvn_support = max(sup_candidates) if sup_candidates else (poc if poc <= close_px else close_px * 0.95)

            res_candidates = [l for l in ind["lvns"] if l >= close_px * 1.005]
            target_resistance = min(res_candidates) if res_candidates else (ind["vah"] if ind["vah"] > close_px else close_px * 1.08)

            holding_data = portfolio.holdings.get(ticker)
            hw = holding_data["high_water"] if holding_data else close_px
            is_runner = bool(holding_data and ((close_px / holding_data["entry_price"] - 1.0 >= 0.25) or (hw / holding_data["entry_price"] - 1.0 >= 0.25)))
            trail_dist = 0.18 if is_runner else 0.12
            trailing_stop = max(ind["sma50"] if not is_runner else hw * (1.0 - trail_dist), hw * (1.0 - trail_dist))

            setup_name = "NONE"
            if ind.get("deep_support_reversal", False):
                setup_name = "DEEP_SUPPORT_REVERSAL"
            elif ind.get("multi_touch_reversal", False):
                setup_name = "MULTI_TOUCH_REVERSAL"
            elif ind["continuation"]:
                setup_name = "CONTINUATION"
            elif ind["pullback"]:
                setup_name = "PULLBACK"
            elif ind["reversal"]:
                setup_name = "REVERSAL"
            levels_map[ticker] = {
                "close": round(close_px, 2),
                "poc": round(poc, 2),
                "hvn_support": round(hvn_support, 2),
                "trailing_stop": round(trailing_stop, 2),
                "target_resistance": round(target_resistance, 2),
                "setup": setup_name,
                "rsi14": round(ind["rsi14"], 1),
                "mom_score": round(ind["mom_score"], 3),
            }
        except Exception as e:
            logger.warning(f"Error computing indicators for {ticker}: {e}")

    # 3. Draw Levels on TradingView Active Chart
    active_chart_sym = primary_ticker
    if active_chart_sym in levels_map:
        lvl = levels_map[active_chart_sym]
        logger.info(f"Step 3: Plotting levels on TradingView Chart for {active_chart_sym}...")
        try:
            # Ensure TradingView is on active_chart_sym before drawing
            curr = bridge.get_symbol()
            if clean_ticker(curr) != active_chart_sym:
                bridge.set_symbol(active_chart_sym)

            # Clear previous drawings
            bridge.clear_drawings()
            # Draw POC (Cyan)
            bridge.draw_level(lvl["poc"], f"POC {lvl['poc']:.2f}", linecolor="#00e5ff", linewidth=2)
            # Draw HVN Support (Green)
            bridge.draw_level(lvl["hvn_support"], f"HVN Sup {lvl['hvn_support']:.2f}", linecolor="#00e676", linewidth=2)
            # Draw Trailing Stop (Red/Orange)
            bridge.draw_level(lvl["trailing_stop"], f"Trailing Stop {lvl['trailing_stop']:.2f}", linecolor="#ff5252", linewidth=2)
            # Draw Target Resistance / LVN (Purple)
            bridge.draw_level(lvl["target_resistance"], f"Target Res {lvl['target_resistance']:.2f}", linecolor="#e040fb", linewidth=2)
            logger.info(f"Successfully rendered 4 key levels on {active_chart_sym} chart.")
        except Exception as e:
            logger.error(f"Failed to plot levels to TradingView chart: {e}")

    # 4. Papertrade Portfolio Engine & Smart Band Rebalancing
    logger.info("Step 4: Running Portfolio Rebalancing Engine...")
    decisions = []

    # Update high water mark on existing holdings
    for t, h in portfolio.holdings.items():
        if t in current_prices:
            px = current_prices[t]
            if px > h.get("high_water", 0.0):
                h["high_water"] = px

    # Current portfolio valuation
    equity = portfolio.cash + sum(
        h["shares"] * current_prices.get(t, h["entry_price"])
        for t, h in portfolio.holdings.items()
    )

    current_pos_engine = {
        t: {
            "sh": h["shares"],
            "entry": h["entry_price"],
            "stop": h.get("stop_loss", 0.0),
            "high_water": h.get("high_water", h["entry_price"]),
        }
        for t, h in portfolio.holdings.items()
    }

    if single_mode:
        # In single symbol mode, preserve unscanned existing positions to prevent unintended selling
        unscanned_pos = {t: p for t, p in current_pos_engine.items() if t not in scores}
        scanned_pos = {t: p for t, p in current_pos_engine.items() if t in scores}

        avail_slots = max(1, MAX_POSITIONS - len(unscanned_pos))
        scanned_targets = select_portfolio_targets(
            scores=scores,
            current_pos=scanned_pos,
            regime_info=regime_info,
            max_positions=avail_slots,
        )

        targets = {}
        for t in unscanned_pos:
            h_val = portfolio.holdings[t]["shares"] * current_prices.get(t, portfolio.holdings[t]["entry_price"])
            targets[t] = {"weight": h_val / equity if equity > 0 else 0.25}
        targets.update(scanned_targets)
    else:
        targets = select_portfolio_targets(
            scores=scores,
            current_pos=current_pos_engine,
            regime_info=regime_info,
            max_positions=MAX_POSITIONS,
        )

    # A. Execute Sells (Full Exits)
    for t in list(portfolio.holdings.keys()):
        if single_mode and t not in scores:
            continue

        px = current_prices.get(t, portfolio.holdings[t]["entry_price"])
        sh = portfolio.holdings[t]["shares"]
        entry = portfolio.holdings[t]["entry_price"]
        pnl = (px - entry) * sh

        if t not in targets:
            proceeds = sh * px * (1.0 - FEE_RATE)
            portfolio.cash += proceeds
            portfolio.realized_pnl += pnl
            del portfolio.holdings[t]

            reason = "trend_or_stop_exit"
            if scores.get(t, {}).get("rsi14", 0) > 85.0:
                reason = "overbought_take_profit"
            elif px < levels_map.get(t, {}).get("trailing_stop", 0):
                reason = "trailing_stop_triggered"

            portfolio.log_trade(t, "SELL", px, sh, reason, pnl=pnl)
            decisions.append(f"EXIT {t}: Sold {sh:.4f} sh @ ${px:.2f} ({reason}, PnL: ${pnl:+.2f})")

    # B. Smart Band Trimming (Overweight Positions)
    for t, tg in targets.items():
        if t in portfolio.holdings and t in current_prices:
            px = current_prices[t]
            have_val = portfolio.holdings[t]["shares"] * px
            want_val = tg["weight"] * equity

            entry_px = portfolio.holdings[t]["entry_price"]
            hw_px = portfolio.holdings[t].get("high_water", px)
            is_runner = tg.get("is_super_runner", False) or ((px / entry_px - 1.0 >= 0.25) or (hw_px / entry_px - 1.0 >= 0.25))

            # Asymmetric Band Trimming:
            # - Posisi normal: pangkas jika > 29% (target 25% + 4% band)
            # - Posisi Super Runner: izinkan alokasi hingga 38% (35%-40%) sebelum trim
            # - REVENUE RULE: band_trim HANYA BOLEH jika posisi sedang UNTUNG / PROFIT (px > entry_px)
            if is_runner:
                runner_max_val = 0.38 * equity
                delta = have_val - runner_max_val
                if (px > entry_px) and delta > 0 and (delta >= MIN_TRADE_NOTIONAL):
                    sh_to_sell = delta / px
                    proceeds = sh_to_sell * px * (1.0 - FEE_RATE)
                    pnl_portion = (px - entry_px) * sh_to_sell
                    portfolio.cash += proceeds
                    portfolio.realized_pnl += pnl_portion
                    portfolio.holdings[t]["shares"] -= sh_to_sell
                    portfolio.log_trade(t, "SELL", px, sh_to_sell, "runner_band_trim", pnl=pnl_portion)
                    decisions.append(f"RUNNER TRIM {t}: Trimmed {sh_to_sell:.4f} sh @ ${px:.2f} (-${delta:.2f})")
            else:
                delta = have_val - want_val
                if (px > entry_px) and delta > 0 and (delta / equity > REBALANCE_BAND) and (delta >= MIN_TRADE_NOTIONAL):
                    sh_to_sell = delta / px
                    proceeds = sh_to_sell * px * (1.0 - FEE_RATE)
                    pnl_portion = (px - entry_px) * sh_to_sell
                    portfolio.cash += proceeds
                    portfolio.realized_pnl += pnl_portion
                    portfolio.holdings[t]["shares"] -= sh_to_sell
                    portfolio.log_trade(t, "SELL", px, sh_to_sell, "band_trim", pnl=pnl_portion)
                    decisions.append(f"TRIM {t}: Trimmed {sh_to_sell:.4f} sh @ ${px:.2f} (-${delta:.2f})")
    # C. Smart Buying (New Positions or Underweight Rebalance)
    for t, tg in targets.items():
        if t not in current_prices:
            continue
        px = current_prices[t]
        have_val = (portfolio.holdings[t]["shares"] * px) if t in portfolio.holdings else 0.0
        want_val = tg["weight"] * equity
        delta = want_val - have_val

        # Buy condition: new position or significantly underweight
        if t not in portfolio.holdings or ((delta / equity > REBALANCE_BAND) and (delta >= MIN_TRADE_NOTIONAL)):
            spend = min(delta, portfolio.cash / (1.0 + FEE_RATE))
            # Minimum trade notional check ($30, or $20 for new opening positions)
            if spend >= MIN_TRADE_NOTIONAL or (t not in portfolio.holdings and spend >= 20.0):
                sh_to_buy = spend / px
                fee = spend * FEE_RATE
                portfolio.cash -= (spend + fee)

                stop_val = levels_map.get(t, {}).get("trailing_stop", px * 0.92)
                setup_val = levels_map.get(t, {}).get("setup", "N/A")

                if t not in portfolio.holdings:
                    portfolio.holdings[t] = {
                        "shares": sh_to_buy,
                        "entry_price": px,
                        "high_water": px,
                        "stop_loss": stop_val,
                        "setup": setup_val,
                    }
                else:
                    # Blend average price
                    prev_sh = portfolio.holdings[t]["shares"]
                    prev_cost = prev_sh * portfolio.holdings[t]["entry_price"]
                    new_sh = prev_sh + sh_to_buy
                    portfolio.holdings[t]["shares"] = new_sh
                    portfolio.holdings[t]["entry_price"] = (prev_cost + spend) / new_sh
                    portfolio.holdings[t]["stop_loss"] = max(portfolio.holdings[t].get("stop_loss", 0), stop_val)

                is_pyramid = (t in portfolio.holdings) and (have_val > 0)
                trade_label = f"pyramid_add_{setup_val}" if is_pyramid else f"rebalance_buy_{setup_val}"
                portfolio.log_trade(t, "BUY", px, sh_to_buy, trade_label)
                action_verb = "PYRAMID ADD" if is_pyramid else "BUY"
                decisions.append(f"{action_verb} {t}: Bought {sh_to_buy:.4f} sh @ ${px:.2f} (+${spend:.2f}, Setup={setup_val})")

    # Generate intuitive rationale
    rationale = generate_decision_rationale(
        portfolio=portfolio,
        decisions=decisions,
        levels_map=levels_map,
        current_prices=current_prices,
        equity=equity,
        single_mode=single_mode,
        target_symbol=primary_ticker if single_mode else None,
    )

    if not decisions:
        decisions.append(f"HOLD: {rationale}")

    # 5. Save state
    portfolio.save(
        current_prices=current_prices,
        regime_info=regime_info,
        levels_map=levels_map,
        decision_notes=decisions,
        rationale=rationale,
    )

    return {
        "status": "success",
        "regime": regime_info["regime"],
        "regime_info": regime_info,
        "decisions": decisions,
        "rationale": rationale,
        "holdings": list(portfolio.holdings.keys()),
        "levels": levels_map,
        "primary_ticker": active_chart_sym,
        "initial_symbol": initial_sym,
    }


def print_papertrade_summary(
    result: Dict[str, Any],
    portfolio: PaperTradePortfolio,
    levels_map: Dict[str, Any],
    active_chart_sym: str,
):
    """Print clean, professional terminal summary including status table and decision rationale."""
    equity = portfolio.cash + sum(
        h["shares"] * levels_map.get(t, {}).get("close", h.get("entry_price", 0.0))
        for t, h in portfolio.holdings.items()
    )
    total_pnl = equity - portfolio.capital
    total_pnl_pct = (total_pnl / portfolio.capital * 100.0) if portfolio.capital > 0 else 0.0
    cash_pct = (portfolio.cash / equity * 100.0) if equity > 0 else 100.0
    regime = result.get("regime", "UNKNOWN")

    print("\n" + "=" * 80)
    print(" " * 22 + "TRADINGVIEW PAPERTRADE RUNNER SUMMARY")
    print("=" * 80)

    # Regime & Portfolio Info
    reg_info = result.get("regime_info", {})
    spy_px = reg_info.get("spy_close")
    spy_str = f" | SPY Close: ${spy_px:.2f}" if spy_px else ""
    cash_tgt = reg_info.get("cash_target", 0.0)
    print(f"Market Regime   : {regime}{spy_str} (Target Cash Buffer: {cash_tgt*100:.0f}%)")
    print(
        f"Portfolio State : Equity: ${equity:,.2f} | Cash: ${portfolio.cash:,.2f} ({cash_pct:.1f}%) | "
        f"Realized P&L: ${portfolio.realized_pnl:+,.2f} | Total P&L: ${total_pnl:+,.2f} ({total_pnl_pct:+.2f}%)"
    )

    # Holdings detail
    if portfolio.holdings:
        h_lines = []
        for t, h in portfolio.holdings.items():
            px = levels_map.get(t, {}).get("close", h["entry_price"])
            val = h["shares"] * px
            pct = (val / equity * 100.0) if equity > 0 else 0.0
            u_pnl = (px - h["entry_price"]) * h["shares"]
            h_lines.append(f"{t}: {h['shares']:.4f} sh @ ${h['entry_price']:.2f} (${val:.2f} | {pct:.1f}% | Setup: {h.get('setup', 'N/A')} | P&L: ${u_pnl:+.2f})")
        print(f"Active Holdings : {', '.join(h_lines)}")
    else:
        print("Active Holdings : None (100% Cash)")

    # Technical Levels Table
    print("\nWATCHLIST & VPVR TECHNICAL LEVELS:")
    print(format_summary_table(levels_map))

    # TradingView Level Rendering Summary
    if active_chart_sym in levels_map:
        lvl = levels_map[active_chart_sym]
        print(f"\n🎯 TradingView Chart Levels ({active_chart_sym}):")
        print(f"   * Point of Control (POC - Cyan)    : ${lvl.get('poc', 0.0):.2f}")
        print(f"   * Support HVN (Green)              : ${lvl.get('hvn_support', 0.0):.2f}")
        print(f"   * Trailing Stop (Red)              : ${lvl.get('trailing_stop', 0.0):.2f}")
        print(f"   * Target Resistance (Purple)       : ${lvl.get('target_resistance', 0.0):.2f}")

    # Decision Rationale
    print("\n💡 Keputusan & Rationale:")
    rationale = result.get("rationale")
    if rationale:
        print(f"   * {rationale}")
    for d in result.get("decisions", []):
        if not d.startswith("HOLD:") and d not in (rationale or ""):
            print(f"   * {d}")

    print("=" * 80 + "\n")


def print_status(papertrade_dir: str) -> None:
    """Print saved portfolio status without TradingView."""
    pf = os.path.join(papertrade_dir, "live_portfolio.json")
    tf = os.path.join(papertrade_dir, "live_trades.csv")
    if not os.path.exists(pf):
        print("Portfolio belum ada. Mulai dengan menjalankan runner.")
        return
    with open(pf, "r", encoding="utf-8") as f:
        d = json.load(f)
    reg = d.get("regime", {})
    eq = d.get("equity", 0.0)
    cash = d.get("cash", 0.0)
    print("================ LIVE PAPERTRADE PORTFOLIO STATUS ================")
    print(f"Updated      : {d.get('timestamp', '-')}")
    print(f"Regime       : {reg.get('regime', '-')}")
    print(
        f"SPY          : close ${reg.get('spy_close', 0):,.2f} | SMA50 ${reg.get('spy_sma50', 0):,.2f} "
        f"| SMA200 ${reg.get('spy_sma200', 0):,.2f}"
    )
    print(f"Capital      : ${d.get('capital', 0):,.2f}")
    print(f"Total Equity : ${eq:,.2f}")
    print(f"Cash         : ${cash:,.2f} ({cash / eq * 100 if eq else 0:.1f}% of equity)")
    print(f"Realized P&L : ${d.get('realized_pnl', 0):,.2f}")
    print(f"Total P&L    : ${d.get('total_pnl', 0):,.2f} ({d.get('total_pnl_pct', 0):+.2f}%)")
    print("\nActive Holdings:")
    holdings = d.get("holdings", {})
    if holdings:
        headers = ["Ticker", "Shares", "Entry Px", "Current Px", "Market Value", "Stop Loss", "Weight %", "Setup", "P&L ($)"]
        rows = [
            [
                t, f"{h.get('shares', 0):.4f}", f"{h.get('entry_price', 0):,.2f}",
                f"{h.get('current_price', 0):,.2f}", f"{h.get('market_value', 0):,.2f}",
                f"{h.get('stop_loss', 0):,.2f}", f"{h.get('weight_pct', 0):.1f}",
                str(h.get("setup", "-")), f"{h.get('unrealized_pnl', 0):+,.2f}",
            ]
            for t, h in holdings.items()
        ]
        widths = [max(len(headers[i]), *(len(r[i]) for r in rows)) for i in range(len(headers))]
        print(" | ".join(h.ljust(w) for h, w in zip(headers, widths)))
        print("-+-".join("-" * w for w in widths))
        for r in rows:
            print(" | ".join(c.ljust(w) for c, w in zip(r, widths)))
    else:
        print("  (tidak ada posisi aktif)")
    if os.path.exists(tf) and os.path.getsize(tf) > 0:
        trades = pd.read_csv(tf).tail(5)
        if len(trades):
            print("\nRecent Trades (last 5):")
            print(trades.to_string(index=False))
    print("=" * 66)


def main():
    parser = argparse.ArgumentParser(description="TradingView Live / Papertrade Runner")
    parser.add_argument("--mock", action="store_true", help="Force offline mock simulation mode")
    parser.add_argument("--capital", type=float, default=DEFAULT_CAPITAL, help="Initial capital balance")
    parser.add_argument("--watchlist", nargs="+", default=DEFAULT_WATCHLIST, help="Watchlist tickers")
    parser.add_argument("--symbol", type=str, default=None, help="Analyze & plot levels for a specific ticker instantly")
    parser.add_argument("--current", action="store_true", help="Analyze & plot levels for currently active TradingView chart symbol")
    parser.add_argument("--reset", action="store_true", help="Reset portfolio papertrade back to clean $1,000 cash")
    parser.add_argument("--status", action="store_true", help="Show saved portfolio status and exit (no TradingView)")
    args = parser.parse_args()

    if args.status:
        print_status(get_papertrade_dir())
        sys.exit(0)

    papertrade_dir = get_papertrade_dir()
    portfolio_file = os.path.join(papertrade_dir, "live_portfolio.json")
    trades_file = os.path.join(papertrade_dir, "live_trades.csv")

    portfolio = PaperTradePortfolio(portfolio_file, trades_file, initial_capital=args.capital)

    if args.reset:
        portfolio.reset(args.capital)
        print(f"\n[RESET] Portfolio papertrade berhasil di-reset ke cash bersih ${args.capital:,.2f}.\n")

    bridge = None
    if not args.mock:
        try:
            live_bridge = TradingViewBridge()
            health = live_bridge.health_check()
            if health.get("connected"):
                logger.info(f"Connected to live TradingView Desktop on {health.get('symbol')} ({health.get('resolution')})")
                bridge = live_bridge
            else:
                logger.warning("TradingView Desktop is offline. Falling back to mock data.")
                print(health.get("instruction") or "")
        except Exception as e:
            logger.warning(f"Failed to connect to live bridge: {e}. Falling back to mock data.")

    # Determine requested target symbol from arguments
    target_symbol = None
    if args.symbol:
        target_symbol = clean_ticker(args.symbol)

    if bridge is None:
        logger.info("Initializing Mock Data Bridge...")
        prices_csv = resolve_file("data/prices.csv")
        bm_csv = resolve_file("data/benchmark.csv")
        initial_mock_sym = target_symbol or "NVDA"
        bridge = MockTradingViewBridge(prices_csv, bm_csv, initial_symbol=initial_mock_sym)

    # 1. UX Requirement: Simpan simbol aktif awal user
    initial_sym = None
    try:
        initial_sym = bridge.get_symbol()
        logger.info(f"Initial active symbol on TradingView: {initial_sym}")
    except Exception as e:
        logger.warning(f"Failed to read initial symbol from bridge: {e}")

    # If --current specified, read active symbol from chart
    if args.current:
        target_symbol = clean_ticker(initial_sym) or "NVDA"
        logger.info(f"--current selected: Target symbol is {target_symbol}")

    try:
        result = execute_papertrade_cycle(
            bridge=bridge,
            portfolio=portfolio,
            watchlist=args.watchlist,
            mock_benchmark_path=resolve_file("data/benchmark.csv"),
            target_symbol=target_symbol,
            initial_sym=initial_sym,
        )

        print_papertrade_summary(
            result=result,
            portfolio=portfolio,
            levels_map=result.get("levels", {}),
            active_chart_sym=result.get("primary_ticker", "NVDA"),
        )
    finally:
        # UX Requirement 1: Di akhir eksekusi, kembalikan chart TradingView ke initial_sym
        # jika user menjalankan runner tanpa opsi --symbol agar user tidak kaget chartnya berpindah ke AAPL.
        if not args.symbol and initial_sym:
            try:
                curr_sym = bridge.get_symbol()
                if clean_ticker(curr_sym) != clean_ticker(initial_sym):
                    bridge.set_symbol(initial_sym)
                    logger.info(f"Chart TradingView dikembalikan ke simbol awal user: {initial_sym}")
            except Exception as e:
                logger.warning(f"Could not restore chart to initial symbol {initial_sym}: {e}")


if __name__ == "__main__":
    main()
