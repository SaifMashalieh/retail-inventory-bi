"""
check_data.py — run this FIRST, before anything else is built.

Reports what is actually in the file: basket structure, SKU counts, cancellations,
negative quantities, date coverage, non-product stock codes and missingness.

Every number the pipeline design depends on is printed here, so the design is
based on the real file rather than on the documentation.

Input: data/raw/uci/online_retail_II.xlsx
Run:   python src/check_data.py
"""

from pathlib import Path
import sys
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "uci"

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 30)


def banner(t):
    print("\n" + "=" * 78)
    print(t)
    print("=" * 78)


banner("LOADING")

candidates = list(RAW.glob("*.xlsx")) + list(RAW.glob("*.csv"))
if not candidates:
    print(f"  ERROR: no data file found in {RAW}")
    print("  See GET_THE_DATA.md")
    sys.exit(1)

path = candidates[0]
print(f"  file: {path.name}  ({path.stat().st_size / 1e6:.1f} MB)")

if path.suffix == ".xlsx":
    xl = pd.ExcelFile(path)
    print(f"  sheets: {xl.sheet_names}")
    parts = []
    for s in xl.sheet_names:
        p = pd.read_excel(path, sheet_name=s)
        p["source_sheet"] = s
        print(f"    {s:<22} {len(p):>9,} rows")
        parts.append(p)
    df = pd.concat(parts, ignore_index=True)
else:
    df = pd.read_csv(path)

print(f"\n  combined: {len(df):,} rows x {df.shape[1]} columns")
print(f"  columns: {list(df.columns)}")

# Column names differ slightly between published versions
cols = {c.lower().replace(" ", "").replace("_", ""): c for c in df.columns}
INV = cols.get("invoice") or cols.get("invoiceno")
SKU = cols.get("stockcode")
QTY = cols.get("quantity")
PRICE = cols.get("price") or cols.get("unitprice")
DATE = cols.get("invoicedate")
CUST = cols.get("customerid")
DESC = cols.get("description")
COUNTRY = cols.get("country")

print(f"\n  resolved: invoice={INV}  sku={SKU}  qty={QTY}  price={PRICE}  date={DATE}")

banner("FIRST ROWS")
print(df.head(5).to_string(max_colwidth=30))

banner("MISSING VALUES")
m = df.isna().sum()
m = m[m > 0]
if len(m):
    for c, n in m.items():
        print(f"  {c:<20} {n:>9,}  ({100 * n / len(df):.1f}%)")
else:
    print("  none")

banner("DATE COVERAGE  — does this support forecasting?")
df[DATE] = pd.to_datetime(df[DATE], errors="coerce")
print(f"  range      : {df[DATE].min()}  ->  {df[DATE].max()}")
print(f"  span       : {(df[DATE].max() - df[DATE].min()).days} days")
print(f"  distinct days: {df[DATE].dt.date.nunique():,}")
print("\n  rows per month:")
per_month = df.groupby(df[DATE].dt.to_period("M")).size()
for k, v in per_month.items():
    print(f"    {k}  {v:>8,}  {'#' * int(v / 1500)}")

banner("BASKET STRUCTURE  — can association rules be mined?")
print(f"  invoices        : {df[INV].nunique():,}")
print(f"  distinct SKUs   : {df[SKU].nunique():,}")
basket = df.groupby(INV)[SKU].nunique()
print(f"  lines per invoice: mean {basket.mean():.1f}   median {basket.median():.0f}   max {basket.max():,}")
print(f"  single-item invoices: {(basket == 1).sum():,}  ({(basket == 1).mean() * 100:.1f}%)")
print(f"  invoices with 2+ items: {(basket > 1).sum():,}  ({(basket > 1).mean() * 100:.1f}%)")
print("\n  ^ association rules need multi-item baskets. The share above is the usable portion.")

banner("CANCELLATIONS AND RETURNS")
is_cancel = df[INV].astype(str).str.upper().str.startswith("C")
print(f"  cancellation invoices : {df.loc[is_cancel, INV].nunique():,}")
print(f"  cancellation rows     : {is_cancel.sum():,}  ({is_cancel.mean() * 100:.1f}%)")
neg = df[QTY] < 0
print(f"  negative quantity rows: {neg.sum():,}  ({neg.mean() * 100:.1f}%)")
print(f"  overlap (cancel AND negative): {(is_cancel & neg).sum():,}")
zero_price = df[PRICE] <= 0
print(f"  zero or negative price: {zero_price.sum():,}  ({zero_price.mean() * 100:.1f}%)")

banner("NON-PRODUCT STOCK CODES  — these would corrupt inventory maths")
codes = df[SKU].astype(str)
suspicious = codes[~codes.str.match(r"^\d{5}[A-Za-z]*$")]
print(f"  codes not matching the 5-digit product pattern: {suspicious.nunique():,} distinct, "
      f"{len(suspicious):,} rows")
print("\n  the 20 most frequent:")
top = suspicious.value_counts().head(20)
for code, n in top.items():
    desc = df.loc[codes == code, DESC].dropna()
    label = desc.iloc[0] if len(desc) else "(no description)"
    print(f"    {code:<16} {n:>7,}  {str(label)[:46]}")

banner("SKU CONCENTRATION  — is ABC classification meaningful?")
df["_revenue"] = df[QTY] * df[PRICE]
clean = df[(df[QTY] > 0) & (df[PRICE] > 0) & ~is_cancel]
rev = clean.groupby(SKU)["_revenue"].sum().sort_values(ascending=False)
cum = rev.cumsum() / rev.sum()
print(f"  SKUs with positive sales: {len(rev):,}")
for share in (0.5, 0.8, 0.95):
    n = (cum <= share).sum() + 1
    print(f"    {share * 100:.0f}% of revenue comes from {n:,} SKUs  ({100 * n / len(rev):.1f}%)")
print("\n  ^ strong concentration is what makes ABC classification worth doing.")

banner("COUNTRIES")
print(df[COUNTRY].value_counts().head(8).to_string())

banner("WHAT THIS TELLS US")
print("""
  Paste this whole output back. The design decisions it settles:

    1. How many multi-item baskets are there — is association mining viable?
    2. What share is cancellations and returns, and how should they be treated?
    3. Which stock codes are not products and must be excluded?
    4. Is revenue concentrated enough for ABC to be meaningful?
    5. Are there enough months for seasonality and forecasting?

  Nothing gets built until these are answered from the real file.
""")
