import pytest

pytestmark = pytest.mark.db


def test_migrate_creates_tables_and_seeds_stores(db_conn):
    with db_conn.cursor() as cur:
        cur.execute("SELECT slug FROM store ORDER BY slug")
        slugs = [r[0] for r in cur.fetchall()]
    assert slugs == ["alifshop", "beemarket", "idea", "mediapark",
                     "olcha", "texnomart", "uzum"]


def test_migrate_is_idempotent(db_conn):
    from narxnoma.db.migrate import migrate

    migrate(db_conn)          # second run must not raise or duplicate
    with db_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM store")
        assert cur.fetchone()[0] == 7


def test_price_check_constraint_rejects_bad_values(db_conn):
    import psycopg

    with db_conn.cursor() as cur:
        cur.execute("SELECT id FROM store WHERE slug = 'olcha'")
        store_id = cur.fetchone()[0]
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute(
                "INSERT INTO raw_offer (store_id, source_key, name_raw, price, url)"
                " VALUES (%s, 'k', 'X', 99, 'u')", (store_id,))
