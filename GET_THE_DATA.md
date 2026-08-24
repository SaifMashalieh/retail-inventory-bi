# Getting the Data

## Online Retail II → `data/raw/uci/`

Every transaction of a UK-based online gift-ware retailer, **1 December 2009 to 9 December
2011**. Many of its customers are wholesalers, so basket sizes are large and reorder behaviour
is visible — which is exactly what an inventory project needs.

**Page:** https://archive.ics.uci.edu/dataset/502/online+retail+ii

**Direct download (43.5 MB zip):**

```
https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip
```

Unzip it and put `online_retail_II.xlsx` into `data/raw/uci/`.

> The file is `.xlsx` with **two sheets** — one per year. Both are needed; the pipeline reads
> and concatenates them. `openpyxl` in `requirements.txt` handles the format.

---

## Why this dataset fits the problem statement

The project needs four things at once. Most retail datasets have two or three.

| Requirement | Field | Why it matters |
|---|---|---|
| **Basket structure** | `Invoice` | Multiple SKUs share an invoice number, so genuine co-purchase can be mined. Without this, association rules are impossible |
| **SKU identity** | `StockCode` | ~4,000 distinct products — enough for meaningful ABC/XYZ classification |
| **Demand over time** | `InvoiceDate` | Two full years, so seasonality is measurable and forecasting is real rather than extrapolated from a few weeks |
| **Value** | `Quantity` × `Price` | Turns units into revenue, which is what ABC classification and the cost of a stockout are measured in |

**1,067,371 rows** — large enough that no one questions the scale, small enough to run on a
laptop.

## Columns

| Column | Meaning |
|---|---|
| `Invoice` | Transaction number. **A leading `C` means the invoice is a cancellation** |
| `StockCode` | Product code — the SKU |
| `Description` | Product name |
| `Quantity` | Units on that line. **Can be negative** — returns |
| `InvoiceDate` | Date and time of the transaction |
| `Price` | Unit price in pounds sterling |
| `Customer ID` | Customer number. **Missing on a substantial share of rows** |
| `Country` | Customer's country |

## Known issues, already visible from the documentation

These are cleaning decisions for report section 7, not surprises:

- **Cancellations** are flagged by a `C` prefix on the invoice. They must be handled
  deliberately — a cancelled sale is not demand, but it *is* evidence about returns
- **Negative quantities** appear on returns
- **Missing `Customer ID`** on many rows. Fine for basket and inventory analysis, which work
  at invoice and SKU level, but it rules out customer-level analysis
- **Non-product stock codes** exist — postage, manual adjustments, bank charges. These are not
  SKUs and would corrupt any inventory calculation if left in

**Licence:** CC BY 4.0 — attribution required.
**Citation:** Chen, D. (2012). *Online Retail II* [Dataset]. UCI Machine Learning Repository.
https://doi.org/10.24432/C5CG6D

---

## Then verify, before anything is built

```
python src/check_data.py
```

Paste the output back. It reports the real structure — basket sizes, SKU counts, the
cancellation rate, negative quantities, date coverage and the non-product codes — so the
pipeline is designed around what is actually there.
