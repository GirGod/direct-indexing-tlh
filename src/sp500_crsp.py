"""Point-in-time S&P 500 membership as CRSP PERMNOs.

GT's WRDS licence does not include CRSP's own S&P 500 list (crsp.msp500list) and
Compustat's index table only holds today's members. So: take the public dated
ticker list (fja05680/sp500) and map each ticker to the CRSP PERMNO that carried
that ticker ON THAT DATE, using CRSP's security history (stksecurityinfohist).

Output: ~/Downloads/wrds/sp500_members_permno.parquet  (month_end, ticker, permno)
        ~/Downloads/wrds/sp500_unmapped.csv            (what failed, for a hand check)
Run:    python3 src/sp500_crsp.py
"""
from pathlib import Path

import pandas as pd

W = Path.home() / "Downloads" / "wrds"
ROOT = Path(__file__).resolve().parent.parent


def month_end_members(start="2000-01-31", end="2025-12-31"):
    """One row per (month-end, ticker): the list in force on that month-end."""
    m = pd.read_csv(ROOT / "data" / "sp500_hist.csv", parse_dates=["date"]).sort_values("date")
    rows = []
    for d in pd.date_range(start, end, freq="ME"):
        tickers = m.loc[m["date"] <= d, "tickers"].iloc[-1].split(",")
        rows += [(d, t) for t in tickers]
    return pd.DataFrame(rows, columns=["month_end", "ticker"])


def crsp_candidates():
    """CRSP ticker spells: (ticker root, share class, permno, start, end), common equity only."""
    s = pd.read_parquet(W / "crsp_secinfo_hist.parquet")
    s = s[s["securitytype"].eq("EQTY")]                          # equities only
    s["secinfostartdt"] = pd.to_datetime(s["secinfostartdt"])
    s["secinfoenddt"] = pd.to_datetime(s["secinfoenddt"]).fillna(pd.Timestamp("2099-12-31"))
    s["shareclass"] = s["shareclass"].fillna("").str.upper()
    return s[["ticker", "shareclass", "permno", "secinfostartdt", "secinfoenddt", "sharetype"]]


def map_to_permno(members, spells):
    # index tickers write share classes as "BRK.B"; CRSP splits them into BRK + class B
    split = members["ticker"].str.split(".", n=1, expand=True)
    members = members.assign(root=split[0], cls=split[1].fillna("").str.upper())
    j = members.merge(spells, left_on="root", right_on="ticker", how="left", suffixes=("", "_crsp"))
    live = (j["month_end"] >= j["secinfostartdt"]) & (j["month_end"] <= j["secinfoenddt"])
    j = j[live & ((j["cls"] == "") | (j["cls"] == j["shareclass"]))]
    # several spells can match (e.g. ADRs, other classes): prefer ordinary shares, then the lowest PERMNO
    j = j.assign(pref=(j["sharetype"] != "NS").astype(int)).sort_values(["month_end", "ticker", "pref", "permno"])
    j = j.drop_duplicates(["month_end", "ticker"])
    exact = j[["month_end", "ticker", "permno"]].assign(match="exact")

    # fallback for renames: the list sometimes uses a ticker the company only took LATER
    # (SPGI was MHFI, ANTM was WLP). Take the spell of that ticker nearest in time.
    left = members.merge(exact[["month_end", "ticker"]], how="left", indicator=True)
    left = left[left["_merge"] == "left_only"].drop(columns="_merge")
    k = left.merge(spells, left_on="root", right_on="ticker", how="inner", suffixes=("", "_crsp"))
    k = k[(k["cls"] == "") | (k["cls"] == k["shareclass"])]
    gap = (k["secinfostartdt"] - k["month_end"]).abs().combine((k["month_end"] - k["secinfoenddt"]).abs(), min)
    k = k.assign(gap=gap.dt.days).sort_values(["month_end", "ticker", "gap"]).drop_duplicates(["month_end", "ticker"])
    k = k[k["gap"] <= 5 * 365]                                   # the same company within 5 years
    near = k[["month_end", "ticker", "permno"]].assign(match="nearest spell")
    return pd.concat([exact, near], ignore_index=True)


if __name__ == "__main__":
    mem = month_end_members()
    mapped = map_to_permno(mem, crsp_candidates())
    out = mem.merge(mapped, on=["month_end", "ticker"], how="left")
    print("matched by:", out["match"].value_counts(dropna=False).to_dict())
    cov = out.groupby(out["month_end"].dt.year)["permno"].apply(lambda s: s.notna().mean())
    print("share of index members mapped to a CRSP PERMNO, by year:")
    print(cov.round(3).to_string())
    out.dropna(subset=["permno"]).astype({"permno": int}).to_parquet(W / "sp500_members_permno.parquet", index=False)
    miss = out[out["permno"].isna()].groupby("ticker")["month_end"].agg(["min", "max", "count"])
    miss.sort_values("count", ascending=False).to_csv(W / "sp500_unmapped.csv")
    print("unmapped tickers:", len(miss), "| top:", miss.sort_values("count", ascending=False).head(12).index.tolist())
