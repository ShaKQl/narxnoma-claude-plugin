"""From a `Research` to the finished .xlsx: workbook, then pivots, then an Excel check.

    pivots="auto"    Excel COM if desktop Excel is here, else raw OOXML
    pivots="com"     Excel COM (flat pivots, slicers, chart, Data Model if present); needs Excel
    pivots="ooxml"   written into the package, Excel builds them on open; no slicers / chart / model
    pivots="none"    Tables, formulas, heat map only; Insert > PivotTable > tblOffers does the rest

Order matters and is not negotiable: openpyxl builds, THEN pivots are added, THEN nothing may
re-save the file through openpyxl (it drops slicers and the Data Model without a word).
"""

import logging
import tempfile
from pathlib import Path

from narxnoma.research.model import Research
from narxnoma.research.workbook import build_workbook

logger = logging.getLogger("narxnoma.research")


def make_workbook(
    r: Research, out: str | Path, pivots: str = "auto", model: str = "auto", verify: bool = True
) -> dict:
    from narxnoma.research.excel import ooxml_pivot, pivots as com

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    info: dict = {"out": str(out), "pivots": "none", "lines": [], "errors": None}
    use_com = pivots == "com" or (pivots == "auto" and com.excel_available())
    if pivots == "com" and not com.excel_available():
        raise com.ExcelUnavailable("pivots='com' needs Windows + desktop Excel")

    if use_com:
        tmp = Path(tempfile.mkdtemp(prefix="narxnoma_")) / "built.xlsx"
        layout = build_workbook(r, str(tmp))
        res = com.add_pivots(tmp, out, model=model)
        info["lines"] += res.lines
        if not res.ok:
            raise RuntimeError("Excel pivot step failed:\n" + str(res))
        info["pivots"], info["model"] = "com", res.model
        tmp.unlink(missing_ok=True)
    elif pivots in ("auto", "ooxml"):
        tmp = Path(tempfile.mkdtemp(prefix="narxnoma_")) / "built.xlsx"
        layout = build_workbook(r, str(tmp), pivot_placeholders=True)
        info["lines"] += [
            "PIVOT " + n
            for n in ooxml_pivot.inject_pivots(str(tmp), str(out), layout["offers_cols"])
        ]
        info["pivots"] = "ooxml"
        tmp.unlink(missing_ok=True)
    else:
        layout = build_workbook(r, str(out))

    info.update(layout=layout)
    if verify and com.excel_available():
        res = com.verify(out)
        info["lines"] += res.lines
        info["errors"] = com.error_count(res)
        if info["errors"]:
            logger.error("Excel reports %d formula error cell(s) in %s", info["errors"], out)
    return info
