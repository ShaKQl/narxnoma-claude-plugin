"""One cycle at a time. A second overlapping run doubles our request rate at
every retailer at once, which is how an IP gets blocked."""
import psycopg
import pytest

from narxnoma.db.repository import try_advisory_lock

pytestmark = pytest.mark.db

KEY = 20260802


def test_the_lock_is_granted_when_free(db_conn):
    assert try_advisory_lock(db_conn, KEY) is True


def test_a_second_connection_is_refused_while_it_is_held(db_conn, dsn):
    assert try_advisory_lock(db_conn, KEY) is True
    with psycopg.connect(dsn) as other:
        assert try_advisory_lock(other, KEY) is False


def test_the_lock_is_released_when_the_session_ends(dsn):
    # Session-scoped, so a crashed cycle cannot wedge the crontab forever.
    # This is the property a lock TABLE would need explicit cleanup for.
    with psycopg.connect(dsn) as first:
        assert try_advisory_lock(first, KEY) is True
    with psycopg.connect(dsn) as second:
        assert try_advisory_lock(second, KEY) is True


def test_different_keys_do_not_block_each_other(db_conn, dsn):
    assert try_advisory_lock(db_conn, KEY) is True
    with psycopg.connect(dsn) as other:
        assert try_advisory_lock(other, KEY + 1) is True
