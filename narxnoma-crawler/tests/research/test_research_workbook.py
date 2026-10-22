import zipfile
import xml.etree.ElementTree as ET

import pytest

openpyxl = pytest.importorskip("openpyxl")

from _synth import make_research  # noqa: E402  (tests/ is on sys.path, no package)

from narxnoma.research.excel.ooxml_pivot import DEFAULT_SPECS, inject_pivots  # noqa: E402
from narxnoma.research.model import Research  # noqa: E402
from narxnoma.research.workbook import BANDS, build_workbook  # noqa: E402


@pytest.fixture()
def research():
    return make_research()


@pytest.fixture()
def built(research, tmp_path):
    path = tmp_path / "r.xlsx"
    layout = build_workbook(research, str(path))
    return path, layout, openpyxl.load_workbook(path)


def test_sheets_and_tables(built):
    _, layout, wb = built
    assert wb.sheetnames == [
        "Start",
        "Prices",
        "Heatmap",
        "Offers",
        "Products",
        "Markets",
        "Links",
        "Settings",
        "Notes",
    ]
    assert set(wb["Offers"].tables) == {"tblOffers"}
    assert set(wb["Products"].tables) == {"tblProducts"}
    assert set(wb["Markets"].tables) == {"tblMarkets"}
    assert layout["n_products"] == 25 and layout["n_offers"] > 25


def test_table_column_names_equal_their_header_cells(built):
    """Excel refuses to open a workbook whose table column names differ from the header text
    ("Column1".. is what openpyxl writes if you initialise columns without restoring names)."""
    _, _, wb = built
    for ws in wb.worksheets:
        for tbl in ws.tables.values():
            header = [c.value for c in ws[1]][: len(tbl.tableColumns)]
            assert [c.name for c in tbl.tableColumns] == [str(h) for h in header]


def test_calculated_columns_fill_new_table_rows(built):
    _, _, wb = built
    cols = {c.name: c for c in wb["Offers"].tables["tblOffers"].tableColumns}
    for name in ("Category", "Baseline", "Delta vs baseline", "Cheapest in product", "Band"):
        assert cols[name].calculatedColumnFormula is not None, name
    pcols = {c.name: c for c in wb["Products"].tables["tblProducts"].tableColumns}
    assert pcols["Baseline"].calculatedColumnFormula is not None
    assert pcols["Our price"].calculatedColumnFormula is None  # an input, not a formula


def test_settings_are_named_cells_with_validation(built):
    _, _, wb = built
    for name in ("cfg_par", "cfg_mid", "cfg_sat", "cfg_baseline"):
        assert name in wb.defined_names
    assert wb["Settings"]["B5"].value == "Our price"
    kinds = {dv.type for dv in wb["Settings"].data_validations.dataValidation}
    assert kinds == {"decimal", "list"}


def test_heat_map_is_conditional_formatting_not_painted_fills(built):
    _, _, wb = built
    prices = wb["Prices"]
    # no market cell carries a static fill
    for row in prices.iter_rows(min_row=2, min_col=4, max_col=3 + 5):
        assert all(c.fill.fill_type in (None, "none") for c in row)
    ((rng, rules),) = prices.conditional_formatting._cf_rules.items()
    kinds = [r.formula[0] for r in rules]
    assert len(rules) == 7  # cheapest-in-row + six graded bands
    assert any("MIN(" in f for f in kinds)
    joined = " ".join(kinds)
    assert all(
        n in joined for n in ("cfg_sat", "cfg_mid", "cfg_par")
    )  # thresholds come from Settings
    assert any(
        r.type == "colorScale"
        for rs in wb["Heatmap"].conditional_formatting._cf_rules.values()
        for r in rs
    )


def test_heat_rules_compare_each_cell_to_its_own_rows_baseline(built):
    _, layout, wb = built
    base_col = openpyxl.utils.get_column_letter(layout["prices_cols"]["baseline"])
    ((_, rules),) = wb["Prices"].conditional_formatting._cf_rules.items()
    graded = [r.formula[0] for r in rules if "cfg_" in r.formula[0]]
    assert all(f"${base_col}2" in f for f in graded)  # relative row, absolute column


def test_formulas_use_prefixed_new_functions(built):
    """MINIFS/MAXIFS written without _xlfn. show #NAME? until a person re-enters the cell."""
    _, _, wb = built
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                if isinstance(c.value, str) and c.value.startswith("="):
                    assert "MINIFS" not in c.value.replace("_xlfn.MINIFS", "")
                    assert "MAXIFS" not in c.value.replace("_xlfn.MAXIFS", "")


def test_one_row_per_offer_and_links_have_hyperlinks(built, research):
    _, _, wb = built
    assert wb["Offers"].max_row - 1 == len(research.offers)
    links = wb["Links"]
    n_links = sum(1 for row in links.iter_rows(min_row=2, min_col=4) for c in row if c.hyperlink)
    n_prices = sum(
        1 for row in links.iter_rows(min_row=2, min_col=4) for c in row if c.value is not None
    )
    assert n_links == n_prices > 0  # every price has a link, every link a price


def test_market_columns_keep_their_order_even_when_empty(built, research):
    _, _, wb = built
    assert [c.value for c in wb["Prices"][1]][3 : 3 + len(research.markets)] == research.markets
    assert wb["Markets"]["H6"].value == "category sweep failed (boom)"  # olcha: a known hole, named


def test_band_labels_sort_in_heat_order():
    assert list(BANDS) == sorted(BANDS)


def test_extra_input_columns_become_pivot_dimensions(built):
    _, _, wb = built
    assert "Brand" in [c.value for c in wb["Products"][1]]


def test_json_roundtrip(research, tmp_path):
    p = tmp_path / "r.json"
    research.to_json(p)
    again = Research.from_json(p)
    assert again == research


def test_empty_inputs_are_refused(tmp_path):
    with pytest.raises(ValueError):
        build_workbook(Research(targets=[], offers=[], markets=["uzum"]), str(tmp_path / "x.xlsx"))


def test_workbook_with_no_offers_still_builds(research, tmp_path):
    research.offers = []
    build_workbook(research, str(tmp_path / "x.xlsx"))


# ---------------------------------------------------------------- raw OOXML pivots
def test_ooxml_pivots_are_wellformed_and_wired(research, tmp_path):
    src, dst = tmp_path / "a.xlsx", tmp_path / "b.xlsx"
    layout = build_workbook(research, str(src), pivot_placeholders=True)
    names = inject_pivots(str(src), str(dst), layout["offers_cols"])
    assert names == [s.name for s in DEFAULT_SPECS]
    z = zipfile.ZipFile(dst)
    for n in z.namelist():
        if n.endswith((".xml", ".rels")):
            ET.fromstring(z.read(n))  # every part parses
    wbx = z.read("xl/workbook.xml").decode()
    assert (
        "<pivotCaches>" in wbx
        and "refreshOnLoad" in z.read("xl/pivotCache/pivotCacheDefinition1.xml").decode()
    )
    ct = z.read("[Content_Types].xml").decode()
    assert ct.count("pivotTable+xml") == 3 and "pivotCacheDefinition+xml" in ct
    assert z.namelist()[0] == "[Content_Types].xml"
    for n in (1, 2, 3):
        assert b"cacheId=" in z.read(f"xl/pivotTables/pivotTable{n}.xml")
    assert openpyxl.load_workbook(dst)["Offers"].tables  # still a readable workbook


def test_ooxml_refuses_a_workbook_without_placeholders(research, tmp_path):
    src = tmp_path / "a.xlsx"
    layout = build_workbook(research, str(src))
    with pytest.raises(ValueError, match="placeholder"):
        inject_pivots(str(src), str(tmp_path / "b.xlsx"), layout["offers_cols"])
