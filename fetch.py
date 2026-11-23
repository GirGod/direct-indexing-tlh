"""Download and cache prices for every ticker that was in the S&P 500 between 2009 and 2025."""
import sys
sys.path.insert(0, "src")
import pandas as pd
from data import load_membership, universe, download_prices, coverage

START, END = pd.Timestamp("2009-01-01"), pd.Timestamp("2025-12-31")
mem = load_membership()
tickers = universe(mem, START, END)
print("tickers ever in the index:", len(tickers))
px = download_prices(tickers, "2009-01-01", "2026-01-01")
print("priced on Yahoo:", px.shape[1], "| days:", px.shape[0])
month_ends = px.resample("ME").last().index
cov = coverage(mem, px.resample("ME").last(), month_ends[month_ends <= END])
print(cov["coverage"].describe().round(3).to_string())
cov.to_csv("output/coverage.csv")
