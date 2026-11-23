"""Run the main case + sensitivities, write the summary tables and the charts."""
import sys
sys.path.insert(0, "src")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from data import load_membership, download_prices
from engine import Config, Backtest
from metrics import summary, taxes_by_year

OUT = "output"
mem = load_membership()
px = download_prices([], None, None)                       # cached by fetch.py
spy = pd.read_pickle("data/spy.pkl").iloc[:, 0].resample("ME").last()


def run(**kw):
    cfg = Config(**kw)
    months, trades = Backtest(cfg, mem, px).run()
    return cfg, months, trades


# main case and its twin
cfg, tlh_m, tlh_t = run(harvest=True)
_, twin_m, twin_t = run(harvest=False)
spy_m = spy.loc[tlh_m.index[0]:tlh_m.index[-1]]
spy_m = spy_m[spy_m.index >= tlh_m.resample("ME").last().index[0]]
spy_m = cfg.cash * spy_m / spy_m.iloc[0]
s, tax_alpha, losses, to = summary(tlh_m, tlh_t, twin_m, twin_t, spy_m, cfg)
pd.Series(s).to_csv(f"{OUT}/summary.csv", header=["value"])

# sensitivities: harvest threshold, and the "keep the replacement if it rose" rule
sens = []
for label, kw in [("threshold 5%", dict(loss_threshold=0.05)),
                  ("threshold 10% (main)", dict(loss_threshold=0.10)),
                  ("threshold 15%", dict(loss_threshold=0.15)),
                  ("10%, keep replacement if up >5%", dict(loss_threshold=0.10, swap_back_max_gain=0.05)),
                  ]:
    c, m, t = run(harvest=True, **kw)
    ss, *_ = summary(m, t, twin_m, twin_t, spy_m, c)
    sens.append({"case": label,
                 "tax alpha /yr": ss["Tax alpha, average per year"],
                 "pre-tax alpha vs twin /yr": ss["Pre-tax alpha vs twin, per year"],
                 "tracking error vs twin": ss["Tracking error vs twin, per year"],
                 "turnover /yr": ss["Average one-way turnover per year"],
                 "trades": len(t)})
pd.DataFrame(sens).to_csv(f"{OUT}/sensitivity.csv", index=False)

# yearly table
yr = pd.DataFrame({
    "tax alpha": tax_alpha,
    "harvested ST loss": losses["st"], "harvested LT loss": losses["lt"],
    "turnover": to["turnover"], "fees": to["fees"],
    "holdings (Dec)": tlh_m["holdings"].groupby(tlh_m.index.year).last(),
})
yr.to_csv(f"{OUT}/yearly.csv")

# ---------- charts ----------
plt.rcParams.update({"figure.figsize": (7, 3.2), "axes.spines.top": False,
                     "axes.spines.right": False, "font.size": 9})

def save(name):
    plt.tight_layout(); plt.savefig(f"{OUT}/{name}.png", dpi=200); plt.close()

plt.plot(tlh_m["value"] / 1e6, label="Direct index + TLH")
plt.plot(twin_m["value"] / 1e6, label="Direct index, no harvesting (twin)")
plt.plot(spy_m / 1e6, label="SPY (S&P 500 ETF)", ls="--")
plt.ylabel("$ millions (pre-tax)"); plt.legend(frameon=False); plt.title("Growth of $1M"); save("growth")

cum = losses.cumsum() / 1e3
plt.bar(losses.index - 0.2, losses["st"] / 1e3, 0.4, label="short-term")
plt.bar(losses.index + 0.2, losses["lt"] / 1e3, 0.4, label="long-term")
plt.ylabel("$ thousands"); plt.legend(frameon=False); plt.title("Harvested losses by year"); save("losses")

plt.bar(tax_alpha.index, tax_alpha * 100)
plt.axhline(tax_alpha.mean() * 100, color="k", lw=0.8, ls="--", label=f"average {tax_alpha.mean():.2%}")
plt.ylabel("% of portfolio value"); plt.legend(frameon=False); plt.title("Tax alpha by year"); save("tax_alpha")

ratio = tlh_m["basis"] / tlh_m["value"]
plt.plot(ratio, label="cost basis / value")
plt.plot(1 - ratio, label="unrealized gain / value")
plt.legend(frameon=False); plt.title("Cost basis and embedded gains"); save("basis")

plt.plot(tlh_m["holdings"], label="TLH holdings"); plt.plot(tlh_m["members"], label="index members with prices", ls="--")
plt.legend(frameon=False); plt.title("Number of holdings"); save("holdings")

active = (tlh_m["value"].resample("ME").last().pct_change() - twin_m["value"].resample("ME").last().pct_change()).dropna()
plt.plot(active.rolling(12).std() * 12 ** 0.5 * 100)
plt.ylabel("% per year"); plt.title("Rolling 12-month tracking error vs the twin"); save("tracking")

for k, v in s.items():
    print(f"{k:42s} {v:,.4f}" if abs(v) < 10 else f"{k:42s} {v:,.0f}")
print(pd.DataFrame(sens).round(4).to_string(index=False))
