"""Data layer: point-in-time S&P 500 membership + daily prices.

Membership comes from the fja05680/sp500 dataset (one row per change date,
listing every member that day), so the backtest only ever holds stocks that
were actually in the index on that date. That removes the main source of
survivorship bias. Prices come from Yahoo Finance via yfinance.
"""
from pathlib import Path

import pandas as pd

DATA = Path(__file__).resolve().parent.parent / "data"


def load_membership(path=DATA / "sp500_hist.csv"):
    """Return a Series indexed by change date; each value is the set of members."""
    df = pd.read_csv(path, parse_dates=["date"])              # two columns: date, tickers
    sets = df["tickers"].str.split(",").apply(set)            # "A,AAPL,..." -> {"A","AAPL",...}
    return pd.Series(sets.values, index=df["date"]).sort_index()


def members_on(membership, date):
    """Members on `date` = the list from the last change date on or before it."""
    return membership[membership.index <= date].iloc[-1]


def to_yahoo(ticker):
    """Yahoo writes share classes with a dash: BRK.B -> BRK-B."""
    return ticker.replace(".", "-")


def universe(membership, start, end):
    """Every ticker that was a member at any point between start and end."""
    window = membership[(membership.index >= start) & (membership.index <= end)]
    first = members_on(membership, start)                     # members already in at the start
    return sorted(set().union(first, *window.values))


def download_prices(tickers, start, end, cache=DATA / "prices.pkl", chunk=100):
    """Daily total-return prices (split- and dividend-adjusted), one column per ticker.

    Delisted names are often missing on Yahoo; they come back empty and are
    reported by coverage(), not silently dropped.
    """
    if cache.exists():
        return pd.read_pickle(cache)
    import yfinance as yf

    frames = []
    for i in range(0, len(tickers), chunk):                   # Yahoo copes better with batches
        batch = [to_yahoo(t) for t in tickers[i:i + chunk]]
        px = yf.download(batch, start=start, end=end, auto_adjust=True,
                         progress=False, threads=True)["Close"]
        frames.append(px)
    prices = pd.concat(frames, axis=1)
    prices.columns = [c.replace("-", ".") for c in prices.columns]   # back to index spelling
    prices = prices.dropna(axis=1, how="all")                 # tickers Yahoo knew nothing about
    prices.to_pickle(cache)
    return prices


def coverage(membership, prices, dates):
    """Share of index members we have a price for, on each date (survivorship check)."""
    rows = []
    for d in dates:
        mem = members_on(membership, d)
        have = [t for t in mem if t in prices.columns and pd.notna(prices.at[d, t])]
        rows.append({"date": d, "members": len(mem), "priced": len(have),
                     "coverage": len(have) / len(mem)})
    return pd.DataFrame(rows).set_index("date")
