"""Pass B: reach the one source that cannot be swept.

mediapark exposes only an autocomplete endpoint — no catalogue browse, no
pagination — so `can_sweep` is False and `sweep()` raises. The only way to
reach it is to ask about products we already know exist, which is why this
runs after clustering rather than during harvest.

It reads the variant list produced by the **previous** cycle, deliberately.
Feeding it this cycle's clustering output would make the pipeline cyclic for
one source's benefit; the cost is that a brand-new phone gets its mediapark
offer one cycle late, which is four hours.
"""
import logging
from dataclasses import dataclass

from narxnoma.db import repository as default_repo

logger = logging.getLogger(__name__)

# One cycle must stay bounded. The catalogue grows without limit, but a
# backfill that scales with it would eventually outlast the four-hour window
# and collide with the next run. Variants are taken oldest-queried first, so
# the whole catalogue is still covered over successive cycles.
DEFAULT_MAX_QUERIES = 200


@dataclass
class BackfillResult:
    queried: int = 0
    offers_written: int = 0
    variants_matched: int = 0
    misses: int = 0


def build_query(display_name: str) -> str:
    """What to ask mediapark for.

    Kept nearly verbatim, including the memory figure and the colour word.
    Unlike every other source here, mediapark *ranks* rather than filtering
    with strict AND, so stripping terms measurably worsens recall — see
    docs/parsers/mediapark.md. The only thing removed is our own generated
    prefix, which is ours and not something a retailer would index.
    """
    query = display_name.strip()
    for prefix in ("Смартфон ", "Smartfon "):
        if query.startswith(prefix):
            query = query[len(prefix):]
    return query.replace(" ГБ,", "").replace(" ГБ", "").strip()


def backfill_search_only_sources(conn, source, store_id, variants,
                                 repo=default_repo,
                                 max_queries: int = DEFAULT_MAX_QUERIES) -> BackfillResult:
    """Search one non-sweepable source for products we already know about.

    `variants` is a sequence of (variant_id, display_name) from a previous
    cycle. Listings that come back are written as ordinary offers; clustering
    will decide on the next run whether each one really is that variant. This
    stage does not attach anything itself, because a search hit is a
    suggestion, not evidence.
    """
    result = BackfillResult()

    for _variant_id, display_name in list(variants)[:max_queries]:
        query = build_query(display_name)
        result.queried += 1
        try:
            listings = list(source.search(query))
        except Exception as exc:  # noqa: BLE001 - one bad query must not end the pass
            logger.warning("backfill query failed for %r: %s", query, exc)
            result.misses += 1
            continue

        if not listings:
            result.misses += 1
            continue

        repo.record_raw_offers(conn, store_id, listings)
        inserted, updated = repo.upsert_offers(conn, store_id, listings)
        result.offers_written += inserted + updated
        result.variants_matched += 1

    logger.info(
        "backfill %s: %d queried, %d matched, %d offers written, %d misses",
        getattr(source, "slug", "?"), result.queried, result.variants_matched,
        result.offers_written, result.misses)
    return result
