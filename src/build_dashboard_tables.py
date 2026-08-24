"""
build_dashboard_tables.py — flat tables for Power BI.

Power BI should not perform the joins or the aggregation. Every heavy operation
is done here in pandas, and Power BI receives narrow, already-shaped tables. That
keeps the .pbix fast, keeps the logic in version control, and means the dashboard
cannot silently disagree with the notebooks.

Input : data/processed/*.csv   (from notebooks 02, 03 and 04)
Output: data/processed/dashboard/*.csv

Run: python src/build_dashboard_tables.py
"""

from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
DASH = PROC / "dashboard"
DASH.mkdir(parents=True, exist_ok=True)


def banner(t):
    print("\n" + "=" * 74)
    print(t)
    print("=" * 74)


def save(df, name, note=""):
    df.to_csv(DASH / f"{name}.csv", index=False)
    print(f"  {name + '.csv':<34} {len(df):>8,} rows  {note}")


banner("LOADING")

weekly = pd.read_csv(PROC / "sku_weekly.csv", parse_dates=["week"])
sku = pd.read_csv(PROC / "sku_profile.csv")
rules = pd.read_csv(PROC / "association_rules.csv")
policy = pd.read_csv(PROC / "inventory_policy.csv")
returns = pd.read_csv(PROC / "returns.csv")
absence = pd.read_csv(PROC / "absence_candidates.csv", parse_dates=["gap_start", "gap_end"])

pull = PROC / "pullthrough_test.csv"
pull = pd.read_csv(pull) if pull.exists() else pd.DataFrame()

fc = PROC / "forecast_accuracy.csv"
fc = pd.read_csv(fc) if fc.exists() else pd.DataFrame()

for n, d in [("sku_weekly", weekly), ("sku_profile", sku), ("rules", rules),
             ("policy", policy), ("returns", returns), ("pullthrough", pull)]:
    print(f"  {n:<16} {len(d):>9,}")

# ================================================================== 1
banner("1. DIMENSION — PRODUCT")

dim = sku[["StockCode", "product", "ABC", "XYZ", "class",
           "revenue", "units", "weeks_active", "cv"]].copy()
dim["cv"] = dim["cv"].replace([np.inf, -np.inf], np.nan).round(3)
dim["revenue"] = dim["revenue"].round(2)
dim["is_forecastable"] = (dim["weeks_active"] >= 26).astype(int)

# Pareto columns, computed here rather than in Power BI.
# A running total built inside Power BI accumulates in the field's natural order
# (alphabetical by product name), which produces a meaningless curve. The Pareto
# curve must accumulate in DESCENDING REVENUE order, so the rank is fixed here.
dim = dim.sort_values("revenue", ascending=False).reset_index(drop=True)
dim["revenue_rank"] = np.arange(1, len(dim) + 1)
dim["cumulative_revenue"] = dim["revenue"].cumsum().round(2)
dim["cumulative_revenue_pct"] = (100 * dim["revenue"].cumsum() / dim["revenue"].sum()).round(3)
dim["sku_pct"] = (100 * dim["revenue_rank"] / len(dim)).round(3)
dim["policy_note"] = dim["class"].map({
    "AX": "Tight reorder point, low safety stock — forecast works",
    "AY": "Moderate safety stock, review monthly",
    "AZ": "High revenue but erratic — expensive to protect",
    "BX": "Automate, review quarterly",
    "BY": "Standard policy",
    "BZ": "Erratic and mid-value — consider make-to-order",
    "CX": "Automate entirely, minimal review",
    "CY": "Low priority",
    "CZ": "Delist candidate — worst capital-to-value ratio",
})
save(dim, "dim_product", "one row per SKU, with its class and policy")

# ================================================================== 2
banner("2. FACT — WEEKLY DEMAND")

wk = weekly.merge(sku[["StockCode", "product", "ABC", "XYZ", "class"]],
                  on="StockCode", how="left")
wk["year"] = wk["week"].dt.year
wk["month"] = wk["week"].dt.to_period("M").astype(str)
wk["week_number"] = wk["week"].dt.isocalendar().week.astype(int)
save(wk, "fact_weekly_demand", "SKU x week, with class attached for slicing")

# ================================================================== 3
banner("3. SUMMARY — ABC / XYZ GRID")

grid = (sku.groupby(["ABC", "XYZ", "class"])
        .agg(skus=("StockCode", "size"), revenue=("revenue", "sum"),
             units=("units", "sum"), mean_cv=("cv", "mean"))
        .reset_index())
grid["pct_skus"] = (100 * grid["skus"] / grid["skus"].sum()).round(2)
grid["pct_revenue"] = (100 * grid["revenue"] / grid["revenue"].sum()).round(2)
grid["revenue"] = grid["revenue"].round(2)
grid["mean_cv"] = grid["mean_cv"].round(3)
save(grid, "summary_abc_xyz", "the nine-cell policy grid")
print("\n" + grid[["class", "skus", "pct_skus", "pct_revenue"]].to_string(index=False))

# ================================================================== 4
banner("4. FACT — CO-STOCKING RULES")

r = rules[["A", "A_name", "B", "B_name", "support", "confidence", "lift"]].copy()
r.columns = ["sku_a", "product_a", "sku_b", "product_b", "support", "confidence", "lift"]
for c in ["support", "confidence", "lift"]:
    r[c] = r[c].round(4)
r["strength"] = pd.cut(r["lift"], [0, 2, 5, 10, 1e9],
                       labels=["weak", "moderate", "strong", "very strong"])
r["co_stock_rule"] = (r["lift"] >= 5).astype(int)
r = r.merge(sku[["StockCode", "class"]].rename(columns={"StockCode": "sku_a", "class": "class_a"}),
            on="sku_a", how="left")
save(r.sort_values("lift", ascending=False), "fact_association_rules",
     f"{int(r.co_stock_rule.sum())} pairs flagged for co-stocking")

# ================================================================== 5
banner("5. FACT — INVENTORY POLICY")

rop_cols = [c for c in policy.columns if c.startswith("ROP_")]
p = policy[["StockCode", "class", "ABC", "XYZ", "weekly_demand",
            "forecast_error", "revenue"] + rop_cols].copy()
p = p.merge(sku[["StockCode", "product"]], on="StockCode", how="left")
p[["weekly_demand", "forecast_error"]] = p[["weekly_demand", "forecast_error"]].round(2)
save(p, "fact_inventory_policy", f"reorder points across {len(rop_cols)} lead-time/service combinations")

# long form so Power BI can slice by lead time and service level
long = p.melt(id_vars=["StockCode", "product", "class", "ABC", "XYZ",
                       "weekly_demand", "forecast_error"],
              value_vars=rop_cols, var_name="scenario", value_name="reorder_point")
long["lead_time_weeks"] = long["scenario"].str.extract(r"ROP_(\d+)w").astype(int)
long["service_level"] = long["scenario"].str.extract(r"_(\d+%)$")
save(long.drop(columns="scenario"), "fact_policy_scenarios",
     "long form — slice by lead time and service level")

# ================================================================== 6
banner("6. SUMMARY — MONTHLY TREND")

m = (wk.groupby(["month", "ABC"])
     .agg(units=("units", "sum"), revenue=("revenue", "sum"), skus=("StockCode", "nunique"))
     .reset_index())
m["revenue"] = m["revenue"].round(2)
save(m, "summary_monthly", "revenue and units by month and ABC class")

# ================================================================== 7
banner("7. FACT — RETURNS")

returns["value"] = (returns["Quantity"] * returns["Price"]).round(2)
ret = (returns.groupby(["StockCode", "Description"])
       .agg(returned_units=("Quantity", "sum"), returned_value=("value", "sum"),
            return_lines=("Quantity", "size"))
       .reset_index())
ret["returned_units"] = -ret["returned_units"]
ret["returned_value"] = -ret["returned_value"]
ret = ret.merge(sku[["StockCode", "units", "class"]], on="StockCode", how="left")
ret["return_rate_pct"] = (100 * ret["returned_units"] / ret["units"]).round(2)

# Some SKUs appear ONLY in returns — they were refunded but have no clean sales
# line (their sales were cancelled, or the sale fell outside the cleaned set).
# Left in, Power BI creates a (Blank) row in dim_product because those codes have
# no matching product, and that blank then pollutes every slicer on the page.
orphans = ret[~ret["StockCode"].isin(sku["StockCode"])]
if len(orphans):
    print(f"  {len(orphans)} returns-only SKUs excluded (no matching sales record):")
    print("   ", ", ".join(orphans["StockCode"].head(8).tolist()))
    print("    ^ these would appear as a (Blank) product in Power BI slicers")
ret = ret[ret["StockCode"].isin(sku["StockCode"])]

save(ret.sort_values("returned_units", ascending=False), "fact_returns",
     "return rate per SKU — a demand-quality adjustment")

# ================================================================== 8
banner("8. SUMMARY — THE PULL-THROUGH RESULT")

if len(pull):
    pt = pd.DataFrame([{
        "metric": "observations", "value": len(pull)},
        {"metric": "median_partner_ratio", "value": round(pull["ratio"].median(), 3)},
        {"metric": "pct_pairs_that_fell", "value": round(100 * (pull["ratio"] < 1).mean(), 1)},
        {"metric": "median_pct_drop", "value": round(100 * (1 - pull["ratio"].median()), 1)},
    ])
    save(pt, "summary_pullthrough", "the headline finding, as KPI cards")
    print("\n" + pt.to_string(index=False))

    detail = pull.merge(sku[["StockCode", "product"]].rename(
        columns={"StockCode": "sku", "product": "product_absent"}), on="sku", how="left")
    detail = detail.merge(sku[["StockCode", "product"]].rename(
        columns={"StockCode": "partner", "product": "product_partner"}), on="partner", how="left")
    save(detail.round(3), "fact_pullthrough_detail", "per sku-partner pair")
else:
    print("  no pull-through results — run notebook 04 first")

# ================================================================== 9
banner("9. SUMMARY — FORECAST ACCURACY")

if len(fc):
    f = fc.merge(sku[["StockCode", "product", "class"]], on="StockCode", how="left")
    f[["mae_naive", "mae_mean", "mae_hw"]] = f[["mae_naive", "mae_mean", "mae_hw"]].round(2)
    f["improvement"] = f["improvement"].round(1)
    save(f, "fact_forecast_accuracy", "model vs naive baseline, per SKU")
else:
    print("  no forecast results — run notebook 04 first")

# ================================================================== 10
banner("10. KPI CARDS")

kpi = pd.DataFrame([
    ("Total revenue", round(sku["revenue"].sum(), 0), "GBP"),
    ("SKUs in catalogue", len(sku), "count"),
    ("Class A SKUs", int((sku.ABC == "A").sum()), "count"),
    ("Class A share of revenue", round(100 * sku.loc[sku.ABC == "A", "revenue"].sum()
                                       / sku["revenue"].sum(), 1), "%"),
    ("Delist candidates (CZ)", int((sku["class"] == "CZ").sum()), "count"),
    ("Co-stocking pairs (lift>=5)", int(r.co_stock_rule.sum()), "count"),
    ("Absence episodes tested", len(absence), "count"),
    ("Forecastable SKUs", int((sku.weeks_active >= 26).sum()), "count"),
], columns=["kpi", "value", "unit"])

if len(pull):
    kpi.loc[len(kpi)] = ("Partner sales lost during a stockout",
                         round(100 * (1 - pull["ratio"].median()), 1), "%")
save(kpi, "kpi_cards", "headline numbers for the dashboard header")
print("\n" + kpi.to_string(index=False))

banner("DONE")
print(f"""
  {len(list(DASH.glob('*.csv')))} tables written to data/processed/dashboard/

  IN POWER BI
    Get Data -> Text/CSV -> select all files in that folder
    Model relationships on StockCode:
        dim_product[StockCode]  1 -> *  fact_weekly_demand[StockCode]
        dim_product[StockCode]  1 -> *  fact_inventory_policy[StockCode]
        dim_product[StockCode]  1 -> *  fact_policy_scenarios[StockCode]
        dim_product[StockCode]  1 -> *  fact_returns[StockCode]
        dim_product[StockCode]  1 -> *  fact_association_rules[sku_a]

  Only dim_product is a dimension. Everything else is a fact table pointing at it.
  See docs/09_dashboard_design.md for the page layouts.
""")
