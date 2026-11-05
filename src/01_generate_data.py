# =============================================================================
# 01_generate_data.py
# Ontario MES Vendor Performance & Formulary Analytics
# STEP 1 — Generate a realistic synthetic dataset
# =============================================================================
#
# WHY SYNTHETIC?
#   Ontario Health atHome's order-level Medical Equipment & Supplies (MES) data
#   is not public. So we build a stand-in whose STRUCTURE mirrors what a
#   Contract Specialist actually receives: three separate systems that do not
#   perfectly agree with each other.
#
#       1. Ordering system      -> fact_order_lines.csv   (what was ordered)
#       2. Vendor confirmations -> fact_deliveries.csv    (what vendors say shipped)
#       3. Accounts payable     -> fact_invoices.csv      (what vendors billed)
#
#   Plus reference ("master" / "dimension") tables:
#       dim_regions.csv, dim_vendors.csv, dim_products.csv
#
# PLANTED PROBLEMS
#   We deliberately bury known issues in the data. Later steps (reconciliation,
#   Power BI scorecard, root-cause analysis) must DISCOVER them. The answer key
#   is written to planted_issues.json so you can show your methods find what
#   is really there.
#       #1 Vendor V01 on-time delivery deteriorates in the two Northern regions
#          from Dec 2025 (the "vendor-specific" problem)
#       #2 Winter weather dip in the North that hits ALL vendors in Jan-Feb
#          (a CONFOUNDER: the root-cause analysis must separate #1 from #2)
#       #3 A high-volume foam dressing goes into recurring stockouts
#       #4 Off-formulary ordering creeps up in the West region
#       #5 Data-quality defects across systems: missing delivery confirmations,
#          invoice quantity mismatches, price variances vs contract, duplicates
#
# All vendor names are fictional.
#
# RUN (from the project root, in your conda env):
#       python src/01_generate_data.py
# Requires only numpy and pandas.
# =============================================================================

import json
from pathlib import Path

import numpy as np
import pandas as pd

# -----------------------------------------------------------------------------
# 0. SETTINGS
# -----------------------------------------------------------------------------
SEED = 42                                  # fixed seed -> identical data every run
rng = np.random.default_rng(SEED)          # modern NumPy random generator

PROJECT_ROOT = Path(__file__).resolve().parents[1]   # .../mes-analytics
OUT_DIR = PROJECT_ROOT / "data" / "raw"
OUT_DIR.mkdir(parents=True, exist_ok=True)

MONTHS = pd.period_range("2024-11", "2026-10", freq="M")   # 24 months of history
BASE_ORDERS_PER_MONTH = 800    # orders in month 1 (each order has ~2.5 lines)
MONTHLY_GROWTH = 0.006         # ~7.4%/yr demand growth (aging population, home-first policy)

NORTH = ["NEA", "NWE"]         # used repeatedly for the planted Northern issues


# -----------------------------------------------------------------------------
# 1. REGIONS  (Ontario Health's six regions)
# -----------------------------------------------------------------------------
# demand_share: illustrative share of provincial MES demand (roughly population).
# sla_days:     contractual delivery window. Remote regions get longer windows.
regions = pd.DataFrame({
    "region_id":    ["TOR", "CEN", "EAS", "WES", "NEA", "NWE"],
    "region_name":  ["Toronto", "Central", "East", "West", "North East", "North West"],
    "demand_share": [0.18, 0.32, 0.22, 0.20, 0.055, 0.025],
    "sla_days":     [2, 2, 2, 2, 3, 4],
})


# -----------------------------------------------------------------------------
# 2. PRODUCT CATEGORIES
# -----------------------------------------------------------------------------
# share     : share of all order lines going to this category
# n_skus    : how many distinct products (SKUs) the category has
# price     : (min, max) list price per unit, CAD
# mean_qty  : average units per order line
# seasonal  : amplitude of winter seasonality (0 = none). Respiratory peaks in January.
CATEGORIES = {
    "Wound Care": dict(share=0.30, n_skus=50, price=(4, 45), mean_qty=10, seasonal=0.0,
        subtypes=["Foam dressing", "Alginate dressing", "Hydrocolloid dressing",
                  "Silver antimicrobial dressing", "Transparent film", "Gauze pad",
                  "Compression bandage", "Negative pressure canister"]),
    "Incontinence": dict(share=0.22, n_skus=30, price=(18, 75), mean_qty=3, seasonal=0.0,
        subtypes=["Adult brief (case)", "Protective underwear (case)", "Underpad (case)",
                  "Catheter, intermittent", "Urinary drainage bag"]),
    "Ostomy": dict(share=0.12, n_skus=30, price=(6, 40), mean_qty=4, seasonal=0.0,
        subtypes=["One-piece pouch", "Two-piece flange", "Two-piece pouch",
                  "Barrier ring", "Stoma paste"]),
    "Enteral Nutrition": dict(share=0.12, n_skus=25, price=(25, 140), mean_qty=6, seasonal=0.0,
        subtypes=["Standard formula (case)", "High-protein formula (case)",
                  "Feeding set", "Extension set", "Enteral syringe (box)"]),
    "Respiratory": dict(share=0.12, n_skus=30, price=(15, 380), mean_qty=2, seasonal=0.35,
        subtypes=["Oxygen tubing", "Nasal cannula", "Nebulizer kit",
                  "Suction catheter (box)", "CPAP mask", "Humidifier chamber"]),
    "Mobility Aids": dict(share=0.12, n_skus=35, price=(60, 950), mean_qty=1, seasonal=0.0,
        subtypes=["Walker", "Rollator", "Commode chair", "Bath bench",
                  "Transfer board", "Wheelchair cushion", "Raised toilet seat"]),
}
CAT_NAMES = list(CATEGORIES)


# -----------------------------------------------------------------------------
# 3. VENDORS  (fictional)
# -----------------------------------------------------------------------------
# baseline_on_time is the vendor's TRUE underlying performance. It is hidden
# truth (it goes in the answer key, not in dim_vendors.csv) — in real life you
# only ever observe outcomes, never the true rate.
vendors = pd.DataFrame(
    [
        ("V01", "Northbridge Medical Supply", "Wound Care|Ostomy|Incontinence",   "ALL",             0.955),
        ("V02", "Lakeview Health Products",   "Wound Care|Incontinence",          "TOR|CEN|EAS|WES", 0.965),
        ("V03", "Algonquin Home Equipment",   "Mobility Aids",                    "ALL",             0.935),
        ("V04", "Pinecrest Respiratory Care", "Respiratory",                      "ALL",             0.945),
        ("V05", "Maplewood Clinical Nutrition","Enteral Nutrition",               "ALL",             0.970),
        ("V06", "CareLink Distribution",      "Wound Care|Ostomy|Mobility Aids",  "TOR|CEN|WES",     0.925),
    ],
    columns=["vendor_id", "vendor_name", "categories", "regions_served", "baseline_on_time"],
)
# Contract service levels (the same for every vendor, as in a standard provincial contract)
vendors["sla_on_time_target"] = 0.95     # >= 95% of lines delivered within the SLA window
vendors["sla_fill_rate_target"] = 0.98   # >= 98% of units shipped on the first shipment


def vendor_serves(vendor_row, category, region_id):
    """True if a vendor's contract covers this category AND this region."""
    cats_ok = category in vendor_row["categories"].split("|")
    regs_ok = vendor_row["regions_served"] == "ALL" or region_id in vendor_row["regions_served"].split("|")
    return cats_ok and regs_ok


# -----------------------------------------------------------------------------
# 4. PRODUCTS (SKUs)
# -----------------------------------------------------------------------------
product_rows = []
sku_counter = 1
for cat, spec in CATEGORIES.items():
    n = spec["n_skus"]
    subtypes = spec["subtypes"]
    n_off = max(2, round(0.12 * n))        # ~12% of each category's SKUs are off-formulary
    eligible_vendors = vendors[vendors["categories"].str.contains(cat)]

    for i in range(n):
        subtype = subtypes[i % len(subtypes)]
        variant = chr(65 + i // len(subtypes))           # A, B, C ... (size / brand variant)
        on_formulary = i < n - n_off                     # last n_off SKUs are off-formulary
        list_price = round(rng.uniform(*spec["price"]), 2)

        # Contract price: formulary items carry a negotiated 5–15% discount.
        # Off-formulary items are bought by exception at a premium over list.
        if on_formulary:
            contract_price = round(list_price * (1 - rng.uniform(0.05, 0.15)), 2)
        else:
            contract_price = round(list_price * rng.uniform(1.15, 1.40), 2)

        # Assign a contracted vendor among those covering the category.
        # V01 is the dominant provincial supplier, so it gets double weight.
        w = np.where(eligible_vendors["vendor_id"] == "V01", 2.0, 1.0)
        vendor_id = rng.choice(eligible_vendors["vendor_id"].values, p=w / w.sum())

        product_rows.append({
            "sku": f"MES-{sku_counter:04d}",
            "product_name": f"{subtype} - variant {variant}",
            "category": cat,
            "subtype": subtype,
            "on_formulary": on_formulary,
            "contracted_vendor_id": vendor_id,
            "list_price": list_price,
            "contract_unit_price": contract_price,
            # popularity: skewed weights so a few SKUs dominate volume (as in real formularies)
            "popularity": rng.gamma(shape=0.7, scale=1.0),
        })
        sku_counter += 1

products = pd.DataFrame(product_rows)

# Planted issue #3: the recurring-stockout SKU is the MOST popular formulary foam dressing,
# so the stockouts genuinely matter for patients and volume.
foam = products[(products["subtype"] == "Foam dressing") & products["on_formulary"]]
STOCKOUT_SKU = foam.loc[foam["popularity"].idxmax(), "sku"]
products.loc[products["sku"] == STOCKOUT_SKU, "popularity"] *= 3   # make it a true top seller

# Fulfilment lookup: if the contracted vendor doesn't serve a region, the order is
# routed to another vendor that covers that category in that region.
vendor_lookup = vendors.set_index("vendor_id")
fulfil_vendor = {}
for _, p in products.iterrows():
    for r in regions["region_id"]:
        v = p["contracted_vendor_id"]
        if not vendor_serves(vendor_lookup.loc[v], p["category"], r):
            v = next(vid for vid, vrow in vendor_lookup.iterrows()
                     if vendor_serves(vrow, p["category"], r))
        fulfil_vendor[(p["sku"], r)] = v


# -----------------------------------------------------------------------------
# 5. ORDERS -> ORDER LINES  (source system 1)
# -----------------------------------------------------------------------------
# Built month by month so we can apply growth, seasonality and the planted
# off-formulary drift in the West.
order_frames = []
order_counter = 0
for t, month in enumerate(MONTHS):
    # 5a. How many orders this month: grows over time, with Poisson noise
    n_orders = rng.poisson(BASE_ORDERS_PER_MONTH * (1 + MONTHLY_GROWTH) ** t)

    # 5b. Order dates: weekdays much busier than weekends
    days = pd.date_range(month.start_time, month.end_time.normalize(), freq="D")
    day_w = np.where(days.dayofweek >= 5, 0.25, 1.0)
    dates = rng.choice(days.values, size=n_orders, p=day_w / day_w.sum())

    # 5c. Region and patient for each order
    order_region = rng.choice(regions["region_id"].values, size=n_orders, p=regions["demand_share"].values)
    patient_ref = np.array([f"PT{x:06d}" for x in rng.integers(1, 60000, size=n_orders)])

    # 5d. Each order has 1 + Poisson(1.5) lines -> ~2.5 lines on average
    n_lines = 1 + rng.poisson(1.5, size=n_orders)
    order_ids = np.arange(order_counter, order_counter + n_orders)
    order_counter += n_orders

    df = pd.DataFrame({
        "order_id": np.repeat([f"ORD-{i:07d}" for i in order_ids], n_lines),
        "line_no": np.concatenate([np.arange(1, k + 1) for k in n_lines]),
        "order_date": np.repeat(dates, n_lines),
        "region_id": np.repeat(order_region, n_lines),
        "patient_ref": np.repeat(patient_ref, n_lines),
        "month_index": t,
    })

    # 5e. Category per line, with respiratory seasonality (cosine peaking in January)
    cat_w = np.array([CATEGORIES[c]["share"] * (1 + CATEGORIES[c]["seasonal"] * np.cos(2 * np.pi * (month.month - 1) / 12))
                      for c in CAT_NAMES])
    df["category"] = rng.choice(CAT_NAMES, size=len(df), p=cat_w / cat_w.sum())

    # 5f. Off-formulary flag. Base rate 5%.
    # Planted issue #4: in the West, the rate ramps from 5% (Jul 2025) to 14% (Oct 2026).
    p_off = np.full(len(df), 0.05)
    if t >= 8:   # month_index 8 = Jul 2025
        p_off[df["region_id"].values == "WES"] = 0.05 + (t - 8) / (len(MONTHS) - 1 - 8) * 0.09
    df["off_formulary"] = rng.random(len(df)) < p_off

    order_frames.append(df)

lines = pd.concat(order_frames, ignore_index=True)
lines["order_line_id"] = lines["order_id"] + "-L" + lines["line_no"].astype(str)

# 5g. Pick the actual SKU: within each (category, formulary status) pool,
#     sample by popularity so volume concentrates on top sellers.
lines["sku"] = ""
for (cat, off), idx in lines.groupby(["category", "off_formulary"]).groups.items():
    pool = products[(products["category"] == cat) & (products["on_formulary"] != off)]
    w = pool["popularity"].values
    lines.loc[idx, "sku"] = rng.choice(pool["sku"].values, size=len(idx), p=w / w.sum())

# 5h. Quantity: mobility aids are always 1 unit; others ~ 1 + Poisson(mean - 1)
mean_qty = lines["category"].map({c: s["mean_qty"] for c, s in CATEGORIES.items()}).values
lines["qty_ordered"] = np.where(lines["category"] == "Mobility Aids", 1, 1 + rng.poisson(mean_qty - 1))

# 5i. Vendor that fulfils this line, and the contract price at time of order
lines["vendor_id"] = [fulfil_vendor[(s, r)] for s, r in zip(lines["sku"], lines["region_id"])]
lines = lines.merge(products[["sku", "contract_unit_price"]], on="sku", how="left")
lines["order_date"] = pd.to_datetime(lines["order_date"])


# -----------------------------------------------------------------------------
# 6. DELIVERIES  (source system 2: vendor delivery confirmations)
# -----------------------------------------------------------------------------
n = len(lines)
sla = lines["region_id"].map(regions.set_index("region_id")["sla_days"]).values
is_north = lines["region_id"].isin(NORTH).values

# 6a. Probability each line arrives on time = vendor's true baseline...
p_on_time = lines["vendor_id"].map(vendors.set_index("vendor_id")["baseline_on_time"]).values.copy()

# 6b. Planted issue #1: V01 deteriorates in the North from Dec 2025.
#     Linear slide over 6 months, from 95.5% down to ~72.5%, then stays there.
DETERIORATION_START = pd.Timestamp("2025-12-01")
months_since = ((lines["order_date"] - DETERIORATION_START).dt.days / 30.4).values
v01_north = (lines["vendor_id"].values == "V01") & is_north & (months_since >= 0)
p_on_time[v01_north] -= np.clip(months_since[v01_north] / 6, 0, 1) * 0.23

# 6c. Planted issue #2 (confounder): Jan-Feb weather in the North hurts EVERY vendor by 6 pts
winter_north = is_north & lines["order_date"].dt.month.isin([1, 2]).values
p_on_time[winter_north] -= 0.06

# 6d. Draw on-time outcomes and transit days
on_time = rng.random(n) < p_on_time
transit_days = np.where(
    on_time,
    rng.integers(1, sla + 1),          # on time: somewhere within the SLA window
    sla + rng.integers(1, 6, size=n),  # late: 1–5 days past the window
)

# 6e. Backorders (first shipment short). Base rate 1.5%.
#     Planted issue #3: the stockout SKU is backordered 65% of the time in three windows.
STOCKOUT_WINDOWS = [("2025-03-03", "2025-03-28"), ("2025-09-08", "2025-10-03"), ("2026-04-06", "2026-05-01")]
p_bo = np.full(n, 0.015)
in_window = np.zeros(n, dtype=bool)
for start, end in STOCKOUT_WINDOWS:
    in_window |= lines["order_date"].between(start, end).values
p_bo[(lines["sku"].values == STOCKOUT_SKU) & in_window] = 0.65
backordered = rng.random(n) < p_bo

qty = lines["qty_ordered"].values
qty_initial = np.where(backordered, rng.integers(0, qty), qty)   # 0..qty-1 shipped if backordered
qty_backorder = qty - qty_initial

initial_date = lines["order_date"] + pd.to_timedelta(transit_days, unit="D")
backorder_date = initial_date + pd.to_timedelta(rng.integers(7, 22, size=n), unit="D")

deliveries = pd.DataFrame({
    "delivery_id": [f"DLV-{i:07d}" for i in range(n)],
    "order_line_id": lines["order_line_id"],
    "vendor_id": lines["vendor_id"],
    "qty_shipped_initial": qty_initial,
    # If nothing shipped initially, there is no initial delivery date
    "initial_delivery_date": initial_date.where(qty_initial > 0),
    "qty_backordered": qty_backorder,
    "backorder_delivery_date": backorder_date.where(qty_backorder > 0),
})

# 6f. Planted issue #5a: 1.5% of delivery confirmations never reach the system
missing_mask = rng.random(n) < 0.015
missing_delivery_ids = deliveries.loc[missing_mask, "order_line_id"].tolist()
deliveries = deliveries.loc[~missing_mask].reset_index(drop=True)


# -----------------------------------------------------------------------------
# 7. INVOICES  (source system 3: accounts payable)
# -----------------------------------------------------------------------------
# Vendors bill each line once everything has been delivered (or, if the delivery
# confirmation went missing, they still bill — that's exactly the risk to catch).
final_delivery = backorder_date.where(qty_backorder > 0, initial_date)
inv = pd.DataFrame({
    "order_line_id": lines["order_line_id"],
    "vendor_id": lines["vendor_id"],
    "invoice_date": final_delivery + pd.to_timedelta(rng.integers(1, 15, size=n), unit="D"),
    "qty_invoiced": qty.copy(),
    "unit_price_invoiced": lines["contract_unit_price"].values.copy(),
})

# 7a. Planted issue #5b: 2% of invoices bill 1–3 more units than delivered
qty_err = rng.random(n) < 0.02
inv.loc[qty_err, "qty_invoiced"] += rng.integers(1, 4, size=qty_err.sum())

# 7b. Planted issue #5c: ~1% price variance vs contract (+3% to +15%),
#     concentrated on V06 (5x more likely) so it shows up as a VENDOR pattern.
w_price = np.where(inv["vendor_id"] == "V06", 5.0, 1.0)
price_err_idx = rng.choice(n, size=int(0.01 * n), replace=False, p=w_price / w_price.sum())
inv.loc[price_err_idx, "unit_price_invoiced"] = (
    inv.loc[price_err_idx, "unit_price_invoiced"] * rng.uniform(1.03, 1.15, size=len(price_err_idx))
).round(2)

# 7c. Planted issue #5d: 0.5% of lines billed twice (duplicate invoice 2–6 weeks later)
dup_idx = rng.choice(n, size=int(0.005 * n), replace=False)
dups = inv.loc[dup_idx].copy()
dups["invoice_date"] = dups["invoice_date"] + pd.to_timedelta(rng.integers(14, 43, size=len(dups)), unit="D")
inv = pd.concat([inv, dups], ignore_index=True).sort_values("invoice_date").reset_index(drop=True)

inv["invoice_id"] = [f"INV-{i:07d}" for i in range(len(inv))]
inv["invoice_amount"] = (inv["qty_invoiced"] * inv["unit_price_invoiced"]).round(2)
inv = inv[["invoice_id", "order_line_id", "vendor_id", "invoice_date",
           "qty_invoiced", "unit_price_invoiced", "invoice_amount"]]


# -----------------------------------------------------------------------------
# 8. SAVE
# -----------------------------------------------------------------------------
order_lines_out = lines[["order_line_id", "order_id", "line_no", "order_date", "region_id",
                         "patient_ref", "sku", "category", "vendor_id",
                         "qty_ordered", "contract_unit_price"]]

regions.to_csv(OUT_DIR / "dim_regions.csv", index=False)
vendors.drop(columns="baseline_on_time").to_csv(OUT_DIR / "dim_vendors.csv", index=False)
products.drop(columns="popularity").to_csv(OUT_DIR / "dim_products.csv", index=False)
order_lines_out.to_csv(OUT_DIR / "fact_order_lines.csv", index=False, date_format="%Y-%m-%d")
deliveries.to_csv(OUT_DIR / "fact_deliveries.csv", index=False, date_format="%Y-%m-%d")
inv.to_csv(OUT_DIR / "fact_invoices.csv", index=False, date_format="%Y-%m-%d")

answer_key = {
    "seed": SEED,
    "issue_1_vendor_deterioration": {
        "vendor_id": "V01", "regions": NORTH, "starts": str(DETERIORATION_START.date()),
        "description": "On-time probability slides linearly from 95.5% to ~72.5% over 6 months, then holds.",
    },
    "issue_2_winter_confounder": {
        "regions": NORTH, "months": ["Jan", "Feb"], "effect": "-6 pts on-time for ALL vendors",
    },
    "issue_3_recurring_stockout": {
        "sku": STOCKOUT_SKU,
        "product_name": products.loc[products["sku"] == STOCKOUT_SKU, "product_name"].item(),
        "windows": STOCKOUT_WINDOWS, "backorder_probability_in_window": 0.65,
    },
    "issue_4_off_formulary_drift": {
        "region": "WES", "from": "2025-07", "rate_start": 0.05, "rate_end": 0.14,
    },
    "issue_5_data_quality": {
        "missing_delivery_confirmations": len(missing_delivery_ids),
        "invoice_qty_overbilled_lines": int(qty_err.sum()),
        "invoice_price_variance_lines": len(price_err_idx),
        "price_variance_concentrated_on": "V06",
        "duplicate_invoices": len(dup_idx),
    },
    "true_vendor_baseline_on_time": vendors.set_index("vendor_id")["baseline_on_time"].to_dict(),
}
with open(OUT_DIR / "planted_issues.json", "w") as f:
    json.dump(answer_key, f, indent=2)


# -----------------------------------------------------------------------------
# 9. SANITY CHECKS — do the planted issues actually show up?
# -----------------------------------------------------------------------------
print("Rows written")
for name, df in [("dim_regions", regions), ("dim_vendors", vendors), ("dim_products", products),
                 ("fact_order_lines", order_lines_out), ("fact_deliveries", deliveries),
                 ("fact_invoices", inv)]:
    print(f"  {name:<18}{len(df):>8,}")

check = lines.assign(on_time=on_time, quarter=lines["order_date"].dt.to_period("Q"))
print("\n#1/#2  On-time rate, V01 in the North vs everyone else, by quarter")
print(check.assign(group=np.where(v01_north | ((check["vendor_id"] == "V01") & is_north), "V01 North", "All other"))
      .pivot_table(index="quarter", columns="group", values="on_time", aggfunc="mean")
      .round(3).to_string())

print(f"\n#3  Backorder rate for {STOCKOUT_SKU}: in windows "
      f"{backordered[(lines['sku'].values == STOCKOUT_SKU) & in_window].mean():.1%} vs "
      f"outside {backordered[(lines['sku'].values == STOCKOUT_SKU) & ~in_window].mean():.1%}")

print("\n#4  Off-formulary share of lines, West vs rest, by quarter")
print(check.assign(west=np.where(check["region_id"] == "WES", "West", "Rest"))
      .pivot_table(index="quarter", columns="west", values="off_formulary", aggfunc="mean")
      .round(3).to_string())

print(f"\n#5  Data-quality defects: {answer_key['issue_5_data_quality']}")
print(f"\nTotal invoiced: ${inv['invoice_amount'].sum():,.0f}")
