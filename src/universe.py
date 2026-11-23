"""The investable universe the engine sees: who is in the index, at what price, how big.

Two sources, one interface (members(d), prices, returns, caps, name(t)):
  CRSPUniverse  - CRSP via WRDS: point-in-time S&P 500 members, delisted stocks
                  included, market caps from price x shares outstanding.
  YahooUniverse - free fallback: fja05680 membership, Yahoo prices and shares.
"""
from pathlib import Path

import numpy as np
import pandas as pd


def _pick(cols, *names):
    """First column whose lower-case name is in `names` (CRSP v1 and v2 differ)."""
    low = {c.lower(): c for c in cols}
    for n in names:
        if n in low:
            return low[n]
    raise KeyError(f"none of {names} in {list(cols)}")


class CRSPUniverse:
    def __init__(self, constituents_csv, msf_csv, start="2009-01-01", end="2025-12-31"):
        # --- membership: one row per (PERMNO, start, end) spell in the S&P 500
        c = pd.read_csv(constituents_csv)
        self.spells = pd.DataFrame({
            "permno": c[_pick(c.columns, "permno")].astype(int),
            "start": pd.to_datetime(c[_pick(c.columns, "start", "mbrstartdt", "startdt")]),
            "end": pd.to_datetime(c[_pick(c.columns, "ending", "mbrenddt", "enddt", "end")]),
        })

        # --- monthly stock file: price, total return, shares outstanding
        m = pd.read_csv(msf_csv, low_memory=False)
        df = pd.DataFrame({
            "permno": m[_pick(m.columns, "permno")].astype(int),
            "date": pd.to_datetime(m[_pick(m.columns, "mthcaldt", "date", "caldt")]),
            "prc": pd.to_numeric(m[_pick(m.columns, "mthprc", "prc")], errors="coerce").abs(),
            "ret": pd.to_numeric(m[_pick(m.columns, "mthret", "ret")], errors="coerce"),
            "shrout": pd.to_numeric(m[_pick(m.columns, "shrout", "mthshrout")], errors="coerce"),
            "ticker": m[_pick(m.columns, "ticker", "tic", "tsymbol")].astype(str),
        })
        df = df[(df["date"] >= start) & (df["date"] <= end)]
        df = df[df["permno"].isin(self.spells["permno"])]           # only stocks that were ever members
        df["date"] = df["date"] + pd.offsets.MonthEnd(0)             # align to calendar month-end

        rets = df.pivot_table(index="date", columns="permno", values="ret")
        # total-return price index: dividends reinvested (MthRet includes delisting returns in CRSP v2)
        growth = (1 + rets.fillna(0)).cumprod()
        first = rets.notna().cummax()                                # only after the stock starts trading
        self.prices = (growth * 100).where(first)
        self.prices = self.prices.where(rets.notna() | (first & rets.notna().iloc[::-1].cummax().iloc[::-1]))
        self.returns = rets
        self.caps = df.pivot_table(index="date", columns="permno", values="prc") * \
            df.pivot_table(index="date", columns="permno", values="shrout") * 1000
        last = df.sort_values("date").groupby("permno")["ticker"].last()
        self.tickers = last.to_dict()

    def members(self, d):
        s = self.spells
        return set(s.loc[(s["start"] <= d) & (s["end"] >= d), "permno"])

    def name(self, t):
        return self.tickers.get(t, str(t))


class YahooUniverse:
    """Fallback: fja05680 membership + Yahoo prices; caps from Yahoo shares (mostly from 2015)."""
    def __init__(self, membership, daily_px, shares=None, close_split_adj=None):
        from data import members_on
        self._mem, self._members_on = membership, members_on
        self.prices = daily_px.resample("ME").last()
        self.returns = self.prices.pct_change(fill_method=None)
        if shares is not None and close_split_adj is not None:
            # Market cap must use price and shares in the SAME split basis. Yahoo's share
            # history is in the old basis (GE pre-reverse-split, NVDA pre-split), so use
            # each stock's LATEST share count with the split-adjusted (not dividend-
            # adjusted) close: both are in today's basis. Cost: buybacks and issuance
            # over time are ignored.
            latest = shares.ffill().iloc[-1]
            close = close_split_adj.resample("ME").last().reindex(self.prices.index)
            self.caps = close * latest.reindex(close.columns)
        else:
            self.caps = None
        self.tickers = {t: t for t in self.prices.columns}

    def members(self, d):
        return self._members_on(self._mem, d)

    def name(self, t):
        return t
