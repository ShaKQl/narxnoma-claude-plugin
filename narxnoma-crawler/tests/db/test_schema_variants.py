import uuid

import psycopg
import pytest

pytestmark = pytest.mark.db

INSERT_VARIANT = (
    "INSERT INTO variant (brand, model_tokens, ram_gb, storage_gb, color,"
    " sim_kind, display_name, slug, category)"
    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'smartphones') RETURNING id"
)
HONOR = ("honor", ["x9d"], 12, 256, "black", "dual",
         "Смартфон Honor X9D 12/256 ГБ, Черный", "honor-x9d-12-256-black")


def test_variant_tables_exist(db_conn):
    with db_conn.cursor() as cur:
        cur.execute("""
            SELECT table_name FROM information_schema.tables
             WHERE table_schema = 'public'
               AND table_name IN ('variant', 'variant_price', 'unresolved_offer')
             ORDER BY table_name
        """)
        assert [r[0] for r in cur.fetchall()] == ["unresolved_offer", "variant", "variant_price"]


def test_slug_is_unique_so_duplicates_are_structurally_impossible(db_conn):
    # The slug is a deterministic function of the identity, so uniqueness here
    # is what stops "Cosmic orange" and "Cosmic Orange" becoming two products.
    with db_conn.cursor() as cur:
        cur.execute(INSERT_VARIANT, HONOR)
        with pytest.raises(psycopg.errors.UniqueViolation):
            cur.execute(INSERT_VARIANT, HONOR)


def test_apple_variant_may_have_no_ram(db_conn):
    # Apple publishes no RAM; requiring it would make every iPhone unkeyable.
    with db_conn.cursor() as cur:
        cur.execute(INSERT_VARIANT, ("apple", ["17", "pro"], None, 256, "silver",
                                     "dual", "Смартфон Apple iPhone 17 Pro 256 ГБ, Серебристый",
                                     "apple-17-pro-256-silver"))
        assert cur.fetchone()[0]


def test_colour_is_mandatory(db_conn):
    # Colour is a hard identity field: unknown colour never equals any colour.
    with db_conn.cursor() as cur, pytest.raises(psycopg.errors.NotNullViolation):
        cur.execute(INSERT_VARIANT, ("honor", ["x9d"], 12, 256, None, "dual",
                                     "x", "honor-x9d-12-256-nocolour"))


def test_sim_kind_rejects_unknown(db_conn):
    # variant_key() normalises "unknown" to "dual", so only two values can ever
    # reach a canonical variant. The CHECK pins that.
    with db_conn.cursor() as cur, pytest.raises(psycopg.errors.CheckViolation):
        cur.execute(INSERT_VARIANT, ("honor", ["x9d"], 12, 256, "black", "unknown",
                                     "x", "honor-x9d-12-256-black-unknown"))


def test_offer_variant_id_must_reference_a_real_variant(db_conn):
    with db_conn.cursor() as cur:
        cur.execute("SELECT id FROM store WHERE slug = 'olcha'")
        store_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO offer (store_id, source_key, name_raw, price, url)"
            " VALUES (%s, 'k1', 'X', 1000000, 'u') RETURNING id", (store_id,))
        offer_id = cur.fetchone()[0]
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            cur.execute("UPDATE offer SET variant_id = %s WHERE id = %s",
                        (uuid.uuid4(), offer_id))


def test_unresolved_offer_requires_a_reason(db_conn):
    with db_conn.cursor() as cur:
        cur.execute("SELECT id FROM store WHERE slug = 'olcha'")
        store_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO offer (store_id, source_key, name_raw, price, url)"
            " VALUES (%s, 'k2', 'X', 1000000, 'u') RETURNING id", (store_id,))
        offer_id = cur.fetchone()[0]
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute("INSERT INTO unresolved_offer (offer_id, reason)"
                        " VALUES (%s, '')", (offer_id,))
