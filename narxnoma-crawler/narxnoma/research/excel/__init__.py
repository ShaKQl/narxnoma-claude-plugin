"""PivotTables and Excel-side verification for research workbooks.

Two ways to get real PivotTables into the file `narxnoma.research.workbook` writes:

    pivots.py        Excel COM (Windows + desktop Excel): flat pivots, slicers, a pivot chart,
                     and -- when this Excel has Power Pivot -- a Data Model with DAX measures.
    ooxml_pivot.py   no Excel at all: the pivot parts are written into the .xlsx package
                     directly and Excel builds them when the file is opened.

Run either AFTER the workbook is built and never re-save the result through openpyxl: it drops
slicers and the Data Model silently.
"""
