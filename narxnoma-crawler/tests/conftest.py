import os

import pytest


@pytest.fixture(scope="session")
def dsn():
    value = os.environ.get("NARXNOMA_DSN")
    if not value:
        pytest.skip("NARXNOMA_DSN not set; start docker-compose and export it")
    return value


@pytest.fixture()
def db_conn(dsn):
    from narxnoma.db.connection import connect
    from narxnoma.db.migrate import migrate

    with connect(dsn) as conn:
        migrate(conn)
        yield conn
        conn.rollback()
