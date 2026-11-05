# =============================================================================
# 03_build_kpis.py
# Ontario MES Vendor Performance & Formulary Analytics
# STEP 3 — Standardized KPI definitions, line-level flags, scorecard tables
# =============================================================================
#
# WHY THIS STEP MATTERS
#   "On-time delivery" sounds obvious until two regions calculate it two ways
#   and report different numbers for the same vendor. The posting's first duty
#   is to "establish and maintain standardized provincial methodologies,
#   definitions, data sources and reporting processes". So every KPI below has
#   ONE written rule (see docs/kpi_definitions.md), coded exactly once here.
#
# INPUTS   data/clean/fact_order_lines_matched.csv   (from Step 2)
#          data/clean/exceptions.csv                 (from Step 2)
#          data/raw/dim_*.csv
#
# OUTPUTS  data/clean/fact_order_lines_kpi.csv        line-level table + KPI flags
#                                                     (the main Power BI fact table)
#          data/model/kpi_vendor_region_month.csv    scorecard grain: vendor x region x month
#          data/model/sku_month_backorders.csv       stockout monitoring by SKU x month
#
# RUN (from the project root):   python src/03_build_kpis.py
# =============================================================================

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW, CLEAN, MODEL = ROOT / "data" / "raw", ROOT / "data" / "clean", ROOT / "data" / "model"
MODEL.mkdir(parents=True, exist_ok=True)

# -----------------------------------------------------------------------------
# 0. BUSINESS RULES (all in one place, so they're easy to review and change)
# -----------------------------------------------------------------------------
ON_TIME_TARGET = 0.95          # contract SLA
FILL_RATE_TARGET = 0.98        # contract SLA
AMBER_BAND = 0.03              # within 3 pts below target = Amber; further below = Red
MIN_LINES_FOR_RAG = 30         # fewer lines than this -> "Low volume", no RAG colour
STOCKOUT_LINE_RATE = 0.20      # SKU-month with >20% of lines backordered = stockout month
STOCKOUT_MIN_LINES = 10        # ...only judged if the SKU had at least 10 lines that month
RECURRING_STOCKOUT_MONTHS = 2  # >=2 stockout months in the trailing 12 = recurring

# -----------------------------------------------------------------------------
# 1. LOAD
# -----------------------------------------------------------------------------
m = pd.read_csv(CLEAN / "fact_order_lines_matched.csv",
                parse_dates=["order_date", "initial_delivery_date", "backorder_delivery_date", "invoice_date"])
exceptions = pd.read_csv(CLEAN / "exceptions.csv")
products = pd.read_csv(RAW / "dim_products.csv")
regions = pd.read_csv(RAW / "dim_regions.csv")

# Attach the attributes the KPIs need: SLA window per region, formulary status per SKU
m = m.merge(regions[["region_id", "sla_days"]], on="region_id", how="left")
m = m.merge(products[["sku", "on_formulary"]], on="sku", how="left")

# Reporting period = month of ORDER date (definition D0). A late delivery counts
# against the month the patient needed it, not the month it eventually arrived.
m["order_month"] = m["order_date"].dt.to_period("M").dt.to_timestamp()

confirmed = m["has_delivery_confirmation"]   # KPIs D1-D4 use confirmed lines only


# -----------------------------------------------------------------------------
# 2. LINE-LEVEL KPI FLAGS
# -----------------------------------------------------------------------------
# D1. ON-TIME DELIVERY
#   A line is on time if its FIRST shipment arrived within the region's SLA
#   window (calendar days from order date). If nothing shipped on the first
#   shipment, the line is late: the patient received nothing on time.
#   Lines with no delivery confirmation are excluded (unknown), not counted as on time.
m["days_to_first_delivery"] = (m["initial_delivery_date"] - m["order_date"]).dt.days
m["on_time_flag"] = np.where(
    ~confirmed, np.nan,                                            # unknown -> excluded
    ((m["qty_shipped_initial"] > 0) & (m["days_to_first_delivery"] <= m["sla_days"])).astype(float),
)

# D2. FIRST-SHIPMENT UNIT FILL RATE  (computed at aggregate level as a ratio of sums)
#   = units shipped on first shipment / units ordered, confirmed lines only.
#   Store both parts so Power BI can aggregate correctly (never average a ratio).
m["fill_units_shipped"] = np.where(confirmed, m["qty_shipped_initial"], np.nan)
m["fill_units_ordered"] = np.where(confirmed, m["qty_ordered"], np.nan)

# D3. BACKORDER FLAG — line had any units backordered
m["backorder_flag"] = np.where(confirmed, (m["qty_backordered"] > 0).astype(float), np.nan)

# D4. DAYS TO COMPLETE — order date to the date the LAST unit arrived
final_date = m["backorder_delivery_date"].where(m["qty_backordered"] > 0, m["initial_delivery_date"])
m["days_to_complete"] = (final_date - m["order_date"]).dt.days

# D5. OFF-FORMULARY FLAG — all lines (formulary compliance doesn't need a delivery)
m["off_formulary_flag"] = (~m["on_formulary"]).astype(int)

# D6. VALID SPEND = primary invoice amount (Step 2 already removed duplicate invoices)
m["valid_invoiced_amount"] = m["invoice_amount"].fillna(0)

# D7. EXCEPTION EXPOSURE — dollars at risk from Step 2, summed per line
m["exception_exposure"] = m["order_line_id"].map(
    exceptions.groupby("order_line_id")["dollar_exposure"].sum()).fillna(0)


# -----------------------------------------------------------------------------
# 3. SCORECARD TABLE: vendor x region x month
# -----------------------------------------------------------------------------
def rag(value, target, n_lines):
    """Red / Amber / Green status against target, with a low-volume guard."""
    if n_lines < MIN_LINES_FOR_RAG or pd.isna(value):
        return "Low volume"
    if value >= target:
        return "Green"
    if value >= target - AMBER_BAND:
        return "Amber"
    return "Red"


g = m.groupby(["vendor_id", "region_id", "order_month"])
score = pd.DataFrame({
    "lines_ordered": g.size(),
    "lines_confirmed": g["has_delivery_confirmation"].sum(),
    "lines_on_time": g["on_time_flag"].sum(),
    "units_ordered_confirmed": g["fill_units_ordered"].sum(),
    "units_shipped_first": g["fill_units_shipped"].sum(),
    "lines_backordered": g["backorder_flag"].sum(),
    "avg_days_to_complete": g["days_to_complete"].mean().round(2),
    "lines_off_formulary": g["off_formulary_flag"].sum(),
    "valid_spend": g["valid_invoiced_amount"].sum().round(2),
    "exception_lines": g["has_exception"].sum(),
    "exception_exposure": g["exception_exposure"].sum().round(2),
}).reset_index()

# Ratios are computed from the summed parts (ratio of sums, not average of ratios)
score["on_time_rate"] = (score["lines_on_time"] / score["lines_confirmed"]).round(4)
score["fill_rate"] = (score["units_shipped_first"] / score["units_ordered_confirmed"]).round(4)
score["backorder_rate"] = (score["lines_backordered"] / score["lines_confirmed"]).round(4)
score["off_formulary_share"] = (score["lines_off_formulary"] / score["lines_ordered"]).round(4)
score["exceptions_per_1000"] = (score["exception_lines"] / score["lines_ordered"] * 1000).round(1)
score["on_time_status"] = [rag(v, ON_TIME_TARGET, n) for v, n in zip(score["on_time_rate"], score["lines_confirmed"])]
score["fill_rate_status"] = [rag(v, FILL_RATE_TARGET, n) for v, n in zip(score["fill_rate"], score["lines_confirmed"])]


# -----------------------------------------------------------------------------
# 4. STOCKOUT MONITORING: SKU x month
# -----------------------------------------------------------------------------
sku_month = (m[confirmed].groupby(["sku", "order_month"])
             .agg(lines=("order_line_id", "size"), lines_backordered=("backorder_flag", "sum"))
             .reset_index())
sku_month["backorder_rate"] = (sku_month["lines_backordered"] / sku_month["lines"]).round(4)
sku_month["stockout_month"] = ((sku_month["lines"] >= STOCKOUT_MIN_LINES)
                               & (sku_month["backorder_rate"] > STOCKOUT_LINE_RATE)).astype(int)

# Recurring flag: rolling count of stockout months over the trailing 12 months.
# Reindex every SKU to the full month calendar first, so "12 rows" really means 12 months.
all_months = pd.date_range(m["order_month"].min(), m["order_month"].max(), freq="MS")
full_index = pd.MultiIndex.from_product([sku_month["sku"].unique(), all_months], names=["sku", "order_month"])
sku_month = sku_month.set_index(["sku", "order_month"]).reindex(full_index).reset_index()
sku_month[["lines", "lines_backordered", "stockout_month"]] = (
    sku_month[["lines", "lines_backordered", "stockout_month"]].fillna(0).astype(int))
sku_month["stockout_months_trailing_12"] = (sku_month.groupby("sku")["stockout_month"]
                                            .transform(lambda s: s.rolling(12, min_periods=1).sum()).astype(int))
sku_month["recurring_stockout_flag"] = (sku_month["stockout_months_trailing_12"] >= RECURRING_STOCKOUT_MONTHS).astype(int)
sku_month = sku_month.merge(products[["sku", "product_name", "category"]], on="sku", how="left")


# -----------------------------------------------------------------------------
# 5. SAVE
# -----------------------------------------------------------------------------
kpi_cols = ["order_line_id", "order_id", "order_date", "order_month", "region_id", "patient_ref",
            "sku", "category", "vendor_id", "on_formulary", "qty_ordered", "contract_unit_price",
            "has_delivery_confirmation", "qty_shipped_initial", "qty_backordered",
            "initial_delivery_date", "backorder_delivery_date", "sla_days",
            "days_to_first_delivery", "on_time_flag", "fill_units_shipped", "fill_units_ordered",
            "backorder_flag", "days_to_complete", "off_formulary_flag",
            "has_invoice", "invoice_id", "valid_invoiced_amount",
            "has_exception", "exception_count", "exception_exposure"]
m[kpi_cols].to_csv(CLEAN / "fact_order_lines_kpi.csv", index=False, date_format="%Y-%m-%d")
score.to_csv(MODEL / "kpi_vendor_region_month.csv", index=False, date_format="%Y-%m-%d")
sku_month.to_csv(MODEL / "sku_month_backorders.csv", index=False, date_format="%Y-%m-%d")


# -----------------------------------------------------------------------------
# 6. REPORT — headline results
# -----------------------------------------------------------------------------
pd.set_option("display.width", 140)


def ratio(df, num, den):
    return df[num].sum() / df[den].sum()


print("PROVINCIAL KPIs, last 12 months (Nov 2025 - Oct 2026)")
last12 = score[score["order_month"] >= "2025-11-01"]
print(f"  On-time delivery      {ratio(last12, 'lines_on_time', 'lines_confirmed'):.1%}   (target {ON_TIME_TARGET:.0%})")
print(f"  First-shipment fill   {ratio(last12, 'units_shipped_first', 'units_ordered_confirmed'):.1%}   (target {FILL_RATE_TARGET:.0%})")
print(f"  Backorder rate        {ratio(last12, 'lines_backordered', 'lines_confirmed'):.1%}")
print(f"  Off-formulary share   {ratio(last12, 'lines_off_formulary', 'lines_ordered'):.1%}")
print(f"  Valid spend           ${last12['valid_spend'].sum():,.0f}")
print(f"  Exception exposure    ${last12['exception_exposure'].sum():,.0f}")

print("\nVENDOR SCORECARD - on-time rate, last 6 months (May - Oct 2026)")
last6 = score[score["order_month"] >= "2026-05-01"]
vs = last6.groupby("vendor_id").agg(lines=("lines_confirmed", "sum"), on_time=("lines_on_time", "sum"),
                                    shipped=("units_shipped_first", "sum"), ordered=("units_ordered_confirmed", "sum"))
vs["on_time_rate"] = vs["on_time"] / vs["lines"]
vs["fill_rate"] = vs["shipped"] / vs["ordered"]
vs["on_time_status"] = [rag(v, ON_TIME_TARGET, n) for v, n in zip(vs["on_time_rate"], vs["lines"])]
print(vs[["lines", "on_time_rate", "on_time_status", "fill_rate"]].round(3).to_string())

print("\nV01 on-time rate by region, last 6 months  -> is the problem everywhere or local?")
v01 = last6[last6["vendor_id"] == "V01"].groupby("region_id")[["lines_on_time", "lines_confirmed"]].sum()
v01["on_time_rate"] = (v01["lines_on_time"] / v01["lines_confirmed"]).round(3)
v01["status"] = [rag(v, ON_TIME_TARGET, n) for v, n in zip(v01["on_time_rate"], v01["lines_confirmed"])]
print(v01.to_string())

print("\nRECURRING STOCKOUTS (flagged at any point in the period)")
rec = sku_month[sku_month["stockout_month"] == 1].groupby(["sku", "product_name"]).agg(
    stockout_months=("order_month", lambda s: ", ".join(s.dt.strftime("%b %Y"))))
rec = rec[rec.index.get_level_values("sku").isin(sku_month.loc[sku_month["recurring_stockout_flag"] == 1, "sku"])]
print(rec.to_string() if len(rec) else "  none")

print("\nOFF-FORMULARY SHARE by region, last quarter (Aug - Oct 2026)")
lq = score[score["order_month"] >= "2026-08-01"].groupby("region_id")[["lines_off_formulary", "lines_ordered"]].sum()
print((lq["lines_off_formulary"] / lq["lines_ordered"]).round(3).sort_values(ascending=False).to_string())

status_counts = score["on_time_status"].value_counts()
print(f"\nScorecard cells (vendor x region x month): {len(score):,}  |  on-time status: {status_counts.to_dict()}")
