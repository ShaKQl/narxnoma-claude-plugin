"""Command line entry point:
    python -m narxnoma.cli fetch --source SLUG [--category C | --query Q]
    python -m narxnoma.cli harvest [--source SLUG]
    python -m narxnoma.cli report
"""
import argparse
import dataclasses
import json
import logging
import sys

from narxnoma.db import repository
from narxnoma.db.connection import connect
from narxnoma.matching.keys import CATEGORIES
from narxnoma.db.migrate import migrate
from narxnoma.pipeline.aggregate import recompute_variant_prices
from narxnoma.pipeline.backfill import DEFAULT_MAX_QUERIES, backfill_search_only_sources
from narxnoma.pipeline import cluster
from narxnoma.pipeline.cluster import cluster_offers
from narxnoma.pipeline.extract import identify
from narxnoma.pipeline.quality import quality_report
from narxnoma.pipeline.quality import render as render_quality
from narxnoma.pipeline.harvest import HarvestResult, harvest_all
from narxnoma.pipeline.report import SourceCoverage, coverage_report
from narxnoma.sources import SOURCES

# A cycle makes 400+ requests at up to a 90-second read timeout; two of them
# overlapping double our request rate at every retailer at once. The advisory
# lock is session-scoped, so Postgres releases it automatically if the
# process dies however it dies -- no cleanup logic to get wrong.
CYCLE_LOCK_KEY = 20260802


def render_report(rows: list[SourceCoverage]) -> str:
    """Readable coverage table. Suspicious rows get a `*** SUSPICIOUS ***`
    marker so they cannot be skimmed past -- a source that quietly lost most
    of its catalogue is the one failure mode nothing else in this system
    would otherwise surface.

    The marker NAMES the rules that fired, because the three of them call for
    three different responses: "never fetched" means the source has never
    stored anything, "stale" means it stored rows once and stopped refreshing
    them (the upsert-only trap -- the count still looks healthy), and
    "last run failed" means the harvest itself errored. A bare SUSPICIOUS
    would leave an operator to guess which.
    """
    header = (f"{'slug':<10} {'offers':>7} {'floor':>7} {'median':>10} "
              f"{'oldest_seen':<20} {'newest_seen':<20} {'age_h':>7} "
              f"{'last_run_ok':<12} flag")
    lines = [header, "-" * len(header)]
    for r in rows:
        oldest = r.oldest_seen.isoformat(timespec="seconds") if r.oldest_seen else "-"
        newest = r.newest_seen.isoformat(timespec="seconds") if r.newest_seen else "-"
        median = str(r.median_price) if r.median_price is not None else "-"
        age = f"{r.age_hours:.1f}" if r.age_hours is not None else "-"
        last_run_ok = "-" if r.last_run_ok is None else str(r.last_run_ok)
        flag = f"*** SUSPICIOUS: {', '.join(r.reasons)} ***" if r.is_suspicious else ""
        lines.append(f"{r.slug:<10} {r.offers:>7} {r.expected_min:>7} {median:>10} "
                     f"{oldest:<20} {newest:<20} {age:>7} "
                     f"{last_run_ok:<12} {flag}")
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


def run_clustering(conn) -> tuple[int, int, int]:
    """reconcile -> extract -> cluster -> aggregate. Returns (attached, created,
    unresolved).

    The reconcile step runs first so that an offer whose name has changed since
    it was attached is back in the unattached pool before clustering loads it.
    Without it a source fix can correct `name_raw` and still leave every
    affected offer sitting on the variant the old, wrong name produced.
    """
    detached = cluster.detach_drifted_offers(conn)
    if detached:
        logging.info("reconciled: detached %d offers whose name no longer matches "
                     "their variant", detached)
    renamed = repository.refresh_display_names(conn)
    if renamed:
        logging.info("reconciled: regenerated %d display names", renamed)
    rows = repository.load_unattached_offers(conn)
    result = cluster_offers(conn, (identify(row) for row in rows))
    # After re-attachment, not before: a variant emptied by the reconcile above
    # is often refilled by the clustering that follows, and deleting it first
    # would churn its id (and its URL) for no reason.
    orphaned = repository.delete_orphan_variants(conn)
    if orphaned:
        logging.info("removed %d variants no offer references any more", orphaned)
    recompute_variant_prices(conn)
    return result.attached, result.created_variants, result.unresolved


def run_backfill(conn) -> int:
    """Query every search-only source for variants the catalogue already has."""
    ids = repository.store_ids(conn)
    written = 0
    with conn.cursor() as cur:
        cur.execute("""
            SELECT v.id, v.display_name
              FROM variant v JOIN variant_price vp ON vp.variant_id = v.id
             ORDER BY vp.store_count DESC, vp.computed_at
             LIMIT %s
        """, (DEFAULT_MAX_QUERIES,))
        variants = cur.fetchall()

    for source in SOURCES.values():
        if source.can_sweep or source.slug not in ids:
            continue
        result = backfill_search_only_sources(conn, source, ids[source.slug], variants)
        logging.info("backfill %-10s queried=%d matched=%d offers=%d",
                     source.slug, result.queried, result.variants_matched,
                     result.offers_written)
        written += result.offers_written
    return written


def _stage(name: str, fn, outcomes: dict) -> None:
    """Run one stage, recording its outcome without letting it kill the rest.

    A clustering failure must not lose the harvest that preceded it: the
    offers are already durably written, and re-running the cycle would just
    re-fetch several thousand listings from retailers for nothing.
    """
    try:
        fn()
        outcomes[name] = True
    except Exception as exc:  # noqa: BLE001 - stage isolation is the point
        logging.exception("stage %s failed", name)
        outcomes[name] = False
        logging.error("%-10s FAILED: %s", name, exc)


def run_fetch(source, category: str, query: str | None, limit: int | None,
              raw: bool, out) -> int:
    """Stream one source's listings as JSON lines, one Listing per line.

    This is the whole engine with the database removed: no Postgres, no
    matcher, no clustering -- exactly what the retailer said, in the shape
    `Listing` guarantees. A search-only source asked to sweep is refused
    here, before any request is made, for the same reason `Source.sweep`
    raises: an empty stream that exits 0 is indistinguishable from an
    empty shop.
    """
    if query is None and not source.can_sweep:
        logging.error("%s cannot be swept (search-only); pass --query", source.slug)
        return 1
    listings = source.search(query) if query is not None else source.sweep(category)
    written = 0
    for listing in listings:
        row = dataclasses.asdict(listing)
        if not raw:
            row.pop("raw")
        out.write(json.dumps(row, ensure_ascii=False) + "\n")
        written += 1
        if limit is not None and written >= limit:
            break
    logging.info("%-10s wrote %d listings", source.slug, written)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="narxnoma")
    sub = parser.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("fetch", help="print one source's listings as JSON lines; "
                                        "needs no database")
    fetch.add_argument("--source", required=True, choices=sorted(SOURCES))
    fetch.add_argument("--category", default="smartphones", choices=sorted(CATEGORIES),
                       help="catalogue sweep to run (default: smartphones)")
    fetch.add_argument("--query", help="search instead of sweeping; the only way "
                                       "into a search-only source such as mediapark")
    fetch.add_argument("--limit", type=int, help="stop after this many listings")
    fetch.add_argument("--raw", action="store_true",
                       help="include the retailer's untouched payload per row")
    harvest = sub.add_parser("harvest", help="sweep retailers into the database")
    harvest.add_argument("--source", action="append", choices=sorted(SOURCES),
                         help="limit to these sources (repeatable)")
    # One category at a time is how a stalled or newly-configured category gets
    # re-run without re-fetching the other six -- a full sweep is 400+ requests
    # and 8-13 minutes, so re-running everything to fix ovens is wasteful and
    # discourages fixing ovens.
    harvest.add_argument("--category", action="append", choices=sorted(CATEGORIES),
                         help="limit to these categories (repeatable; "
                              "default: every category)")
    sub.add_parser("report", help="print per-source coverage and freshness; "
                                  "exits non-zero if any source is suspicious")
    sub.add_parser("cluster", help="identify offers and attach them to canonical "
                                   "products, refusing anything ambiguous")
    sub.add_parser("aggregate", help="recompute each variant's price rollup")
    sub.add_parser("quality", help="matcher health; exits non-zero if the "
                                   "unresolved rate is above the threshold")
    sub.add_parser("cycle", help="harvest, then cluster, aggregate and report "
                                 "quality, isolating each stage")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.command == "fetch":
        # JSON lines are meant to be piped into a file; a Windows console
        # defaulting to cp1251 would otherwise raise on the first Uzbek name.
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        return run_fetch(SOURCES[args.source], args.category, args.query,
                         args.limit, args.raw, sys.stdout)

    if args.command == "report":
        with connect() as conn:
            migrate(conn)
            rows = coverage_report(conn)
        print(render_report(rows))
        return report_exit_code(rows)

    if args.command == "cluster":
        with connect() as conn:
            migrate(conn)
            attached, created, unresolved = run_clustering(conn)
        logging.info("attached=%d new_variants=%d unresolved=%d",
                     attached, created, unresolved)
        return 0

    if args.command == "aggregate":
        with connect() as conn:
            migrate(conn)
            written = recompute_variant_prices(conn)
        logging.info("variant_price rows written: %d", written)
        return 0

    if args.command == "quality":
        with connect() as conn:
            migrate(conn)
            report = quality_report(conn)
        print(render_quality(report))
        return 1 if report.is_alerting else 0

    if args.command == "cycle":
        outcomes: dict[str, bool] = {}
        with connect() as conn:
            migrate(conn)
            if not repository.try_advisory_lock(conn, CYCLE_LOCK_KEY):
                logging.error(
                    "another cycle is already running; refusing to start a "
                    "second one. Two concurrent cycles double our request rate "
                    "at every retailer at once.")
                return 1
            results: list = []
            _stage("harvest", lambda: results.extend(
                harvest_all(conn, [SOURCES[s] for s in sorted(SOURCES)])), outcomes)
            _stage("cluster", lambda: run_clustering(conn), outcomes)
            # Pass B: the sources that cannot be swept are reached by asking
            # about products the catalogue now knows exist. It runs after
            # clustering for that reason, and its results are clustered on the
            # NEXT cycle -- a search hit is a suggestion, not evidence.
            _stage("backfill", lambda: run_backfill(conn), outcomes)
            rows = coverage_report(conn)
            report = quality_report(conn)

        for r in results:
            logging.info("%-10s seen=%-6d kept=%-6d %s",
                         r.slug, r.seen, r.kept, render_status(r))
        print(render_report(rows))
        print()
        print(render_quality(report))

        # The exit code reflects the worst outcome across the whole cycle.
        failed_stage = not all(outcomes.values())
        failed_source = any(not r.ok and not r.skipped for r in results)
        return 1 if (failed_stage or failed_source
                     or report_exit_code(rows) or report.is_alerting) else 0

    # harvest
    chosen = [SOURCES[s] for s in (args.source or sorted(SOURCES))]

    with connect() as conn:
        migrate(conn)
        results = harvest_all(conn, chosen, categories=args.category)
        rows = coverage_report(conn)

    for r in results:
        logging.info("%-10s seen=%-6d kept=%-6d %s", r.slug, r.seen, r.kept, render_status(r))
    print(render_report(rows))
    return 0 if all(r.ok for r in results) and report_exit_code(rows) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
