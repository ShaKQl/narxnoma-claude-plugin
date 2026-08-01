import pathlib

import psycopg

SCHEMA = pathlib.Path(__file__).with_name("schema.sql")


def migrate(conn: psycopg.Connection) -> None:
    """Apply schema.sql. Idempotent by construction."""
    with conn.cursor() as cur:
        cur.execute(SCHEMA.read_text(encoding="utf-8"))
    conn.commit()
