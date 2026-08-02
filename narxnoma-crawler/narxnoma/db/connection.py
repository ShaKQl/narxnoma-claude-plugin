import contextlib
from typing import Iterator

import psycopg

from narxnoma.config import load_settings


@contextlib.contextmanager
def connect(dsn: str | None = None) -> Iterator[psycopg.Connection]:
    """Open a connection that COMMITS on clean exit and rolls back on error.

    The commit is not optional and its absence was a real, silent bug. psycopg
    opens an implicit transaction on the first statement -- including a plain
    read, such as the catalogue load every pipeline stage begins with. Once
    that transaction is open, the repository's own `with conn.transaction()`
    blocks nest inside it as savepoints, which release without committing. So
    a `close()` with no commit rolled back everything the process had done.

    The symptom was as quiet as it gets: `recompute_variant_prices` reported
    "recomputed prices for 1380 variants", every log line looked healthy, the
    exit code was whatever the reports said -- and the database was untouched.
    """
    target = dsn or load_settings().dsn
    conn = psycopg.connect(target)
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
