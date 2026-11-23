"""Turn the monthly rows and trades of a run into the numbers the brief asks for."""
import numpy as np
import pandas as pd


def taxes_by_year(trades, cfg):
    """Realized gains by year and character, and the tax they cost (negative = tax saved).

    Assumption: the investor has enough gains elsewhere that every realized loss is
    used in the year it is taken, at the rate of its own character (ST or LT).
    """
    sells = trades[trades["side"] == "sell"].copy()
    sells["year"] = pd.to_datetime(sells["date"]).dt.year
    g = sells.groupby("year")[["st", "lt"]].sum()
    g["tax"] = g["st"] * cfg.st_rate + g["lt"] * cfg.lt_rate
    return g


def harvested_losses(trades):
    """Losses taken by the harvest rule only, by year, split ST / LT."""
    h = trades[(trades["side"] == "sell") & (trades["why"] == "harvest")].copy()
    h["year"] = pd.to_datetime(h["date"]).dt.year
    return -h.groupby("year")[["st", "lt"]].sum()            # shown as positive losses


def returns(values):
    values = values.resample("ME").last()                     # always measure on month-ends
    r = values.pct_change().dropna()
    years = len(r) / 12
    cagr = (values.iloc[-1] / values.iloc[0]) ** (1 / years) - 1
    vol = r.std() * np.sqrt(12)
    return r, cagr, vol


def tracking_error(r_port, r_bench):
    active = (r_port - r_bench).dropna()
    return active.std() * np.sqrt(12), active.mean() * 12


def turnover(trades, months):
    """Yearly one-way turnover = (buys + sells) / 2 / average portfolio value."""
    t = trades.copy()
    t["year"] = pd.to_datetime(t["date"]).dt.year
    traded = t.groupby("year")["value"].sum() / 2
    avg = months["value"].groupby(months.index.year).mean()
    fees = t.groupby("year")["fee"].sum()
    return pd.DataFrame({"turnover": traded / avg, "fees": fees})


def summary(tlh_m, tlh_t, twin_m, twin_t, spy_m, cfg):
    """One table: pre-tax, tracking, tax alpha, losses, basis, holdings, turnover."""
    r_tlh, cagr_tlh, vol_tlh = returns(tlh_m["value"])
    r_twin, cagr_twin, _ = returns(twin_m["value"])
    r_spy, cagr_spy, _ = returns(spy_m)
    te_twin, act_twin = tracking_error(r_tlh, r_twin)
    te_spy, act_spy = tracking_error(r_tlh, r_spy)

    tax_tlh = taxes_by_year(tlh_t, cfg)["tax"]
    tax_twin = taxes_by_year(twin_t, cfg)["tax"].reindex(tax_tlh.index, fill_value=0)
    avg_val = tlh_m["value"].groupby(tlh_m.index.year).mean()
    tax_alpha = (tax_twin - tax_tlh) / avg_val                 # tax saved this year / portfolio value
    losses = harvested_losses(tlh_t)
    end = tlh_m.iloc[-1]
    unreal = end["value"] - end["basis"]
    # liquidating at the end: pay long-term tax on every unrealized gain
    liq_tlh = end["value"] - cfg.lt_rate * max(unreal, 0) - tax_tlh.sum()
    end_twin = twin_m.iloc[-1]
    liq_twin = end_twin["value"] - cfg.lt_rate * max(end_twin["value"] - end_twin["basis"], 0) - tax_twin.sum()
    to = turnover(tlh_t, tlh_m)

    return {
        "CAGR, TLH (pre-tax)": cagr_tlh,
        "CAGR, no-harvest twin (pre-tax)": cagr_twin,
        "CAGR, SPY (pre-tax)": cagr_spy,
        "Pre-tax alpha vs twin, per year": act_twin,
        "Pre-tax alpha vs SPY, per year": act_spy,
        "Tracking error vs twin, per year": te_twin,
        "Tracking error vs SPY, per year": te_spy,
        "Volatility, TLH": vol_tlh,
        "Tax alpha, average per year": tax_alpha.mean(),
        "Tax alpha, first 5 years": tax_alpha.iloc[:5].mean(),
        "Tax alpha, last 5 years": tax_alpha.iloc[-5:].mean(),
        "Harvested ST losses, total $": losses["st"].sum(),
        "Harvested LT losses, total $": losses["lt"].sum(),
        "Tax saved vs twin, total $": (tax_twin - tax_tlh).sum(),
        "Unrealized gain / value at end": unreal / end["value"],
        "After-tax value if liquidated, TLH $": liq_tlh,
        "After-tax value if liquidated, twin $": liq_twin,
        "Average holdings": tlh_m["holdings"].mean(),
        "Average one-way turnover per year": to["turnover"].mean(),
        "Trading costs, total $": tlh_t["fee"].sum(),
    }, tax_alpha, losses, to
