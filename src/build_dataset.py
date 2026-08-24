"""
build_dataset.py — turns the raw transaction file into the analysis tables.

Script twin of notebooks/02_cleaning.ipynb. Same decisions, same numbers, no
narrative. The notebook is where the reasoning lives; this exists so the whole
pipeline re-runs in one command.

Input : data/raw/uci/online_retail_II.xlsx
Output: data/processed/transactions_clean.csv   one row per sold line
        data/processed/returns.csv              cancellations, kept separately
        data/processed/sku_weekly.csv           weekly demand per SKU
        data/processed/baskets.csv              invoice -> SKU, multi-item only
        data/processed/cleaning_ledger.csv
        data/processed/absence_candidates.csv   feasibility for objective 4

Run: python src/build_dataset.py
"""

from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "uci"
PROC = ROOT / "data" / "processed"
PROC.mkdir(parents=True, exist_ok=True)

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 40)

ledger = []


def log(step, decision, before, after):
    ledger.append({"step": step, "decision": decision, "rows_before": before,
                   "rows_after": after, "rows_removed": before - after})
    pct = 100 * (before - after) / before if before else 0
    print(f"[{step}] {decision}")
    print(f"        {before:,} -> {after:,}   ({before - after:,} removed, {pct:.2f}%)")


def banner(t):
    print("\n" + "=" * 78)
    print(t)
    print("=" * 78)


# ================================================================== D1 load
banner("D1 — LOAD BOTH SHEETS")

src = RAW / "online_retail_II.xlsx"
sheets = pd.ExcelFile(src).sheet_names
parts = []
for s in sheets:
    p = pd.read_excel(src, sheet_name=s)
    p["source_sheet"] = s
    print(f"  {s:<20} {len(p):>9,} rows")
    parts.append(p)

df = pd.concat(parts, ignore_index=True)
df.columns = [c.strip().replace(" ", "_") for c in df.columns]
N_RAW = len(df)
print(f"\n  combined: {N_RAW:,} rows")

# -------------------------------------------------------------------------
# Two DIFFERENT kinds of duplicate exist here, and conflating them is a mistake.
#
#   (a) CROSS-SHEET. The two sheets are "Year 2009-2010" and "Year 2010-2011",
#       and both contain December 2010. Those rows are the same transaction
#       published twice. Confirmed empirically: Dec 2010 carries ~45,000
#       duplicate-flagged rows against 400-2,700 in every other month.
#       -> remove, unambiguously.
#
#   (b) WITHIN-SHEET. Identical lines inside one sheet. These are plausibly
#       REAL: the same product entered twice on one order is ordinary retail
#       behaviour, and InvoiceDate is per-invoice so both lines share a
#       timestamp by construction.
#       -> keep. Removing them would delete genuine demand and understate
#          the affected SKUs.
# -------------------------------------------------------------------------
KEY = ["Invoice", "StockCode", "Quantity", "InvoiceDate", "Price"]

flagged = df.duplicated(subset=KEY, keep=False)
by_month = (df[flagged].groupby(pd.to_datetime(df.loc[flagged, "InvoiceDate"])
                                .dt.to_period("M")).size())
print("\n  duplicate-flagged rows by month (top 3):")
print(by_month.sort_values(ascending=False).head(3).to_string())

# A row is a cross-sheet duplicate if the same key appears in BOTH sheets.
sheets_per_key = df.groupby(KEY, dropna=False)["source_sheet"].transform("nunique")
cross_sheet = sheets_per_key > 1

n = len(df)
# keep the first copy of each cross-sheet duplicate, drop the rest
df = df[~(cross_sheet & df.duplicated(subset=KEY, keep="first"))]
log("D1a", "drop cross-sheet duplicates (December 2010 appears in both sheets)", n, len(df))

within = df.duplicated(subset=KEY, keep=False).sum()
print(f"\n  within-sheet duplicate lines KEPT: {within:,}")
print("        ^ treated as genuine repeated order lines, not errors.")
print("          Reversing this decision would remove real demand — see notebook 02.")

df["StockCode"] = df["StockCode"].astype(str).str.strip().str.upper()
df["Description"] = df["Description"].astype(str).str.strip()
df["Invoice"] = df["Invoice"].astype(str).str.strip()

# ================================================================== D2 returns
banner("D2 — SEPARATE CANCELLATIONS FROM SALES")

# An invoice beginning with C is a cancellation. These are NOT demand — they are
# demand being reversed — so they cannot sit in the sales table. But they are
# real information about return behaviour, so they are saved rather than deleted.
is_cancel = df["Invoice"].str.startswith("C")
returns = df[is_cancel].copy()
print(f"  cancellation invoices : {returns['Invoice'].nunique():,}")
print(f"  cancellation lines    : {len(returns):,}  ({100 * len(returns) / len(df):.2f}%)")

n = len(df)
df = df[~is_cancel]
log("D2", "move cancellations to returns.csv (kept, not deleted)", n, len(df))

# ================================================================== D3 service codes
banner("D3 — REMOVE SERVICE AND ADJUSTMENT CODES")

# These are not products. Leaving them in would corrupt every inventory figure:
# postage would receive a reorder point, and 'Manual' adjustments would appear
# in association rules as though customers were buying them.
#
# CRITICAL: the exclusion is an EXPLICIT LIST, not a pattern. Codes such as
# DCGS0058 ("MISO PRETTY GUM") and DCGS0066N ("NAVY CUDDLES DOG HOODIE") do not
# match the usual 5-digit product pattern but ARE real products. A regex-based
# rule would silently delete them.
SERVICE_CODES = {
    "POST", "DOT", "C2", "M", "D", "S", "BANK CHARGES", "ADJUST", "ADJUST2",
    "AMAZONFEE", "CRUK", "B", "TEST001", "TEST002", "PADS",
}
is_voucher = df["StockCode"].str.startswith("GIFT_0001")
is_service = df["StockCode"].isin(SERVICE_CODES) | is_voucher

removed = df[is_service]
print(f"  distinct service codes found: {removed['StockCode'].nunique()}")
print(removed.groupby("StockCode").size().sort_values(ascending=False).head(12).to_string())

n = len(df)
df = df[~is_service]
log("D3", "remove service codes, postage, vouchers and test rows", n, len(df))

kept_odd = df.loc[~df["StockCode"].str.match(r"^\d{5}[A-Z]*$"), "StockCode"].unique()
print(f"\n  non-standard codes KEPT as genuine products: {len(kept_odd)}")
print(f"  e.g. {sorted(kept_odd)[:8]}")

# ================================================================== D4 bad values
banner("D4 — IMPOSSIBLE VALUES")

n = len(df)
neg_qty = (df["Quantity"] <= 0).sum()
df = df[df["Quantity"] > 0]
log("D4", f"drop non-positive quantity ({neg_qty:,} rows, returns not tied to a C invoice)", n, len(df))

n = len(df)
bad_price = (df["Price"] <= 0).sum()
df = df[df["Price"] > 0]
log("D4", f"drop zero or negative price ({bad_price:,} rows — gifts, errors, write-offs)", n, len(df))

n = len(df)
df = df[df["Description"].notna() & (df["Description"].str.lower() != "nan")]
log("D4", "drop rows with no product description", n, len(df))

# ================================================================== D5 derive
banner("D5 — DERIVED FIELDS")

df["revenue"] = df["Quantity"] * df["Price"]
df["date"] = pd.to_datetime(df["InvoiceDate"]).dt.normalize()
df["week"] = df["date"].dt.to_period("W").dt.start_time
df["month"] = df["date"].dt.to_period("M").astype(str)
df["dow"] = df["date"].dt.dayofweek
df["is_uk"] = (df["Country"] == "United Kingdom").astype(int)

# One description per SKU — descriptions vary in spelling across rows
sku_name = (df.groupby("StockCode")["Description"]
            .agg(lambda s: s.value_counts().index[0]).rename("product"))
df = df.merge(sku_name, on="StockCode", how="left")

print(f"  rows          : {len(df):,}")
print(f"  SKUs          : {df['StockCode'].nunique():,}")
print(f"  invoices      : {df['Invoice'].nunique():,}")
print(f"  date range    : {df['date'].min().date()} to {df['date'].max().date()}")
print(f"  weeks covered : {df['week'].nunique()}")
print(f"  total revenue : £{df['revenue'].sum():,.0f}")

# ================================================================== D6 baskets
banner("D6 — BASKET TABLE FOR ASSOCIATION MINING")

basket_size = df.groupby("Invoice")["StockCode"].nunique()
multi = basket_size[basket_size > 1].index
baskets = df[df["Invoice"].isin(multi)][["Invoice", "StockCode", "product"]].drop_duplicates()

print(f"  invoices total      : {len(basket_size):,}")
print(f"  multi-item invoices : {len(multi):,}  ({100 * len(multi) / len(basket_size):.1f}%)")
print(f"  basket lines        : {len(baskets):,}")
print(f"  median basket size  : {basket_size[multi].median():.0f} SKUs")
print(f"  95th percentile     : {basket_size[multi].quantile(0.95):.0f} SKUs")
print(f"  largest basket      : {basket_size.max():,} SKUs")

# ================================================================== D7 weekly demand
banner("D7 — WEEKLY DEMAND PER SKU")

weekly = (df.groupby(["StockCode", "week"])
          .agg(units=("Quantity", "sum"), revenue=("revenue", "sum"),
               orders=("Invoice", "nunique"))
          .reset_index())

all_weeks = pd.date_range(df["week"].min(), df["week"].max(), freq="W-MON")
print(f"  SKU-week rows observed: {len(weekly):,}")
print(f"  weeks in period       : {len(all_weeks)}")
print(f"  a fully-stocked SKU would have {len(all_weeks)} rows; median SKU has "
      f"{weekly.groupby('StockCode').size().median():.0f}")

# ================================================================== D8 absence
banner("D8 — ABSENCE CANDIDATES  (feasibility check for objective 4)")

# Objective 4 needs SKUs that sold regularly, stopped, then RESUMED. Requiring
# resumption is what separates a stockout-like gap from a discontinued line.
MIN_WEEKS_BEFORE = 8      # established selling history
MIN_GAP = 3               # weeks of zero sales
MIN_WEEKS_AFTER = 4       # must come back

cand = []
for sku, g in weekly.groupby("StockCode"):
    wk = set(g["week"])
    if len(wk) < MIN_WEEKS_BEFORE + MIN_WEEKS_AFTER:
        continue
    present = pd.Series(all_weeks.isin(list(wk)), index=all_weeks)
    # find runs of absence
    grp = (present != present.shift()).cumsum()
    for _, run in present.groupby(grp):
        if run.iloc[0]:
            continue
        if len(run) < MIN_GAP:
            continue
        start, end = run.index[0], run.index[-1]
        before = present.loc[:start].iloc[:-1]
        after = present.loc[end:].iloc[1:]
        if before.sum() >= MIN_WEEKS_BEFORE and after.sum() >= MIN_WEEKS_AFTER:
            cand.append({"StockCode": sku, "gap_start": start, "gap_end": end,
                         "gap_weeks": len(run), "weeks_before": int(before.sum()),
                         "weeks_after": int(after.sum())})

absence = pd.DataFrame(cand)
print(f"  qualifying absence episodes: {len(absence):,}")
if len(absence):
    print(f"  distinct SKUs             : {absence['StockCode'].nunique():,}")
    print(f"  median gap length         : {absence['gap_weeks'].median():.0f} weeks")
    print(f"\n  VERDICT: objective 4 is "
          f"{'VIABLE' if absence['StockCode'].nunique() >= 30 else 'THIN — consider demoting to secondary'}")
else:
    print("  VERDICT: no qualifying episodes — objective 4 should be dropped")

# ================================================================== save
banner("SAVING")

df.to_csv(PROC / "transactions_clean.csv", index=False)
print(f"  transactions_clean.csv  {len(df):,} rows")
returns.to_csv(PROC / "returns.csv", index=False)
print(f"  returns.csv             {len(returns):,} rows")
baskets.to_csv(PROC / "baskets.csv", index=False)
print(f"  baskets.csv             {len(baskets):,} rows")
weekly.to_csv(PROC / "sku_weekly.csv", index=False)
print(f"  sku_weekly.csv          {len(weekly):,} rows")
absence.to_csv(PROC / "absence_candidates.csv", index=False)
print(f"  absence_candidates.csv  {len(absence):,} rows")

led = pd.DataFrame(ledger)
led.loc[len(led)] = {"step": "TOTAL", "decision": "raw lines -> clean sales lines",
                     "rows_before": N_RAW, "rows_after": len(df),
                     "rows_removed": N_RAW - len(df)}
led.to_csv(PROC / "cleaning_ledger.csv", index=False)
print(f"  cleaning_ledger.csv")

print(f"\n  RECONCILIATION")
print(f"    raw lines      {N_RAW:,}")
print(f"    removed        {N_RAW - len(df):,}   ({100 * (N_RAW - len(df)) / N_RAW:.1f}%)")
print(f"    clean sales    {len(df):,}")
print(f"    (of which {len(returns):,} were moved to returns, not discarded)")

# ================================================================== headline
banner("HEADLINE NUMBERS")

rev = df.groupby("StockCode")["revenue"].sum().sort_values(ascending=False)
cum = rev.cumsum() / rev.sum()
a = (cum <= 0.80).sum() + 1
b = (cum <= 0.95).sum() + 1

print(f"""
CATALOGUE
  SKUs sold                  {len(rev):,}
  Invoices                   {df['Invoice'].nunique():,}
  Total revenue              £{df['revenue'].sum():,.0f}
  Period                     {df['date'].min().date()} to {df['date'].max().date()}

CONCENTRATION  — the case for ABC
  Class A (80% of revenue)   {a:,} SKUs   ({100 * a / len(rev):.1f}% of catalogue)
  Class B (next 15%)         {b - a:,} SKUs
  Class C (last 5%)          {len(rev) - b:,} SKUs   ({100 * (len(rev) - b) / len(rev):.1f}% of catalogue)

BASKETS  — the case for association mining
  Multi-item invoices        {len(multi):,}  ({100 * len(multi) / len(basket_size):.1f}%)
  Median basket              {basket_size[multi].median():.0f} SKUs

DEMAND SIGNAL  — the case for forecasting
  Weeks of history           {len(all_weeks)}
  SKUs with 26+ weeks        {(weekly.groupby('StockCode').size() >= 26).sum():,}
  SKUs with under 8 weeks    {(weekly.groupby('StockCode').size() < 8).sum():,}  <- unforecastable, XYZ handles these
""")

print("Next: notebooks/01_eda.ipynb")
