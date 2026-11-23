"""Run the TLH portfolio and its no-harvest twin, save monthly rows and trades."""
import sys, time
sys.path.insert(0, "src")
import pandas as pd
from data import load_membership, download_prices
from engine import Config, Backtest
from universe import YahooUniverse

def main(**overrides):
    mem = load_membership()
    px = download_prices([], None, None)            # cached by fetch.py
    uni = YahooUniverse(mem, px, pd.read_pickle("data/shares.pkl"), pd.read_pickle("data/close_split_adj.pkl"))
    out = {}
    for name, harvest in [("tlh", True), ("twin", False)]:
        cfg = Config(harvest=harvest, **overrides)
        t0 = time.time()
        months, trades = Backtest(cfg, uni, px).run()
        months.to_csv(f"output/{name}_months.csv"); trades.to_csv(f"output/{name}_trades.csv", index=False)
        out[name] = (months, trades)
        print(f"{name}: {len(months)} months, {len(trades)} trades, end value {months['value'].iloc[-1]:,.0f}, {time.time()-t0:.0f}s")
    return out

if __name__ == "__main__":
    main()
