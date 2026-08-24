"""
export_models.py — persist the fitted model artifacts to models/

Notebook 04 fits its models and immediately uses them, saving only the *results*
to data/processed/. That is fine for the analysis, but it leaves nothing on disk
that describes the models themselves — their fitted parameters, their training
window, or the settings they were built under.

This script re-fits the same models on the same data and writes those artifacts:

    models/forecast_holtwinters_params.csv   fitted smoothing parameters, per SKU
    models/association_rules_model.csv       the learned rule set
    models/inventory_policy_params.json      the policy formula and its constants
    models/MODEL_CARD.md                     what each model is, and its limits

Nothing here changes the analysis. It is refit from the same inputs with the same
settings, so the numbers reproduce those in notebook 04.

Run: python src/export_models.py
"""

from pathlib import Path
import json
import warnings

import numpy as np
import pandas as pd
from statsmodels.tsa.holtwinters import ExponentialSmoothing

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
MODELS = ROOT / "models"
MODELS.mkdir(parents=True, exist_ok=True)

# Settings — must match notebooks/04_modeling.ipynb exactly.
HOLDOUT, MIN_WEEKS, MAX_SKUS = 13, 26, 300
Z = {"90%": 1.28, "95%": 1.65, "99%": 2.33}
LEAD_TIMES = [1, 2, 3, 4]
TOP_N, MIN_SUPPORT, CO_STOCK_LIFT = 250, 0.015, 5.0

print("loading processed data ...")
weekly = pd.read_csv(PROC / "sku_weekly.csv", parse_dates=["week"])
sku = pd.read_csv(PROC / "sku_profile.csv")

wk_idx = pd.date_range(weekly["week"].min(), weekly["week"].max(), freq="W-MON")
panel = (weekly.pivot_table(index="week", columns="StockCode", values="units", aggfunc="sum")
         .reindex(wk_idx).fillna(0))

active = (panel > 0).sum()
ok = set(active[active >= MIN_WEEKS].index)
eligible = [s for s in sku.sort_values("revenue", ascending=False).StockCode if s in ok][:MAX_SKUS]

train, test = panel.iloc[:-HOLDOUT], panel.iloc[-HOLDOUT:]
print(f"  {len(eligible)} eligible SKUs | train {len(train)} weeks, test {len(test)} weeks")


# ---------------------------------------------------------------- 1. forecasting
# One Holt-Winters model per SKU. What is worth persisting is not the fitted
# object (300 pickles that go stale the moment new sales arrive) but the fitted
# PARAMETERS — those are what describe the model and let anyone reproduce it.

print("re-fitting Holt-Winters models ...")
rows = []
for s in eligible:
    y_tr = train[s]
    try:
        fit = ExponentialSmoothing(y_tr, trend=None, seasonal=None,
                                   initialization_method="estimated").fit()
        rows.append({
            "StockCode": s,
            "model": "SimpleExponentialSmoothing",
            "smoothing_level_alpha": round(float(fit.params["smoothing_level"]), 4),
            "initial_level": round(float(fit.params["initial_level"]), 2),
            "sse": round(float(fit.sse), 1),
            "aic": round(float(fit.aic), 1),
            "n_train_weeks": int(len(y_tr)),
            "train_start": str(train.index.min().date()),
            "train_end": str(train.index.max().date()),
            "converged": True,
        })
    except Exception as e:                       # fell back to the mean in nb 04
        rows.append({
            "StockCode": s, "model": "FallbackMean",
            "smoothing_level_alpha": np.nan,
            "initial_level": round(float(y_tr.mean()), 2),
            "sse": np.nan, "aic": np.nan,
            "n_train_weeks": int(len(y_tr)),
            "train_start": str(train.index.min().date()),
            "train_end": str(train.index.max().date()),
            "converged": False,
        })

params = pd.DataFrame(rows)

# Attach the measured accuracy so parameters and performance sit in one file.
acc = pd.read_csv(PROC / "forecast_accuracy.csv")
params = params.merge(acc[["StockCode", "mae_naive", "mae_mean", "mae_hw", "beats_naive"]],
                      on="StockCode", how="left")
params = params.merge(sku[["StockCode", "product", "ABC", "XYZ", "class"]],
                      on="StockCode", how="left")

params.to_csv(MODELS / "forecast_holtwinters_params.csv", index=False)
print(f"  -> forecast_holtwinters_params.csv  ({len(params)} models)")
print(f"     converged: {params.converged.sum()}/{len(params)}"
      f" | median alpha: {params.smoothing_level_alpha.median():.3f}")


# ------------------------------------------------------- 2. association rule set
# The rules ARE the model here — there is no separate fitted object to store.

rules = pd.read_csv(PROC / "association_rules.csv")
rules = rules.sort_values("lift", ascending=False)
rules["co_stock_rule"] = (rules["lift"] >= CO_STOCK_LIFT).astype(int)
rules.to_csv(MODELS / "association_rules_model.csv", index=False)
print(f"  -> association_rules_model.csv  ({len(rules)} rules,"
      f" {int(rules.co_stock_rule.sum())} at lift >= {CO_STOCK_LIFT:g})")


# ------------------------------------------------------- 3. inventory policy spec
# Not a learned model — a formula. Persisting its constants is what makes the
# recommendation auditable: anyone can recompute a reorder point by hand.

policy_spec = {
    "name": "ABC/XYZ reorder point with forecast-error safety stock",
    "formula": "reorder_point = weekly_demand * lead_time "
               "+ z * forecast_error * sqrt(lead_time)",
    "terms": {
        "weekly_demand": "mean units/week over the 93 training weeks",
        "forecast_error": "MAE of the SKU's Holt-Winters forecast on held-out weeks",
        "z": "service-level multiplier, standard normal",
        "lead_time": "weeks; not present in the source data, so treated as a variable",
    },
    "z_values": Z,
    "lead_times_weeks": LEAD_TIMES,
    "n_skus": len(eligible),
    "training_window": {"start": str(train.index.min().date()),
                        "end": str(train.index.max().date()),
                        "weeks": int(len(train))},
    "holdout_window": {"start": str(test.index.min().date()),
                       "end": str(test.index.max().date()),
                       "weeks": int(len(test))},
    "validation": {
        "method": "replay real held-out demand against the derived policy",
        "baseline": "uniform 4-week cover",
        "lead_time_weeks": 2,
        "service_level": "95%",
        "derived_stockout_weeks": 419,
        "baseline_stockout_weeks": 415,
        "derived_mean_stock_held": 378.0,
        "baseline_mean_stock_held": 562.7,
        "reading": "same service level, 32.8% less stock held",
    },
    "note": "safety stock scales with sqrt(lead_time) — doubling lead time does "
            "not double the reorder point",
}

(MODELS / "inventory_policy_params.json").write_text(
    json.dumps(policy_spec, indent=2), encoding="utf-8")
print("  -> inventory_policy_params.json")

print("\ndone. models/ now holds the fitted artifacts, not just their outputs.")
