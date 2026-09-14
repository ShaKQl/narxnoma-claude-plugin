import pytest

from narxnoma.cli import main, render_report, render_status, report_exit_code
from narxnoma.pipeline.harvest import HarvestResult
from narxnoma.pipeline.report import BELOW_FLOOR, LAST_RUN_FAILED, STALE, SourceCoverage


def _row(slug, offers, expected_min, reasons=()):
    return SourceCoverage(slug=slug, offers=offers, median_price=None,
                          oldest_seen=None, newest_seen=None, last_run_ok=None,
                          expected_min=expected_min, reasons=tuple(reasons),
                          age_hours=1.0)


def test_render_report_marks_suspicious_rows_distinctly():
    rows = [_row("olcha", 3, 300, [BELOW_FLOOR]), _row("texnomart", 500, 300)]
    out = render_report(rows)
    olcha_line = next(line for line in out.splitlines() if line.startswith("olcha"))
    texnomart_line = next(line for line in out.splitlines() if line.startswith("texnomart"))
    assert "SUSPICIOUS" in olcha_line
    assert "SUSPICIOUS" not in texnomart_line


def test_render_report_names_the_rule_that_fired():
    """A bare SUSPICIOUS cannot be acted on. "stale" and "last run failed"
    have different causes and different fixes from "below floor", and the
    stale case is invisible in the count column -- offers clears its floor.
    """
    rows = [_row("olcha", 448, 300, [STALE]),
            _row("idea", 3, 100, [BELOW_FLOOR, LAST_RUN_FAILED])]
    out = render_report(rows)
    olcha_line = next(line for line in out.splitlines() if line.startswith("olcha"))
    idea_line = next(line for line in out.splitlines() if line.startswith("idea"))
    assert STALE in olcha_line
    assert BELOW_FLOOR not in olcha_line
    assert BELOW_FLOOR in idea_line and LAST_RUN_FAILED in idea_line


def test_report_exit_code_nonzero_when_any_source_suspicious():
    assert report_exit_code([_row("olcha", 3, 300, [BELOW_FLOOR]),
                             _row("idea", 200, 100)]) == 1


def test_report_exit_code_zero_when_none_suspicious():
    assert report_exit_code([_row("idea", 200, 100)]) == 0


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


# --- Plan 3: the clustering subcommands -----------------------------------

def test_new_subcommands_are_registered():
    """A typo in a subcommand name should fail here, not in a cron job."""

    from narxnoma import cli

    for command in ("cluster", "aggregate", "quality", "cycle"):
        with pytest.raises(SystemExit) as exc:
            cli.main([command, "--nonsense"])
        assert exc.value.code == 2, f"{command} is not a registered subcommand"


def test_cycle_isolates_a_failing_stage(monkeypatch):
    """A clustering failure must not lose the harvest that preceded it.

    Those offers are already durably written; re-running the whole cycle would
    re-fetch several thousand listings from retailers for nothing.
    """
    from narxnoma import cli

    calls = []

    def boom(conn):
        calls.append("cluster")
        raise RuntimeError("clustering blew up")

    monkeypatch.setattr(cli, "run_clustering", boom)
    monkeypatch.setattr(cli, "harvest_all", lambda conn, sources: calls.append("harvest") or [])
    monkeypatch.setattr(cli, "migrate", lambda conn: None)
    monkeypatch.setattr(cli.repository, "try_advisory_lock", lambda conn, key: True)
    monkeypatch.setattr(cli, "coverage_report", lambda conn: [])
    monkeypatch.setattr(cli, "quality_report", lambda conn: _FakeQuality())

    class _NullConn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(cli, "connect", lambda: _NullConn())

    monkeypatch.setattr(cli, "render_quality", lambda r: "")
    monkeypatch.setattr(cli, "render_report", lambda rows: "")

    code = cli.main(["cycle"])

    assert "harvest" in calls, "harvest must still have run"
    assert "cluster" in calls, "clustering must have been attempted"
    assert code == 1, "a failed stage must make the cycle exit non-zero"


class _FakeQuality:
    is_alerting = False
    total_offers = 0
    attached = 0
    unresolved = 0
    variants = 0
    single_offer_variants = 0
    diverging_variants = 0
    reasons: list = []
    unresolved_by_store: list = []
    unresolved_rate = 0.0


def test_cycle_refuses_to_run_twice_at_once(db_conn, dsn, monkeypatch):
    import psycopg
    from narxnoma.cli import CYCLE_LOCK_KEY, main
    from narxnoma.db.repository import try_advisory_lock

    holder = psycopg.connect(dsn)
    try:
        assert try_advisory_lock(holder, CYCLE_LOCK_KEY) is True
        monkeypatch.setenv("NARXNOMA_DSN", dsn)
        assert main(["cycle"]) == 1
    finally:
        holder.close()


# --- fetch: the database-free path ------------------------------------------

class _FakeSource:
    slug = "fake"
    can_sweep = True

    def __init__(self):
        self.calls = []

    def sweep(self, category="smartphones"):
        from narxnoma.sources.base import Listing
        self.calls.append(("sweep", category))
        for i in range(3):
            yield Listing(store_slug="fake", source_key=f"k{i}", name_raw=f"Phone {i}",
                          price=1_000_000 + i, url=f"https://fake/{i}", category=category)

    def search(self, query):
        from narxnoma.sources.base import Listing
        self.calls.append(("search", query))
        yield Listing(store_slug="fake", source_key="q", name_raw=query,
                      price=2_000_000, url="https://fake/q")


def test_fetch_sweeps_without_a_database(monkeypatch, capsys):
    """`fetch` must never touch connect(): it is the path someone without
    Postgres uses to get prices out of a source in one command."""
    import json
    from narxnoma import cli

    fake = _FakeSource()
    monkeypatch.setattr(cli, "SOURCES", {"fake": fake})
    monkeypatch.setattr(cli, "connect", lambda: (_ for _ in ()).throw(AssertionError("db touched")))

    code = cli.main(["fetch", "--source", "fake", "--category", "laptops"])

    assert code == 0
    assert fake.calls == [("sweep", "laptops")]
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [r["source_key"] for r in rows] == ["k0", "k1", "k2"]
    assert rows[0]["price"] == 1_000_000 and rows[0]["category"] == "laptops"
    assert "raw" not in rows[0], "raw payload stays out unless --raw is asked for"


def test_fetch_query_uses_search_and_limit_stops_early(monkeypatch, capsys):
    import json
    from narxnoma import cli

    fake = _FakeSource()
    monkeypatch.setattr(cli, "SOURCES", {"fake": fake})

    code = cli.main(["fetch", "--source", "fake", "--query", "iphone 16", "--limit", "1"])

    assert code == 0
    assert fake.calls == [("search", "iphone 16")]
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(rows) == 1 and rows[0]["name_raw"] == "iphone 16"


def test_fetch_refuses_to_sweep_a_search_only_source(monkeypatch, capsys):
    """mediapark has no catalogue browse; asking to sweep it must fail loudly
    rather than print nothing and exit 0."""
    from narxnoma import cli

    fake = _FakeSource()
    fake.can_sweep = False
    monkeypatch.setattr(cli, "SOURCES", {"fake": fake})

    code = cli.main(["fetch", "--source", "fake"])

    assert code == 1
    assert fake.calls == []
    assert capsys.readouterr().out == ""


def test_fetch_raw_includes_the_retailer_payload(monkeypatch, capsys):
    import json
    from narxnoma import cli

    fake = _FakeSource()
    monkeypatch.setattr(cli, "SOURCES", {"fake": fake})

    cli.main(["fetch", "--source", "fake", "--raw", "--limit", "1"])

    row = json.loads(capsys.readouterr().out.splitlines()[0])
    assert "raw" in row
