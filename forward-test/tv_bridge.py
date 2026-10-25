"""TradingView Desktop CDP Bridge via Node.js CLI.

Integrates Python quantitative trading engines with TradingView Desktop
using the MCP bridge CLI (node tradingview/src/cli/index.js <command>).
"""

import json
import logging
import os
import shutil
import subprocess
import time
from typing import Any, Dict, List, Optional
import pandas as pd

logger = logging.getLogger("tv_bridge")


class TradingViewConnectionError(Exception):
    """Raised when TradingView Desktop is offline or CDP port is unreachable."""
    pass


class TradingViewBridge:
    """Python bridge for TradingView Desktop CDP automation."""

    def __init__(
        self,
        cli_path: Optional[str] = None,
        node_path: Optional[str] = None,
        timeout: int = 15,
    ):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        repo_root = os.path.dirname(base_dir)

        # Locate CLI index.js
        if cli_path is None:
            candidates = [
                os.path.join(repo_root, "tradingview", "src", "cli", "index.js"),
                os.path.join(base_dir, "tradingview", "src", "cli", "index.js"),
                os.path.join("tradingview", "src", "cli", "index.js"),
            ]
            for c in candidates:
                if os.path.exists(c):
                    cli_path = os.path.abspath(c)
                    break
            if not cli_path or not os.path.exists(cli_path):
                raise FileNotFoundError(f"Cannot find TradingView CLI at {candidates}")

        self.cli_path = cli_path
        self.node_path = node_path or shutil.which("node") or "node"
        self.timeout = timeout
        self.launch_bat = os.path.join(repo_root, "tradingview", "scripts", "launch_tv_debug.bat")

    def _get_offline_instruction(self) -> str:
        bat_path = self.launch_bat if os.path.exists(self.launch_bat) else "tradingview\\scripts\\launch_tv_debug.bat"
        return (
            f"TradingView Desktop belum dibuka dengan remote debugging port (9222).\n"
            f"Langkah solusi:\n"
            f"1. Jalankan batch script: {bat_path}\n"
            f"   atau buka TradingView Desktop dengan flag: --remote-debugging-port=9222\n"
            f"2. Pastikan tab chart TradingView aktif dan terbuka."
        )

    def _execute_cli(self, args: List[str], timeout: Optional[int] = None) -> Dict[str, Any]:
        """Execute node CLI command and parse JSON output."""
        cmd = [self.node_path, self.cli_path] + args
        t = timeout or self.timeout

        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=t,
            )
        except FileNotFoundError as e:
            raise RuntimeError(f"Node.js binary not found ('{self.node_path}'). Please install Node.js.") from e
        except subprocess.TimeoutExpired as e:
            raise TradingViewConnectionError(
                f"Timeout ({t}s) saat memanggil CLI TradingView: {' '.join(cmd)}.\n"
                + self._get_offline_instruction()
            ) from e

        stdout = res.stdout.strip()
        stderr = res.stderr.strip()

        # Handle exit codes & connection failure
        if res.returncode != 0:
            err_msg = stderr or stdout
            try:
                err_json = json.loads(stdout or stderr)
                if isinstance(err_json, dict) and "error" in err_json:
                    err_msg = err_json["error"]
            except Exception:
                pass

            if res.returncode == 2 or "CDP connection failed" in err_msg or "ECONNREFUSED" in err_msg:
                raise TradingViewConnectionError(
                    f"Koneksi TradingView Desktop gagal: {err_msg}\n\n"
                    + self._get_offline_instruction()
                )
            raise RuntimeError(f"TradingView CLI error (code {res.returncode}): {err_msg}")

        if not stdout:
            return {"success": True}

        try:
            data = json.loads(stdout)
            return data
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse JSON output from CLI: {stdout}") from e

    def health_check(self) -> Dict[str, Any]:
        """Check CDP connection and TradingView Desktop state."""
        try:
            data = self._execute_cli(["status"], timeout=5)
            connected = bool(data.get("cdp_connected", False) and data.get("success", False))
            return {
                "connected": connected,
                "symbol": data.get("chart_symbol", "unknown"),
                "resolution": data.get("chart_resolution", "unknown"),
                "chart_type": data.get("chart_type"),
                "api_available": data.get("api_available", False),
                "details": data,
                "instruction": None if connected else self._get_offline_instruction(),
            }
        except TradingViewConnectionError as e:
            return {
                "connected": False,
                "symbol": None,
                "resolution": None,
                "chart_type": None,
                "api_available": False,
                "error": str(e),
                "instruction": self._get_offline_instruction(),
            }
        except Exception as e:
            return {
                "connected": False,
                "error": str(e),
                "instruction": self._get_offline_instruction(),
            }

    def get_symbol(self) -> str:
        """Get the current chart symbol."""
        data = self._execute_cli(["symbol"])
        sym = data.get("symbol")
        if not sym:
            raise ValueError("No symbol returned by TradingView")
        return str(sym)

    def set_symbol(self, symbol: str) -> Dict[str, Any]:
        """Set the chart symbol (e.g. 'AAPL', 'NVDA', 'SPY')."""
        return self._execute_cli(["symbol", symbol])

    def get_quote(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        """Get real-time price quote."""
        args = ["quote"]
        if symbol:
            args.append(symbol)
        data = self._execute_cli(args)
        return data

    def get_ohlcv(self, count: int = 100) -> pd.DataFrame:
        """Get OHLCV bar data and return DataFrame with columns [open, high, low, close, volume]."""
        data = self._execute_cli(["ohlcv", "-n", str(count)])
        bars = data.get("bars", [])
        if not bars:
            raise ValueError("No bars returned by TradingView OHLCV API")

        df = pd.DataFrame(bars)
        required = ["open", "high", "low", "close", "volume"]
        for col in required:
            if col not in df.columns:
                raise KeyError(f"Missing required column '{col}' in OHLCV data")

        # Format dataframe
        df = df[["open", "high", "low", "close", "volume"] + ([c for c in df.columns if c not in required])]
        if "time" in df.columns:
            df["time"] = pd.to_datetime(df["time"], unit="s", errors="coerce")
            df = df.set_index("time")
        return df

    def draw_level(
        self,
        price: float,
        text: str = "",
        linecolor: str = "#00ffff",
        linewidth: int = 2,
    ) -> Dict[str, Any]:
        """Draw a horizontal price level (e.g. POC, Support HVN, Stop Loss)."""
        current_ts = int(time.time())
        overrides = json.dumps({
            "linecolor": linecolor,
            "linewidth": linewidth,
            "showLabel": bool(text),
        })

        args = [
            "draw", "shape",
            "-t", "horizontal_line",
            "-p", str(float(price)),
            "--time", str(current_ts),
            "--overrides", overrides,
        ]
        if text:
            args.extend(["--text", text])

        return self._execute_cli(args)

    def clear_drawings(self) -> Dict[str, Any]:
        """Clear all user drawings on the active chart."""
        return self._execute_cli(["draw", "clear"])

    def create_alert(
        self,
        symbol: str,
        price: float,
        condition: str = "crossing",
        message: str = "",
    ) -> Dict[str, Any]:
        """Create a price alert on TradingView. Ensures symbol is selected if needed."""
        if symbol:
            try:
                curr_sym = self.get_symbol()
                # Check if symbols match (ignoring exchange prefix like BATS: or NASDAQ:)
                curr_clean = curr_sym.split(":")[-1]
                target_clean = symbol.split(":")[-1]
                if curr_clean != target_clean:
                    self.set_symbol(symbol)
            except Exception as e:
                logger.warning(f"Failed to verify/switch symbol before alert: {e}")

        msg = message or f"{symbol} {condition} {price:.2f}"
        args = [
            "alert", "create",
            "-p", str(float(price)),
            "-c", condition,
            "-m", msg,
        ]
        return self._execute_cli(args, timeout=12)
