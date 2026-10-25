"""Point-in-time screen: top 200 US stocks by market cap at 2024-12-31 (close x shares outstanding known by then).
Candidate pool = S&P 500 members (Wikipedia). No ETFs."""
import warnings; warnings.filterwarnings("ignore")
from concurrent.futures import ThreadPoolExecutor
from io import StringIO
import pandas as pd, requests, yfinance as yf

ASOF = "2024-12-31"
html = requests.get("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}, timeout=30).text
pool = pd.read_html(StringIO(html))[0]["Symbol"].str.replace(".", "-", regex=False).tolist()

px = yf.download(pool, start="2024-12-20", end="2025-01-02", auto_adjust=False, progress=False)["Close"]
px = px.loc[:ASOF].iloc[-1].dropna()

def process(t):
    try:
        tk = yf.Ticker(t)
        s = tk.get_shares_full(start="2024-09-01", end="2025-01-01")
        s = s[s.index.tz_localize(None) <= pd.Timestamp(ASOF)] if s is not None and len(s) else None
        if s is None or not len(s): return None
        sp = tk.splits   # yfinance Close is split-adjusted; undo splits after ASOF to get raw ASOF price
        f = float(sp[sp.index.tz_localize(None) > pd.Timestamp(ASOF)].prod()) if len(sp) else 1.0
        raw = float(px[t]) * f
        return (t, raw, float(s.iloc[-1]), raw * float(s.iloc[-1]))
    except Exception:
        return None

with ThreadPoolExecutor(max_workers=30) as ex:
    rows = [r for r in ex.map(process, px.index) if r is not None]

df = pd.DataFrame(rows, columns=["ticker", "close", "shares", "mcap"]).sort_values("mcap", ascending=False)
df.head(200).to_csv("data/universe.csv", index=False)
print(len(pool), len(df)); print(df.head(200).to_string(index=False))
