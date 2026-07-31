"""Command line entry point: python -m narxnoma.cli harvest [--source SLUG]"""
import argparse
import logging
import sys

from narxnoma.db.connection import connect
from narxnoma.db.migrate import migrate
from narxnoma.pipeline.harvest import HarvestResult, harvest_all
from narxnoma.sources import SOURCES


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
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    chosen = [SOURCES[s] for s in (args.source or sorted(SOURCES))]

    with connect() as conn:
        migrate(conn)
        results = harvest_all(conn, chosen)

    for r in results:
        logging.info("%-10s seen=%-6d kept=%-6d %s", r.slug, r.seen, r.kept, render_status(r))
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
