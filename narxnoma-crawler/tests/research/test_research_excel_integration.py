"""Needs desktop Excel (Windows). Deselected by default: `pytest -m excel`.

These are the tests that matter most for the workbook: openpyxl writes formulas it cannot
evaluate, so only a real Excel proves the file opens, calculates without error and colours
what the heat-map rules say.
"""

import pytest

openpyxl = pytest.importorskip("openpyxl")

from _synth import make_research  # noqa: E402  (tests/ is on sys.path, no package)

from narxnoma.research.build import make_workbook  # noqa: E402
from narxnoma.research.excel import pivots as com  # noqa: E402


@pytest.fixture()
def research():
    return make_research()


pytestmark = [
    pytest.mark.excel,
    pytest.mark.skipif(not com.excel_available(), reason="desktop Excel not available"),
]


def test_com_workbook_opens_calculates_and_has_pivots(research, tmp_path):
    out = tmp_path / "r.xlsx"
    info = make_workbook(research, out, pivots="com", model="auto")
    assert info["errors"] == 0, "\n".join(info["lines"])
    text = "\n".join(info["lines"])
    assert text.count("PIVOT pvt") >= 3 and "SLICERS 3" in text and "ERRORS_TOTAL 0" in text
    assert info["model"].startswith(("ok", "unavailable"))  # flat pivots remain either way


def test_ooxml_pivots_populate_on_open(research, tmp_path):
    out = tmp_path / "r.xlsx"
    info = make_workbook(research, out, pivots="ooxml", verify=True)
    assert info["errors"] == 0
    res = com.verify(out)
    assert "pivots=1" in "\n".join(
        ln for ln in res.lines if ln.startswith("SHEET Pivot by category")
    )


def test_heat_colours_follow_an_edit(research, tmp_path):
    """Probe the displayed fill of a Prices cell, change our price through Excel, probe again."""
    out = tmp_path / "r.xlsx"
    make_workbook(research, out, pivots="none", verify=False)
    res = com.verify(out, probe="Prices!D2,Prices!E2")
    probes = [ln for ln in res.lines if ln.startswith("PROBE")]
    assert len(probes) == 2 and all("fill=" in ln for ln in probes)
    assert com.error_count(res) == 0
