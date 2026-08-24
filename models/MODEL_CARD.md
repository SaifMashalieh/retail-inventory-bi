# Model Card

Every model built in this project, what it was trained on, how it performed, and where
it should not be trusted. Regenerate the artifacts beside this file with:

```
python src/export_models.py
```

Source of truth for the analysis is `notebooks/04_modeling.ipynb`. This directory holds
the fitted artifacts; `data/processed/` holds the results those models produced.

---

## Contents of this directory

| File | What it is |
|---|---|
| `forecast_holtwinters_params.csv` | Fitted parameters for 300 per-SKU forecasting models, with their measured accuracy |
| `association_rules_model.csv` | The learned rule set — 480 rules, 272 flagged as co-stocking pairs |
| `inventory_policy_params.json` | The reorder-point formula, its constants, and its validation result |
| `MODEL_CARD.md` | This file |

**Why no `.pkl` files.** The fitted Holt-Winters objects are not serialised deliberately.
There are 300 of them, the whole set refits in under a minute, and a pickled model goes
stale the moment new sales arrive. What is worth persisting is the *parameters* — those
describe the model, reproduce exactly, and stay readable in ten years. A pickle is neither.

---

## Model 1 — Association rules (FP-Growth)

**Type:** unsupervised pattern mining
**Objectives:** 3, 8 (and it supplies the partner pairs used in objective 4)
**Library:** mlxtend

| Setting | Value |
|---|---|
| Basket matrix | 33,505 invoices × 250 SKUs |
| SKU selection | 250 most basket-frequent SKUs |
| Minimum support | 0.015 (1.5%) |
| Max itemset length | 2 |
| Ranking metric | **lift** |
| Co-stocking threshold | lift ≥ 5.0 |

**Output:** 490 frequent itemsets → 480 pairwise rules with lift > 1 → **272 co-stocking pairs**.

**Strongest rule:** SET/6 RED SPOTTY PAPER CUPS ↔ PLATES, lift 26.4.

**Why FP-Growth and not Apriori.** With ~4,700 SKUs, Apriori's candidate generation is the
bottleneck and forces a high support threshold. That is the wrong trade here — in a
long-tail catalogue the interesting pairs live at low support.

**Why lift and not confidence.** Confidence is inflated by popularity; almost everything
looks "confidently" bought alongside a best-seller. Lift controls for the base rate.

**Limitations**
- Restricted to the top 250 SKUs. Rules involving long-tail products are not discoverable at this support threshold, and their absence is a property of the method, not evidence that none exist.
- Pairs only (`max_len=2`). Three-item affinities are not modelled.
- Association is not causation. A rule says two items co-occur, not that one causes the other — which is precisely why objective 4 exists as a separate empirical test.

---

## Model 2 — Demand forecasting (Simple Exponential Smoothing)

**Type:** supervised regression on a target constructed from the time axis
**Objective:** 6
**Library:** statsmodels — `ExponentialSmoothing(trend=None, seasonal=None)`

| Setting | Value |
|---|---|
| SKUs modelled | 300 — highest revenue with ≥ 26 active weeks |
| Training window | 2009-11-30 → 2011-09-05 (93 weeks) |
| Holdout window | 2011-09-12 → 2011-12-05 (13 weeks) |
| One model per | SKU, fitted independently |
| Initialisation | `estimated` |
| Convergence | 300 / 300 |

### Fitted parameters

`smoothing_level_alpha` is how much weight the model gives the most recent week. Low alpha
means a stable series the model can average over; high alpha means it must chase the
latest value because the past is not informative.

| Statistic | Alpha |
|---|---|
| Median | 0.178 |
| Mean | 0.227 |
| Interquartile range | 0.060 – 0.337 |
| Below 0.1 | 106 SKUs |
| Above 0.5 | 33 SKUs |

### Accuracy, against baselines

| Method | Median MAE (units/week) |
|---|---|
| Naive — next week = this week | 79.58 |
| Training-period mean | 75.29 |
| **Exponential smoothing** | **73.04** |

Beats naive on **156 of 300 SKUs (52.0%)**; median improvement where it wins, 16.4%.

### The result worth reading twice

Grouping the fitted parameters by the ABC/XYZ class the SKU was assigned *independently*,
before any forecasting was done:

| Class | SKUs | Median alpha | Share beating naive |
|---|---|---|---|
| AX | 42 | 0.098 | 61.9% |
| AY | 171 | 0.170 | 55.6% |
| AZ | 87 | 0.288 | 40.2% |

Alpha rises and forecastability falls, monotonically, across the volatility axis. The XYZ
classification predicted which SKUs would be forecastable **before any model was fitted**,
and the fitted parameters confirm it by a completely separate route. That is not a
coincidence; it is the same underlying property measured twice, and it is the strongest
internal validation in the project.

**Limitations**
- No trend or seasonal component. Tested and rejected: with 93 weekly observations, seasonal Holt-Winters overfits on most of these series. Seasonality is handled at the catalogue level (objective 10) rather than per SKU.
- Only the top 300 SKUs by revenue. For the remaining ~4,400, forecasting is not attempted — and that omission is a finding, not a gap.
- A 13-week holdout covering September–December means the test period contains the November peak. That is the hardest possible test, and the accuracy figures should be read with that in mind.

---

## Model 3 — Inventory policy

**Type:** deterministic formula, validated by simulation
**Objective:** 7

```
reorder point = weekly_demand × lead_time + z × forecast_error × √lead_time
```

| Term | Source |
|---|---|
| `weekly_demand` | Mean units/week over the 93 training weeks |
| `forecast_error` | MAE of that SKU's model on held-out weeks — not raw variance |
| `z` | 1.28 (90%), 1.65 (95%), 2.33 (99%) |
| `lead_time` | 1–4 weeks. **Not in the source data**, so treated as a variable, never assumed |

Safety stock scales with **√lead_time**, so doubling lead time does not double the reorder
point. Buyers routinely over-correct for long lead times; the sensitivity table shows by
how much.

### Validation by simulation

Policy derived from training weeks only, then replayed against 13 weeks of real held-out
demand across 300 SKUs, at a 2-week lead time and 95% service level.

| Policy | Stockout weeks | SKUs with any stockout | Mean stock held |
|---|---|---|---|
| Derived (ABC/XYZ + forecast error) | 419 | 166 | 378.0 |
| Uniform 4-week cover | 415 | 129 | 562.7 |

**Reading it accurately:** service is essentially unchanged — one percent worse, not
better — while holding **32.8% less stock**. The result is the same service level with a
third less capital tied up, and overstating it as "fewer stockouts" would be wrong.

**Limitations**
- **No stock-on-hand data exists.** Reorder points are derived from demand and its variability rather than observed against real inventory. Retailers publish transactions, not stock positions. The simulation tests the policy's logic honestly; it cannot check it against the retailer's warehouse.
- Lead time is a user input, not a measurement.
- The simulation assumes a single outstanding order per SKU and instantaneous ordering.

---

## Not models

Recorded here so nothing in this project is described as more than it is:

- **ABC/XYZ classification** — a deterministic rule applied to cumulative revenue share and coefficient of variation. Nothing is learned; the classes are defined, not discovered.
- **Pull-through test** — a Wilcoxon signed-rank hypothesis test on 85 SKU–partner pairs (median drop 52.6%, p = 3.25 × 10⁻⁸). A statistical test, not a model.

---

## Reproducibility

All three artifacts regenerate from `data/processed/` with no access to the raw file:

```
python src/export_models.py
```

Figures reproduce those in `notebooks/04_modeling.ipynb` because the settings are pinned
identically at the top of that script.
