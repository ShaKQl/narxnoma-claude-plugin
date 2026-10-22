"""Market research: a list of products -> every market's offers -> an analysable workbook.

    targets.py    read the product list (csv / xlsx / txt)
    collect.py    sweep or search the markets, with an on-disk cache
    match.py      the matching engine applied to a target list, keeping every offer
    model.py      Target / Offer / Research and the JSON that lets a workbook be rebuilt
    workbook.py   the analysable .xlsx (Excel Tables, formulas, heat map, Settings)
    excel/        PivotTables: Excel COM driver, Data Model probe, raw-OOXML writer

Everything outside `workbook.py` and `excel/` needs only the standard library and
`requests`; the workbook layer needs `openpyxl` (extra: `pip install narxnoma-crawler[excel]`).
"""
