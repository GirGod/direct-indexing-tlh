"""Download the WRDS building blocks once and keep them locally (never in git).

Needs a WRDS account and a saved login (~/.pgpass, created once by
  python3 -c "import wrds; wrds.Connection(wrds_username='<you>').create_pgpass_file()").
WRDS terms allow remote Python connections like this one; they forbid scripting the website.

Writes to ~/Downloads/wrds/:
  crsp_msf_v2_2000_2025.parquet   monthly prices, returns (incl. delisting), market cap, shares, ticker
  crsp_secinfo_hist.parquet       ticker / security history with dates -> map index tickers to PERMNOs
  crsp_ccm_link.parquet           CRSP <-> Compustat link table (for fundamentals)
  ff_factors_monthly.parquet      Fama-French factors + momentum, monthly
  ff_factors_daily.parquet        the same, daily
"""
import sys
from pathlib import Path

import wrds

USER = sys.argv[1] if len(sys.argv) > 1 else "girishkishore10"
OUT = Path.home() / "Downloads" / "wrds"
OUT.mkdir(parents=True, exist_ok=True)

QUERIES = {
    "crsp_msf_v2_2000_2025": """
        select permno, permco, mthcaldt, ticker, siccd, primaryexch, sharetype, securitytype,
               mthprc, mthret, mthretx, mthcap, shrout, mthdelflg
        from crsp.msf_v2
        where mthcaldt between '2000-01-01' and '2025-12-31'""",
    "crsp_secinfo_hist": """
        select permno, secinfostartdt, secinfoenddt, ticker, tradingsymbol, securitynm,
               shareclass, sharetype, securitytype, primaryexch, cusip
        from crsp.stksecurityinfohist""",
    "crsp_ccm_link": """
        select gvkey, lpermno as permno, lpermco as permco, linktype, linkprim, linkdt, linkenddt
        from crsp.ccmxpf_lnkhist
        where linktype in ('LU','LC') and linkprim in ('P','C')""",
    "ff_factors_monthly": "select * from ff.factors_monthly",
    "ff_factors_daily": "select * from ff.factors_daily",
}

db = wrds.Connection(wrds_username=USER)
for name, sql in QUERIES.items():
    if (OUT / f"{name}.parquet").exists():
        print(f"{name}: already downloaded")
        continue
    try:
        df = db.raw_sql(sql)
    except Exception as e:                      # e.g. a product the school does not subscribe to
        print(f"{name}: SKIPPED ({str(e).splitlines()[0][:90]})")
        continue
    df.to_parquet(OUT / f"{name}.parquet", index=False)
    print(f"{name}: {len(df):,} rows")
db.close()
