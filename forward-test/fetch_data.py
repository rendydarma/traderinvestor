import warnings; warnings.filterwarnings("ignore")
from concurrent.futures import ThreadPoolExecutor
import pandas as pd, yfinance as yf
TICKERS = pd.read_csv("data/universe.csv").ticker.tolist()

def fetch_one(t):
    for _ in range(3):
        try:
            d = yf.Ticker(t).history(start="2024-01-01", end="2026-10-24", auto_adjust=False, actions=True).reset_index()
            if d.empty:
                continue
            d["Date"] = pd.to_datetime(d["Date"]).dt.strftime("%Y-%m-%d")
            r = d["Stock Splits"].replace(0, 1.0)
            f = r[::-1].cumprod()[::-1] / r   # product of splits strictly after each bar: undo later split adjustment
            for c in ["Open","High","Low","Close","Dividends"]: d[c] = d[c] * f
            d["Volume"] = d["Volume"] / f
            d["Split"] = r
            d = d[["Date","Open","High","Low","Close","Volume","Dividends","Split"]].rename(columns=str.lower)
            d.insert(0, "ticker", t)
            return d
        except Exception:
            pass
    return None

with ThreadPoolExecutor(max_workers=25) as ex:
    rows = [d for d in ex.map(fetch_one, TICKERS) if d is not None]

out = pd.concat(rows, ignore_index=True)
out.to_csv("data/prices.csv", index=False)
print(out.groupby("ticker").agg(n=("date","count"), last=("date","max"), divs=("dividends","sum")))

for _ in range(3):
    try:
        b = yf.Ticker("SPY").history(start="2024-01-01", end="2026-10-24", auto_adjust=False, actions=True).reset_index()
        if not b.empty:
            b["Date"] = pd.to_datetime(b["Date"]).dt.strftime("%Y-%m-%d")
            b[["Date","Close","Dividends"]].rename(columns=str.lower).to_csv("data/benchmark.csv", index=False)
            break
    except Exception:
        pass
