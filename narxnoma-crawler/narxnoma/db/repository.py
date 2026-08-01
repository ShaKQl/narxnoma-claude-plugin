"""The only place that writes offers. Keeps SQL out of the pipeline.

Commit boundary: each function below commits its own transaction
independently. start_run, the data writes (record_raw_offers /
upsert_offers) and finish_run are deliberately *not* one unit of work.
For a long-running crawl that is the right choice -- if a source dies half
way through a sweep, the listings already written should stay written
rather than being rolled back along with everything else, and start_run,
finish_run and the upsert are all idempotent enough that re-running a
failed step is safe.
"""
import functools
import json
from typing import Any, Iterable
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from narxnoma.sources.base import Listing


def _scrub_nuls(value: Any) -> Any:
    """Recursively strip NUL (\\u0000) characters from strings nested in
    dicts, lists and scalars. \\u0000 is valid JSON but PostgreSQL's jsonb
    type rejects it outright with error 22P05, and retailer payloads --
    parsed straight from their API JSON -- occasionally contain it."""
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, dict):
        return {k: _scrub_nuls(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub_nuls(v) for v in value]
    return value


# default=str: a retailer payload can contain a value json.dumps cannot
# serialise on its own (e.g. something that survived parsing as a non-JSON
# type). Rather than raising a TypeError mid-batch and aborting every row,
# such a value is degraded to its str() form.
_dump_json = functools.partial(json.dumps, ensure_ascii=False, default=str)


def store_ids(conn: psycopg.Connection) -> dict[str, UUID]:
    # Every function in this module wraps its body in conn.transaction(),
    # which commits on success and rolls back on error. Without this, a
    # failed statement leaves the connection in psycopg's "aborted
    # transaction" state, and every subsequent call on that connection
    # raises InFailedSqlTransaction -- including the finish_run(ok=False,
    # ...) call a caller makes to record the very failure that just
    # happened. The rollback here is what keeps the connection usable for
    # that call.
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("SELECT slug, id FROM store WHERE is_active")
            return {slug: sid for slug, sid in cur.fetchall()}


def record_raw_offers(conn: psycopg.Connection, store_id: UUID,
                      listings: Iterable[Listing]) -> int:
    """Append one row per observation. Never updates -- this is the permanent
    log price history is later derived from, not a cache of current state."""
    rows = [
        (store_id, listing.source_key, listing.name_raw, listing.price, listing.url,
         listing.availability, listing.image_url,
         Jsonb(_scrub_nuls(listing.raw), dumps=_dump_json))
        for listing in listings
    ]
    if not rows:
        return 0
    with conn.transaction():
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO raw_offer"
                " (store_id, source_key, name_raw, price, url, availability, image_url, payload)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)", rows)
    return len(rows)


def upsert_offers(conn: psycopg.Connection, store_id: UUID,
                  listings: Iterable[Listing]) -> tuple[int, int]:
    """Insert new listings, refresh existing ones. first_seen never moves.

    RETURNING always yields the *new* row version, whether the INSERT or the
    ON CONFLICT DO UPDATE branch fired. Its xmax is 0 (true) when INSERT
    fired -- a brand-new row has never been locked by anyone. It is
    non-zero (false) when DO UPDATE fired instead: Postgres locks the
    conflicting row first while evaluating ON CONFLICT, and that locker's
    transaction id is carried forward onto the new row version's xmax. This
    is an undocumented detail of how ON CONFLICT DO UPDATE is implemented,
    not a guarantee made by the PostgreSQL documentation -- re-verify it
    against the release notes before relying on it across a major version
    upgrade. first_seen is omitted from the DO UPDATE SET list entirely, so
    on conflict it keeps its original DEFAULT now() value from the first
    insert.

    Deliberately not batched into a single multi-row VALUES statement: with
    ON CONFLICT, one statement touching the same conflict key twice raises
    "cannot affect row a second time", which a buggy client sweep could
    trigger. The per-row loop tolerates that; a batched statement would not.
    """
    inserted = updated = 0
    with conn.transaction():
        with conn.cursor() as cur:
            for listing in listings:
                cur.execute(
                    "INSERT INTO offer"
                    " (store_id, source_key, name_raw, price, url, availability, image_url)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s)"
                    " ON CONFLICT (store_id, source_key) DO UPDATE SET"
                    "   name_raw = EXCLUDED.name_raw,"
                    "   price = EXCLUDED.price,"
                    "   url = EXCLUDED.url,"
                    "   availability = EXCLUDED.availability,"
                    "   image_url = EXCLUDED.image_url,"
                    "   last_seen = now()"
                    " RETURNING (xmax = 0) AS was_inserted",
                    (store_id, listing.source_key, listing.name_raw, listing.price,
                     listing.url, listing.availability, listing.image_url))
                if cur.fetchone()[0]:
                    inserted += 1
                else:
                    updated += 1
    return inserted, updated


def start_run(conn: psycopg.Connection, store_id: UUID) -> int:
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("INSERT INTO harvest_run (store_id) VALUES (%s) RETURNING id", (store_id,))
            run_id = cur.fetchone()[0]
    return run_id


def finish_run(conn: psycopg.Connection, run_id: int, ok: bool,
               seen: int, kept: int, error: str | None = None) -> None:
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE harvest_run SET finished_at = now(), ok = %s,"
                " listings_seen = %s, listings_kept = %s, error = %s WHERE id = %s",
                (ok, seen, kept, error, run_id))
