# Tax-loss harvesting in a direct-indexed S&P 500 portfolio

A backtest of a direct-indexed S&P 500 portfolio ($1M cash, market-cap weights, every tax lot tracked) that harvests losses under the 30-day wash-sale rule, compared with an identical portfolio that never harvests. Period: January 2015 to December 2025, monthly. The write-up is `report/report.pdf`.

## Reproduce the results

Python 3.10 or later.

```bash
pip install yfinance pandas numpy matplotlib scipy
```

```bash
# 1. point-in-time S&P 500 membership (public dataset by fja05680)
mkdir -p data output
curl -sL -o data/sp500_hist.csv "https://raw.githubusercontent.com/fja05680/sp500/master/S%26P%20500%20Historical%20Components%20%26%20Changes%20(Updated).csv"
```

```bash
# 2. prices and market-cap inputs from Yahoo Finance (a few minutes; cached in data/)
python fetch.py          # total-return prices, every member since 2009, + coverage check
python fetch_shares.py   # shares outstanding history
python fetch_close.py    # split-adjusted (not dividend-adjusted) closes, for market caps
python -c "import yfinance as yf; yf.download('SPY', start='2009-01-01', end='2026-01-01', auto_adjust=True)['Close'].to_pickle('data/spy.pkl')"
```

```bash
# 3. run the main case, its no-harvest twin and the sensitivities; writes output/
python analyze.py
```

`analyze.py` prints the summary and writes `output/summary.csv`, `output/yearly.csv`, `output/sensitivity.csv` and the six charts used in the report. Runs are deterministic. Yahoo revises its data from time to time, so a fresh download can move the numbers slightly.

To rebuild the PDF: `cd report && pandoc report.md -o report.pdf --pdf-engine=tectonic`.

## What is where

| File | What it does |
|---|---|
| `src/data.py` | point-in-time membership, Yahoo price download and cache, coverage check |
| `src/universe.py` | what the engine sees each month: members, prices, market caps (Yahoo; a CRSP loader is included for a rerun on WRDS data) |
| `src/engine.py` | the backtest: tax lots, HIFO, wash-sale checks, harvesting, replacement, swap-back, index changes |
| `src/metrics.py` | taxes by year, tax alpha, harvested losses, tracking error, turnover |
| `analyze.py` | runs everything and draws the charts |
| `run.py` | runs the main case and the twin only, saving every trade |
| `fetch_wrds.py` | optional: downloads CRSP monthly stock data, CRSP ticker history and Fama-French factors from WRDS (needs a WRDS account) into `~/Downloads/wrds/` |
| `src/sp500_crsp.py` | optional: maps the dated S&P 500 ticker list to CRSP PERMNOs month by month (96% of members in 2010, 99.8% in 2015, 100% from 2018), for a survivorship-free rerun |

## Main assumptions (details in the report)

- Market-cap weights from split-adjusted close × latest shares outstanding; buy-and-hold, so weights drift like the index.
- Harvest a lot when it is 10% or more below its cost; replace it with the most correlated index member (252 trading days); swap back after 31 days.
- Tax rates 40.8% short-term and 23.8% long-term; losses are fully usable each year; 5 bps trading cost per side.
- Known limits: Yahoo lacks many delisted stocks (residual survivorship bias), share counts ignore buybacks, and checks are monthly.
