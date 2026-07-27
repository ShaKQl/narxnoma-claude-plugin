# Narxnoma Sources & Harvest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sweep all seven retailers into Postgres, so a single command turns live retailer APIs into an append-only `raw_offer` log and a current-state `offer` table.

**Architecture:** One `Source` implementation per retailer behind a common protocol, each exposing `sweep()` (browse the catalogue) and optionally `search(query)`. A polite HTTP layer is shared. The `harvest` stage runs sources independently — one failing source degrades coverage without aborting the cycle — and writes through a thin repository. Clustering offers into canonical products is **Plan 3**; this plan stops at raw offers landing correctly.

**Tech Stack:** Python 3.11+, `requests`, `psycopg[binary]` 3.x, PostgreSQL 16, pytest.

## Global Constraints

- Python 3.11 or newer.
- `narxnoma/matching/**` remains stdlib-only — `tests/matching/test_purity.py` enforces it. **Never import `requests` or `psycopg` from a matching module.** Sources may import both.
- Every price is stored as an **integer in SUM**. Any source reporting another unit converts at parse time (alifshop reports tiyin — divide by 100).
- A price outside **100,000 – 100,000,000 SUM** is rejected at write time, not stored.
- Every `Listing` must carry `store_slug`, `source_key`, `name_raw`, `price` and `url`. A listing missing any of them is dropped and counted, never written.
- `source_key` is the retailer's own stable identifier for that listing, and is unique per store. It is what makes a crawl idempotent.
- `raw_offer` is **append-only**. Never update or delete a row in it.
- Politeness: sequential requests per source, 0.3–0.6 s between them, a real browser `User-Agent`, and the exact `Origin`/`Referer` that retailer's own SPA sends.
- Unit tests must not touch the network. Parsing is tested against recorded fixtures; live contract tests are marked and skipped by default.
- `docs/parsers/` is the source of truth for every endpoint. If an implementation and a doc disagree, verify live, then fix **both in the same commit**.

---

## File Structure

```
narxnoma-crawler/
  docker-compose.yml                  local Postgres 16 for development and tests
  narxnoma/
    config.py                         env-driven settings: DSN, UA, delays
    db/
      __init__.py
      schema.sql                      DDL, idempotent
      connection.py                   connection helper
      migrate.py                      apply schema.sql
      repository.py                   store lookup, raw_offer insert, offer upsert
    sources/
      __init__.py                     SOURCES registry
      base.py                         Listing dataclass, Source protocol, price fences
      http.py                         polite session factory
      olcha.py  alifshop.py  texnomart.py  idea.py
      beemarket.py  mediapark.py  uzum.py
    pipeline/
      harvest.py                      run sources, write through repository
    cli.py                            `python -m narxnoma.cli harvest [--source X]`
  tests/
    fixtures/sources/<slug>.json      one recorded response per source
    sources/test_<slug>.py            offline parse tests
    sources/test_contract_live.py     live shape assertions, marked, skipped by default
    db/test_repository.py             marked db, skipped without a DSN
    pipeline/test_harvest.py          harvest with fake sources, no network
```

`narxnoma-seed/sources.py` in this repo holds a **verified working implementation of all seven clients**, exercised live on 2026-07-26. Read it alongside `docs/parsers/<site>.md` when implementing each client — it is reference, not something to copy wholesale, because the production shape differs (it returns `Listing` objects and supports `sweep()`).

---

### Task 1: Config, Listing, Source protocol, polite HTTP

**Files:**
- Create: `narxnoma-crawler/narxnoma/config.py`
- Create: `narxnoma-crawler/narxnoma/sources/__init__.py`
- Create: `narxnoma-crawler/narxnoma/sources/base.py`
- Create: `narxnoma-crawler/narxnoma/sources/http.py`
- Test: `narxnoma-crawler/tests/sources/test_base.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Settings` (from `config`); `Listing` frozen dataclass with fields `store_slug, source_key, name_raw, price, url, availability, image_url, raw`; `PRICE_MIN`, `PRICE_MAX`, `is_plausible_price(price) -> bool`; `Source` protocol with `slug: str`, `sweep() -> Iterator[Listing]`, `search(query: str) -> Iterator[Listing]`, `can_sweep: bool`; `polite_session(referer, origin, extra_headers) -> requests.Session` and `polite_get`/`polite_post` wrappers applying the delay.

- [ ] **Step 1: Add runtime dependencies**

Edit `narxnoma-crawler/pyproject.toml`, replacing the empty `dependencies` list:

```toml
dependencies = ["requests>=2.32", "psycopg[binary]>=3.2"]
```

- [ ] **Step 2: Write the failing tests**

`tests/sources/test_base.py`:

```python
import pytest

from narxnoma.sources.base import (
    PRICE_MAX, PRICE_MIN, Listing, is_plausible_price,
)


def test_price_fences():
    # A tiyin/SUM confusion is 100x out and must never reach the database.
    assert is_plausible_price(2_723_000) is True
    assert is_plausible_price(272_300_000) is False   # 100x too large
    assert is_plausible_price(27_230) is False        # 100x too small
    assert is_plausible_price(0) is False
    assert is_plausible_price(None) is False
    assert PRICE_MIN == 100_000
    assert PRICE_MAX == 100_000_000


def test_listing_requires_identity_fields():
    with pytest.raises(ValueError):
        Listing(store_slug="olcha", source_key="", name_raw="X", price=1_000_000, url="u")
    with pytest.raises(ValueError):
        Listing(store_slug="olcha", source_key="k", name_raw="", price=1_000_000, url="u")
    with pytest.raises(ValueError):
        Listing(store_slug="olcha", source_key="k", name_raw="X", price=1_000_000, url="")


def test_listing_rejects_implausible_price():
    with pytest.raises(ValueError):
        Listing(store_slug="olcha", source_key="k", name_raw="X", price=99, url="u")


def test_listing_is_frozen_and_hashable():
    lst = Listing(store_slug="olcha", source_key="k", name_raw="X", price=1_000_000, url="u")
    assert lst.availability == "UNKNOWN"
    hash(lst)
    with pytest.raises(Exception):
        lst.price = 5
```

- [ ] **Step 3: Run to verify failure**

Run: `cd narxnoma-crawler && python -m pytest tests/sources/test_base.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'narxnoma.sources'`

- [ ] **Step 4: Implement config**

`narxnoma/config.py`:

```python
"""Environment-driven settings. Import this, never os.environ directly."""
import os
from dataclasses import dataclass

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class Settings:
    dsn: str
    user_agent: str = USER_AGENT
    min_delay: float = 0.3
    max_delay: float = 0.6
    connect_timeout: int = 15
    read_timeout: int = 90


def load_settings() -> Settings:
    return Settings(
        dsn=os.environ.get("NARXNOMA_DSN", "postgresql://narxnoma:narxnoma@localhost:5432/narxnoma"),
        min_delay=float(os.environ.get("NARXNOMA_MIN_DELAY", "0.3")),
        max_delay=float(os.environ.get("NARXNOMA_MAX_DELAY", "0.6")),
    )
```

- [ ] **Step 5: Implement base**

`narxnoma/sources/base.py`:

```python
"""Shared vocabulary for every retailer client."""
from dataclasses import dataclass, field
from typing import Any, Iterator, Protocol, runtime_checkable

# A price outside this range is a unit bug, not a bargain. alifshop reports
# tiyin (1/100 SUM); forgetting the divisor lands 100x high.
PRICE_MIN = 100_000
PRICE_MAX = 100_000_000

AVAILABILITY = ("IN_STOCK", "OUT_OF_STOCK", "UNKNOWN")


def is_plausible_price(price: int | None) -> bool:
    return price is not None and PRICE_MIN <= price <= PRICE_MAX


@dataclass(frozen=True)
class Listing:
    """One offer as the retailer stated it. Nothing is inferred here."""

    store_slug: str
    source_key: str
    name_raw: str
    price: int
    url: str
    availability: str = "UNKNOWN"
    image_url: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)

    def __post_init__(self) -> None:
        for name in ("store_slug", "source_key", "name_raw", "url"):
            if not getattr(self, name):
                raise ValueError(f"Listing.{name} must not be empty")
        if not is_plausible_price(self.price):
            raise ValueError(f"implausible price {self.price!r} for {self.source_key!r}")
        if self.availability not in AVAILABILITY:
            raise ValueError(f"unknown availability {self.availability!r}")


@runtime_checkable
class Source(Protocol):
    slug: str
    can_sweep: bool

    def sweep(self) -> Iterator[Listing]:
        """Every phone the retailer will show us, without a target list."""

    def search(self, query: str) -> Iterator[Listing]:
        """Listings matching a query. Used for sources that cannot be swept."""
```

- [ ] **Step 6: Implement the polite HTTP layer**

`narxnoma/sources/http.py`:

```python
"""Polite HTTP. Every retailer call goes through here.

We look exactly like the retailer's own SPA: their User-Agent, their Origin
and Referer, one request at a time, with a delay between them.
"""
import random
import time

import requests

from narxnoma.config import load_settings

_SETTINGS = load_settings()


def polite_session(referer: str, origin: str | None = None,
                   extra_headers: dict[str, str] | None = None) -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": _SETTINGS.user_agent,
        "Accept": "application/json, text/plain, */*",
        "Referer": referer,
    })
    if origin:
        session.headers["Origin"] = origin
    if extra_headers:
        session.headers.update(extra_headers)
    return session


def pause() -> None:
    time.sleep(random.uniform(_SETTINGS.min_delay, _SETTINGS.max_delay))


def get_json(session: requests.Session, url: str, **kwargs) -> dict:
    timeout = (_SETTINGS.connect_timeout, _SETTINGS.read_timeout)
    response = session.get(url, timeout=timeout, **kwargs)
    response.raise_for_status()
    pause()
    return response.json() or {}


def post_json(session: requests.Session, url: str, **kwargs) -> dict:
    timeout = (_SETTINGS.connect_timeout, _SETTINGS.read_timeout)
    response = session.post(url, timeout=timeout, **kwargs)
    response.raise_for_status()
    pause()
    return response.json() or {}
```

`narxnoma/sources/__init__.py`:

```python
"""Retailer clients. Each implements the Source protocol in base.py."""
```

- [ ] **Step 7: Run to verify pass**

Run: `cd narxnoma-crawler && python -m pytest tests/sources/test_base.py -v`
Expected: PASS — 4 passed

- [ ] **Step 8: Confirm the matching purity guard still holds**

Run: `cd narxnoma-crawler && python -m pytest tests/matching/test_purity.py -v`
Expected: PASS — `requests` must not have leaked into `narxnoma/matching/`.

- [ ] **Step 9: Commit**

```bash
git add narxnoma-crawler/pyproject.toml narxnoma-crawler/narxnoma/config.py narxnoma-crawler/narxnoma/sources narxnoma-crawler/tests/sources
git commit -m "feat(sources): add Listing, Source protocol and polite HTTP layer"
```

---

### Task 2: Postgres schema and migration

**Files:**
- Create: `narxnoma-crawler/docker-compose.yml`
- Create: `narxnoma-crawler/narxnoma/db/__init__.py`
- Create: `narxnoma-crawler/narxnoma/db/schema.sql`
- Create: `narxnoma-crawler/narxnoma/db/connection.py`
- Create: `narxnoma-crawler/narxnoma/db/migrate.py`
- Test: `narxnoma-crawler/tests/db/test_migrate.py`
- Test: `narxnoma-crawler/tests/conftest.py`

**Interfaces:**
- Consumes: `load_settings` (Task 1).
- Produces: `connect()` context manager; `migrate(conn)` applying `schema.sql` idempotently; pytest fixture `db_conn` that skips when `NARXNOMA_DSN` is unset.

- [ ] **Step 1: Add local Postgres**

`docker-compose.yml`:

```yaml
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_USER: narxnoma
      POSTGRES_PASSWORD: narxnoma
      POSTGRES_DB: narxnoma
    ports: ["5432:5432"]
    volumes: ["narxnoma_pgdata:/var/lib/postgresql/data"]
volumes:
  narxnoma_pgdata:
```

- [ ] **Step 2: Write the schema**

`narxnoma/db/schema.sql`:

```sql
-- Idempotent. Safe to run on every start.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS store (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug         text UNIQUE NOT NULL,
    name         text NOT NULL,
    website_url  text NOT NULL,
    is_active    boolean NOT NULL DEFAULT true,
    created_at   timestamptz NOT NULL DEFAULT now()
);

-- Append-only observation log. Price history falls out of this for free.
CREATE TABLE IF NOT EXISTS raw_offer (
    id           bigserial PRIMARY KEY,
    store_id     uuid NOT NULL REFERENCES store(id),
    source_key   text NOT NULL,
    name_raw     text NOT NULL,
    price        bigint NOT NULL CHECK (price BETWEEN 100000 AND 100000000),
    url          text NOT NULL,
    availability text NOT NULL DEFAULT 'UNKNOWN',
    image_url    text,
    payload      jsonb,
    observed_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS raw_offer_store_key_time
    ON raw_offer (store_id, source_key, observed_at DESC);

-- Current state, one row per retailer listing. variant_id is filled in Plan 3.
CREATE TABLE IF NOT EXISTS offer (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    store_id     uuid NOT NULL REFERENCES store(id),
    source_key   text NOT NULL,
    variant_id   uuid,
    name_raw     text NOT NULL,
    price        bigint NOT NULL CHECK (price BETWEEN 100000 AND 100000000),
    url          text NOT NULL,
    availability text NOT NULL DEFAULT 'UNKNOWN',
    image_url    text,
    first_seen   timestamptz NOT NULL DEFAULT now(),
    last_seen    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (store_id, source_key)
);
CREATE INDEX IF NOT EXISTS offer_last_seen ON offer (last_seen DESC);
CREATE INDEX IF NOT EXISTS offer_variant ON offer (variant_id);

-- One row per source per cycle. Makes a silently-dead source visible.
CREATE TABLE IF NOT EXISTS harvest_run (
    id            bigserial PRIMARY KEY,
    store_id      uuid NOT NULL REFERENCES store(id),
    started_at    timestamptz NOT NULL DEFAULT now(),
    finished_at   timestamptz,
    ok            boolean,
    listings_seen integer NOT NULL DEFAULT 0,
    listings_kept integer NOT NULL DEFAULT 0,
    error         text
);

INSERT INTO store (slug, name, website_url) VALUES
    ('uzum',      'Uzum',      'https://uzum.uz'),
    ('alifshop',  'Alif Shop', 'https://alifshop.uz'),
    ('beemarket', 'BeeMarket', 'https://market.beeline.uz'),
    ('idea',      'Idea',      'https://idea.uz'),
    ('mediapark', 'Mediapark', 'https://mediapark.uz'),
    ('olcha',     'Olcha',     'https://olcha.uz'),
    ('texnomart', 'Texnomart', 'https://texnomart.uz')
ON CONFLICT (slug) DO NOTHING;
```

- [ ] **Step 3: Write the failing test**

`tests/conftest.py`:

```python
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
```

`tests/db/test_migrate.py`:

```python
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
```

Register the markers in `pyproject.toml` under `[tool.pytest.ini_options]`:

```toml
markers = [
    "db: needs a PostgreSQL instance (set NARXNOMA_DSN)",
    "live: hits a real retailer API",
]
addopts = "-m 'not live'"
```

- [ ] **Step 4: Run to verify failure**

Run: `cd narxnoma-crawler && python -m pytest tests/db -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'narxnoma.db'` (or SKIP if `NARXNOMA_DSN` is unset; export it first, after `docker compose up -d`).

- [ ] **Step 5: Implement**

`narxnoma/db/__init__.py`:

```python
"""PostgreSQL access. The only module that knows SQL."""
```

`narxnoma/db/connection.py`:

```python
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
```

`narxnoma/db/migrate.py`:

```python
import pathlib

import psycopg

SCHEMA = pathlib.Path(__file__).with_name("schema.sql")


def migrate(conn: psycopg.Connection) -> None:
    """Apply schema.sql. Idempotent by construction."""
    with conn.cursor() as cur:
        cur.execute(SCHEMA.read_text(encoding="utf-8"))
    conn.commit()
```

- [ ] **Step 6: Run to verify pass**

```bash
cd narxnoma-crawler && docker compose up -d
export NARXNOMA_DSN=postgresql://narxnoma:narxnoma@localhost:5432/narxnoma
python -m pytest tests/db -v
```

Expected: PASS — 3 passed

- [ ] **Step 7: Commit**

```bash
git add narxnoma-crawler/docker-compose.yml narxnoma-crawler/narxnoma/db narxnoma-crawler/tests/db narxnoma-crawler/tests/conftest.py narxnoma-crawler/pyproject.toml
git commit -m "feat(db): add Postgres schema, migration and store seed"
```

---

### Task 3: Repository

**Files:**
- Create: `narxnoma-crawler/narxnoma/db/repository.py`
- Test: `narxnoma-crawler/tests/db/test_repository.py`

**Interfaces:**
- Consumes: `Listing` (Task 1), `connect`/`migrate` (Task 2).
- Produces: `store_ids(conn) -> dict[str, UUID]`; `record_raw_offers(conn, store_id, listings) -> int`; `upsert_offers(conn, store_id, listings) -> tuple[int, int]` returning `(inserted, updated)`; `start_run(conn, store_id) -> int`; `finish_run(conn, run_id, ok, seen, kept, error=None)`.

- [ ] **Step 1: Write the failing tests**

`tests/db/test_repository.py`:

```python
import pytest

from narxnoma.db import repository as repo
from narxnoma.sources.base import Listing

pytestmark = pytest.mark.db


def listing(key="k1", price=2_723_000, name="Смартфон Xiaomi Redmi Note 15 8/256 ГБ, Синий"):
    return Listing(store_slug="olcha", source_key=key, name_raw=name,
                   price=price, url=f"https://olcha.uz/{key}", availability="IN_STOCK")


def test_store_ids_returns_all_seeded_stores(db_conn):
    ids = repo.store_ids(db_conn)
    assert set(ids) == {"uzum", "alifshop", "beemarket", "idea",
                        "mediapark", "olcha", "texnomart"}


def test_raw_offer_is_append_only(db_conn):
    sid = repo.store_ids(db_conn)["olcha"]
    repo.record_raw_offers(db_conn, sid, [listing(price=2_723_000)])
    repo.record_raw_offers(db_conn, sid, [listing(price=2_699_000)])
    with db_conn.cursor() as cur:
        cur.execute("SELECT price FROM raw_offer WHERE source_key='k1' ORDER BY observed_at")
        assert [r[0] for r in cur.fetchall()] == [2_723_000, 2_699_000]


def test_upsert_inserts_then_updates_keeping_first_seen(db_conn):
    sid = repo.store_ids(db_conn)["olcha"]
    assert repo.upsert_offers(db_conn, sid, [listing(price=2_723_000)]) == (1, 0)
    with db_conn.cursor() as cur:
        cur.execute("SELECT first_seen FROM offer WHERE source_key='k1'")
        first = cur.fetchone()[0]

    assert repo.upsert_offers(db_conn, sid, [listing(price=2_699_000)]) == (0, 1)
    with db_conn.cursor() as cur:
        cur.execute("SELECT price, first_seen, last_seen FROM offer WHERE source_key='k1'")
        price, first_seen, last_seen = cur.fetchone()
    assert price == 2_699_000
    assert first_seen == first          # first_seen must never move
    assert last_seen >= first_seen


def test_upsert_does_not_duplicate_on_rerun(db_conn):
    sid = repo.store_ids(db_conn)["olcha"]
    repo.upsert_offers(db_conn, sid, [listing()])
    repo.upsert_offers(db_conn, sid, [listing()])
    with db_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM offer WHERE source_key='k1'")
        assert cur.fetchone()[0] == 1


def test_run_bookkeeping(db_conn):
    sid = repo.store_ids(db_conn)["olcha"]
    run_id = repo.start_run(db_conn, sid)
    repo.finish_run(db_conn, run_id, ok=True, seen=440, kept=438)
    with db_conn.cursor() as cur:
        cur.execute("SELECT ok, listings_seen, listings_kept, finished_at IS NOT NULL"
                    " FROM harvest_run WHERE id=%s", (run_id,))
        assert cur.fetchone() == (True, 440, 438, True)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd narxnoma-crawler && python -m pytest tests/db/test_repository.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'narxnoma.db.repository'`

- [ ] **Step 3: Implement**

`narxnoma/db/repository.py`:

```python
"""The only place that writes offers. Keeps SQL out of the pipeline."""
import json
from typing import Iterable
from uuid import UUID

import psycopg

from narxnoma.sources.base import Listing


def store_ids(conn: psycopg.Connection) -> dict[str, UUID]:
    with conn.cursor() as cur:
        cur.execute("SELECT slug, id FROM store WHERE is_active")
        return {slug: sid for slug, sid in cur.fetchall()}


def record_raw_offers(conn: psycopg.Connection, store_id: UUID,
                      listings: Iterable[Listing]) -> int:
    rows = [
        (store_id, listing.source_key, listing.name_raw, listing.price, listing.url,
         listing.availability, listing.image_url, json.dumps(listing.raw, ensure_ascii=False))
        for listing in listings
    ]
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO raw_offer"
            " (store_id, source_key, name_raw, price, url, availability, image_url, payload)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)", rows)
    conn.commit()
    return len(rows)


def upsert_offers(conn: psycopg.Connection, store_id: UUID,
                  listings: Iterable[Listing]) -> tuple[int, int]:
    """Insert new listings, refresh existing ones. first_seen never moves."""
    inserted = updated = 0
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
    conn.commit()
    return inserted, updated


def start_run(conn: psycopg.Connection, store_id: UUID) -> int:
    with conn.cursor() as cur:
        cur.execute("INSERT INTO harvest_run (store_id) VALUES (%s) RETURNING id", (store_id,))
        run_id = cur.fetchone()[0]
    conn.commit()
    return run_id


def finish_run(conn: psycopg.Connection, run_id: int, ok: bool,
               seen: int, kept: int, error: str | None = None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE harvest_run SET finished_at = now(), ok = %s,"
            " listings_seen = %s, listings_kept = %s, error = %s WHERE id = %s",
            (ok, seen, kept, error, run_id))
    conn.commit()
```

- [ ] **Step 4: Run to verify pass**

Run: `cd narxnoma-crawler && python -m pytest tests/db -v`
Expected: PASS — 8 passed

- [ ] **Step 5: Commit**

```bash
git add narxnoma-crawler/narxnoma/db/repository.py narxnoma-crawler/tests/db/test_repository.py
git commit -m "feat(db): add repository with append-only raw offers and offer upsert"
```

---

### Tasks 4–10: the seven retailer clients

Each client is one task with the same shape. Implement them in this order — it runs
easiest-first, so the protocol is proven before the hard one:

| Task | Source | Sweep strategy | The trap that costs you |
|---|---|---|---|
| 4 | **olcha** | full category pull, `category=telefony`, `per_page` capped at 20 server-side (~22 pages) | product URL needs the `/view/` segment — `/ru/product/<alias>` 404s |
| 5 | **texnomart** | generic query `q=smartfon`, ~25 pages | two similar hosts; only `gw.texnomart.uz/.../search/result` carries prices, `gateway.…/search/header` does not. `old_price` is often `0` — never use it as a fallback |
| 6 | **idea** | brand queries, `quantity=100` honoured (~94 per call), no pagination | `type[]` is a **repeated** parameter, not a comma list. `url` is absolute — use it verbatim |
| 7 | **beemarket** | fully browsable: empty query, 233 pages, `is_bshop=1`, 1-based | doubly-nested `data.data`. Use `actual_price`, not `price` |
| 8 | **alifshop** | per-brand sweep, `page` is **0-based**, `size` capped at 20 | `price` is in **tiyin — divide by 100**. Product URL is `/moderated-offer/<slug>`, not `/product/<slug>` |
| 9 | **mediapark** | **cannot sweep** (`can_sweep = False`) — autocomplete only, `search()` per variant | the slug lies about specs; match on `name`, use `linkUrl` verbatim. `price` is a string |
| 10 | **uzum** | per-brand GraphQL sweep; offset caps at ~1000 so sweep brand by brand | 401 without a self-minted token; `Accept-Language` + `Referer` mint it, `Origin` is not required. GraphQL returns **HTTP 200 with an `errors` key** on failure — check `errors`, not the status code. Match at **SKU** level: `minSellPrice` understates by millions |

For every one of these tasks:

**Files:**
- Create: `narxnoma-crawler/narxnoma/sources/<slug>.py`
- Create: `narxnoma-crawler/tests/fixtures/sources/<slug>.json`
- Test: `narxnoma-crawler/tests/sources/test_<slug>.py`

**Interfaces:**
- Consumes: `Listing`, `Source`, `polite_session`, `get_json`/`post_json` (Task 1).
- Produces: a class `<Slug>Source` with `slug`, `can_sweep`, `sweep()`, `search(query)`, and a module-level `parse(payload) -> list[Listing]` that turns one raw API response into listings.

**Steps for each:**

- [ ] **Step 1: Record a real response into a fixture.** Call the documented endpoint once with the documented headers, and save the raw JSON to `tests/fixtures/sources/<slug>.json`. Trim it to at most 20 items so the fixture stays readable, but do not otherwise edit it — an edited fixture tests your assumptions rather than the retailer's behaviour. Note the exact request you made in a comment at the top of the test file.

- [ ] **Step 2: Write the failing parse test** against that fixture. It must assert, at minimum: the listing count is greater than zero; every price is an integer within the fences; every listing has a non-empty `source_key`, `name_raw` and `url`; and one specific known product from the fixture parses to its exact expected price and URL. For alifshop additionally assert the tiyin division by checking a price against the raw payload value divided by 100.

- [ ] **Step 3: Run it and confirm it fails** with `ModuleNotFoundError`.

- [ ] **Step 4: Implement the client.** Read `docs/parsers/<slug>.md` for the endpoint contract and `narxnoma-seed/sources.py` for the verified request handling. `parse()` must be a pure function of the payload so it is testable offline. Drop and count any item that fails `Listing` construction rather than raising — one malformed item must not kill a sweep.

- [ ] **Step 5: Run the parse test and confirm it passes.**

- [ ] **Step 6: Add a live contract test** in `tests/sources/test_contract_live.py`, marked `@pytest.mark.live`, that calls the real endpoint and asserts the documented field names still exist and prices still land inside the fences. This is what catches a silent API change before it becomes wrong prices. It is skipped by default via `addopts`.

- [ ] **Step 7: Run the live test once manually** to prove it works: `python -m pytest tests/sources/test_contract_live.py -m live -k <slug> -v`.

- [ ] **Step 8: Commit** with the message `feat(sources): add <slug> client with recorded-fixture parse tests`.

---

### Task 11: Harvest pipeline and CLI

**Files:**
- Create: `narxnoma-crawler/narxnoma/pipeline/__init__.py`
- Create: `narxnoma-crawler/narxnoma/pipeline/harvest.py`
- Create: `narxnoma-crawler/narxnoma/cli.py`
- Modify: `narxnoma-crawler/narxnoma/sources/__init__.py` — add the `SOURCES` registry
- Test: `narxnoma-crawler/tests/pipeline/test_harvest.py`

**Interfaces:**
- Consumes: every client (Tasks 4–10), the repository (Task 3).
- Produces: `SOURCES: dict[str, Source]`; `harvest_source(conn, source, store_id) -> HarvestResult`; `harvest_all(conn, sources) -> list[HarvestResult]`; a CLI entry point.

- [ ] **Step 1: Write the failing tests**

`tests/pipeline/test_harvest.py`:

```python
import pytest

from narxnoma.pipeline.harvest import HarvestResult, harvest_all
from narxnoma.sources.base import Listing


class FakeSource:
    slug = "olcha"
    can_sweep = True

    def __init__(self, listings=None, boom=False):
        self._listings = listings or []
        self._boom = boom

    def sweep(self):
        if self._boom:
            raise RuntimeError("upstream 503")
        yield from self._listings

    def search(self, query):
        return iter(())


class FakeRepo:
    def __init__(self):
        self.raw, self.upserts, self.runs = [], [], []

    def store_ids(self, conn):
        return {"olcha": "sid-olcha", "idea": "sid-idea"}

    def record_raw_offers(self, conn, store_id, listings):
        listings = list(listings)
        self.raw.extend(listings)
        return len(listings)

    def upsert_offers(self, conn, store_id, listings):
        listings = list(listings)
        self.upserts.extend(listings)
        return len(listings), 0

    def start_run(self, conn, store_id):
        self.runs.append({"store": store_id})
        return len(self.runs)

    def finish_run(self, conn, run_id, ok, seen, kept, error=None):
        self.runs[run_id - 1].update(ok=ok, seen=seen, kept=kept, error=error)


def a_listing(key):
    return Listing(store_slug="olcha", source_key=key, name_raw="Смартфон X",
                   price=1_500_000, url=f"https://olcha.uz/{key}")


def test_harvest_writes_raw_and_offers():
    repo = FakeRepo()
    results = harvest_all(conn=None, sources=[FakeSource([a_listing("a"), a_listing("b")])],
                          repo=repo)
    assert [r.ok for r in results] == [True]
    assert results[0].kept == 2
    assert len(repo.raw) == 2 and len(repo.upserts) == 2


def test_one_failing_source_does_not_abort_the_cycle():
    repo = FakeRepo()
    good = FakeSource([a_listing("a")])
    bad = FakeSource(boom=True)
    bad.slug = "idea"
    results = harvest_all(conn=None, sources=[bad, good], repo=repo)
    by_slug = {r.slug: r for r in results}
    assert by_slug["idea"].ok is False
    assert "503" in by_slug["idea"].error
    assert by_slug["olcha"].ok is True          # the good source still ran
    assert len(repo.upserts) == 1


def test_failure_is_recorded_against_the_run():
    repo = FakeRepo()
    bad = FakeSource(boom=True)
    harvest_all(conn=None, sources=[bad], repo=repo)
    assert repo.runs[0]["ok"] is False
    assert repo.runs[0]["error"]
```

- [ ] **Step 2: Run to verify failure**

Run: `cd narxnoma-crawler && python -m pytest tests/pipeline -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'narxnoma.pipeline'`

- [ ] **Step 3: Implement**

`narxnoma/pipeline/__init__.py`:

```python
"""Crawl stages. harvest -> extract -> cluster -> aggregate -> publish."""
```

`narxnoma/pipeline/harvest.py`:

```python
"""Stage 1: retailer APIs -> raw_offer + offer.

Each source runs in isolation. A source that fails degrades coverage for
this cycle; it never aborts the others and never corrupts their data.
"""
import logging
from dataclasses import dataclass

from narxnoma.db import repository as default_repo

logger = logging.getLogger(__name__)


@dataclass
class HarvestResult:
    slug: str
    ok: bool
    seen: int = 0
    kept: int = 0
    error: str | None = None


def harvest_source(conn, source, store_id, repo=default_repo) -> HarvestResult:
    run_id = repo.start_run(conn, store_id)
    seen = kept = 0
    try:
        listings = []
        for listing in source.sweep():
            seen += 1
            listings.append(listing)
        kept = len(listings)
        repo.record_raw_offers(conn, store_id, listings)
        repo.upsert_offers(conn, store_id, listings)
    except Exception as exc:                     # noqa: BLE001 - isolation is the point
        logger.exception("harvest failed for %s", source.slug)
        repo.finish_run(conn, run_id, ok=False, seen=seen, kept=kept, error=str(exc))
        return HarvestResult(source.slug, ok=False, seen=seen, kept=kept, error=str(exc))

    repo.finish_run(conn, run_id, ok=True, seen=seen, kept=kept)
    return HarvestResult(source.slug, ok=True, seen=seen, kept=kept)


def harvest_all(conn, sources, repo=default_repo) -> list[HarvestResult]:
    ids = repo.store_ids(conn)
    results = []
    for source in sources:
        store_id = ids.get(source.slug)
        if store_id is None:
            results.append(HarvestResult(source.slug, ok=False, error="store not seeded"))
            continue
        results.append(harvest_source(conn, source, store_id, repo=repo))
    return results
```

`narxnoma/cli.py`:

```python
"""Command line entry point: python -m narxnoma.cli harvest [--source SLUG]"""
import argparse
import logging
import sys

from narxnoma.db.connection import connect
from narxnoma.db.migrate import migrate
from narxnoma.pipeline.harvest import harvest_all
from narxnoma.sources import SOURCES


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="narxnoma")
    sub = parser.add_subparsers(dest="command", required=True)
    harvest = sub.add_parser("harvest", help="sweep retailers into the database")
    harvest.add_argument("--source", action="append", choices=sorted(SOURCES),
                         help="limit to these sources (repeatable)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    chosen = [SOURCES[s] for s in (args.source or sorted(SOURCES))]

    with connect() as conn:
        migrate(conn)
        results = harvest_all(conn, chosen)

    for r in results:
        status = "ok" if r.ok else f"FAILED: {r.error}"
        logging.info("%-10s seen=%-6d kept=%-6d %s", r.slug, r.seen, r.kept, status)
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
```

Add the registry to `narxnoma/sources/__init__.py`:

```python
"""Retailer clients. Each implements the Source protocol in base.py."""
from narxnoma.sources.alifshop import AlifshopSource
from narxnoma.sources.beemarket import BeemarketSource
from narxnoma.sources.idea import IdeaSource
from narxnoma.sources.mediapark import MediaparkSource
from narxnoma.sources.olcha import OlchaSource
from narxnoma.sources.texnomart import TexnomartSource
from narxnoma.sources.uzum import UzumSource

SOURCES = {s.slug: s for s in (
    OlchaSource(), TexnomartSource(), IdeaSource(), BeemarketSource(),
    AlifshopSource(), MediaparkSource(), UzumSource(),
)}
```

- [ ] **Step 4: Run to verify pass**

Run: `cd narxnoma-crawler && python -m pytest tests/pipeline -v`
Expected: PASS — 3 passed

- [ ] **Step 5: Run the full offline suite**

Run: `cd narxnoma-crawler && python -m pytest tests/ -q`
Expected: PASS — everything from Plan 1 plus this plan's offline tests.

- [ ] **Step 6: Run a real harvest against one source**

```bash
docker compose up -d
export NARXNOMA_DSN=postgresql://narxnoma:narxnoma@localhost:5432/narxnoma
python -m narxnoma.cli harvest --source olcha
```

Expected: a log line reporting a few hundred listings seen and kept. Then confirm in
the database:

```bash
psql "$NARXNOMA_DSN" -c "SELECT count(*), min(price), max(price) FROM offer"
```

Every price must sit inside the fences. Open two of the stored URLs in a browser and
confirm the rendered price matches the stored one — a transport check cannot tell you
the URL is right.

- [ ] **Step 7: Commit**

```bash
git add narxnoma-crawler/narxnoma/pipeline narxnoma-crawler/narxnoma/cli.py narxnoma-crawler/narxnoma/sources/__init__.py narxnoma-crawler/tests/pipeline
git commit -m "feat(pipeline): add harvest stage with per-source isolation and CLI"
```

---

### Task 12: Full sweep and freshness report

**Files:**
- Create: `narxnoma-crawler/narxnoma/pipeline/report.py`
- Test: `narxnoma-crawler/tests/pipeline/test_report.py`

**Interfaces:**
- Consumes: the repository (Task 3).
- Produces: `coverage_report(conn) -> list[SourceCoverage]` with `slug, offers, median_price, oldest_seen, newest_seen, last_run_ok`.

This task exists because a source can fail silently by returning fewer rows rather than
by raising. The incumbent has a store dead since April still flagged healthy.

- [ ] **Step 1: Write the failing test**

`tests/pipeline/test_report.py`:

```python
import pytest

from narxnoma.db import repository as repo
from narxnoma.pipeline.report import coverage_report
from narxnoma.sources.base import Listing

pytestmark = pytest.mark.db


def test_coverage_report_counts_offers_per_source(db_conn):
    ids = repo.store_ids(db_conn)
    repo.upsert_offers(db_conn, ids["olcha"], [
        Listing(store_slug="olcha", source_key=f"k{i}", name_raw="Смартфон X",
                price=1_000_000 + i, url=f"https://olcha.uz/k{i}")
        for i in range(3)
    ])
    rows = {r.slug: r for r in coverage_report(db_conn)}
    assert rows["olcha"].offers == 3
    assert rows["idea"].offers == 0          # every store appears, even at zero
    assert rows["olcha"].newest_seen is not None
```

- [ ] **Step 2: Run to verify failure**

Run: `cd narxnoma-crawler && python -m pytest tests/pipeline/test_report.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'narxnoma.pipeline.report'`

- [ ] **Step 3: Implement**

`narxnoma/pipeline/report.py`:

```python
"""Coverage and freshness per source.

A source that quietly returns fewer rows is more dangerous than one that
raises, because nothing alerts. This is what makes that visible.
"""
from dataclasses import dataclass
from datetime import datetime


@dataclass
class SourceCoverage:
    slug: str
    offers: int
    median_price: int | None
    oldest_seen: datetime | None
    newest_seen: datetime | None
    last_run_ok: bool | None


def coverage_report(conn) -> list[SourceCoverage]:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT s.slug,
                   count(o.id),
                   percentile_disc(0.5) WITHIN GROUP (ORDER BY o.price),
                   min(o.last_seen),
                   max(o.last_seen),
                   (SELECT hr.ok FROM harvest_run hr
                     WHERE hr.store_id = s.id
                     ORDER BY hr.started_at DESC LIMIT 1)
              FROM store s
              LEFT JOIN offer o ON o.store_id = s.id
             GROUP BY s.id, s.slug
             ORDER BY s.slug
        """)
        return [SourceCoverage(*row) for row in cur.fetchall()]
```

- [ ] **Step 4: Run to verify pass**

Run: `cd narxnoma-crawler && python -m pytest tests/pipeline -v`
Expected: PASS — 4 passed

- [ ] **Step 5: Run a full sweep of every source**

```bash
python -m narxnoma.cli harvest
```

Expected: roughly 1,100–1,900 requests and 8–13 minutes total. Record the actual counts
per source. Then compare against the coverage measured on 2026-07-26 — olcha ~440
phones, texnomart ~500, beemarket browsable to 233 pages. A source returning an order
of magnitude fewer rows than expected has a broken sweep, not a small catalogue.

- [ ] **Step 6: Commit**

```bash
git add narxnoma-crawler/narxnoma/pipeline/report.py narxnoma-crawler/tests/pipeline/test_report.py
git commit -m "feat(pipeline): add per-source coverage and freshness report"
```

---

## Self-Review

**Spec coverage.** This plan implements spec §4 (harvest stage, two-phase design), §6
(`store`, `raw_offer`, `offer` tables), §8 (source isolation, price fences, provenance,
idempotent crawls) and §10 (crawl schedule constants). Spec §5 canonical clustering,
`variant`/`variant_price`/`unresolved_offer`, and §7 web are **not** in this plan — they
are Plan 3 and Plan 4.

**Type consistency.** `Listing` field names are identical in Tasks 1, 3, 4–10 and 11.
`repo.upsert_offers` returns `(inserted, updated)` in both its definition (Task 3) and
every caller (Task 11). `HarvestResult` fields match between `harvest_source` and the
CLI's log line.

**Deliberate deviations from the spec, stated so they are not mistaken for gaps:**

- The spec describes harvest Pass B (mediapark's targeted search) reading the *previous*
  cycle's variant list. There are no variants until Plan 3, so mediapark ships here with
  `can_sweep = False` and an unused `search()`. Wiring Pass B belongs to Plan 3.
- `unresolved_offer` is not created yet; nothing writes to it before clustering exists.
- `offer.variant_id` is created nullable now so Plan 3 only has to fill it, not migrate.

**Carried in from Plan 1's final review** — the source layer must handle this, and Task 10
is where it lands: reseller cards bundle several colours and storage tiers in one title,
so a card title alone clusters under an arbitrary colour. `uzum.md §5` mandates matching
at SKU level from `characteristicValues`, using the card title only for brand context and
truncated at its first comma.

## Follow-on plans

3. **Clustering + aggregation** — `extract`/`cluster`/`aggregate`, `variant`,
   `variant_price`, `unresolved_offer`, uzum spread, and mediapark's Pass B.
4. **Web** — Next.js against the Narxnoma design.
