# =============================================================================
# 07_rfp_evaluation.py
# Ontario MES Vendor Performance & Formulary Analytics
# STEP 7 — Mock RFP evaluation workbook (weighted scoring matrix, live Excel formulas)
# =============================================================================
#
# THE SCENARIO
#   Following Steps 5-6, the MES team issues a (mock) RFP for a provincial foam
#   dressing supply contract. Four bidders respond. This script builds the
#   evaluation workbook a procurement team would use, with the standard
#   three-stage structure used in broader-public-sector procurement:
#
#     Stage 1  Mandatory requirements  - pass/fail; any fail = disqualified
#     Stage 2  Rated technical (60 pts) - consensus scores 0-5 x criterion weight;
#                                        must reach 70% of technical points to continue
#     Stage 3  Price (40 pts)           - scored on COST PER HEALING EPISODE (Step 6),
#                                        not unit price: lowest cost / bidder cost x 40
#
#   Every score is an Excel FORMULA driven by input cells (blue), so evaluators
#   can change a score or a weight and the ranking updates. A sensitivity block
#   shows whether the winner changes if price is weighted 30%, 40% or 50%.
#
#   Incumbent bidders' delivery scores are backed by EVIDENCE from our own data
#   (Step 3 KPIs), shown on the "Past Performance" sheet.
#
# All bidders, bids and scores are FICTIONAL and for demonstration only.
#
# OUTPUT  outputs/tables/rfp_evaluation.xlsx
# RUN     python src/07_rfp_evaluation.py
# =============================================================================

from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.formatting.rule import CellIsRule, FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "tables" / "rfp_evaluation.xlsx"
OUT.parent.mkdir(parents=True, exist_ok=True)

# -----------------------------------------------------------------------------
# 0. STYLES (financial-model conventions: blue = input, black = formula,
#    green = link to another sheet, yellow fill = key assumption)
# -----------------------------------------------------------------------------
F = "Arial"
BASE = Font(name=F, size=10)
BOLD = Font(name=F, size=10, bold=True)
TITLE = Font(name=F, size=14, bold=True)
SUB = Font(name=F, size=10, italic=True, color="52514E")
INPUT = Font(name=F, size=10, color="0000FF")
LINK = Font(name=F, size=10, color="008000")
HEAD = Font(name=F, size=10, bold=True, color="FFFFFF")
HEAD_FILL = PatternFill("solid", fgColor="1F3864")
KEY_FILL = PatternFill("solid", fgColor="FFFF00")
TOTAL_FILL = PatternFill("solid", fgColor="E8EEF7")
THIN = Side(style="thin", color="BFBFBF")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP = Alignment(wrap_text=True, vertical="top")
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
GREEN_FILL = PatternFill("solid", fgColor="C6EFCE")
RED_FILL = PatternFill("solid", fgColor="FFC7CE")

wb = Workbook()


def header(ws, row, values, col=1):
    for i, v in enumerate(values):
        c = ws.cell(row=row, column=col + i, value=v)
        c.font, c.fill, c.alignment, c.border = HEAD, HEAD_FILL, CENTER, BOX


def put(ws, ref, value, font=BASE, fmt=None, fill=None, align=None, border=True):
    c = ws[ref]
    c.value = value
    c.font = font
    if fmt:
        c.number_format = fmt
    if fill:
        c.fill = fill
    if align:
        c.alignment = align
    if border:
        c.border = BOX
    return c


def widths(ws, w):
    for i, x in enumerate(w, start=1):
        ws.column_dimensions[get_column_letter(i)].width = x


BIDDERS = ["B1 Northbridge Medical Supply (incumbent, V01)",
           "B2 Lakeview Health Products (incumbent, V02)",
           "B3 Boreal Medical Logistics (new entrant)",
           "B4 Summit Wound Care (new entrant)"]
SHORT = ["B1 Northbridge", "B2 Lakeview", "B3 Boreal", "B4 Summit"]
BCOLS = ["C", "D", "E", "F"]          # bidder columns on every scoring sheet

# -----------------------------------------------------------------------------
# 1. READ ME
# -----------------------------------------------------------------------------
ws = wb.active
ws.title = "Read Me"
widths(ws, [3, 110])
lines = [
    ("Mock RFP Evaluation - Provincial Foam Dressing Supply Contract", TITLE),
    ("Ontario MES Vendor Performance & Formulary Analytics - Step 7. Fictional bidders and scores, for demonstration only.", SUB),
    ("", BASE),
    ("HOW THE EVALUATION WORKS", BOLD),
    ("Stage 1 - Mandatory requirements (sheet 'Mandatory'): pass/fail. Any 'Fail' disqualifies the bidder.", BASE),
    ("Stage 2 - Rated technical, 60 points (sheet 'Technical'): consensus score 0-5 per criterion x weight. "
     "Bidders below the 70% technical threshold do not proceed to price.", BASE),
    ("Stage 3 - Price, 40 points (sheet 'Price'): scored on COST PER HEALING EPISODE (dressings + nursing visits), "
     "not unit price - the Step 6 finding that the cheapest dressing can cost the system more.", BASE),
    ("Result (sheet 'Summary'): total score, rank, recommendation, and a check of whether the winner changes "
     "if price is weighted 30%, 40% or 50%.", BASE),
    ("", BASE),
    ("COLOUR LEGEND", BOLD),
    ("Blue text = input you can edit (scores, bids, weights).  Black text = formula, do not overwrite.  "
     "Green text = pulled from another sheet.  Yellow fill = key assumption.", BASE),
    ("", BASE),
    ("SCORING SCALE (technical criteria)", BOLD),
    ("0 = not addressed  |  1 = poor  |  2 = weak, significant gaps  |  3 = meets requirements  |  "
     "4 = exceeds in some areas  |  5 = exceeds throughout, low risk", BASE),
    ("", BASE),
    ("EVIDENCE", BOLD),
    ("Delivery scores for the incumbents (B1, B2) are backed by their actual contract performance "
     "(sheet 'Past Performance', from Steps 3 and 5). New entrants are scored on references and their proposed network.", BASE),
]
for i, (t, f) in enumerate(lines, start=1):
    c = ws.cell(row=i, column=2, value=t)
    c.font, c.alignment = f, Alignment(wrap_text=True, vertical="top")

# -----------------------------------------------------------------------------
# 2. WEIGHTS & RULES (all levers in one place)
# -----------------------------------------------------------------------------
wr = wb.create_sheet("Weights & Rules")
widths(wr, [4, 46, 14, 70])
put(wr, "B1", "Evaluation weights and rules", TITLE, border=False)
header(wr, 3, ["Criterion", "Points", "What evaluators look for"], col=2)
CRITERIA = [
    ("T1 Product performance & wear time", 15, "Wear time, clinical evidence, clinician panel feedback"),
    ("T2 Supply continuity & inventory", 15, "Safety stock, dual manufacturing sources, stockout plan, Canadian warehousing"),
    ("T3 Delivery performance & Northern coverage", 15, "Evidence of on-time delivery in all six regions, especially North East / North West"),
    ("T4 Reporting & data", 5, "Monthly KPI files matching our definitions, delivery confirmations, API/EDI"),
    ("T5 Implementation & transition", 10, "Transition plan, clinician education, risk of disruption to patients"),
]
for i, (name, pts, desc) in enumerate(CRITERIA, start=4):
    put(wr, f"B{i}", name)
    put(wr, f"C{i}", pts, INPUT, "0", KEY_FILL, CENTER)
    put(wr, f"D{i}", desc, align=WRAP)
put(wr, "B9", "Technical total", BOLD, fill=TOTAL_FILL)
put(wr, "C9", "=SUM(C4:C8)", BOLD, "0", TOTAL_FILL, CENTER)
put(wr, "B10", "Price", BOLD)
put(wr, "C10", 40, INPUT, "0", KEY_FILL, CENTER)
put(wr, "D10", "Scored on cost per healing episode: lowest eligible cost / bidder cost x price points", align=WRAP)
put(wr, "B11", "Grand total", BOLD, fill=TOTAL_FILL)
put(wr, "C11", "=C9+C10", BOLD, "0", TOTAL_FILL, CENTER)

header(wr, 13, ["Rule / cost assumption", "Value", "Source / note"], col=2)
RULES = [
    ("Technical threshold to proceed to price", 0.70, "0%", "Common BPS practice; set in the RFP document"),
    ("Healing episode length (weeks)", 8, "0", "Step 6 assumption, equal across products"),
    ("Share of dressing changes done at a nursing visit", 0.5, "0%", "Step 6 assumption (illustrative)"),
    ("Cost per home nursing visit ($)", 90, "$#,##0", "Step 6 assumption (illustrative); replace with Ontario Health atHome rate"),
]
for i, (name, v, fmt, note) in enumerate(RULES, start=14):
    put(wr, f"B{i}", name)
    put(wr, f"C{i}", v, INPUT, fmt, KEY_FILL, CENTER)
    put(wr, f"D{i}", note, align=WRAP)
# Named positions used below
THRESH, WEEKS, NURSE_SHARE, NURSE_COST = ("'Weights & Rules'!$C$14", "'Weights & Rules'!$C$15",
                                         "'Weights & Rules'!$C$16", "'Weights & Rules'!$C$17")
TECH_MAX, PRICE_PTS = "'Weights & Rules'!$C$9", "'Weights & Rules'!$C$10"

# -----------------------------------------------------------------------------
# 3. PAST PERFORMANCE (evidence from our data)
# -----------------------------------------------------------------------------
k = pd.read_csv(ROOT / "data" / "clean" / "fact_order_lines_kpi.csv", parse_dates=["order_month"])
k = k[k["order_month"] >= "2025-11-01"]                     # last 12 months
k["area"] = k["region_id"].isin(["NEA", "NWE"]).map({True: "North", False: "South"})


def perf(v, area=None):
    d = k[k["vendor_id"] == v]
    if area:
        d = d[d["area"] == area]
    conf = d[d["on_time_flag"].notna()]
    if len(conf) == 0:
        return None, None, 0
    return conf["on_time_flag"].mean(), conf["fill_units_shipped"].sum() / conf["fill_units_ordered"].sum(), len(conf)


pp = wb.create_sheet("Past Performance")
widths(pp, [4, 34, 16, 16, 16, 16, 40])
put(pp, "B1", "Incumbent past performance - last 12 months (Nov 2025 - Oct 2026)", TITLE, border=False)
put(pp, "B2", "Source: fact_order_lines_kpi.csv (Steps 2-3), KPI definitions v1.0. Values computed by this script from the data.",
    SUB, border=False)
header(pp, 4, ["Measure", "B1 Northbridge (V01)", "B2 Lakeview (V02)", "Contract target", "", "Reading"], col=2)
rows = []
for label, area in [("On-time delivery - South (4 regions)", "South"), ("On-time delivery - North (NE + NW)", "North")]:
    r1, r2 = perf("V01", area)[0], perf("V02", area)[0]
    rows.append((label, r1, r2, 0.95))
rows.append(("First-shipment fill rate - all regions", perf("V01")[1], perf("V02")[1], 0.98))
exc = k.groupby("vendor_id").apply(lambda d: (d["exception_count"] > 0).mean() * 1000)
rows.append(("Billing exceptions per 1,000 lines", exc["V01"], exc["V02"], None))
notes = ["Both meet target in the South",
         "B1 well below target since Dec 2025 (Step 5: transport issue). B2 has no Northern network today",
         "Both above target", "Similar; neither is an outlier (V06 is)"]
for i, ((label, a, b, t), note) in enumerate(zip(rows, notes), start=5):
    fmt = "0.0" if "exceptions" in label else "0.0%"
    put(pp, f"B{i}", label)
    put(pp, f"C{i}", round(a, 4) if a is not None else "n/a", BASE, fmt, align=CENTER)
    put(pp, f"D{i}", round(b, 4) if b is not None else "No Northern contract", BASE, fmt, align=CENTER)
    put(pp, f"E{i}", t if t is not None else "-", BASE, fmt, align=CENTER)
    put(pp, f"G{i}", note, align=WRAP)
pp.row_dimensions[6].height = 28

# -----------------------------------------------------------------------------
# 4. MANDATORY (Stage 1)
# -----------------------------------------------------------------------------
md = wb.create_sheet("Mandatory")
widths(md, [4, 58, 16, 16, 16, 16])
put(md, "B1", "Stage 1 - Mandatory requirements (pass / fail)", TITLE, border=False)
put(md, "B2", "Enter Pass or Fail. Any Fail disqualifies the bidder from further evaluation.", SUB, border=False)
header(md, 4, ["Requirement"] + SHORT, col=2)
MANDATORY = [
    ("M1 Valid Health Canada medical device licence for the offered product", ["Pass", "Pass", "Pass", "Pass"]),
    ("M2 Delivery to all six Ontario Health regions (own network or named subcontractor)", ["Pass", "Pass", "Pass", "Pass"]),
    ("M3 French-language customer service (French Language Services Act)", ["Pass", "Pass", "Pass", "Fail"]),
    ("M4 Required insurance and WSIB clearance", ["Pass", "Pass", "Pass", "Pass"]),
    ("M5 Signed conflict-of-interest declaration", ["Pass", "Pass", "Pass", "Pass"]),
]
for i, (req, vals) in enumerate(MANDATORY, start=5):
    put(md, f"B{i}", req, align=WRAP)
    for col, v in zip(BCOLS, vals):
        put(md, f"{col}{i}", v, INPUT, align=CENTER)
md["E6"].comment = Comment("B2 has no Northern network today; passes M2 via a named Northern carrier subcontract.", "Evaluator")
md["F7"].comment = Comment("No French-language service line offered in the proposal.", "Evaluator")
put(md, "B10", "Stage 1 result", BOLD, fill=TOTAL_FILL)
for col in BCOLS:
    put(md, f"{col}10", f'=IF(COUNTIF({col}5:{col}9,"Fail")>0,"Disqualified","Pass")', BOLD, fill=TOTAL_FILL, align=CENTER)
md.conditional_formatting.add("C5:F10", CellIsRule(operator="equal", formula=['"Fail"'], fill=RED_FILL))
md.conditional_formatting.add("C5:F10", CellIsRule(operator="equal", formula=['"Disqualified"'], fill=RED_FILL))
md.conditional_formatting.add("C5:F10", CellIsRule(operator="equal", formula=['"Pass"'], fill=GREEN_FILL))

# -----------------------------------------------------------------------------
# 5. TECHNICAL (Stage 2)
# -----------------------------------------------------------------------------
tc = wb.create_sheet("Technical")
widths(tc, [4, 44, 14, 14, 14, 14, 3, 14, 14, 14, 14])
put(tc, "B1", "Stage 2 - Rated technical evaluation", TITLE, border=False)
put(tc, "B2", "Consensus scores 0-5 (blue, editable). Points = score / 5 x criterion points. Evidence in cell comments.",
    SUB, border=False)
put(tc, "C4", "Consensus score (0-5)", BOLD, align=CENTER, border=False)
put(tc, "H4", "Points", BOLD, align=CENTER, border=False)
tc.merge_cells("C4:F4")
tc.merge_cells("H4:K4")
header(tc, 5, ["Criterion"] + SHORT, col=2)
header(tc, 5, SHORT, col=8)
SCORES = [  # B1, B2, B3, B4
    [4, 3, 5, 3],   # T1 product
    [4, 4, 3, 3],   # T2 supply continuity
    [2, 2, 4, 3],   # T3 delivery & North
    [4, 3, 3, 2],   # T4 reporting
    [4, 3, 2, 2],   # T5 implementation
]
EVIDENCE = {
    ("C", 0): "Offers variant C extended-wear foam (up to 7 days). Strong clinician panel feedback.",
    ("C", 2): "Past Performance sheet: on target in the South, but North on-time 78% over 12 months and ~70% in "
              "the latest 6 (Step 5). Corrective action plan submitted but not yet proven.",
    ("D", 2): "No Northern network; relies on a first-time subcontracted carrier. Unproven.",
    ("D", 0): "Standard foam, ~3 changes per week. Meets requirements.",
    ("E", 0): "Silicone-bordered extended-wear foam; 1.75 changes/week in two published-style comparisons provided.",
    ("E", 1): "Single manufacturing source overseas; 60 days of Canadian safety stock offered.",
    ("E", 2): "Depots in Sudbury and Thunder Bay; references report 96% on-time in comparable Northern contracts.",
    ("E", 4): "New to Ontario home care; transition requires clinician retraining across all regions.",
}
for r, ((name, pts, _), scores) in enumerate(zip(CRITERIA, SCORES)):
    row = 6 + r
    put(tc, f"B{row}", name, align=WRAP)
    for j, (col, s) in enumerate(zip(BCOLS, scores)):
        c = put(tc, f"{col}{row}", s, INPUT, "0", align=CENTER)
        if (col, r) in EVIDENCE:
            c.comment = Comment(EVIDENCE[(col, r)], "Evaluator")
        pcol = get_column_letter(8 + j)
        put(tc, f"{pcol}{row}", f"={col}{row}/5*'Weights & Rules'!$C${4 + r}", BASE, "0.0", align=CENTER)

put(tc, "B11", "Technical points", BOLD, fill=TOTAL_FILL)
put(tc, "B12", "% of technical maximum", BOLD, fill=TOTAL_FILL)
put(tc, "B13", "Stage 1 result", BOLD)
put(tc, "B14", "Proceeds to price?", BOLD, fill=TOTAL_FILL)
for j, col in enumerate(BCOLS):
    pcol = get_column_letter(8 + j)
    put(tc, f"{pcol}11", f"=SUM({pcol}6:{pcol}10)", BOLD, "0.0", TOTAL_FILL, CENTER)
    put(tc, f"{pcol}12", f"={pcol}11/{TECH_MAX}", BOLD, "0.0%", TOTAL_FILL, CENTER)
    put(tc, f"{pcol}13", f"=Mandatory!{col}10", LINK, align=CENTER)
    put(tc, f"{pcol}14", f'=IF(AND({pcol}13="Pass",{pcol}12>={THRESH}),"Yes","No")', BOLD, fill=TOTAL_FILL, align=CENTER)
tc.conditional_formatting.add("H14:K14", CellIsRule(operator="equal", formula=['"Yes"'], fill=GREEN_FILL))
tc.conditional_formatting.add("H14:K14", CellIsRule(operator="equal", formula=['"No"'], fill=RED_FILL))

# -----------------------------------------------------------------------------
# 6. PRICE (Stage 3)
# -----------------------------------------------------------------------------
pr = wb.create_sheet("Price")
widths(pr, [4, 46, 16, 16, 16, 16])
put(pr, "B1", "Stage 3 - Price evaluation on cost per healing episode", TITLE, border=False)
put(pr, "B2", "Only bidders that proceed from Stage 2 are price-scored. Unit price alone is shown for comparison but NOT scored.",
    SUB, border=False)
header(pr, 4, ["Item"] + SHORT, col=2)
BIDS = {"unit": [34.88, 19.00, 38.50, 21.00], "changes": [2.0, 3.0, 1.75, 2.5]}
put(pr, "B5", "Bid unit price ($ per dressing)")
put(pr, "B6", "Dressing changes per week (bid product, label claim)")
put(pr, "B7", "Changes per healing episode")
put(pr, "B8", "Dressing cost per episode ($)")
put(pr, "B9", "Nursing cost per episode ($)")
put(pr, "B10", "Total cost per healing episode ($)", BOLD, fill=TOTAL_FILL)
put(pr, "B11", "Proceeds to price?")
put(pr, "B12", "Eligible cost (blank if not eligible)")
put(pr, "B13", "Price points", BOLD, fill=TOTAL_FILL)
put(pr, "B15", "Note: B2 has the LOWEST unit price but did not reach the technical threshold; "
               "it would not have won on episode cost either (see row 10).", SUB, border=False)
for j, col in enumerate(BCOLS):
    tcol = get_column_letter(8 + j)
    put(pr, f"{col}5", BIDS["unit"][j], INPUT, "$#,##0.00", align=CENTER)
    put(pr, f"{col}6", BIDS["changes"][j], INPUT, "0.00", align=CENTER)
    put(pr, f"{col}7", f"={col}6*{WEEKS}", BASE, "0.0", align=CENTER)
    put(pr, f"{col}8", f"={col}7*{col}5", BASE, "$#,##0", align=CENTER)
    put(pr, f"{col}9", f"={col}7*{NURSE_SHARE}*{NURSE_COST}", BASE, "$#,##0", align=CENTER)
    put(pr, f"{col}10", f"={col}8+{col}9", BOLD, "$#,##0", TOTAL_FILL, CENTER)
    put(pr, f"{col}11", f"=Technical!{tcol}14", LINK, align=CENTER)
    put(pr, f"{col}12", f'=IF({col}11="Yes",{col}10,"")', BASE, "$#,##0", align=CENTER)
    put(pr, f"{col}13", f'=IF({col}11="Yes",MIN($C$12:$F$12)/{col}10*{PRICE_PTS},0)', BOLD, "0.0", TOTAL_FILL, CENTER)

# -----------------------------------------------------------------------------
# 7. SUMMARY + weighting sensitivity
# -----------------------------------------------------------------------------
sm = wb.create_sheet("Summary")
widths(sm, [4, 44, 16, 16, 16, 16])
put(sm, "B1", "Evaluation summary and recommendation", TITLE, border=False)
header(sm, 3, ["Result"] + SHORT, col=2)
labels = ["Stage 1 (mandatory)", "Technical points (of 60)", "Technical %", "Proceeds to price?",
          "Price points (of 40)", "TOTAL SCORE (of 100)", "Rank"]
for i, lab in enumerate(labels, start=4):
    put(sm, f"B{i}", lab, BOLD if lab.startswith("TOTAL") else BASE, fill=TOTAL_FILL if lab.startswith("TOTAL") else None)
for j, col in enumerate(BCOLS):
    tcol = get_column_letter(8 + j)
    put(sm, f"{col}4", f"=Mandatory!{col}10", LINK, align=CENTER)
    put(sm, f"{col}5", f"=Technical!{tcol}11", LINK, "0.0", align=CENTER)
    put(sm, f"{col}6", f"=Technical!{tcol}12", LINK, "0.0%", align=CENTER)
    put(sm, f"{col}7", f"=Technical!{tcol}14", LINK, align=CENTER)
    put(sm, f"{col}8", f"=Price!{col}13", LINK, "0.0", align=CENTER)
    put(sm, f"{col}9", f'=IF({col}7="Yes",{col}5+{col}8,"Not eligible")', BOLD, "0.0", TOTAL_FILL, CENTER)
    put(sm, f"{col}10", f'=IF(ISNUMBER({col}9),RANK({col}9,$C$9:$F$9),"-")', BASE, "0", align=CENTER)

put(sm, "B12", "Recommended bidder", BOLD, fill=KEY_FILL)
put(sm, "C12", '=INDEX($C$3:$F$3,MATCH(MAX($C$9:$F$9),$C$9:$F$9,0))', BOLD, fill=KEY_FILL, align=CENTER)
sm.merge_cells("C12:D12")
put(sm, "B13", "Margin over runner-up (points)")
put(sm, "C13", "=LARGE($C$9:$F$9,1)-LARGE($C$9:$F$9,2)", BASE, "0.0", align=CENTER)

# Sensitivity: rescale technical and price to alternative weightings.
put(sm, "B15", "Weighting sensitivity - does the winner change?", BOLD, border=False)
header(sm, 16, ["Price weight"] + SHORT + ["Winner"], col=2)
widths(sm, [4, 44, 16, 16, 16, 16, 18])
for i, pw in enumerate([0.30, 0.40, 0.50], start=17):
    put(sm, f"B{i}", pw, INPUT, "0%", align=CENTER)
    for col in BCOLS:
        # technical share of its max x (1 - pw) x 100 + price share of its max x pw x 100
        put(sm, f"{col}{i}",
            f'=IF({col}$7="Yes",{col}$5/{TECH_MAX}*(1-$B{i})*100+{col}$8/{PRICE_PTS}*$B{i}*100,"-")',
            BASE, "0.0", align=CENTER)
    put(sm, f"G{i}", f'=INDEX($C$3:$F$3,MATCH(MAX(C{i}:F{i}),C{i}:F{i},0))', BOLD, align=CENTER)

put(sm, "B21", "Reading the result", BOLD, border=False)
notes = [
    "B4 is disqualified at Stage 1 (no French-language service), regardless of price.",
    "B2 bid the lowest unit price but falls below the 70% technical threshold, driven by an unproven Northern delivery network.",
    "B1 (incumbent) clears the threshold only narrowly: its Northern delivery record (Step 5) costs it technical points.",
    "B3 wins on both technical merit and cost per episode; the result holds at 30%, 40% and 50% price weighting.",
    "Key risk with B3: new entrant and single overseas manufacturing source -> require safety stock and a transition plan in the contract.",
]
for i, n in enumerate(notes, start=22):
    c = sm.cell(row=i, column=2, value="- " + n)
    c.font, c.alignment = BASE, Alignment(wrap_text=False)

for s in wb.worksheets:
    s.sheet_view.showGridLines = False
wb.move_sheet("Summary", offset=-(len(wb.sheetnames) - 2))   # Summary right after Read Me
wb.save(OUT)
print(f"Saved {OUT}")
