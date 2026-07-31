"""Stage 1: retailer APIs -> raw_offer + offer.

Each source runs in isolation. A source that fails degrades coverage for
this cycle; it never aborts the others and never corrupts their data. That
isolation guarantee covers the bookkeeping calls (start_run/finish_run) as
much as the sweep itself -- a transient database hiccup on start_run must
not be any more fatal to the cycle than a transient upstream 503.
"""
import logging
from dataclasses import dataclass

from narxnoma.db import repository as default_repo

logger = logging.getLogger(__name__)

# Flush accumulated listings through the repository every this-many items
# instead of buffering an entire sweep in memory and writing it all at the
# end. repository.py's own docstring justifies the per-call commit boundary
# by saying a source that dies half way through should keep what it already
# fetched -- that guarantee is worthless if nothing is written until the
# generator that feeds it is fully exhausted. Harmless at today's sizes
# (olcha ~448) but matters as uzum's and alifshop's brand-by-brand paging
# grows.
WRITE_BATCH_SIZE = 500


@dataclass
class HarvestResult:
    """Outcome of one source's harvest attempt.

    `seen` and `kept` are currently always equal, which makes `seen`
    misleading if read as "how many items the retailer's catalogue had."
    Every Listing that reaches `sweep()`'s caller already passed validation
    inside the client via `try_build_listing` (sources/base.py) -- items
    that fail that validation are logged and dropped *before* they are
    yielded, not counted here. So `seen` counts listings the client chose
    to yield, not raw catalogue items. Threading a genuine drop count out
    of all seven clients is a larger change than this one; the honest fix
    for now is not pretending seen/kept can diverge. Task 12's
    EXPECTED_MIN_OFFERS floors -- not a gap between these two fields -- are
    what actually catch a source silently shrinking.
    """

    slug: str
    ok: bool
    seen: int = 0
    kept: int = 0
    error: str | None = None
    #: True when the source was never attempted because can_sweep is False
    #: (or another skip condition below). Kept distinct from `error` being
    #: set so callers never have to infer "was this a failure or a skip"
    #: from whether error happens to be non-None -- see harvest_all and
    #: cli.py's render_status.
    skipped: bool = False


def _flush_batch(conn, repo, store_id, batch: list) -> int:
    """Write one batch of listings through both tables. Returns the count
    written, so the caller can keep a running total across batches."""
    repo.record_raw_offers(conn, store_id, batch)
    repo.upsert_offers(conn, store_id, batch)
    return len(batch)


def harvest_source(conn, source, store_id, repo=default_repo) -> HarvestResult:
    """Sweep one source and persist what it yields, in WRITE_BATCH_SIZE chunks.

    The entire function body -- including start_run and both finish_run
    calls -- lives inside the try block. Nothing here may propagate out to
    harvest_all: a database error on start_run is a source-independent
    failure just like a database error on finish_run, and either one
    escaping would abort every source still queued behind this one, which
    is exactly the isolation guarantee this module exists to provide.
    """
    listings_seen = kept = 0
    run_id = None
    try:
        run_id = repo.start_run(conn, store_id)

        batch: list = []
        for listing in source.sweep():
            listings_seen += 1
            batch.append(listing)
            if len(batch) >= WRITE_BATCH_SIZE:
                kept += _flush_batch(conn, repo, store_id, batch)
                batch = []
        if batch:
            kept += _flush_batch(conn, repo, store_id, batch)

        # See HarvestResult's docstring: listings_seen == kept here isn't a
        # coincidence worth preserving as a health signal, it's structural.
        repo.finish_run(conn, run_id, ok=True, seen=listings_seen, kept=kept)
        return HarvestResult(source.slug, ok=True, seen=listings_seen, kept=kept)
    except Exception as exc:                     # noqa: BLE001 - isolation is the point
        logger.exception("harvest failed for %s", source.slug)
        if run_id is not None:
            try:
                repo.finish_run(conn, run_id, ok=False, seen=listings_seen,
                                kept=kept, error=str(exc))
            except Exception:                     # noqa: BLE001 - see above
                # Recording the failure itself failed (e.g. the same DB
                # hiccup that caused start_run/writes to fail in the first
                # place). Log it and still return a failed HarvestResult --
                # raising here would defeat the whole point of this
                # try/except by taking the rest of the cycle down with it.
                logger.exception(
                    "also failed to record the failure against run %s for %s; "
                    "its harvest_run row may be left unfinished",
                    run_id, source.slug)
        return HarvestResult(source.slug, ok=False, seen=listings_seen,
                             kept=kept, error=str(exc))


def harvest_all(conn, sources, repo=default_repo) -> list[HarvestResult]:
    ids = repo.store_ids(conn)
    results = []
    for source in sources:
        # A search-only source (mediapark) has no catalogue to browse. Skip it
        # explicitly rather than calling sweep() -- sweep() raises for those, and
        # honouring can_sweep is the caller's job. skipped=True (not just a
        # string stuffed into `error`) is what lets the CLI render this
        # distinctly from an ordinary successful sweep -- see base.py's
        # Source protocol docstring for why an indistinguishable-from-success
        # skip is precisely the failure mode this must not become.
        if not source.can_sweep:
            logger.info("skipping %s: search-only source, nothing to sweep", source.slug)
            results.append(HarvestResult(source.slug, ok=True, skipped=True,
                                         error="search-only, skipped"))
            continue
        store_id = ids.get(source.slug)
        if store_id is None:
            results.append(HarvestResult(source.slug, ok=False, error="store not seeded"))
            continue
        results.append(harvest_source(conn, source, store_id, repo=repo))
    return results
