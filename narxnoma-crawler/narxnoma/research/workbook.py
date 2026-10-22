"""The analysable workbook: a database you can pivot, and formulas that follow your edits.

A static survey file is a picture. This one is a small database plus a view of it:

    Offers    Excel Table `tblOffers`   one row per (product x market) offer, every one kept. The
                                        pivot source. Category / Baseline / Delta / Band are
                                        formulas, so a table row you add fills itself in.
    Products  Excel Table `tblProducts` one row per researched product. Our price is an INPUT
                                        (yellow): change it and every delta, colour, band follows.
    Markets   Excel Table `tblMarkets`  one row per market: coverage, delta, wins, freshness.
    Prices    product x market grid     the cheapest accepted offer per market, as formulas over
                                        `tblOffers`, plus min / median / delta columns. Heat map.
    Heatmap   product x market grid     each cell's difference from baseline, colour scale.
    Links     product x market grid     as-fetched snapshot, every price a hyperlink to its offer.
    Settings  thresholds + baseline     named cells (cfg_par, cfg_mid, cfg_sat, cfg_baseline) that
                                        the heat map, the bands and the pivots all read.
    Notes     provenance                every derived number defined, every market's freshness.

The heat map is CONDITIONAL FORMATTING, never a baked fill. A baked fill goes stale the moment
a price is edited, and a wrong colour is read faster than the number it contradicts. Each rule
compares a cell to ITS ROW's baseline -- which a colour scale cannot do, a formula rule can --
and takes its thresholds from Settings, so it is data-driven and survives a re-sort.

PivotTables are not made here: openpyxl cannot write them and would drop them on re-save. Run
`excel/` (COM, or the raw-OOXML writer) AFTER this module, and never re-save the result through
openpyxl: it silently removes slicers.
"""

from datetime import datetime

from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.formatting.rule import ColorScaleRule, FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter as L
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.workbook.properties import CalcProperties
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.hyperlink import Hyperlink
from openpyxl.worksheet.table import Table, TableStyleInfo

from narxnoma.research.model import Research

NAVY = "1F3864"
HEADER_FILL = PatternFill("solid", fgColor=NAVY)
HEADER_FONT = Font(bold=True, color="FFFFFF")
INPUT_FILL = PatternFill("solid", fgColor="FFF2CC")
LINK_FONT = Font(color="0563C1", underline="single")
MONEY = "#,##0"
PCT = "+0.0%;-0.0%;0.0%"

# heat colours, darkest = furthest from the baseline. Red: the market is CHEAPER than the
# baseline (we are exposed); green: the market is dearer (our price is competitive).
HEAT = {
    "cheap3": "F8696B",
    "cheap2": "FBA39C",
    "cheap1": "FDD9D6",
    "dear1": "DDF0E1",
    "dear2": "A9D8B2",
    "dear3": "63BE7B",
}

BANDS = (
    "1 Market much cheaper",
    "2 Market cheaper",
    "3 Market slightly cheaper",
    "4 About equal",
    "5 Market slightly dearer",
    "6 Market dearer",
    "7 Market much dearer",
)


def tr(table: str, col: str) -> str:
    """Structured reference to a column of the current row."""
    return f"{table}[[#This Row],[{col}]]"


def _header(ws, row, titles, widths=None):
    for i, t in enumerate(titles, 1):
        c = ws.cell(row=row, column=i, value=t)
        c.fill, c.font = HEADER_FILL, HEADER_FONT
        c.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
        if widths:
            ws.column_dimensions[L(i)].width = widths[i - 1]
    ws.row_dimensions[row].height = 32


def _table(ws, name, ref, style="TableStyleMedium2"):
    t = Table(displayName=name, ref=ref)
    t.tableStyleInfo = TableStyleInfo(name=style, showRowStripes=True)
    ws.add_table(t)
    return t


def _calc_columns(ws, table: Table, formulas: dict[str, str]) -> None:
    """Mark columns as calculated so a row added to the table fills itself in.

    `_initialise_columns()` names every column "Column1..N"; the names must be put back from the
    header cells or Excel refuses to open the file (table column names must equal the header text).
    """
    from openpyxl.worksheet.table import TableFormula

    table._initialise_columns()
    first = table.ref.split(":")[0]
    row = int("".join(ch for ch in first if ch.isdigit()))
    for i, col in enumerate(table.tableColumns, 1):
        col.name = str(ws.cell(row=row, column=i).value)
        if col.name in formulas:
            col.calculatedColumnFormula = TableFormula(attr_text=formulas[col.name])


def _uzs(target, usd_rate):
    if target.our_price is None:
        return None
    if target.currency == "USD":
        return round(target.our_price * usd_rate) if usd_rate else None
    return target.our_price


PIVOT_PLACEHOLDERS = (
    ("Pivot by category", "Average market price vs baseline, by category and market"),
    ("Pivot price matrix", "Cheapest price by product and market"),
    ("Pivot market bands", "Offers per heat band, by market"),
)


def build_workbook(r: Research, path: str, pivot_placeholders: bool = False) -> dict:
    """Write the workbook. Returns the layout facts the pivot step needs.

    `pivot_placeholders=True` adds empty 'Pivot ...' sheets for the raw-OOXML pivot writer
    (excel/ooxml_pivot.py) to land on. The COM driver creates its own sheets: leave this False.
    """
    markets = list(r.markets)
    nm = len(markets)
    n = len(r.targets)
    if not n or not nm:
        raise ValueError("a workbook needs at least one product and one market")
    wb = Workbook()
    wb.calculation = CalcProperties(fullCalcOnLoad=True)
    wb.properties.title = r.title
    wb.properties.creator = "narxnoma"
    wb.properties.subject = "Market research: Offers / Products / Markets tables, Prices heat map"

    ws_start = wb.active
    ws_start.title = "Start"
    ws_prices = wb.create_sheet("Prices")
    ws_heat = wb.create_sheet("Heatmap")
    if pivot_placeholders:
        for name, title in PIVOT_PLACEHOLDERS:
            ph = wb.create_sheet(name)
            ph["A1"], ph["A1"].font = title, Font(bold=True, size=14)
            ph["A2"], ph["A2"].font = (
                (
                    "Built by Excel when this file is opened (refresh on load). "
                    "Data > Refresh All after edits."
                ),
                Font(italic=True, color="808080"),
            )
    ws_off = wb.create_sheet("Offers")
    ws_prod = wb.create_sheet("Products")
    ws_mkt = wb.create_sheet("Markets")
    ws_links = wb.create_sheet("Links")
    ws_set = wb.create_sheet("Settings")
    ws_notes = wb.create_sheet("Notes")

    # ------------------------------------------------------------------ Settings
    _header(ws_set, 1, ["Setting", "Value", "What it does"], [34, 16, 90])
    settings = [
        (
            "Par band (+/-)",
            0.02,
            "cfg_par",
            "Differences inside this band count as 'about equal' (no colour).",
        ),
        ("Moderate difference from", 0.10, "cfg_mid", "Medium red / green from here."),
        (
            "Strong difference from",
            0.20,
            "cfg_sat",
            "Darkest red / green from here; the Heatmap colour scale saturates here.",
        ),
        (
            "Baseline",
            "Our price",
            "cfg_baseline",
            "What every delta is measured against: 'Our price' or 'Market median'. "
            "A product with no price of ours always falls back to the median.",
        ),
    ]
    for i, (label, val, name, note) in enumerate(settings, 2):
        ws_set.cell(row=i, column=1, value=label)
        c = ws_set.cell(row=i, column=2, value=val)
        c.fill = INPUT_FILL
        if name != "cfg_baseline":
            c.number_format = "0%"
        ws_set.cell(row=i, column=3, value=note).alignment = Alignment(
            wrap_text=True, vertical="top"
        )
        wb.defined_names[name] = DefinedName(name, attr_text=f"Settings!$B${i}")
    dv = DataValidation(
        type="decimal",
        operator="between",
        formula1="0",
        formula2="1",
        showErrorMessage=True,
        errorTitle="Threshold",
        error="Enter a fraction between 0 and 1 (0.1 = 10%).",
    )
    ws_set.add_data_validation(dv)
    dv.add("B2:B4")
    dv2 = DataValidation(
        type="list", formula1='"Our price,Market median"', allow_blank=False, showErrorMessage=True
    )
    ws_set.add_data_validation(dv2)
    dv2.add("B5")
    ws_set["A8"] = "Heat-map legend (market price vs baseline)"
    ws_set["A8"].font = Font(bold=True)
    legend = [
        ("cheap3", "Market much cheaper (<= -strong)"),
        ("cheap2", "Market cheaper (<= -moderate)"),
        ("cheap1", "Market slightly cheaper"),
        (None, "About equal (inside the par band)"),
        ("dear1", "Market slightly dearer"),
        ("dear2", "Market dearer (>= +moderate)"),
        ("dear3", "Market much dearer (>= +strong)"),
    ]
    for i, (key, text) in enumerate(legend, 9):
        sw = ws_set.cell(row=i, column=1, value=text)
        if key:
            sw.fill = PatternFill("solid", fgColor=HEAT[key])
    ws_set.cell(row=16, column=1, value="Bold border = the cheapest price in its row").font = Font(
        bold=True
    )

    # ------------------------------------------------------ Products (inputs + per-product facts)
    # column order is fixed up front: later formulas address columns by header name
    extra_keys = sorted({k for t in r.targets for k in t.extra})
    p_in = [
        "Product",
        "Category",
        "Our price",
        "Currency",
        "Our price original",
        "Note",
    ] + extra_keys
    p_calc = ["Baseline", "Offers", "Cheapest", "Highest", "Average", "Ours vs cheapest"]
    p_cols = p_in + p_calc
    pc = {name: i for i, name in enumerate(p_cols, 1)}
    _header(
        ws_prod,
        1,
        p_cols,
        [52, 16, 16, 9, 16, 28] + [18] * len(extra_keys) + [16, 9, 16, 16, 16, 16],
    )
    prices_median_col = 3 + nm + 4  # Prices: A B C | markets | Baseline Matched Min Median ...
    for i, t in enumerate(r.targets, 2):
        ws_prod.cell(row=i, column=pc["Product"], value=t.name)
        ws_prod.cell(row=i, column=pc["Category"], value=t.category or "")
        up = _uzs(t, r.usd_rate)
        c = ws_prod.cell(row=i, column=pc["Our price"], value=up)
        c.number_format, c.fill = MONEY, INPUT_FILL
        ws_prod.cell(row=i, column=pc["Category"]).fill = INPUT_FILL
        ws_prod.cell(row=i, column=pc["Currency"], value=t.currency)
        if t.our_price is not None:
            ws_prod.cell(
                row=i, column=pc["Our price original"], value=t.our_price
            ).number_format = "#,##0.##"
        ws_prod.cell(row=i, column=pc["Note"], value=t.note)
        for k in extra_keys:
            ws_prod.cell(row=i, column=pc[k], value=t.extra.get(k))
        mc = L(prices_median_col)
        f = {
            "Baseline": (
                f'=IF(AND(cfg_baseline="Our price",ISNUMBER({tr("tblProducts", "Our price")}),'
                f"N({tr('tblProducts', 'Our price')})>0),{tr('tblProducts', 'Our price')},"
                f"IFERROR(INDEX(Prices!${mc}:${mc},"
                f'MATCH({tr("tblProducts", "Product")},Prices!$A:$A,0)),""))'
            ),
            "Offers": f"=COUNTIFS(tblOffers[Product],{tr('tblProducts', 'Product')})",
            "Cheapest": (
                f'=IF({tr("tblProducts", "Offers")}=0,"",_xlfn.MINIFS(tblOffers[Price],'
                f"tblOffers[Product],{tr('tblProducts', 'Product')}))"
            ),
            "Highest": (
                f'=IF({tr("tblProducts", "Offers")}=0,"",_xlfn.MAXIFS(tblOffers[Price],'
                f"tblOffers[Product],{tr('tblProducts', 'Product')}))"
            ),
            "Average": (
                f'=IF({tr("tblProducts", "Offers")}=0,"",AVERAGEIFS(tblOffers[Price],'
                f"tblOffers[Product],{tr('tblProducts', 'Product')}))"
            ),
            "Ours vs cheapest": (
                f"=IF(AND(ISNUMBER({tr('tblProducts', 'Our price')}),"
                f"ISNUMBER({tr('tblProducts', 'Cheapest')})),"
                f'{tr("tblProducts", "Our price")}/{tr("tblProducts", "Cheapest")}-1,"")'
            ),
        }
        for name in p_calc:
            c = ws_prod.cell(row=i, column=pc[name], value=f[name])
            c.number_format = PCT if name == "Ours vs cheapest" else MONEY
    prod_last = n + 1
    t_prod = _table(ws_prod, "tblProducts", f"A1:{L(len(p_cols))}{prod_last}")
    _calc_columns(ws_prod, t_prod, {k: ws_prod.cell(row=2, column=pc[k]).value[1:] for k in p_calc})
    ws_prod.freeze_panes = "B2"

    # ------------------------------------------------------------------ Offers (the pivot source)
    o_cols = [
        "Product",
        "Category",
        "Market",
        "Listing",
        "Price",
        "Availability",
        "Score",
        "Name delta",
        "URL",
        "Fetched",
        "Baseline",
        "Delta vs baseline",
        "Cheapest in product",
        "Band",
    ]
    oc = {name: i for i, name in enumerate(o_cols, 1)}
    _header(ws_off, 1, o_cols, [52, 16, 12, 56, 14, 14, 8, 36, 50, 20, 14, 12, 11, 26])
    order = {t.name: i for i, t in enumerate(r.targets)}
    offers = sorted(
        r.offers,
        key=lambda o: (
            order.get(o.target, 0),
            markets.index(o.market) if o.market in markets else 99,
            o.price,
        ),
    )
    o_f = {
        "Category": (
            f"=IFERROR(INDEX(tblProducts[Category],MATCH({tr('tblOffers', 'Product')},"
            f'tblProducts[Product],0)),"")'
        ),
        "Baseline": (
            f"=IFERROR(INDEX(tblProducts[Baseline],MATCH({tr('tblOffers', 'Product')},"
            f'tblProducts[Product],0)),"")'
        ),
        "Delta vs baseline": (
            f"=IF(AND(ISNUMBER({tr('tblOffers', 'Baseline')}),"
            f"N({tr('tblOffers', 'Baseline')})>0),"
            f'{tr("tblOffers", "Price")}/{tr("tblOffers", "Baseline")}-1,"")'
        ),
        "Cheapest in product": (
            f"=IF({tr('tblOffers', 'Price')}=_xlfn.MINIFS(tblOffers[Price],"
            f"tblOffers[Product],{tr('tblOffers', 'Product')}),1,0)"
        ),
    }
    d = tr("tblOffers", "Delta vs baseline")
    o_f["Band"] = (
        f'=IF({d}="","",IF({d}<=-cfg_sat,"{BANDS[0]}",IF({d}<=-cfg_mid,"{BANDS[1]}",'
        f'IF({d}<-cfg_par,"{BANDS[2]}",IF({d}<=cfg_par,"{BANDS[3]}",IF({d}<cfg_mid,"{BANDS[4]}",'
        f'IF({d}<cfg_sat,"{BANDS[5]}","{BANDS[6]}")))))))'
    )
    fetched_default = r.run_at[:19].replace("T", " ")
    for i, o in enumerate(offers, 2):
        ws_off.cell(row=i, column=oc["Product"], value=o.target)
        ws_off.cell(row=i, column=oc["Market"], value=o.market)
        ws_off.cell(row=i, column=oc["Listing"], value=o.listing_name)
        ws_off.cell(row=i, column=oc["Price"], value=o.price).number_format = MONEY
        ws_off.cell(row=i, column=oc["Availability"], value=o.availability)
        ws_off.cell(row=i, column=oc["Score"], value=o.score)
        ws_off.cell(row=i, column=oc["Name delta"], value=o.name_delta)
        u = ws_off.cell(row=i, column=oc["URL"], value=o.url)
        u.hyperlink, u.font = o.url, LINK_FONT
        ws_off.cell(
            row=i,
            column=oc["Fetched"],
            value=(r.fetched_at.get(o.market) or fetched_default)[:19].replace("T", " "),
        )
        for name, f in o_f.items():
            c = ws_off.cell(row=i, column=oc[name], value=f)
            if name == "Baseline":
                c.number_format = MONEY
            elif name == "Delta vs baseline":
                c.number_format = PCT
    off_last = max(len(offers) + 1, 2)
    if not offers:  # a table needs one data row to be valid
        ws_off.cell(row=2, column=1, value="(no offers found)")
    t_off = _table(ws_off, "tblOffers", f"A1:{L(len(o_cols))}{off_last}")
    if offers:
        _calc_columns(ws_off, t_off, {k: ws_off.cell(row=2, column=oc[k]).value[1:] for k in o_f})
    ws_off.freeze_panes = "B2"
    ws_off.auto_filter.ref = None

    # --------------------------------------------------------- Prices (formula grid + heat map)
    p_head = (
        ["Product", "Category", "Our price"]
        + markets
        + [
            "Baseline",
            "Markets matched",
            "Market min",
            "Market median",
            "Delta ours vs median",
            "Cheapest market",
        ]
    )
    _header(ws_prices, 1, p_head, [52, 16, 14] + [14] * nm + [14, 9, 14, 14, 12, 14])
    m0, m1 = 4, 3 + nm  # first / last market column
    bcol, ncol, mincol, medcol, dcol, chcol = (m1 + k for k in range(1, 7))
    assert medcol == prices_median_col

    def R(row):
        return f"{L(m0)}{row}:{L(m1)}{row}"

    for i, t in enumerate(r.targets, 2):
        key = f"$A{i}"
        ws_prices.cell(row=i, column=1, value=f"=INDEX(tblProducts[Product],{i - 1})")
        ws_prices.cell(row=i, column=2, value=f"=INDEX(tblProducts[Category],{i - 1})")
        c = ws_prices.cell(
            row=i,
            column=3,
            value=f'=IF(INDEX(tblProducts[Our price],{i - 1})="","",'
            f"INDEX(tblProducts[Our price],{i - 1}))",
        )
        c.number_format = MONEY
        for j in range(nm):
            col = L(m0 + j)
            c = ws_prices.cell(
                row=i,
                column=m0 + j,
                value=(
                    f'=IF(COUNTIFS(tblOffers[Product],{key},tblOffers[Market],{col}$1)=0,"",'
                    f"_xlfn.MINIFS(tblOffers[Price],tblOffers[Product],{key},tblOffers[Market],{col}$1))"
                ),
            )
            c.number_format = MONEY
        ws_prices.cell(
            row=i,
            column=bcol,
            value=(
                f'=IFERROR(INDEX(tblProducts[Baseline],MATCH({key},tblProducts[Product],0)),"")'
            ),
        ).number_format = MONEY
        ws_prices.cell(row=i, column=ncol, value=f"=COUNT({R(i)})")
        ws_prices.cell(
            row=i, column=mincol, value=f'=IF(COUNT({R(i)})=0,"",MIN({R(i)}))'
        ).number_format = MONEY
        ws_prices.cell(
            row=i, column=medcol, value=f'=IF(COUNT({R(i)})=0,"",MEDIAN({R(i)}))'
        ).number_format = MONEY
        ws_prices.cell(
            row=i,
            column=dcol,
            value=(
                f"=IF(AND(ISNUMBER($C{i}),ISNUMBER({L(medcol)}{i})),IF({L(medcol)}{i}>0,"
                f'$C{i}/{L(medcol)}{i}-1,""),"")'
            ),
        ).number_format = PCT
        ws_prices.cell(
            row=i,
            column=chcol,
            value=(
                f'=IF(COUNT({R(i)})=0,"",INDEX(${L(m0)}$1:${L(m1)}$1,MATCH(MIN({R(i)}),{R(i)},0)))'
            ),
        )
    last = n + 1
    ws_prices.freeze_panes = "D2"
    ws_prices.auto_filter.ref = f"A1:{L(chcol)}{max(last, 2)}"
    # heat map: rules compare each cell with ITS ROW's baseline and read thresholds from Settings
    grid = f"{L(m0)}2:{L(m1)}{max(last, 2)}"
    c0, B = f"{L(m0)}2", f"${L(bcol)}2"
    ok = f"AND(ISNUMBER({c0}),N({B})>0,"
    ws_prices.conditional_formatting.add(
        grid,
        FormulaRule(
            formula=[f"AND(ISNUMBER({c0}),{c0}=MIN(${L(m0)}2:${L(m1)}2))"],
            font=Font(bold=True),
            border=Border(*(Side(style="medium", color="1F3864"),) * 4),
        ),
    )
    rules = [
        (f"{ok}{c0}<={B}*(1-cfg_sat))", HEAT["cheap3"]),
        (f"{ok}{c0}<={B}*(1-cfg_mid))", HEAT["cheap2"]),
        (f"{ok}{c0}<{B}*(1-cfg_par))", HEAT["cheap1"]),
        (f"{ok}{c0}>={B}*(1+cfg_sat))", HEAT["dear3"]),
        (f"{ok}{c0}>={B}*(1+cfg_mid))", HEAT["dear2"]),
        (f"{ok}{c0}>{B}*(1+cfg_par))", HEAT["dear1"]),
    ]
    for formula, colour in rules:
        ws_prices.conditional_formatting.add(
            grid,
            FormulaRule(
                formula=[formula],
                fill=PatternFill("solid", bgColor=colour, fgColor=colour),
                stopIfTrue=True,
            ),
        )

    # --------------------------------------------------------- Heatmap (graded colour scale)
    _header(ws_heat, 1, ["Product"] + markets, [52] + [14] * nm)
    for i in range(2, last + 1):
        ws_heat.cell(row=i, column=1, value=f"=Prices!A{i}")
        for j in range(nm):
            pcell = f"Prices!{L(m0 + j)}{i}"
            ws_heat.cell(
                row=i,
                column=2 + j,
                value=(
                    f'=IF(AND(ISNUMBER({pcell}),N(Prices!${L(bcol)}{i})>0),{pcell}/Prices!${L(bcol)}{i}-1,"")'
                ),
            ).number_format = PCT
    if n:
        ws_heat.conditional_formatting.add(
            f"B2:{L(1 + nm)}{last}",
            ColorScaleRule(
                start_type="formula",
                start_value="-cfg_sat",
                start_color=HEAT["cheap3"],
                mid_type="num",
                mid_value=0,
                mid_color="FFFFFF",
                end_type="formula",
                end_value="cfg_sat",
                end_color=HEAT["dear3"],
            ),
        )
    ws_heat.freeze_panes = "B2"
    ws_heat["A" + str(last + 2)] = (
        "Each cell: (market price - baseline) / baseline. Red = the market is cheaper "
        "than the baseline, green = dearer. Thresholds: Settings."
    )
    ws_heat["A" + str(last + 2)].font = Font(italic=True, color="808080")

    # ------------------------------------------------------------------ Markets
    mk_cols = [
        "Market",
        "Offers",
        "Products covered",
        "Average delta",
        "Share cheaper than baseline",
        "Cheapest wins",
        "Catalogue fetched",
        "Note",
    ]
    _header(ws_mkt, 1, mk_cols, [14, 9, 16, 14, 18, 12, 24, 70])
    dgrid = f"Heatmap!$B$2:${L(1 + nm)}${max(last, 2)}"
    hhead = f"Heatmap!$B$1:${L(1 + nm)}$1"
    pgrid = f"Prices!${L(m0)}$2:${L(m1)}${max(last, 2)}"
    phead = f"Prices!${L(m0)}$1:${L(m1)}$1"
    pmin = f"Prices!${L(mincol)}$2:${L(mincol)}${max(last, 2)}"
    for i, m in enumerate(markets, 2):
        mref = tr("tblMarkets", "Market")
        ws_mkt.cell(row=i, column=1, value=m)
        ws_mkt.cell(row=i, column=2, value=f"=COUNTIFS(tblOffers[Market],{mref})")
        ws_mkt.cell(
            row=i,
            column=3,
            value=(
                f"=SUMPRODUCT((tblOffers[Market]={mref})/COUNTIFS(tblOffers[Product],tblOffers[Product],"
                f'tblOffers[Market],tblOffers[Market]&""))'
            )
            if offers
            else 0,
        )
        col = f"INDEX({dgrid},0,MATCH({mref},{hhead},0))"
        ws_mkt.cell(row=i, column=4, value=f'=IFERROR(AVERAGE({col}),"")').number_format = PCT
        ws_mkt.cell(
            row=i, column=5, value=f'=IFERROR(COUNTIF({col},"<0")/COUNT({col}),"")'
        ).number_format = "0%"
        ws_mkt.cell(
            row=i,
            column=6,
            value=(
                f"=SUMPRODUCT(--(INDEX({pgrid},0,MATCH({mref},{phead},0))={pmin}),"
                f"--ISNUMBER({pmin}))"
            ),
        )
        ws_mkt.cell(row=i, column=7, value=(r.fetched_at.get(m) or "")[:19].replace("T", " "))
        ws_mkt.cell(
            row=i,
            column=8,
            value=r.notes.get(m) or ("" if m in r.fetched_at else "no data collected"),
        )
    mk_last = nm + 1
    _table(ws_mkt, "tblMarkets", f"A1:{L(len(mk_cols))}{mk_last}")
    ws_mkt.freeze_panes = "B2"
    if nm and offers:
        ch = BarChart()
        ch.type, ch.style = "bar", 2
        ch.title = "Average market price vs baseline, by market"
        ch.title.overlay = False
        ch.add_data(Reference(ws_mkt, min_col=4, min_row=1, max_row=mk_last), titles_from_data=True)
        ch.set_categories(Reference(ws_mkt, min_col=1, min_row=2, max_row=mk_last))
        # openpyxl 3.1 hides both axes unless told otherwise; labels go "low" so a negative bar
        # does not run over its own market name
        ch.x_axis.delete = False
        ch.y_axis.delete = False
        ch.x_axis.tickLblPos = "low"
        ch.x_axis.scaling.orientation = "maxMin"  # first market on top, as in the table
        ch.y_axis.number_format = "0%"
        ch.y_axis.majorGridlines.spPr = None
        ch.legend = None
        serie = ch.series[0]
        serie.graphicalProperties.solidFill = NAVY
        serie.invertIfNegative = False
        ch.height, ch.width = 9, 18
        ws_mkt.add_chart(ch, f"A{mk_last + 3}")

    # ------------------------------------------------------------------ Links (as-fetched snapshot)
    _header(ws_links, 1, ["Product", "Category", "Our price"] + markets, [52, 16, 14] + [14] * nm)
    cheapest = {}
    for o in offers:
        k = (o.target, o.market)
        if k not in cheapest or o.price < cheapest[k].price:
            cheapest[k] = o
    for i, t in enumerate(r.targets, 2):
        ws_links.cell(row=i, column=1, value=t.name)
        ws_links.cell(row=i, column=2, value=t.category or "")
        up = _uzs(t, r.usd_rate)
        ws_links.cell(row=i, column=3, value=up).number_format = MONEY
        for j, m in enumerate(markets):
            o = cheapest.get((t.name, m))
            if o:
                c = ws_links.cell(row=i, column=4 + j, value=o.price)
                c.hyperlink, c.font, c.number_format = o.url, LINK_FONT, MONEY
    ws_links.freeze_panes = "D2"

    # ------------------------------------------------------------------ Notes
    found = {o.target for o in offers}
    stale = ", ".join(f"{m} {t[:16].replace('T', ' ')}" for m, t in sorted(r.fetched_at.items()))
    nodata = ", ".join(
        m for m in markets if m not in r.fetched_at or not any(o.market == m for o in offers)
    )
    rows = [
        ("Run", r.run_at.replace("T", " ")),
        ("Products", f"{n} researched, {len(found)} with at least one offer."),
        ("Catalogue freshness", stale or "n/a"),
        ("Markets with no offers", nodata or "none"),
        (
            "A market cell",
            "The cheapest accepted offer of that market for that product (Prices = formulas over "
            "tblOffers; Links = as-fetched snapshot with hyperlinks). Every other offer stays "
            "in Offers.",
        ),
        (
            "Market median",
            "Median of one representative (cheapest) price per market, so a marketplace with many "
            "sellers does not outvote a single-shop retailer.",
        ),
        (
            "Baseline",
            "Settings!cfg_baseline: 'Our price' (default) or 'Market median'. A product with no "
            "price of "
            "ours uses the median.",
        ),
        (
            "Delta vs baseline",
            "(market price - baseline) / baseline. Negative = the market is cheaper than the "
            "baseline. 'Delta ours vs median' on Prices is the other way round: "
            "(our price - median) / median, positive = we are dearer.",
        ),
        ("Empty cell", "No match found. Never a price of zero."),
        (
            "Identity rule",
            "Brand, model, RAM and storage must match; colour is not identity except on iPhones. "
            "Phones accept at score >= 30, other categories at >= 25 (brand + model tokens "
            "both ways).",
        ),
        (
            "Name delta",
            "Words present in one name but not the other. Not an error by itself: read it before "
            "quoting a row.",
        ),
        (
            "Heat map",
            "Conditional formatting over Prices and Heatmap, thresholds from Settings. "
            "It follows edits "
            "and re-sorts; nothing is painted by hand.",
        ),
        (
            "Formulas",
            "MINIFS / MAXIFS need Excel 2019 / Microsoft 365 (or LibreOffice). Pivot "
            "refresh: Data > "
            "Refresh All; PivotTables read tblOffers, which grows when you add rows.",
        ),
        (
            "Currency",
            "Prices in UZS."
            + (
                f" USD inputs converted at {r.usd_rate:,.2f} UZS ({r.usd_rate_date})."
                if r.usd_rate
                else ""
            ),
        ),
    ]
    ws_notes.column_dimensions["A"].width = 26
    ws_notes.column_dimensions["B"].width = 120
    for i, (k, v) in enumerate(rows, 1):
        ws_notes.cell(row=i, column=1, value=k).font = Font(bold=True)
        ws_notes.cell(row=i, column=2, value=v).alignment = Alignment(
            wrap_text=True, vertical="top"
        )

    # ------------------------------------------------------------------ Start
    ws_start.column_dimensions["A"].width = 24
    ws_start.column_dimensions["B"].width = 100
    ws_start["A1"] = r.title
    ws_start["A1"].font = Font(bold=True, size=16, color=NAVY)
    ws_start["A2"] = (
        f"{n} products x {nm} markets, {len(offers)} offers. Built {datetime.now():%Y-%m-%d %H:%M}."
    )
    guide = [
        (
            "Prices",
            "Heat map: cheapest price per market, coloured against your baseline. "
            "Bold border = cheapest in row.",
        ),
        ("Heatmap", "The same grid as percentage differences, graded colour scale."),
        (
            "Offers",
            "The database: every offer. Pivot source. Add or delete rows; formulas fill "
            "and the grid follows.",
        ),
        (
            "Products",
            "Your products. Yellow cells (Our price, Category) are inputs: change them and "
            "everything follows.",
        ),
        ("Markets", "Scoreboard per market, with a chart."),
        ("Links", "As-fetched prices, each one a hyperlink to its offer."),
        ("Settings", "Heat-map thresholds and the baseline."),
        ("Notes", "Definitions, freshness, what an empty cell means."),
    ]
    for i, (sheet, text) in enumerate(guide, 4):
        c = ws_start.cell(row=i, column=1, value=sheet)
        c.hyperlink = Hyperlink(ref=c.coordinate, location=f"'{sheet}'!A1", display=sheet)
        c.font = LINK_FONT
        ws_start.cell(row=i, column=2, value=text)
    ws_start.cell(row=13, column=1, value="PivotTables").font = Font(bold=True)
    ws_start.cell(
        row=13,
        column=2,
        value=(
            "Sheets named 'Pivot ...' (if present) read tblOffers. Data > Refresh All "
            "after you change anything. To build your own: Insert > PivotTable > "
            "Table/Range = tblOffers."
        ),
    )

    wb.save(path)
    return {
        "markets": markets,
        "n_products": n,
        "n_offers": len(offers),
        "offers_cols": o_cols,
        "path": path,
        "prices_cols": {"first_market": m0, "last_market": m1, "baseline": bcol},
    }
