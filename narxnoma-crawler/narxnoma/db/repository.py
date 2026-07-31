"""The only place that writes offers. Keeps SQL out of the pipeline."""
import json
from typing import Iterable
from uuid import UUID

import psycopg

from narxnoma.sources.base import Listing


def store_ids(conn: psycopg.Connection) -> dict[str, UUID]:
    with conn.cursor() as cur:
        cur.execute("SELECT slug, id FROM store WHERE is_active")
        return {slug: sid for slug, sid in cur.fetchall()}


def record_raw_offers(conn: psycopg.Connection, store_id: UUID,
                      listings: Iterable[Listing]) -> int:
    """Append one row per observation. Never updates -- this is the permanent
    log price history is later derived from, not a cache of current state."""
    rows = [
        (store_id, listing.source_key, listing.name_raw, listing.price, listing.url,
         listing.availability, listing.image_url, json.dumps(listing.raw, ensure_ascii=False))
        for listing in listings
    ]
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO raw_offer"
            " (store_id, source_key, name_raw, price, url, availability, image_url, payload)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)", rows)
    conn.commit()
    return len(rows)


def upsert_offers(conn: psycopg.Connection, store_id: UUID,
                  listings: Iterable[Listing]) -> tuple[int, int]:
    """Insert new listings, refresh existing ones. first_seen never moves.

    RETURNING (xmax = 0) tells INSERT from UPDATE: xmax is the id of the
    transaction that deleted/superseded a row version. A freshly INSERTed
    row has never been superseded, so its xmax is 0 (true). When
    ON CONFLICT DO UPDATE fires instead, Postgres writes a new row version
    and stamps the old one's xmax with the current transaction id before
    the new version takes its place, so the returned row's xmax is
    non-zero (false) -- an update, not an insert. first_seen is omitted
    from the DO UPDATE SET list entirely, so on conflict it keeps its
    original DEFAULT now() value from the first insert.
    """
    inserted = updated = 0
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
    conn.commit()
    return inserted, updated


def start_run(conn: psycopg.Connection, store_id: UUID) -> int:
    with conn.cursor() as cur:
        cur.execute("INSERT INTO harvest_run (store_id) VALUES (%s) RETURNING id", (store_id,))
        run_id = cur.fetchone()[0]
    conn.commit()
    return run_id


def finish_run(conn: psycopg.Connection, run_id: int, ok: bool,
               seen: int, kept: int, error: str | None = None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE harvest_run SET finished_at = now(), ok = %s,"
            " listings_seen = %s, listings_kept = %s, error = %s WHERE id = %s",
            (ok, seen, kept, error, run_id))
    conn.commit()
