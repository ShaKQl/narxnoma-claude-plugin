"""Command line entry point:
    python -m narxnoma.cli harvest [--source SLUG]
    python -m narxnoma.cli report
"""
import argparse
import logging
import sys

from narxnoma.db.connection import connect
from narxnoma.db.migrate import migrate
from narxnoma.pipeline.harvest import HarvestResult, harvest_all
from narxnoma.pipeline.report import SourceCoverage, coverage_report
from narxnoma.sources import SOURCES


def render_report(rows: list[SourceCoverage]) -> str:
    """Readable coverage table. Suspicious rows get a `*** SUSPICIOUS ***`
    marker so they cannot be skimmed past -- a source that quietly lost most
    of its catalogue is the one failure mode nothing else in this system
    would otherwise surface."""
    header = (f"{'slug':<10} {'offers':>7} {'floor':>7} {'median':>10} "
              f"{'oldest_seen':<20} {'newest_seen':<20} {'last_run_ok':<12} flag")
    lines = [header, "-" * len(header)]
    for r in rows:
        oldest = r.oldest_seen.isoformat(timespec="seconds") if r.oldest_seen else "-"
        newest = r.newest_seen.isoformat(timespec="seconds") if r.newest_seen else "-"
        median = str(r.median_price) if r.median_price is not None else "-"
        last_run_ok = "-" if r.last_run_ok is None else str(r.last_run_ok)
        flag = "*** SUSPICIOUS ***" if r.is_suspicious else ""
        lines.append(f"{r.slug:<10} {r.offers:>7} {r.expected_min:>7} {median:>10} "
                     f"{oldest:<20} {newest:<20} {last_run_ok:<12} {flag}")
    return "\n".join(lines)


def report_exit_code(rows: list[SourceCoverage]) -> int:
    """Non-zero the moment any source is suspicious -- a crawl that
    "succeeded" while losing most of a catalogue is not a success."""
    return 1 if any(r.is_suspicious for r in rows) else 0


def render_status(result: HarvestResult) -> str:
    """Render one of three visibly distinct states for a harvest result.

    `skipped` is checked before `ok` on purpose: a skipped source currently
    also carries ok=True (it isn't a failure), so checking `ok` first would
    render it as plain "ok" -- indistinguishable from a source that
    genuinely swept its whole catalogue. That was the bug: mediapark's
    skip looked identical to a real, successful, zero-listing run.
    """
    if result.skipped:
        return f"SKIPPED ({result.error})"
    if not result.ok:
        return f"FAILED: {result.error}"
    return "ok"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="narxnoma")
    sub = parser.add_subparsers(dest="command", required=True)
    harvest = sub.add_parser("harvest", help="sweep retailers into the database")
    harvest.add_argument("--source", action="append", choices=sorted(SOURCES),
                         help="limit to these sources (repeatable)")
    sub.add_parser("report", help="print per-source coverage and freshness; "
                                  "exits non-zero if any source is suspicious")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.command == "report":
        with connect() as conn:
            migrate(conn)
            rows = coverage_report(conn)
        print(render_report(rows))
        return report_exit_code(rows)

    # harvest
    chosen = [SOURCES[s] for s in (args.source or sorted(SOURCES))]

    with connect() as conn:
        migrate(conn)
        results = harvest_all(conn, chosen)
        rows = coverage_report(conn)

    for r in results:
        logging.info("%-10s seen=%-6d kept=%-6d %s", r.slug, r.seen, r.kept, render_status(r))
    print(render_report(rows))
    return 0 if all(r.ok for r in results) and report_exit_code(rows) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
