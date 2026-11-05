# =============================================================================
# 02_reconcile.py
# Ontario MES Vendor Performance & Formulary Analytics
# STEP 2 — Reconcile the three source systems and build an exception report
# =============================================================================
#
# THE PROBLEM
#   Orders, vendor delivery confirmations and invoices come from three different
#   systems. Before ANY KPI can be trusted, they must be matched line by line.
#   This is the posting's duty: "Collect, integrate data from multiple sources,
#   validate, analyze, reconcile discrepancies to ensure reporting is accurate."
#
# THE CHECKS (each one becomes rows in exceptions.csv)
#   0. Integrity     – broken keys, orphans, vendor mismatches between systems
#   1. DUPLICATE_INVOICE                       – same order line billed twice
#   2. INVOICED_WITHOUT_DELIVERY_CONFIRMATION  – billed, but no proof it arrived
#      NO_DELIVERY_CONFIRMATION                – not billed, and no proof it arrived
#   3. NOT_YET_INVOICED                        – delivered but not billed (accrual)
#   4. QTY_OVERBILLED / QTY_UNDERBILLED        – invoice qty != delivered qty
#   5. PRICE_ABOVE_CONTRACT                    – unit price > contract price
#
#   Every exception carries a dollar exposure, so management sees money at risk,
#   not just a count.
#
# OUTPUTS (data/clean/)
#   fact_order_lines_matched.csv  – one row per order line, all 3 systems joined
#                                   (this feeds Step 3 KPIs and the Power BI model)
#   exceptions.csv                – one row per exception (the work queue)
#   exception_summary.csv         – exceptions by check x vendor
#
# RUN (from the project root):   python src/02_reconcile.py
# =============================================================================

import json
from pathlib import Path

import numpy as np
import pandas as pd

# -----------------------------------------------------------------------------
# 0. SETTINGS AND LOADING
# -----------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
CLEAN = ROOT / "data" / "clean"
CLEAN.mkdir(parents=True, exist_ok=True)

# Price tolerance: invoices within 0.5% of contract price are accepted
# (covers rounding). Anything above is an exception. This is a business rule,
# so it lives at the top where a manager can see and change it.
PRICE_TOLERANCE = 0.005

orders = pd.read_csv(RAW / "fact_order_lines.csv", parse_dates=["order_date"])
deliv = pd.read_csv(RAW / "fact_deliveries.csv",
                    parse_dates=["initial_delivery_date", "backorder_delivery_date"])
inv = pd.read_csv(RAW / "fact_invoices.csv", parse_dates=["invoice_date"])
products = pd.read_csv(RAW / "dim_products.csv")
vendors = pd.read_csv(RAW / "dim_vendors.csv")
regions = pd.read_csv(RAW / "dim_regions.csv")

print(f"Loaded: {len(orders):,} order lines | {len(deliv):,} deliveries | {len(inv):,} invoices\n")

# All exceptions are collected here as small DataFrames, then stacked at the end.
exception_frames = []


def add_exceptions(df, check, severity, detail, exposure):
    """Append exceptions in one standard layout.

    df        : rows that failed the check (must have order_line_id, vendor_id)
    check     : short code for the check
    severity  : High / Medium / Low
    detail    : human-readable explanation (array or scalar)
    exposure  : dollars at risk (array or scalar)
    """
    if len(df) == 0:
        return
    exception_frames.append(pd.DataFrame({
        "check": check,
        "severity": severity,
        "order_line_id": df["order_line_id"].values,
        "vendor_id": df["vendor_id"].values,
        "invoice_id": df["invoice_id"].values if "invoice_id" in df else None,
        "detail": detail,
        "dollar_exposure": np.round(exposure, 2),
    }))


# -----------------------------------------------------------------------------
# CHECK 0. INTEGRITY — are the keys sound before we join anything?
# -----------------------------------------------------------------------------
# If any of these fail, joins silently drop or duplicate rows and every KPI
# downstream is wrong. So we test them first and print a pass/fail table.
order_ids = set(orders["order_line_id"])
vendor_of_line = orders.set_index("order_line_id")["vendor_id"]

integrity = {
    "Duplicate order_line_id in orders":       orders["order_line_id"].duplicated().sum(),
    "Duplicate order_line_id in deliveries":   deliv["order_line_id"].duplicated().sum(),
    "Unknown SKU in orders":                   (~orders["sku"].isin(products["sku"])).sum(),
    "Unknown vendor in orders":                (~orders["vendor_id"].isin(vendors["vendor_id"])).sum(),
    "Unknown region in orders":                (~orders["region_id"].isin(regions["region_id"])).sum(),
    "Orphan deliveries (no matching order)":   (~deliv["order_line_id"].isin(order_ids)).sum(),
    "Orphan invoices (no matching order)":     (~inv["order_line_id"].isin(order_ids)).sum(),
    "Delivery vendor != order vendor":         (deliv["vendor_id"].values
                                                != vendor_of_line.reindex(deliv["order_line_id"]).values).sum(),
    "Invoice vendor != order vendor":          (inv["vendor_id"].values
                                                != vendor_of_line.reindex(inv["order_line_id"]).values).sum(),
}
print("CHECK 0 - Integrity")
for name, count in integrity.items():
    print(f"  {'PASS' if count == 0 else 'FAIL':<5} {name:<42} {count:>6,}")
print()


# -----------------------------------------------------------------------------
# CHECK 1. DUPLICATE INVOICES
# -----------------------------------------------------------------------------
# Rule: an order line should be billed exactly once. The EARLIEST invoice is
# treated as the valid one; any later invoice for the same line is a duplicate.
inv = inv.sort_values(["invoice_date", "invoice_id"]).reset_index(drop=True)
inv["first_invoice_id"] = inv.groupby("order_line_id")["invoice_id"].transform("first")
is_dup = inv["order_line_id"].duplicated(keep="first")

dups = inv[is_dup]
add_exceptions(dups, "DUPLICATE_INVOICE", "High",
               detail=("Duplicate of " + dups["first_invoice_id"]).values,
               exposure=dups["invoice_amount"].values)       # full amount would be overpaid

inv_primary = inv[~is_dup].drop(columns="first_invoice_id")   # one valid invoice per line


# -----------------------------------------------------------------------------
# BUILD THE MATCHED TABLE: orders + deliveries + primary invoice
# -----------------------------------------------------------------------------
# Left joins from ORDERS, so every order line survives even if a delivery or
# invoice is missing. indicator=True tells us which side was missing.
m = orders.merge(deliv.drop(columns="vendor_id"), on="order_line_id", how="left", indicator="_deliv")
m["has_delivery_confirmation"] = m["_deliv"] == "both"
m = m.drop(columns="_deliv")

m = m.merge(inv_primary.drop(columns="vendor_id"), on="order_line_id", how="left", indicator="_inv")
m["has_invoice"] = m["_inv"] == "both"
m = m.drop(columns="_inv")

# Total units the vendor confirms delivering (first shipment + backorder fill)
m["qty_delivered_total"] = m["qty_shipped_initial"] + m["qty_backordered"]


# -----------------------------------------------------------------------------
# CHECK 2. MISSING DELIVERY CONFIRMATIONS
# -----------------------------------------------------------------------------
# Billed with no proof of delivery is the high-risk case: payment should be
# held until the vendor provides proof of delivery (POD).
no_pod = m[~m["has_delivery_confirmation"]]
billed = no_pod[no_pod["has_invoice"]]
unbilled = no_pod[~no_pod["has_invoice"]]

add_exceptions(billed, "INVOICED_WITHOUT_DELIVERY_CONFIRMATION", "High",
               detail="Invoice received but vendor has not confirmed delivery - hold payment pending POD",
               exposure=billed["invoice_amount"].values)
add_exceptions(unbilled, "NO_DELIVERY_CONFIRMATION", "Medium",
               detail="No delivery confirmation and no invoice - confirm patient received supplies",
               exposure=0.0)


# -----------------------------------------------------------------------------
# CHECK 3. DELIVERED BUT NOT YET INVOICED
# -----------------------------------------------------------------------------
# Not an error, but finance needs it for accruals (cost incurred, bill not received).
not_inv = m[m["has_delivery_confirmation"] & ~m["has_invoice"]]
add_exceptions(not_inv, "NOT_YET_INVOICED", "Low",
               detail="Delivered, invoice outstanding - include in accruals",
               exposure=(not_inv["qty_delivered_total"] * not_inv["contract_unit_price"]).values)


# -----------------------------------------------------------------------------
# CHECK 4. QUANTITY: invoiced vs delivered
# -----------------------------------------------------------------------------
# Compare against confirmed deliveries. If the confirmation is missing, fall
# back to the ordered quantity (the most the vendor could legitimately bill).
inv_lines = m[m["has_invoice"]].copy()
inv_lines["qty_reference"] = inv_lines["qty_delivered_total"].fillna(inv_lines["qty_ordered"])
inv_lines["qty_basis"] = np.where(inv_lines["has_delivery_confirmation"], "delivered", "ordered")
qty_diff = inv_lines["qty_invoiced"] - inv_lines["qty_reference"]

over = inv_lines[qty_diff > 0]
add_exceptions(over, "QTY_OVERBILLED", "High",
               detail=(("Invoiced " + over["qty_invoiced"].astype(int).astype(str)
                        + " vs " + over["qty_reference"].astype(int).astype(str)
                        + " " + over["qty_basis"])).values,
               exposure=(qty_diff[qty_diff > 0] * over["contract_unit_price"]).values)

under = inv_lines[qty_diff < 0]
add_exceptions(under, "QTY_UNDERBILLED", "Low",
               detail="Invoiced fewer units than delivered - expect a supplementary invoice",
               exposure=0.0)


# -----------------------------------------------------------------------------
# CHECK 5. PRICE vs CONTRACT
# -----------------------------------------------------------------------------
inv_lines["price_variance_pct"] = inv_lines["unit_price_invoiced"] / inv_lines["contract_unit_price"] - 1
high_price = inv_lines[inv_lines["price_variance_pct"] > PRICE_TOLERANCE]
add_exceptions(high_price, "PRICE_ABOVE_CONTRACT", "High",
               detail=("Billed " + (high_price["price_variance_pct"] * 100).round(1).astype(str)
                       + "% above contract").values,
               exposure=((high_price["unit_price_invoiced"] - high_price["contract_unit_price"])
                         * high_price["qty_invoiced"]).values)


# -----------------------------------------------------------------------------
# ASSEMBLE THE EXCEPTION REPORT
# -----------------------------------------------------------------------------
exceptions = pd.concat(exception_frames, ignore_index=True)
exceptions.insert(0, "exception_id", [f"EXC-{i:06d}" for i in range(1, len(exceptions) + 1)])
exceptions = exceptions.merge(orders[["order_line_id", "order_date", "region_id", "sku"]],
                              on="order_line_id", how="left")

# Flag exceptions back onto the matched table (Power BI can filter on these)
m["invoice_count"] = m["order_line_id"].map(inv["order_line_id"].value_counts()).fillna(0).astype(int)
m["exception_count"] = m["order_line_id"].map(exceptions["order_line_id"].value_counts()).fillna(0).astype(int)
m["has_exception"] = m["exception_count"] > 0


# -----------------------------------------------------------------------------
# SAVE
# -----------------------------------------------------------------------------
m.to_csv(CLEAN / "fact_order_lines_matched.csv", index=False, date_format="%Y-%m-%d")
exceptions.to_csv(CLEAN / "exceptions.csv", index=False, date_format="%Y-%m-%d")

summary = (exceptions.pivot_table(index="check", columns="vendor_id", values="exception_id",
                                  aggfunc="count", fill_value=0))
summary["TOTAL"] = summary.sum(axis=1)
summary["dollar_exposure"] = exceptions.groupby("check")["dollar_exposure"].sum().round(0)
summary.to_csv(CLEAN / "exception_summary.csv")


# -----------------------------------------------------------------------------
# REPORT
# -----------------------------------------------------------------------------
pd.set_option("display.width", 140)
print("EXCEPTIONS BY CHECK AND VENDOR")
print(summary.to_string())
print(f"\nTotal exceptions: {len(exceptions):,}  |  "
      f"order lines affected: {m['has_exception'].sum():,} of {len(m):,} "
      f"({m['has_exception'].mean():.1%})  |  "
      f"dollar exposure: ${exceptions['dollar_exposure'].sum():,.0f}")

# Rate per 1,000 invoiced lines shows WHO has a pattern, not just who is biggest.
lines_per_vendor = m[m["has_invoice"]].groupby("vendor_id").size()
price_rate = (high_price.groupby("vendor_id").size() / lines_per_vendor * 1000).fillna(0).round(1)
print("\nPrice-above-contract exceptions per 1,000 invoiced lines (vendor pattern check)")
print(price_rate.to_string())

# Validate against the answer key from Step 1: did every check find what was planted?
key = json.loads((RAW / "planted_issues.json").read_text())["issue_5_data_quality"]
found = exceptions["check"].value_counts()
missing_found = found.get("INVOICED_WITHOUT_DELIVERY_CONFIRMATION", 0) + found.get("NO_DELIVERY_CONFIRMATION", 0)
print("\nVALIDATION vs planted answer key")
for label, planted, got in [
    ("Missing delivery confirmations", key["missing_delivery_confirmations"], missing_found),
    ("Quantity overbilled",            key["invoice_qty_overbilled_lines"],   found.get("QTY_OVERBILLED", 0)),
    ("Price above contract",           key["invoice_price_variance_lines"],   found.get("PRICE_ABOVE_CONTRACT", 0)),
    ("Duplicate invoices",             key["duplicate_invoices"],             found.get("DUPLICATE_INVOICE", 0)),
]:
    print(f"  {label:<32} planted {planted:>5,}  found {got:>5,}  {'OK' if planted == got else 'CHECK'}")
