# MES Performance Reporting — KPI Definitions

**Scope:** Provincial Medical Equipment & Supplies (MES) portfolio, all vendors and regions
**Version:** 1.0 · **Owner:** MES Analytics · **Implemented in:** `src/03_build_kpis.py`

Every figure in the dashboard and in governance reporting uses these definitions. If a number
cannot be produced under these rules, it is reported as unavailable, not estimated.

## General rules

| Rule | Definition |
|---|---|
| **D0 · Unit and period** | The unit of measure is the **order line** (one SKU on one order). Lines are reported in the month of the **order date**, so a late delivery counts against the month the patient needed it. |
| **Data source precedence** | Ordered quantities and dates come from the ordering system. Delivery quantities and dates come from vendor delivery confirmations. Spend comes from accounts payable invoices, after duplicates are removed (Step 2). |
| **Unconfirmed lines** | Lines with no delivery confirmation are **excluded** from delivery KPIs (D1–D4) and reported separately as a data-quality exception. They are never counted as on time. |
| **Ratios** | Always computed as a **ratio of sums** (total on-time lines ÷ total confirmed lines), never as an average of monthly or regional percentages. |
| **Low volume** | Vendor × region × month cells with **fewer than 30 confirmed lines** receive no Red/Amber/Green status, because one late delivery can move the rate by several points. |

## Delivery and supply KPIs

| KPI | Formula | Target | Status |
|---|---|---|---|
| **D1 · On-time delivery** | Lines whose **first shipment** arrived within the region's SLA window ÷ confirmed lines. A line with nothing on its first shipment is **late**. SLA window: 2 days in Toronto, Central, East and West; 3 days in North East; 4 days in North West (calendar days from order date). | ≥ 95% | Green ≥ 95% · Amber 92–95% · Red < 92% |
| **D2 · First-shipment fill rate** | Units shipped on the first shipment ÷ units ordered (confirmed lines). | ≥ 98% | Green ≥ 98% · Amber 95–98% · Red < 95% |
| **D3 · Backorder rate** | Confirmed lines with any backordered units ÷ confirmed lines. | Monitor | n/a |
| **D4 · Days to complete** | Average days from order date until the last unit arrived (includes backorder fills). | Monitor | n/a |
| **Stockout month** | A SKU-month where more than 20% of lines were backordered, with at least 10 lines that month. | n/a | n/a |
| **Recurring stockout** | A SKU with **2 or more stockout months in the trailing 12 months.** The flag triggers a supply-risk review with the vendor. | n/a | Flag |

## Formulary and financial KPIs

| KPI | Formula | Notes |
|---|---|---|
| **D5 · Off-formulary share** | Lines for SKUs not on the MES formulary ÷ all lines ordered. | Uses all lines, including unconfirmed ones; compliance is about what was ordered. |
| **D6 · Valid spend** | Sum of primary invoice amounts. Duplicate invoices are excluded. | Spend is assigned to the order month (not the invoice month), so it lines up with utilization. |
| **D7 · Exception exposure** | Dollars at risk from reconciliation exceptions: duplicate invoices, billing without proof of delivery, quantity overbilling, and price above contract (> 0.5% tolerance). | See `data/clean/exceptions.csv` for the line-level work queue. |
| **Exceptions per 1,000 lines** | Order lines with at least one exception ÷ lines ordered × 1,000. | Compare vendors on this **rate**, not on raw counts; large vendors have more exceptions simply because they handle more volume. |

## Known limitations

- Transit time is measured in calendar days. Business-day SLAs would need a statutory holiday calendar.
- On-time delivery is judged on the first shipment only. A vendor that ships 1 of 10 units on time still passes D1, which is why D1 must be read alongside D2 (fill rate).
- The data is synthetic (see `src/01_generate_data.py`). The methods carry over to real data; the results do not.
