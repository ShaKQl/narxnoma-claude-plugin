"""Stage 1: retailer APIs -> raw_offer + offer.

Each source runs in isolation. A source that fails degrades coverage for
this cycle; it never aborts the others and never corrupts their data.
"""
import logging
from dataclasses import dataclass

from narxnoma.db import repository as default_repo

logger = logging.getLogger(__name__)


@dataclass
class HarvestResult:
    slug: str
    ok: bool
    seen: int = 0
    kept: int = 0
    error: str | None = None


def harvest_source(conn, source, store_id, repo=default_repo) -> HarvestResult:
    run_id = repo.start_run(conn, store_id)
    seen = kept = 0
    try:
        listings = []
        for listing in source.sweep():
            seen += 1
            listings.append(listing)
        kept = len(listings)
        repo.record_raw_offers(conn, store_id, listings)
        repo.upsert_offers(conn, store_id, listings)
    except Exception as exc:                     # noqa: BLE001 - isolation is the point
        logger.exception("harvest failed for %s", source.slug)
        repo.finish_run(conn, run_id, ok=False, seen=seen, kept=kept, error=str(exc))
        return HarvestResult(source.slug, ok=False, seen=seen, kept=kept, error=str(exc))

    repo.finish_run(conn, run_id, ok=True, seen=seen, kept=kept)
    return HarvestResult(source.slug, ok=True, seen=seen, kept=kept)


def harvest_all(conn, sources, repo=default_repo) -> list[HarvestResult]:
    ids = repo.store_ids(conn)
    results = []
    for source in sources:
        # A search-only source (mediapark) has no catalogue to browse. Skip it
        # explicitly rather than calling sweep() -- sweep() raises for those, and
        # honouring can_sweep is the caller's job.
        if not source.can_sweep:
            logger.info("skipping %s: search-only source, nothing to sweep", source.slug)
            results.append(HarvestResult(source.slug, ok=True, error="search-only, skipped"))
            continue
        store_id = ids.get(source.slug)
        if store_id is None:
            results.append(HarvestResult(source.slug, ok=False, error="store not seeded"))
            continue
        results.append(harvest_source(conn, source, store_id, repo=repo))
    return results
