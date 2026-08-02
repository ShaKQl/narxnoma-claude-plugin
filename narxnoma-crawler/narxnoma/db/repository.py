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

from narxnoma.matching import VariantKey, display_name, slug
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


# --------------------------------------------------------------- clustering
# Canonical products. These are permanent identities; offers are temporary
# observations of them.

def load_variant_keys(conn: psycopg.Connection) -> dict[VariantKey, UUID]:
    """Every canonical variant that exists, as keys the matcher can compare.

    Clustering needs the whole set in memory because resolving a partial key
    means asking "how many existing variants is this compatible with?" -- and
    the answer must be exact. One is an attachment; two is a refusal.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, brand, model_tokens, ram_gb, storage_gb, color, sim_kind"
            " FROM variant")
        return {
            VariantKey(brand=brand, model_tokens=frozenset(tokens), ram_gb=ram,
                       storage_gb=storage, color=color, sim_kind=sim): vid
            for vid, brand, tokens, ram, storage, color, sim in cur.fetchall()
        }


def upsert_variant(conn: psycopg.Connection, key: VariantKey) -> UUID:
    """Find or create the canonical variant for this identity.

    The slug is a deterministic function of the key, so ON CONFLICT on it makes
    creation idempotent and race-free -- and makes duplicate canonical products
    structurally impossible, which is the defect this platform exists to fix.
    """
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO variant (brand, model_tokens, ram_gb, storage_gb,"
                " color, sim_kind, display_name, slug)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
                " ON CONFLICT (slug) DO NOTHING RETURNING id",
                (key.brand, sorted(key.model_tokens), key.ram_gb, key.storage_gb,
                 key.color, key.sim_kind, display_name(key), slug(key)))
            row = cur.fetchone()
            if row is not None:
                return row[0]
            # Already existed -- another offer in this same run created it.
            cur.execute("SELECT id FROM variant WHERE slug = %s", (slug(key),))
            return cur.fetchone()[0]


def attach_offer_to_variant(conn: psycopg.Connection, offer_id: UUID,
                            variant_id: UUID) -> None:
    """Attach, and clear any previous refusal.

    An offer parked as ambiguous in one cycle is often resolvable in a later
    one, once some other retailer's listing has created the variant it needed.
    Leaving the unresolved row behind would make that count a permanently
    rising number nobody can act on.
    """
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("UPDATE offer SET variant_id = %s WHERE id = %s",
                        (variant_id, offer_id))
            cur.execute("DELETE FROM unresolved_offer WHERE offer_id = %s", (offer_id,))


def record_unresolved(conn: psycopg.Connection, offer_id: UUID, reason: str,
                      candidate_ids: list[UUID] | None = None) -> None:
    """Refuse to guess, and say why.

    unresolved_offer is a quality metric we watch, not a dumping ground: a
    rising rate means the matcher needs work, so the reason must be specific.
    """
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("UPDATE offer SET variant_id = NULL WHERE id = %s", (offer_id,))
            cur.execute(
                "INSERT INTO unresolved_offer (offer_id, reason, candidate_ids)"
                " VALUES (%s, %s, %s)"
                " ON CONFLICT (offer_id) DO UPDATE SET"
                "   reason = EXCLUDED.reason,"
                "   candidate_ids = EXCLUDED.candidate_ids,"
                "   recorded_at = now()",
                (offer_id, reason, candidate_ids or []))


def delete_empty_malformed_variants(conn: psycopg.Connection, is_wellformed) -> int:
    """Remove variants that hold no offers and could never hold one.

    Deliberately narrow. A variant whose offers have merely gone out of stock
    is KEPT -- schema.sql makes min_price nullable precisely so we neither
    publish an unbuyable price nor lose the product's history. This deletes
    only variants the clustering guard would refuse outright, which can never
    be attached to again, and which would otherwise serve a product page with
    no price for a phone that does not exist.
    """
    removed = 0
    with conn.transaction():
        for key, variant_id in load_variant_keys(conn).items():
            if is_wellformed(key):
                continue
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM variant WHERE id = %s"
                    " AND NOT EXISTS (SELECT 1 FROM offer o WHERE o.variant_id = %s)",
                    (variant_id, variant_id))
                removed += cur.rowcount
    return removed


def refresh_display_names(conn: psycopg.Connection) -> int:
    """Regenerate every variant's display_name from its key. Returns rows changed.

    display_name is a pure function of the key, but it is STORED, and
    `upsert_variant` uses ON CONFLICT DO NOTHING -- so a variant's name is
    written once, at creation, and never revisited. A correction to the
    generator would then apply only to products first seen afterwards, leaving
    the existing catalogue on the old wording indefinitely. That is the same
    shape as the schema.sql header rule: a change that silently applies to
    fresh data and not to production.

    Adding the eSIM marker was exactly such a correction, and it had 52 live
    variants to repair.
    """
    changed = 0
    with conn.transaction():
        for key, variant_id in load_variant_keys(conn).items():
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE variant SET display_name = %s"
                    " WHERE id = %s AND display_name IS DISTINCT FROM %s",
                    (display_name(key), variant_id, display_name(key)))
                changed += cur.rowcount
    return changed


def load_attached_offers(conn: psycopg.Connection) -> list[dict]:
    """Offers currently attached to a variant, with their latest raw payload.

    The mirror of `load_unattached_offers`, and the input to the drift check:
    an attachment written in an earlier cycle is only trustworthy while the
    name it was derived from is unchanged. See `cluster.detach_drifted_offers`.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT o.id, o.name_raw, o.variant_id,
                   (SELECT r.payload FROM raw_offer r
                     WHERE r.store_id = o.store_id AND r.source_key = o.source_key
                     ORDER BY r.observed_at DESC LIMIT 1)
              FROM offer o
             WHERE o.variant_id IS NOT NULL
        """)
        return [{"id": oid, "name_raw": name, "variant_id": vid, "raw": payload}
                for oid, name, vid, payload in cur.fetchall()]


def detach_offer(conn: psycopg.Connection, offer_id: UUID) -> None:
    """Return an offer to the unattached pool so clustering reconsiders it."""
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("UPDATE offer SET variant_id = NULL WHERE id = %s", (offer_id,))


def load_unattached_offers(conn: psycopg.Connection) -> list[dict]:
    """Offers not currently attached to a variant, with their latest raw payload.

    Deliberately includes offers already sitting in unresolved_offer: they must
    be reconsidered every run, not parked forever.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT o.id, o.name_raw,
                   (SELECT r.payload FROM raw_offer r
                     WHERE r.store_id = o.store_id AND r.source_key = o.source_key
                     ORDER BY r.observed_at DESC LIMIT 1)
              FROM offer o
             WHERE o.variant_id IS NULL
        """)
        return [{"id": oid, "name_raw": name, "raw": payload}
                for oid, name, payload in cur.fetchall()]
