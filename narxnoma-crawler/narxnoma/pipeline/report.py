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
catches it instead, with three independent rules: the offer count against a
measured floor, the AGE of the newest offer against MAX_OFFER_AGE_HOURS, and
the outcome of the last recorded run. Any one of them firing is enough.

The age rule is not a refinement of the count rule, it is the load-bearing
one after day one: `offer` is upsert-only, so a source that dies leaves its
rows behind and keeps clearing its floor indefinitely.
"""
from dataclasses import dataclass
from datetime import datetime

# How old the newest offer for a swept source may be before the source is
# treated as dead. Harvest runs on a four-hour cycle, so 9 hours is a little
# over two cycles: one missed cycle is tolerated, two are not.
#
# This threshold is what makes the report able to detect a source that STOPPED,
# as opposed to one that never started. `offer` is upsert-only -- nothing in
# this system ever deletes or ages a row -- so a retailer that renames a
# category and starts returning nothing leaves yesterday's rows sitting in the
# table, the count keeps clearing the floor, and `report` keeps exiting 0 while
# the site serves month-old prices as current. The count alone only ever
# catches a source that was dead on its FIRST run against a fresh database.
MAX_OFFER_AGE_HOURS = 9

# Suspicion reasons, kept as named constants so the CLI, the tests and the
# report agree on the wording. An operator reading the table has to be able to
# tell "never fetched" from "stopped updating" from "last run failed" -- three
# different call-outs with three different fixes.
BELOW_FLOOR = "below floor"
NEVER_FETCHED = "never fetched"
STALE = f"stale (>{MAX_OFFER_AGE_HOURS}h)"
LAST_RUN_FAILED = "last run failed"

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
    # Measured live 2026-08-10 by counting every leaf asaxiy sweeps: 233
    # phones + 57 TVs + 90 laptops + 113 ACs + 107 fridges + 132 washers + 18
    # cookers = 750. asaxiy is a broad-range shop (books, toys, groceries) with
    # a narrower electronics range than the specialists, so this floor is set
    # against its own measured size, not against olcha's.
    "asaxiy": 400,
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
    #: Every rule that fired, in report order. `reasons` is the single source
    #: of truth; `is_suspicious` is derived from it so the two cannot drift.
    reasons: tuple[str, ...] = ()
    #: Hours since the newest offer row for this source, or None when the
    #: source has no offers at all. Carried so the CLI can show it.
    age_hours: float | None = None

    @property
    def is_suspicious(self) -> bool:
        return bool(self.reasons)


def suspicion_reasons(
    *,
    offers: int,
    expected_min: int,
    age_hours: float | None,
    last_run_ok: bool | None,
) -> tuple[str, ...]:
    """Every rule that says this source is not healthy.

    Pure and DB-free so each rule can be tested independently.

    A source whose floor is 0 is exempt from ALL of them. Today that is only
    mediapark: it is search-only, harvest_all skips it by contract, so it has
    no runs and no offers BY DESIGN. Zero is its healthy state, and any rule
    that fired on it would be a permanent false alarm -- the fastest way to
    train an operator to ignore this report.
    """
    if expected_min == 0:
        return ()
    reasons: list[str] = []
    if offers < expected_min:
        reasons.append(BELOW_FLOOR)
    if age_hours is None:
        # No offer rows at all. Distinct from STALE on purpose: nothing was
        # ever stored, rather than something was stored and stopped refreshing.
        reasons.append(NEVER_FETCHED)
    elif age_hours > MAX_OFFER_AGE_HOURS:
        # THE RULE THIS REPORT WAS MISSING. `offer` is upsert-only, so a dead
        # source keeps yesterday's row count forever and clears its floor
        # while serving stale prices.
        reasons.append(STALE)
    if last_run_ok is False:
        # Not `not last_run_ok`: None means "no run recorded yet", which the
        # other two rules already cover, and which is not itself a failure.
        reasons.append(LAST_RUN_FAILED)
    return tuple(reasons)


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
                     ORDER BY hr.started_at DESC LIMIT 1),
                   -- Age is computed by Postgres, against the same clock and
                   -- time zone that wrote last_seen, rather than compared to a
                   -- Python datetime.now() that may not even be tz-aware.
                   EXTRACT(EPOCH FROM (now() - max(o.last_seen))) / 3600.0
              FROM store s
              LEFT JOIN offer o ON o.store_id = s.id
             GROUP BY s.id, s.slug
             ORDER BY s.slug
        """)
        rows = []
        for (slug, offers, median_price, oldest_seen, newest_seen,
             last_run_ok, age_hours) in cur.fetchall():
            expected_min = EXPECTED_MIN_OFFERS.get(slug, 0)
            age_hours = float(age_hours) if age_hours is not None else None
            rows.append(SourceCoverage(
                slug=slug, offers=offers, median_price=median_price,
                oldest_seen=oldest_seen, newest_seen=newest_seen,
                last_run_ok=last_run_ok, expected_min=expected_min,
                age_hours=age_hours,
                reasons=suspicion_reasons(
                    offers=offers, expected_min=expected_min,
                    age_hours=age_hours, last_run_ok=last_run_ok,
                ),
            ))
        return rows
