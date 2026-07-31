import os

import pytest
from psycopg.conninfo import conninfo_to_dict


def require_disposable_test_database(dsn: str) -> None:
    """Belt-and-braces guard, independent of the NARXNOMA_TEST_DSN /
    NARXNOMA_DSN split above: refuse to truncate any database whose name
    does not mark it as disposable.

    The primary guard against wiping production is that the test suite
    reads NARXNOMA_TEST_DSN, a variable distinct from NARXNOMA_DSN (the
    setting narxnoma/config.py hands the deployed crawler and web app).
    This function is the second line of defense, for the case where
    NARXNOMA_TEST_DSN itself gets pointed at the wrong database.
    """
    dbname = conninfo_to_dict(dsn).get("dbname") or ""
    if "test" not in dbname:
        raise RuntimeError(
            f"refusing to truncate database {dbname!r}: the test suite only "
            "runs against a database whose name contains 'test', so that a "
            "human can see at a glance it is disposable. Point "
            "NARXNOMA_TEST_DSN at a database like 'narxnoma_test', not "
            f"{dbname!r}."
        )


@pytest.fixture(scope="session")
def dsn():
    value = os.environ.get("NARXNOMA_TEST_DSN")
    if not value:
        pytest.skip("NARXNOMA_TEST_DSN not set; start postgres and export it")
    return value


@pytest.fixture()
def db_conn(dsn):
    from narxnoma.db.connection import connect
    from narxnoma.db.migrate import migrate

    require_disposable_test_database(dsn)

    with connect(dsn) as conn:
        migrate(conn)
        with conn.cursor() as cur:
            cur.execute("TRUNCATE raw_offer, offer, harvest_run RESTART IDENTITY CASCADE")
        conn.commit()
        try:
            yield conn
        finally:
            conn.rollback()
