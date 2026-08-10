import pytest

pytestmark = pytest.mark.db


def test_migrate_creates_tables_and_seeds_stores(db_conn):
    with db_conn.cursor() as cur:
        cur.execute("SELECT slug FROM store ORDER BY slug")
        slugs = [r[0] for r in cur.fetchall()]
    # asaxiy arrives in migration 3, not in the migration-1 seed list -- see
    # the comment there. Listed explicitly rather than derived from SOURCES:
    # a source registered with no store row is precisely the bug this catches.
    assert slugs == ["alifshop", "asaxiy", "beemarket", "idea", "mediapark",
                     "olcha", "texnomart", "uzum"]


def test_migrate_is_idempotent(db_conn):
    from narxnoma.db.migrate import migrate

    migrate(db_conn)          # second run must not raise or duplicate
    with db_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM store")
        assert cur.fetchone()[0] == 8


def test_price_check_constraint_rejects_bad_values(db_conn):
    import psycopg

    with db_conn.cursor() as cur:
        cur.execute("SELECT id FROM store WHERE slug = 'olcha'")
        store_id = cur.fetchone()[0]
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute(
                "INSERT INTO raw_offer (store_id, source_key, name_raw, price, url)"
                " VALUES (%s, 'k', 'X', 99, 'u')", (store_id,))


def test_connect_commits_on_clean_exit(dsn):
    """A write through connect() must survive the connection closing.

    This was a real, silent bug: psycopg opens an implicit transaction on the
    first statement -- including the plain read every pipeline stage starts
    with -- after which the repository's own `with conn.transaction()` blocks
    nest as savepoints that release without committing. Closing without a
    commit rolled back everything, while every log line still reported success.
    """
    import psycopg

    from narxnoma.db.connection import connect

    with connect(dsn) as conn:
        with conn.cursor() as cur:          # plain read: opens the implicit tx
            cur.execute("SELECT count(*) FROM store")
        with conn.transaction():            # nests as a savepoint
            with conn.cursor() as cur:
                cur.execute("INSERT INTO store (slug, name, website_url)"
                            " VALUES ('committest', 'Commit Test', 'https://x')")

    with psycopg.connect(dsn) as check, check.cursor() as cur:
        cur.execute("SELECT count(*) FROM store WHERE slug = 'committest'")
        persisted = cur.fetchone()[0]
        cur.execute("DELETE FROM store WHERE slug = 'committest'")
        check.commit()
    assert persisted == 1, "the write was rolled back when the connection closed"


def test_connect_rolls_back_when_the_body_raises(dsn):
    import psycopg

    from narxnoma.db.connection import connect

    with pytest.raises(RuntimeError):
        with connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO store (slug, name, website_url)"
                            " VALUES ('rollbacktest', 'X', 'https://x')")
            raise RuntimeError("something went wrong mid-cycle")

    with psycopg.connect(dsn) as check, check.cursor() as cur:
        cur.execute("SELECT count(*) FROM store WHERE slug = 'rollbacktest'")
        assert cur.fetchone()[0] == 0
