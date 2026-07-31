"""Coverage and freshness per source.

A source that quietly returns fewer rows is more dangerous than one that
raises, because nothing alerts. Every source built so far shares this blind
spot: all of them raise loudly when an endpoint 404s or returns non-JSON,
but none of them notice a retailer that starts answering HTTP 200 with an
empty item list. In that case `sweep()` exits cleanly after page one, the
harvest records `ok = True` with zero listings, and the catalogue quietly
empties while every check stays green.

`harvest.HarvestResult.seen`/`kept` cannot catch this -- they are
structurally identical (see that module's docstring). This report is what
catches it instead, by comparing each source's live offer count against a
measured floor.
"""
from dataclasses import dataclass
from datetime import datetime

# Measured live 2026-07-26/27. These are floors, not targets: a source returning
# far fewer offers than this has almost certainly had its endpoint rescoped, not
# had its catalogue shrink. Update deliberately, with a note, never to silence an alert.
EXPECTED_MIN_OFFERS = {
    "olcha": 300,        # ~460 phones observed across 23 pages
    "texnomart": 300,    # ~500 observed across 25 pages
    "beemarket": 250,    # 436 observed via the smartfony category endpoint
    "idea": 100,         # no pagination; reach is bounded by the brand-query list
    "alifshop": 200,     # per-brand sweep
    "uzum": 200,         # per-brand GraphQL sweep
    "mediapark": 0,      # search-only, never swept
}


@dataclass
class SourceCoverage:
    slug: str
    offers: int
    median_price: int | None
    oldest_seen: datetime | None
    newest_seen: datetime | None
    last_run_ok: bool | None
    expected_min: int
    is_suspicious: bool


def coverage_report(conn) -> list[SourceCoverage]:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT s.slug,
                   count(o.id),
                   percentile_disc(0.5) WITHIN GROUP (ORDER BY o.price),
                   min(o.last_seen),
                   max(o.last_seen),
                   (SELECT hr.ok FROM harvest_run hr
                     WHERE hr.store_id = s.id
                     ORDER BY hr.started_at DESC LIMIT 1)
              FROM store s
              LEFT JOIN offer o ON o.store_id = s.id
             GROUP BY s.id, s.slug
             ORDER BY s.slug
        """)
        rows = []
        for slug, offers, median_price, oldest_seen, newest_seen, last_run_ok in cur.fetchall():
            expected_min = EXPECTED_MIN_OFFERS.get(slug, 0)
            # A floor of 0 (mediapark: search-only, never swept) can never be
            # breached -- `offers < 0` is never true -- so this reads as plain
            # "below floor" rather than needing a special case for it.
            is_suspicious = offers < expected_min
            rows.append(SourceCoverage(
                slug=slug, offers=offers, median_price=median_price,
                oldest_seen=oldest_seen, newest_seen=newest_seen,
                last_run_ok=last_run_ok, expected_min=expected_min,
                is_suspicious=is_suspicious,
            ))
        return rows
