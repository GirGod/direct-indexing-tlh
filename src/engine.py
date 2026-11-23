"""Backtest engine: a direct-indexed S&P 500 portfolio with tax lots and tax-loss harvesting.

One monthly loop. On each month-end:
  1. sell anything that left the index (or stopped trading),
  2. buy the stocks that joined it,
  3. swap back harvested names whose 30-day wash-sale window has passed,
  4. harvest: sell tax lots that are down past the threshold, buy the most
     correlated eligible stock in their place.
Run it with harvest=False and you get the "twin": the same portfolio with no
harvesting, which is the benchmark the tax alpha is measured against.
"""
from dataclasses import dataclass, field

import numpy as np
import pandas as pd




@dataclass
class Config:
    start: str = "2015-01-01"
    end: str = "2025-12-31"
    cash: float = 1_000_000          # the account starts as $1M cash
    harvest: bool = True             # False = the no-harvest twin
    loss_threshold: float = 0.10     # harvest a lot once it is 10% below its cost
    swap_back_max_gain: float = None # None = always swap back after 31 days (drift control);
                                     # a number (e.g. 0.05) = keep the replacement if it is up more
    wash_days: int = 30              # IRS wash-sale window, each side of a loss sale
    st_rate: float = 0.408           # short-term: 37% top federal + 3.8% NIIT
    lt_rate: float = 0.238           # long-term: 20% top federal + 3.8% NIIT
    tcost: float = 0.0005            # 5 bps per side on traded value
    corr_days: int = 252             # one year of daily returns to pick replacements
    freq: str = "ME"                 # how often the loop runs: "ME" month-end (main), "W-FRI" weekly


@dataclass
class Lot:
    shares: float
    cost: float                      # cost per share (the basis)
    date: pd.Timestamp               # purchase date -> holding period


@dataclass
class Book:
    """Everything the portfolio owns, plus the memory the tax rules need."""
    cash: float
    lots: dict = field(default_factory=dict)        # ticker -> [Lot, ...]
    last_buy: dict = field(default_factory=dict)    # ticker -> date of last purchase
    last_loss_sale: dict = field(default_factory=dict)  # ticker -> date of last loss sale
    pairs: list = field(default_factory=list)       # open harvest swaps waiting to swap back

    def shares(self, t):
        return sum(l.shares for l in self.lots.get(t, []))

    def value(self, px):
        return self.cash + sum(self.shares(t) * px[t] for t in self.lots)

    def basis(self):
        return sum(l.shares * l.cost for ls in self.lots.values() for l in ls)


class Backtest:
    def __init__(self, cfg, universe, daily_px):
        self.cfg = cfg
        self.u = universe                                                 # members(d), caps
        self.rets = daily_px.pct_change(fill_method=None)                 # daily returns for correlations
        self.monthly = daily_px.resample(cfg.freq).last()                 # prices on each check date
        self.last_px = daily_px.ffill().resample(cfg.freq).last()         # last traded price, for delistings
        self.caps = universe.caps.reindex(self.monthly.index, method="ffill") if universe.caps is not None else None
        self.book = Book(cash=cfg.cash)
        self.trades = []                                                  # one row per trade
        self.rows = []                                                    # one row per month

    # ---------- trading primitives ----------
    def buy(self, t, amount, d, px, why):
        """Spend `amount` dollars on ticker t at price px, net of costs."""
        if amount <= 0:
            return 0.0
        fee = amount * self.cfg.tcost
        shares = (amount - fee) / px
        self.book.lots.setdefault(t, []).append(Lot(shares, px, d))
        self.book.cash -= amount
        self.book.last_buy[t] = d
        self.trades.append(dict(date=d, ticker=t, side="buy", value=amount, fee=fee,
                                st=0.0, lt=0.0, why=why))
        return shares

    def sell_lots(self, t, lots, d, px, why):
        """Sell specific lots of t. Returns proceeds; records ST/LT realized gains."""
        st = lt = gross = 0.0
        for lot in lots:
            gain = lot.shares * (px - lot.cost)
            held = (d - lot.date).days
            if held > 365:
                lt += gain                                                # long-term: held over a year
            else:
                st += gain
            gross += lot.shares * px
            self.book.lots[t].remove(lot)
        if not self.book.lots[t]:
            del self.book.lots[t]
        fee = gross * self.cfg.tcost
        self.book.cash += gross - fee
        if st + lt < 0:
            self.book.last_loss_sale[t] = d
        self.trades.append(dict(date=d, ticker=t, side="sell", value=gross, fee=fee,
                                st=st, lt=lt, why=why))
        return gross - fee

    def sell_all(self, t, d, px, why):
        """Sell every lot, highest cost first (HIFO) - the order only matters for partial sales."""
        lots = sorted(self.book.lots[t], key=lambda l: -l.cost)
        return self.sell_lots(t, lots, d, px, why)

    # ---------- the tax rules ----------
    def wash_blocked_buy(self, t, d):
        """Buying t now would wash a loss we took on t in the last 30 days."""
        last = self.book.last_loss_sale.get(t)
        return last is not None and (d - last).days <= self.cfg.wash_days

    def wash_blocked_sale(self, t, d):
        """Selling t at a loss now would be washed by a purchase of t in the last 30 days."""
        last = self.book.last_buy.get(t)
        return last is not None and (d - last).days <= self.cfg.wash_days

    def replacement(self, x, d, members, px):
        """The member most correlated with x over the last year that we may legally buy."""
        window = self.rets.loc[:d].iloc[-self.cfg.corr_days:]
        cands = [t for t in sorted(members) if t != x and t in window.columns and pd.notna(px.get(t))
                 and not self.wash_blocked_buy(t, d)]
        corr = window[cands].corrwith(window[x]).dropna()
        return corr.idxmax() if len(corr) else None

    def cap_weights(self, members, d):
        """Each member's share of the index's total market cap on date d (equal weight if no caps)."""
        if self.caps is None:
            return {t: 1 / len(members) for t in sorted(members)}
        caps = self.caps.loc[d].reindex(sorted(members))
        caps = caps.fillna(caps.median())                                # a missing cap gets a typical size
        return (caps / caps.sum()).to_dict()

    # ---------- one month ----------
    def step(self, d):
        cfg, book = self.cfg, self.book
        px = self.monthly.loc[d]
        members = {t for t in self.u.members(d) if t in px.index and pd.notna(px[t])}
        waiting = {p["x"] for p in book.pairs}                           # harvested, not yet swapped back

        # 1. index exits and delistings: sell everything we hold that is no longer a member
        for t in list(book.lots):
            if t not in members:
                price = px[t] if pd.notna(px.get(t)) else self.last_px.at[d, t]
                self.sell_all(t, d, price, "index exit")
        book.pairs = [p for p in book.pairs if p["x"] in members and p["y"] in book.lots]

        # 2. index entries: buy each new member at its market-cap weight in the index
        value = book.value(px)
        new = [t for t in sorted(members) if t not in book.lots and t not in waiting
               and not self.wash_blocked_buy(t, d)]
        if new:
            weights = self.cap_weights(members, d)
            want = {t: value * weights[t] for t in new}                  # dollars each entrant should get
            scale = min(1.0, book.cash / sum(want.values()))             # never spend cash we don't have
            for t in sorted(new):
                self.buy(t, want[t] * scale, d, px[t], "index entry")

        if cfg.harvest:
            # 3. swap back: 31+ days after a harvest, sell the replacement and rebuy the original
            keep = []
            for p in book.pairs:
                if (d - p["date"]).days <= cfg.wash_days or self.wash_blocked_buy(p["x"], d):
                    keep.append(p)
                    continue
                y_lots = [l for l in book.lots.get(p["y"], []) if l.date == p["date"]]
                gain = sum(l.shares * (px[p["y"]] - l.cost) for l in y_lots)
                basis = sum(l.shares * l.cost for l in y_lots)
                if gain < 0 and self.wash_blocked_sale(p["y"], d):         # selling y at a loss now would be
                    keep.append(p)                                         # washed by a recent buy of y: wait
                    continue
                cap = cfg.swap_back_max_gain
                if y_lots and (cap is None or gain <= cap * basis):      # undo the swap
                    cash = self.sell_lots(p["y"], y_lots, d, px[p["y"]], "swap back")
                    self.buy(p["x"], cash, d, px[p["x"]], "swap back")
                # else: the replacement has a big gain; keep it rather than pay the tax
            book.pairs = keep

            # 4. harvest: lots down past the threshold, unless a recent purchase would wash them
            for x in sorted(book.lots):
                if x not in members or self.wash_blocked_sale(x, d):
                    continue
                losers = [l for l in book.lots[x] if px[x] < l.cost * (1 - cfg.loss_threshold)]
                if not losers:
                    continue
                y = self.replacement(x, d, members, px)
                if y is None:
                    continue
                cash = self.sell_lots(x, losers, d, px[x], "harvest")
                self.buy(y, cash, d, px[y], "harvest replacement")
                book.pairs.append(dict(x=x, y=y, date=d))

        # record the month
        self.rows.append(dict(date=d, value=book.value(px), cash=book.cash, basis=book.basis(),
                              holdings=len(book.lots), members=len(members)))

    def run(self):
        dates = self.monthly.loc[self.cfg.start:self.cfg.end].index
        for d in dates:
            self.step(d)
        months = pd.DataFrame(self.rows).set_index("date")
        trades = pd.DataFrame(self.trades)
        return months, trades
