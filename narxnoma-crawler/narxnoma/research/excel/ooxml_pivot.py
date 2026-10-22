"""PivotTables with no Excel: write the pivot parts into the .xlsx package and let Excel build them.

openpyxl cannot create a PivotTable (it can only carry one through), and COM needs desktop Excel.
This writes the minimum a PivotTable needs -- a cache definition whose source is the Excel Table
`tblOffers`, an empty records part, and one pivot-table definition per spec -- and marks the cache
`refreshOnLoad`, so Excel fills the shared items, the totals and the cells itself on first open.
That is the same trick libraries such as EPPlus use. What it does NOT give you: slicers, pivot
charts, the Data Model, number formats beyond the built-in ones (the COM path has all of them).

Run on a workbook built with `build_workbook(..., pivot_placeholders=True)`: the empty
'Pivot ...' sheets it creates are where these land. Never re-save the result through openpyxl.
"""

import posixpath
import re
import zipfile
from dataclasses import dataclass
from xml.sax.saxutils import escape

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
CT_DEF = "application/vnd.openxmlformats-officedocument.spreadsheetml.pivotCacheDefinition+xml"
CT_REC = "application/vnd.openxmlformats-officedocument.spreadsheetml.pivotCacheRecords+xml"
CT_TBL = "application/vnd.openxmlformats-officedocument.spreadsheetml.pivotTable+xml"

_AXIS_FIELD = (
    '<pivotField axis="{axis}" showAll="0">'
    '<items count="1"><item t="default"/></items></pivotField>'
)

# built-in number formats: 3 = #,##0   10 = 0.00%   (custom formats would need a styles.xml edit)
NUMFMT_INT, NUMFMT_PCT = 3, 10


@dataclass
class PivotSpec:
    name: str  # pivot table name, e.g. "pvtCategoryMarket"
    sheet: str  # placeholder sheet it lands on
    anchor: str  # top-left cell of the pivot, e.g. "A5"
    row_field: str  # a column of tblOffers
    col_field: str
    data_field: str
    function: str  # sum | count | average | min | max
    caption: str
    numfmt: int = NUMFMT_INT


DEFAULT_SPECS = (
    PivotSpec(
        "pvtCategoryMarket",
        "Pivot by category",
        "A5",
        "Category",
        "Market",
        "Delta vs baseline",
        "average",
        "Avg delta vs baseline",
        NUMFMT_PCT,
    ),
    PivotSpec(
        "pvtPriceMatrix",
        "Pivot price matrix",
        "A5",
        "Product",
        "Market",
        "Price",
        "min",
        "Cheapest price",
        NUMFMT_INT,
    ),
    PivotSpec(
        "pvtMarketBands",
        "Pivot market bands",
        "A5",
        "Market",
        "Band",
        "Product",
        "count",
        "Offers",
        NUMFMT_INT,
    ),
)


def _cache_xml(fields: list[str]) -> str:
    cf = "".join(
        f'<cacheField name="{escape(f)}" numFmtId="0"><sharedItems/></cacheField>' for f in fields
    )
    return (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<pivotCacheDefinition xmlns="{NS_MAIN}" xmlns:r="{NS_R}" r:id="rId1" refreshOnLoad="1" '
        f'refreshedBy="narxnoma" refreshedDate="45000" createdVersion="3" refreshedVersion="3" '
        f'minRefreshableVersion="3" recordCount="0"><cacheSource type="worksheet">'
        f'<worksheetSource name="tblOffers"/></cacheSource><cacheFields count="{len(fields)}">{cf}'
        f"</cacheFields></pivotCacheDefinition>"
    )


def _records_xml() -> str:
    return (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<pivotCacheRecords xmlns="{NS_MAIN}" xmlns:r="{NS_R}" count="0"/>'
    )


def _table_xml(spec: PivotSpec, fields: list[str], cache_id: int) -> str:
    ri, ci, di = (fields.index(f) for f in (spec.row_field, spec.col_field, spec.data_field))
    pf = []
    for i, _ in enumerate(fields):
        if i == ri:
            pf.append(_AXIS_FIELD.format(axis="axisRow"))
        elif i == ci:
            pf.append(_AXIS_FIELD.format(axis="axisCol"))
        elif i == di:
            pf.append('<pivotField dataField="1" showAll="0"/>')
        else:
            pf.append('<pivotField showAll="0"/>')
    col = re.match(r"([A-Z]+)(\d+)", spec.anchor)
    ref = f"{spec.anchor}:{col.group(1)}{int(col.group(2)) + 2}"  # a stub: Excel resizes on refresh
    return (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<pivotTableDefinition xmlns="{NS_MAIN}" name="{escape(spec.name)}" cacheId="{cache_id}" '
        f'dataCaption="Values" updatedVersion="3" minRefreshableVersion="3" createdVersion="3" '
        f'useAutoFormatting="1" itemPrintTitles="1" indent="0" outline="1" outlineData="1" '
        f'multipleFieldFilters="0"><location ref="{ref}" firstHeaderRow="1" firstDataRow="2" '
        f'firstDataCol="1"/>'
        f'<pivotFields count="{len(fields)}">{"".join(pf)}</pivotFields>'
        f'<rowFields count="1"><field x="{ri}"/></rowFields>'
        f'<colFields count="1"><field x="{ci}"/></colFields>'
        f'<dataFields count="1"><dataField name="{escape(spec.caption)}" fld="{di}" '
        f'subtotal="{spec.function}" '
        f'baseField="0" baseItem="0" numFmtId="{spec.numfmt}"/></dataFields>'
        f'<pivotTableStyleInfo name="PivotStyleMedium2" showRowHeaders="1" showColHeaders="1" '
        f'showRowStripes="1" showColStripes="0" showLastColumn="1"/></pivotTableDefinition>'
    )


def _rels_xml(rels: list[tuple[str, str, str]]) -> str:
    body = "".join(f'<Relationship Id="{i}" Type="{t}" Target="{tg}"/>' for i, t, tg in rels)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{body}</Relationships>'
    )


def _next_rid(rels_xml: str) -> str:
    ids = [int(m) for m in re.findall(r'Id="rId(\d+)"', rels_xml)]
    return f"rId{max(ids, default=0) + 1}"


def inject_pivots(src: str, dst: str, offers_fields: list[str], specs=DEFAULT_SPECS) -> list[str]:
    """Copy `src` to `dst` with the pivot parts added. Returns the names of the pivots written."""
    zin = zipfile.ZipFile(src)
    parts = {n: zin.read(n) for n in zin.namelist()}
    zin.close()

    wbx = parts["xl/workbook.xml"].decode("utf-8")
    wbr = parts["xl/_rels/workbook.xml.rels"].decode("utf-8")
    ctx = parts["[Content_Types].xml"].decode("utf-8")
    sheet_target = {}
    for m in re.finditer(r'<sheet\b[^>]*?name="([^"]+)"[^>]*?r:id="([^"]+)"', wbx):
        t = re.search(
            rf'<Relationship\b[^>]*?Id="{m.group(2)}"[^>]*?Target="([^"]+)"', wbr
        ) or re.search(rf'<Relationship\b[^>]*?Target="([^"]+)"[^>]*?Id="{m.group(2)}"', wbr)
        sheet_target[m.group(1)] = posixpath.normpath(
            posixpath.join("xl", t.group(1).lstrip("/").removeprefix("xl/"))
        )
    missing = [s.sheet for s in specs if s.sheet not in sheet_target]
    if missing:
        raise ValueError(
            f"placeholder sheet(s) missing: {missing}; build with pivot_placeholders=True"
        )

    cache_id = 1
    parts["xl/pivotCache/pivotCacheDefinition1.xml"] = _cache_xml(offers_fields).encode("utf-8")
    parts["xl/pivotCache/pivotCacheRecords1.xml"] = _records_xml().encode("utf-8")
    parts["xl/pivotCache/_rels/pivotCacheDefinition1.xml.rels"] = _rels_xml(
        [("rId1", f"{REL}/pivotCacheRecords", "pivotCacheRecords1.xml")]
    ).encode("utf-8")
    overrides = [
        ("/xl/pivotCache/pivotCacheDefinition1.xml", CT_DEF),
        ("/xl/pivotCache/pivotCacheRecords1.xml", CT_REC),
    ]

    rid = _next_rid(wbr)
    wbr = wbr.replace(
        "</Relationships>",
        f'<Relationship Id="{rid}" Type="{REL}/pivotCacheDefinition" '
        f'Target="pivotCache/pivotCacheDefinition1.xml"/></Relationships>',
    )
    pc_xml = (
        f'<pivotCaches><pivotCache xmlns:r="{NS_R}" cacheId="{cache_id}" r:id="{rid}"/>'
        "</pivotCaches>"
    )
    if "<pivotCaches" in wbx:
        raise ValueError("workbook already has pivot caches")
    if re.search(r"<calcPr\b[^>]*/>", wbx):
        wbx = re.sub(r"(<calcPr\b[^>]*/>)", r"\1" + pc_xml, wbx, count=1)
    else:
        wbx = wbx.replace("</workbook>", pc_xml + "</workbook>")

    written = []
    for n, spec in enumerate(specs, 1):
        tpath = f"xl/pivotTables/pivotTable{n}.xml"
        parts[tpath] = _table_xml(spec, offers_fields, cache_id).encode("utf-8")
        parts[f"xl/pivotTables/_rels/pivotTable{n}.xml.rels"] = _rels_xml(
            [("rId1", f"{REL}/pivotCacheDefinition", "../pivotCache/pivotCacheDefinition1.xml")]
        ).encode("utf-8")
        overrides.append((f"/{tpath}", CT_TBL))
        sheet_part = sheet_target[spec.sheet]
        rels_part = posixpath.join(
            posixpath.dirname(sheet_part), "_rels", posixpath.basename(sheet_part) + ".rels"
        )
        cur = parts.get(rels_part, _rels_xml([]).encode("utf-8")).decode("utf-8")
        srid = _next_rid(cur)
        cur = cur.replace(
            "</Relationships>",
            f'<Relationship Id="{srid}" Type="{REL}/pivotTable" '
            f'Target="../pivotTables/pivotTable{n}.xml"/></Relationships>',
        )
        parts[rels_part] = cur.encode("utf-8")
        written.append(spec.name)

    ctx = ctx.replace(
        "</Types>",
        "".join(f'<Override PartName="{p}" ContentType="{c}"/>' for p, c in overrides) + "</Types>",
    )
    parts["xl/workbook.xml"] = wbx.encode("utf-8")
    parts["xl/_rels/workbook.xml.rels"] = wbr.encode("utf-8")
    parts["[Content_Types].xml"] = ctx.encode("utf-8")

    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        zout.writestr("[Content_Types].xml", parts.pop("[Content_Types].xml"))  # must be first
        for name, data in parts.items():
            zout.writestr(name, data)
    return written
