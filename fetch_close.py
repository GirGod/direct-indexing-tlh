"""Split-adjusted (not dividend-adjusted) closes, for market caps = close x current shares."""
import sys
sys.path.insert(0, "src")
import pandas as pd
import yfinance as yf
from data import download_prices, to_yahoo

px = download_prices([], None, None)
tickers = list(px.columns)
frames = []
for i in range(0, len(tickers), 100):
    batch = [to_yahoo(t) for t in tickers[i:i + 100]]
    frames.append(yf.download(batch, start="2014-12-01", end="2026-01-01", auto_adjust=False,
                              progress=False, threads=True)["Close"])
close = pd.concat(frames, axis=1)
close.columns = [c.replace("-", ".") for c in close.columns]
close.to_pickle("data/close_split_adj.pkl")
print("closes:", close.shape)
