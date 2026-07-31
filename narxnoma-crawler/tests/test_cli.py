import pytest

from narxnoma.cli import main, render_report, render_status, report_exit_code
from narxnoma.pipeline.harvest import HarvestResult
from narxnoma.pipeline.report import SourceCoverage


def _row(slug, offers, expected_min, is_suspicious):
    return SourceCoverage(slug=slug, offers=offers, median_price=None,
                          oldest_seen=None, newest_seen=None, last_run_ok=None,
                          expected_min=expected_min, is_suspicious=is_suspicious)


def test_render_report_marks_suspicious_rows_distinctly():
    rows = [_row("olcha", 3, 300, True), _row("texnomart", 500, 300, False)]
    out = render_report(rows)
    olcha_line = next(line for line in out.splitlines() if line.startswith("olcha"))
    texnomart_line = next(line for line in out.splitlines() if line.startswith("texnomart"))
    assert "SUSPICIOUS" in olcha_line
    assert "SUSPICIOUS" not in texnomart_line


def test_report_exit_code_nonzero_when_any_source_suspicious():
    assert report_exit_code([_row("olcha", 3, 300, True), _row("idea", 200, 100, False)]) == 1


def test_report_exit_code_zero_when_none_suspicious():
    assert report_exit_code([_row("idea", 200, 100, False)]) == 0


@pytest.mark.db
def test_cli_report_exits_nonzero_when_a_source_is_suspicious(db_conn, dsn, monkeypatch):
    # Reuses the `dsn` fixture (NARXNOMA_TEST_DSN) rather than reading
    # NARXNOMA_DSN directly, so the connection main() ends up using is
    # guaranteed to be the same disposable database db_conn just truncated.
    import narxnoma.cli as cli_module
    from narxnoma.db.connection import connect as real_connect

    monkeypatch.setattr(cli_module, "connect", lambda: real_connect(dsn))

    # db_conn's fixture already truncated offer/raw_offer/harvest_run, so
    # every source sits at zero offers -- below every non-zero floor.
    exit_code = main(["report"])
    assert exit_code != 0


def test_render_status_ok():
    result = HarvestResult("olcha", ok=True, seen=448, kept=448)
    assert render_status(result) == "ok"


def test_render_status_failed():
    result = HarvestResult("idea", ok=False, error="upstream 503")
    assert render_status(result) == "FAILED: upstream 503"


def test_render_status_skipped_is_not_reported_as_ok():
    # Fix 1: a skipped source (mediapark, search-only) must render visibly
    # differently from a source that actually swept its catalogue -- the
    # original bug was that both printed as plain "ok".
    result = HarvestResult("mediapark", ok=True, skipped=True,
                           error="search-only, skipped")
    status = render_status(result)
    assert status != "ok"
    assert status == "SKIPPED (search-only, skipped)"
    assert result.skipped is True
