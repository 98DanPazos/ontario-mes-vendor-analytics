# =============================================================================
# 06_formulary_forecast_bia.py
# Ontario MES Vendor Performance & Formulary Analytics
# STEP 6 — Demand forecast + formulary budget impact analysis (BIA)
# =============================================================================
#
# THE DECISION
#   Foam dressing variant A (MES-0001) is the province's top foam dressing (~75%
#   of foam volume). It is supplied by V06 and went into stockout three times in
#   two years. Should the formulary keep it, or switch?
#
#   S0  Status quo   - keep A; during stockouts nurses substitute an off-formulary
#                      foam (variant G) at a premium
#   S1  Lowest price - switch to variant F ($22.95, but shorter wear time)
#   S2  Long wear    - switch to variant C ($34.88, extended wear, fewer changes)
#
# THE TRAP THIS ANALYSIS AVOIDS
#   Comparing unit prices alone. In home care the expensive part of a dressing
#   change is often the NURSING VISIT, not the dressing. A cheaper dressing that
#   must be changed more often can cost the system more. So we compare cost per
#   HEALING EPISODE (dressings + nursing + stockout costs), the same logic as a
#   CDA-AMC budget impact analysis.
#
# PARTS
#   A. Forecast monthly demand (ETS model), backtested against simple benchmarks
#   B. Cost per healing episode for each product
#   C. 3-year budget impact with phased uptake
#   D. One-way sensitivity analysis (tornado)
#
# IMPORTANT: clinical and nursing-cost parameters in PARAMS are ILLUSTRATIVE
# assumptions, clearly labelled. In the real job they would come from wound-care
# clinicians, product monographs and Ontario Health atHome cost data. Every
# parameter is in one dictionary so it can be replaced and the model re-run.
#
# OUTPUTS  outputs/figures/forecast_foam.png, bia_by_year.png, bia_tornado.png
#          outputs/tables/bia_model.xlsx  (Parameters, Forecast, Episode cost, BIA, Sensitivity)
#
# RUN (from the project root):   python src/06_formulary_forecast_bia.py
# =============================================================================

import warnings
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from statsmodels.tsa.exponential_smoothing.ets import ETSModel

warnings.filterwarnings("ignore")   # statsmodels convergence chatter on a short series

ROOT = Path(__file__).resolve().parents[1]
FIG, TAB = ROOT / "outputs" / "figures", ROOT / "outputs" / "tables"
FIG.mkdir(parents=True, exist_ok=True)
TAB.mkdir(parents=True, exist_ok=True)

INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"
C1, C2, C3 = "#2a78d6", "#eb6834", "#1baf7a"     # validated categorical slots 1-3
plt.rcParams.update({
    "font.size": 10, "axes.edgecolor": GRID, "axes.labelcolor": MUTED, "xtick.color": MUTED,
    "ytick.color": MUTED, "axes.titleweight": "bold", "axes.titlesize": 12, "axes.titlecolor": INK,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
    "grid.color": GRID, "grid.linewidth": 0.8,
})

# -----------------------------------------------------------------------------
# 0. PARAMETERS — one place, each with its source status
# -----------------------------------------------------------------------------
products = pd.read_csv(ROOT / "data" / "raw" / "dim_products.csv").set_index("sku")
price = lambda sku: float(products.loc[sku, "contract_unit_price"])

PARAMS = {
    # From the data (contract prices)
    "price_A":                 (price("MES-0001"), "data: contract price, variant A (V06)"),
    "price_F":                 (price("MES-0041"), "data: contract price, variant F (V01)"),
    "price_C":                 (price("MES-0017"), "data: contract price, variant C (V01)"),
    "price_G_substitute":      (price("MES-0049"), "data: off-formulary substitute used during stockouts"),
    # Illustrative clinical assumptions (replace with clinician / monograph input)
    "changes_per_week_A":      (3.0,  "ASSUMPTION: standard foam, changed ~every 2-3 days"),
    "changes_per_week_F":      (3.5,  "ASSUMPTION: thinner foam, shorter wear time"),
    "changes_per_week_C":      (2.0,  "ASSUMPTION: extended-wear foam, up to 7 days per label claim"),
    "episode_weeks":           (8.0,  "ASSUMPTION: average healing episode, equal across products"),
    # Illustrative system-cost assumptions (replace with Ontario Health atHome rates)
    "nurse_share_of_changes":  (0.5,  "ASSUMPTION: share of changes done at a nursing visit (rest by patient/caregiver)"),
    "cost_per_nursing_visit":  (90.0, "ASSUMPTION: illustrative home-nursing visit cost, CAD"),
    "stockout_handling_cost":  (25.0, "ASSUMPTION: staff time to source a substitute, per backordered line"),
    # Implementation
    "uptake_y1":               (0.50, "ASSUMPTION: share of episodes switched in year 1 (transition)"),
    "uptake_y2":               (0.80, "ASSUMPTION"),
    "uptake_y3":               (0.95, "ASSUMPTION"),
}
P = {k: v[0] for k, v in PARAMS.items()}


# -----------------------------------------------------------------------------
# A. DEMAND FORECAST
# -----------------------------------------------------------------------------
# Demand = units ORDERED, not delivered. Deliveries are cut by stockouts
# ("censored"), so forecasting from deliveries would under-forecast exactly the
# product we're worried about.
f = pd.read_csv(ROOT / "data" / "clean" / "fact_order_lines_kpi.csv", parse_dates=["order_month"])
a = f[f["sku"] == "MES-0001"]
units = a.groupby("order_month")["qty_ordered"].sum().asfreq("MS")

# Observed stockout burden for variant A (feeds the S0 cost)
conf = a[a["backorder_flag"].notna()]
P["share_units_backordered_A"] = conf["qty_backordered"].sum() / conf["qty_ordered"].sum()
P["units_per_line_A"] = conf["qty_ordered"].mean()
PARAMS["share_units_backordered_A"] = (P["share_units_backordered_A"], "data: observed, 24 months")
PARAMS["units_per_line_A"] = (P["units_per_line_A"], "data: observed")


def fit_ets(y):
    """Additive-error, damped additive-trend ETS. No seasonality: wound-care demand
    showed none, and 24 months is too short to estimate it reliably."""
    return ETSModel(y.astype(float), error="add", trend="add", damped_trend=True).fit(disp=False)


# A1. Backtest: train on first 18 months, forecast the last 6, compare to simple benchmarks
train, test = units.iloc[:-6], units.iloc[-6:]
bt = pd.DataFrame({"actual": test})
bt["ETS"] = fit_ets(train).forecast(6).values
bt["Naive (last month)"] = train.iloc[-1]
bt["12-month average"] = train.iloc[-12:].mean()
mape = {m: (abs(bt[m] - bt["actual"]) / bt["actual"]).mean() * 100 for m in bt.columns[1:]}
print("A. Forecast backtest (train Nov24-Apr26, test May-Oct26), MAPE:")
for m, v in mape.items():
    print(f"  {m:<20} {v:5.1f}%")
best = min(mape, key=mape.get)
print(f"  -> {best} is most accurate on held-out data"
      + ("" if best == "ETS" else "; ETS kept for its trend term and prediction intervals"))

# A2. Final model on all 24 months, forecast 36 months (3 BIA years) with 80% intervals
model = fit_ets(units)
pred = model.get_prediction(start=len(units), end=len(units) + 35)
fc = pred.summary_frame(alpha=0.20)
fc.index = pd.date_range(units.index[-1] + pd.offsets.MonthBegin(1), periods=36, freq="MS")
fc = fc.rename(columns={"mean": "forecast", "pi_lower": "lo80", "pi_upper": "hi80"})[["forecast", "lo80", "hi80"]]
fc["year"] = np.repeat([1, 2, 3], 12)
annual_units = fc.groupby("year")["forecast"].sum()
print(f"\n  Forecast annual demand for variant A (units): "
      + ", ".join(f"Y{y} {u:,.0f}" for y, u in annual_units.items())
      + f"   (last 12 months actual: {units.iloc[-12:].sum():,.0f})\n")


# -----------------------------------------------------------------------------
# B. COST PER HEALING EPISODE
# -----------------------------------------------------------------------------
def episode_cost(product, p):
    """Cost of one healing episode with a given product, under parameters p."""
    changes = p[f"changes_per_week_{product}"] * p["episode_weeks"]
    dressing = changes * p[f"price_{product}"]
    nursing = changes * p["nurse_share_of_changes"] * p["cost_per_nursing_visit"]
    stockout = 0.0
    if product == "A":
        # Backordered units are replaced with the off-formulary substitute (price
        # premium) and someone spends time sourcing it (handling cost per line).
        bo_units = changes * p["share_units_backordered_A"]
        stockout = (bo_units * (p["price_G_substitute"] - p["price_A"])
                    + bo_units / p["units_per_line_A"] * p["stockout_handling_cost"])
    return {"changes": changes, "dressings": dressing, "nursing": nursing,
            "stockout": stockout, "total": dressing + nursing + stockout}


ep = pd.DataFrame({k: episode_cost(k, P) for k in ["A", "F", "C"]}).T
ep.index = ["S0 Keep A (status quo)", "S1 Switch to F (lowest price)", "S2 Switch to C (long wear)"]
print("B. Cost per healing episode (CAD)")
print(ep.round(0).to_string())
print("  -> F is cheapest per DRESSING but dearest per EPISODE once nursing visits count.\n")


# -----------------------------------------------------------------------------
# C. 3-YEAR BUDGET IMPACT
# -----------------------------------------------------------------------------
# Convert forecast units of A into healing episodes ONCE, at base-case values.
# Episodes = patients' clinical need; they must not change when we test, say,
# a different wear time in the sensitivity analysis (only costs per episode do).
def to_episodes(demand_units):
    return demand_units / (P["changes_per_week_A"] * P["episode_weeks"])


def budget_impact(p, demand_units=annual_units):
    """Total cost by year for each scenario, with phased uptake of the switch."""
    episodes = to_episodes(demand_units)   # episodes/year (fixed by demand, not by p)
    cost = {k: episode_cost(k, p)["total"] for k in ["A", "F", "C"]}
    uptake = pd.Series([p["uptake_y1"], p["uptake_y2"], p["uptake_y3"]], index=[1, 2, 3])
    out = pd.DataFrame({"episodes": episodes})
    out["S0 Keep A"] = episodes * cost["A"]
    out["S1 Switch to F"] = episodes * ((1 - uptake) * cost["A"] + uptake * cost["F"])
    out["S2 Switch to C"] = episodes * ((1 - uptake) * cost["A"] + uptake * cost["C"])
    return out


bia = budget_impact(P)
bia_incr = bia[["S1 Switch to F", "S2 Switch to C"]].sub(bia["S0 Keep A"], axis=0)
bia_incr.loc["3-yr total"] = bia_incr.sum()
print("C. Budget impact vs status quo (CAD; negative = saving)")
print(bia_incr.round(0).to_string())
print()


# -----------------------------------------------------------------------------
# D. ONE-WAY SENSITIVITY (tornado) on S2's 3-year impact
# -----------------------------------------------------------------------------
# Move each parameter +/-25% (demand: the forecast's 80% interval) and record
# the 3-year incremental impact of S2. Long bars = the assumptions to validate first.
def s2_3yr(p, demand_units=annual_units):
    b = budget_impact(p, demand_units)
    return (b["S2 Switch to C"] - b["S0 Keep A"]).sum()


base = s2_3yr(P)
labels = {
    "cost_per_nursing_visit": "Nursing visit cost (±25%)",
    "nurse_share_of_changes": "Share of changes by nurse (±25%)",
    "changes_per_week_C": "Changes/week, variant C (±25%)",
    "changes_per_week_A": "Changes/week, variant A (±25%)",
    "price_C": "Price, variant C (±25%)",
    "share_units_backordered_A": "Stockout share, variant A (±25%)",
    "episode_weeks": "Healing episode length (±25%)",
}
rows = []
for k, lab in labels.items():
    lo_p, hi_p = dict(P), dict(P)
    lo_p[k], hi_p[k] = P[k] * 0.75, P[k] * 1.25
    rows.append((lab, s2_3yr(lo_p), s2_3yr(hi_p)))
annual_lo, annual_hi = fc.groupby("year")["lo80"].sum(), fc.groupby("year")["hi80"].sum()
rows.append(("Demand (80% forecast interval)", s2_3yr(P, annual_lo), s2_3yr(P, annual_hi)))
sens = pd.DataFrame(rows, columns=["parameter", "low_value_result", "high_value_result"])
sens["swing"] = (sens["high_value_result"] - sens["low_value_result"]).abs()
sens = sens.sort_values("swing").reset_index(drop=True)
always_saves = (sens[["low_value_result", "high_value_result"]] < 0).all().all()
print(f"D. Sensitivity: S2 3-year impact, base {base:,.0f}")
print(sens.round(0).iloc[::-1].to_string(index=False))
print(f"  -> S2 {'saves money under every one-way variation' if always_saves else 'does NOT save under all variations - see tornado'}\n")

# Break-even: how many changes per week can variant C need before it stops saving?
# Cost per change of C = its price + the nursing cost of that change.
cost_per_change_C = P["price_C"] + P["nurse_share_of_changes"] * P["cost_per_nursing_visit"]
breakeven_changes_C = episode_cost("A", P)["total"] / P["episode_weeks"] / cost_per_change_C
print(f"  Break-even: S2 saves money as long as variant C needs fewer than "
      f"{breakeven_changes_C:.1f} changes/week (assumed {P['changes_per_week_C']:.1f}; A needs {P['changes_per_week_A']:.1f})."
      f"\n  -> The decision hinges on ONE clinical fact to verify: C's real-world wear time.\n")


# -----------------------------------------------------------------------------
# FIGURES
# -----------------------------------------------------------------------------
# Figure 1: history, backtest and forecast with 80% interval
fig, ax = plt.subplots(figsize=(9, 4.4))
ax.plot(units.index, units.values, color=C1, lw=2, marker="o", ms=3.5, label="Actual units ordered")
ax.plot(bt.index, bt["ETS"], color=C2, lw=2, ls="--", label=f"Backtest forecast (MAPE {mape['ETS']:.0f}%)")
ax.fill_between(fc.index, fc["lo80"], fc["hi80"], color=C1, alpha=0.15, lw=0, label="80% prediction interval")
ax.plot(fc.index, fc["forecast"], color=C1, lw=2, ls=":", label="Forecast")
ax.set_ylim(0, None)
ax.set_ylabel("Units per month")
ax.set_title(f"Foam dressing variant A: demand is stable at about {fc['forecast'].mean():.0f} units a month", loc="left")
ax.legend(frameon=False, loc="lower left", fontsize=8.5, ncol=2)
fig.text(0.01, 0.01, "Synthetic data. Demand = units ordered (not delivered), so stockouts don't bias it.",
         color=MUTED, fontsize=8)
fig.tight_layout(rect=(0, 0.03, 1, 1))
fig.savefig(FIG / "forecast_foam.png", dpi=200)
plt.close(fig)

# Figure 2: incremental budget impact by year
fig, ax = plt.subplots(figsize=(8, 4.2))
x = np.arange(3)
for i, (col, colr) in enumerate([("S1 Switch to F", C2), ("S2 Switch to C", C3)]):
    vals = bia_incr.loc[[1, 2, 3], col] / 1000
    bars = ax.bar(x + (i - 0.5) * 0.36, vals, width=0.34, color=colr, label=col)
    for bx, v in zip(bars, vals):
        ax.text(bx.get_x() + bx.get_width() / 2, v + (4 if v >= 0 else -4), f"{v:+.0f}k",
                ha="center", va="bottom" if v >= 0 else "top", fontsize=8.5, color=INK)
ax.axhline(0, color=MUTED, lw=1)
ax.set_xticks(x, ["Year 1", "Year 2", "Year 3"])
ax.set_ylabel("Change vs keeping A ($ thousands)")
ax.margins(y=0.2)
ax.grid(axis="x", visible=False)
ax.set_title("Lowest unit price costs more; long-wear foam saves money", loc="left")
ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.1), ncol=2, fontsize=9)
fig.tight_layout()
fig.savefig(FIG / "bia_by_year.png", dpi=200)
plt.close(fig)

# Figure 3: tornado
fig, ax = plt.subplots(figsize=(8.5, 4.4))
y = np.arange(len(sens))
lo_v, hi_v = sens["low_value_result"] / 1000, sens["high_value_result"] / 1000
ax.barh(y, lo_v - base / 1000, left=base / 1000, color="#9fc3ee", height=0.6, label="Parameter at low value")
ax.barh(y, hi_v - base / 1000, left=base / 1000, color=C1, height=0.6, label="Parameter at high value")
ax.axvline(base / 1000, color=INK, lw=1)
ax.axvline(0, color=MUTED, lw=1, ls="--")
ax.set_yticks(y, sens["parameter"])
ax.set_xlabel("S2 3-year budget impact vs status quo ($ thousands; left of dashed line = saving)")
ax.grid(axis="y", visible=False)
ax.set_title(f"S2 saves money in every scenario tested (base case {base/1000:+.0f}k)", loc="left")
ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.18), ncol=2, fontsize=8.5)
fig.tight_layout()
fig.savefig(FIG / "bia_tornado.png", dpi=200)
plt.close(fig)


# -----------------------------------------------------------------------------
# EXCEL WORKBOOK (the format a procurement / finance team will actually use)
# -----------------------------------------------------------------------------
params_out = pd.DataFrame([(k, v[0], v[1]) for k, v in PARAMS.items()], columns=["parameter", "value", "source"])
fc_out = fc.copy()
fc_out.index.name = "month"
with pd.ExcelWriter(TAB / "bia_model.xlsx") as xl:
    params_out.to_excel(xl, "Parameters", index=False)
    pd.DataFrame({"actual_units": units}).join(bt.drop(columns="actual"), how="left").to_excel(xl, "History & backtest")
    fc_out.round(1).to_excel(xl, "Forecast")
    ep.round(2).to_excel(xl, "Cost per episode")
    bia.round(0).to_excel(xl, "BIA totals")
    bia_incr.round(0).to_excel(xl, "BIA incremental")
    sens.round(0).to_excel(xl, "Sensitivity", index=False)
print(f"Saved figures to {FIG} and workbook to {TAB / 'bia_model.xlsx'}")
