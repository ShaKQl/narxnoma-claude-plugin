import contextlib
from typing import Iterator

import psycopg

from narxnoma.config import load_settings


@contextlib.contextmanager
def connect(dsn: str | None = None) -> Iterator[psycopg.Connection]:
    target = dsn or load_settings().dsn
    conn = psycopg.connect(target)
    try:
        yield conn
    finally:
        conn.close()
