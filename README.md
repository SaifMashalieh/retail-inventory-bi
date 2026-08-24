# Retail Sales Analysis for Inventory Management

**Discovering purchase patterns and improving replenishment decisions**

Graduation Project — Course 307498, Department of Business Intelligence and Data
Analytics, University of Petra. First Semester, 2025/2026.

**Authors:** Saif Mashalieh (202210039) · Mohammad Marei (202210644)  
**Supervised by:** Dr. Wasef Matar

---

## What this project does

Retailers order product by product, as though demand for each item were independent, and apply
one stock-cover rule across a catalogue whose items differ enormously in both value and
volatility. This project measures what that costs, using two years of transaction records from a
UK gift-ware wholesaler — then turns the measurement into a replenishment recommendation a buyer
can act on.

| Finding | Evidence |
|---|---|
| **A stockout costs roughly double what it appears to.** When a product is absent, its strongest co-purchase partners lose a median **52.6%** of their weekly sales. | 85 sku-partner pairs, effect in 78.8%, Wilcoxon signed-rank *p* = 3.25 × 10⁻⁸ |
| **The same service level is achievable on 33% less stock.** A policy built from ABC/XYZ class and measured forecast error, replayed against held-out demand. | 419 stockout weeks vs 415 for uniform 4-week cover; 378 units mean stock vs 562.7 |
| **Half the catalogue earns a twentieth of the money.** 2,379 SKUs (50.4%) sit in the CZ cell and produce 4.8% of revenue. | 21.8% of SKUs generate 80% of revenue |

---

## 📄 [Full project documentation → `docs/documentation.md`](docs/documentation.md)

### Table of Content

- [**Glossary of Terms and Abbreviations**](docs/documentation.md#glossary-of-terms-and-abbreviations)
- [**Abstract**](docs/documentation.md#abstract)
- [**Acknowledgment**](docs/documentation.md#acknowledgment)
- [**Business Intelligence Project Description and Objectives**](docs/documentation.md#business-intelligence-project-description-and-objectives)
- [**Data Research and Acquiring Effort**](docs/documentation.md#data-research-and-acquiring-effort)
- [**Data Description and Understanding**](docs/documentation.md#data-description-and-understanding)
- [**Data Primary Cleaning and Transformation**](docs/documentation.md#data-primary-cleaning-and-transformation)
- [**Data Visualization and Insights**](docs/documentation.md#data-visualization-and-insights)
- [**Dashboard Design & Business Insights**](docs/documentation.md#dashboard-design--business-insights)
- [**Advanced Analytics and AI Modeling**](docs/documentation.md#advanced-analytics-and-ai-modeling)
- [**Tools Research and Selection Effort**](docs/documentation.md#tools-research-and-selection-effort)
- [**Project Deployment Effort – Use Case**](docs/documentation.md#project-deployment-effort--use-case)
- [**Results**](docs/documentation.md#results)
- [**References**](docs/documentation.md#references)
- [**Appendix A — Objective Traceability**](docs/documentation.md#appendix-a--objective-traceability)
- [**Appendix B — Source Code**](docs/documentation.md#appendix-b--source-code)

Supporting documents: [model card](models/MODEL_CARD.md) — what each model does and where it
should not be trusted · [how to obtain the data](GET_THE_DATA.md)

---

## Data

[Online Retail II](https://archive.ics.uci.edu/dataset/502/online+retail+ii), UCI Machine
Learning Repository — 1,067,371 transactions, December 2009 to December 2011, CC BY 4.0.

> Chen, D. (2012). *Online Retail II* [Data set]. UCI Machine Learning Repository.
> https://doi.org/10.24432/C5CG6D

The raw workbook is **not committed** — download it yourself, see
[`GET_THE_DATA.md`](GET_THE_DATA.md). Cleaning removes 52,620 lines (4.9%) through eight
logged decisions that reconcile exactly: 1,067,371 raw → **1,014,751 clean**, **4,724 SKUs**,
**104 weeks**.

**A note on the committed data.** Three large intermediates are regenerated rather than
committed — `transactions_clean.csv` (169 MB, past GitHub's file-size limit), `baskets.csv`,
and `dashboard/fact_weekly_demand.csv`. The remaining processed tables **are** committed
deliberately: the deployed Streamlit application reads six of them at runtime, so excluding
them would publish an app that cannot start.

---

## Code setup and dependencies

```bash
# 1. clone
git clone https://github.com/SaifMashalieh/retail-inventory-bi.git
cd retail-inventory-bi

# 2. environment
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 3. data — download online_retail_II.xlsx into data/raw/  (see GET_THE_DATA.md)
python src/check_data.py               # verify the download matches the schema

# 4. pipeline
python src/build_dataset.py            # raw  → cleaned analytical tables
python src/build_dashboard_tables.py   # clean → 12 flat tables for Power BI
python src/export_models.py            # write model artefacts + model card

# 5. application
streamlit run src/streamlit_app.py
```

Then run the notebooks in order — `01_eda` → `02_cleaning` → `03_visualization`
→ `04_modeling`. Every figure and every number quoted in the documentation is regenerated
by them.

---

## Project structure

```
├── README.md                  this file
├── LICENSE                    MIT (dataset separately CC BY 4.0)
├── requirements.txt
├── docs/
│   └── documentation.md       the full project write-up
├── data/
│   ├── raw/                   online_retail_II.xlsx (download, not committed)
│   └── processed/             cleaned tables + model outputs
│       └── dashboard/         12 flat tables for Power BI
├── notebooks/
│   ├── 01_eda.ipynb           feasibility checks on the raw file
│   ├── 02_cleaning.ipynb      eight decisions, with a reconciling ledger
│   ├── 03_visualization.ipynb 13 charts and the ABC/XYZ profile
│   └── 04_modeling.ipynb      association rules, pull-through, forecasting, policy
├── src/
│   ├── check_data.py             verifies the raw workbook
│   ├── build_dataset.py          script twin of notebook 02
│   ├── build_dashboard_tables.py flattens results for Power BI
│   ├── export_models.py          writes the model artefacts
│   └── streamlit_app.py          the deployed prototype
├── models/                    MODEL_CARD.md + fitted model artefacts
├── dashboards/                retail_inventory.pbix + page screenshots
├── images/                    18 report charts + 4 application screenshots
└── .streamlit/config.toml     pinned theme for the deployed app
```

---

## Method in brief

**Association rules** — FP-Growth over invoice-level baskets, top 250 SKUs by basket frequency,
minimum support 1.5%. 480 pairwise rules, 272 at lift ≥ 5. FP-Growth rather than Apriori because
~4,700 SKUs make candidate generation the bottleneck; ranked by lift rather than confidence
because confidence is inflated by popularity.

**Pull-through test** — for each absence episode (a SKU that sold regularly, stopped for 3+ weeks,
then resumed), its strongest partners' sales during the gap are compared against those same
partners' sales in the four weeks either side. Requiring resumption separates a stockout from a
discontinued line; comparing against adjacent weeks differences out seasonality.

**Classification** — ABC on revenue, XYZ on the coefficient of variation of weekly demand,
measured across all 104 weeks. Two axes rather than one because volume and volatility turn out to
be near-independent.

**Forecasting** — Holt-Winters on the 300 highest-revenue SKUs with 26+ active weeks, evaluated
on 13 held-out weeks against naive and moving-average baselines. It beats naive on 156 of 300
(52%) — which is itself the finding: forecasting pays for the stable high-volume SKUs and not for
the rest.

**Inventory policy** — `ROP = d̄ × L + z × σₑ × √L`. Lead time is not assumed; it is reported as a
sensitivity across 1–4 weeks. The policy is derived from 93 training weeks and replayed against
13 held-out weeks.

---

## Limitation

There is no stock-on-hand data. Reorder points are derived from demand and its variability rather
than validated against real inventory positions — retailers publish transactions, not stock
levels. The simulation tests the policy's logic against demand it was never fitted to, which is
the strongest validation available from public data, but it cannot confirm the reorder points
against a real warehouse.
