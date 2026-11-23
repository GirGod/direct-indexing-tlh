"""Shares outstanding history from Yahoo, for market-cap weights (price x shares)."""
import sys
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, "src")
import pandas as pd
import yfinance as yf
from data import download_prices, to_yahoo

px = download_prices([], None, None)

def one(t):
    try:
        s = yf.Ticker(to_yahoo(t)).get_shares_full(start="2009-01-01", end="2026-01-01")
        if s is None or len(s) == 0:
            return t, None
        s.index = pd.to_datetime(s.index).tz_localize(None)
        return t, s.groupby(level=0).last()
    except Exception:
        return t, None

with ThreadPoolExecutor(8) as ex:
    res = dict(ex.map(one, list(px.columns)))
got = {t: s for t, s in res.items() if s is not None}
shares = pd.DataFrame(got).sort_index()
shares.to_pickle("data/shares.pkl")
first = shares.apply(lambda c: c.first_valid_index())
print("tickers with shares history:", len(got), "of", px.shape[1])
print("first date with data, by year:", first.dt.year.value_counts().sort_index().to_dict())
