from narxnoma.cli import render_status
from narxnoma.pipeline.harvest import HarvestResult


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
