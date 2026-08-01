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
- **The development machine has no Docker and no local PostgreSQL.** Tests marked `db`
  (Tasks 2, 3 and 12) therefore *skip* during development and are verified for real on the
  server during deployment. Every other test — Tasks 1 and 4–11 — must pass locally, so a
  task is not done until its non-`db` tests are green. Do not weaken a test to make it run
  without a database; mark it `db` and move on.
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
- Produces: `Settings` (from `config`); `Listing` frozen dataclass with fields `store_slug, source_key, name_raw, price, url, availability, image_url, raw`; `PRICE_MIN`, `PRICE_MAX`, `is_plausible_price(price) -> bool`; `try_build_listing(**kwargs) -> Listing | None`; `Source` protocol with `slug: str`, `sweep() -> Iterator[Listing]`, `search(query: str) -> Iterator[Listing]`, `can_sweep: bool`; and from `http.py`: `polite_session(referer, origin, extra_headers) -> requests.Session`, `pause()`, `get_json(session, url, **kwargs) -> dict`, `post_json(session, url, **kwargs) -> dict`, `NonJsonResponse(ValueError)` raised by `get_json`/`post_json` when a 200-status body fails to decode as JSON, carrying `url`, `status_code`, and a 200-character `body_snippet`. Every retailer client calls `get_json`/`post_json` — they apply the timeout and the inter-request delay.

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
- Produces: `connect()` context manager; `migrate(conn)` applying `schema.sql` idempotently; pytest fixture `db_conn` that skips when `NARXNOMA_TEST_DSN` is unset.

**Note (added in the p2-task-12 fix pass):** the `db_conn` fixture below reads
`NARXNOMA_TEST_DSN`, a variable distinct from `NARXNOMA_DSN` (the production setting read
by `narxnoma/config.py`). It also refuses to truncate a database whose name doesn't
contain `test`. See `docs/deployment/local-postgres.md` for why: `db_conn` truncates its
database unconditionally on every `db` test, so a test suite that shared a variable with
production could destroy live crawler data.

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
-- Idempotent. Executed on every application start.
--
-- HOW TO CHANGE THIS FILE. Never edit an existing CREATE TABLE to add or alter a
-- column: CREATE TABLE IF NOT EXISTS is a no-op on a database that already has the
-- table, so the change would apply on a fresh database and silently not apply in
-- production. Instead append an explicit migration at the bottom of the file --
-- ALTER TABLE ... ADD COLUMN IF NOT EXISTS ... -- and bump the schema_version row.

CREATE TABLE IF NOT EXISTS schema_version (
    version     integer PRIMARY KEY,
    applied_at  timestamptz NOT NULL DEFAULT now()
);
INSERT INTO schema_version (version) VALUES (1) ON CONFLICT (version) DO NOTHING;

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
    availability text NOT NULL DEFAULT 'UNKNOWN'
        CHECK (availability IN ('IN_STOCK', 'OUT_OF_STOCK', 'UNKNOWN')),
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
    availability text NOT NULL DEFAULT 'UNKNOWN'
        CHECK (availability IN ('IN_STOCK', 'OUT_OF_STOCK', 'UNKNOWN')),
    image_url    text,
    first_seen   timestamptz NOT NULL DEFAULT now(),
    last_seen    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (store_id, source_key)
);
CREATE INDEX IF NOT EXISTS offer_last_seen ON offer (last_seen DESC);
CREATE INDEX IF NOT EXISTS offer_variant ON offer (variant_id) WHERE variant_id IS NOT NULL;

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
CREATE INDEX IF NOT EXISTS harvest_run_store_started
    ON harvest_run (store_id, started_at DESC);

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
```

`tests/test_conftest_guard.py` — a test for the guard itself, so a regression in
`require_disposable_test_database` is caught without needing a live database:

```python
import pytest

from conftest import require_disposable_test_database


def test_refuses_a_database_without_test_in_its_name():
    with pytest.raises(RuntimeError):
        require_disposable_test_database("postgresql://narxnoma@127.0.0.1:55432/narxnoma")


def test_does_not_raise_for_a_database_named_with_test_suffix():
    require_disposable_test_database("postgresql://narxnoma@127.0.0.1:55432/narxnoma_test")
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
    "db: needs a PostgreSQL instance (set NARXNOMA_TEST_DSN, a disposable database distinct from the production NARXNOMA_DSN)",
    "live: hits a real retailer API",
]
addopts = "-m 'not live'"
```

- [ ] **Step 4: Run to verify failure**

Run: `cd narxnoma-crawler && python -m pytest tests/db -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'narxnoma.db'` (or SKIP if `NARXNOMA_TEST_DSN` is unset; export it first, after `docker compose up -d`). Do not export `NARXNOMA_DSN` for this — that is the production variable; the test suite reads `NARXNOMA_TEST_DSN` only, and never falls back.

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
docker compose exec db createdb -U narxnoma narxnoma_test   # once, alongside the default narxnoma db
export NARXNOMA_TEST_DSN=postgresql://narxnoma:narxnoma@localhost:5432/narxnoma_test
python -m pytest tests/db -v
```

Expected: PASS — 3 passed. Use `NARXNOMA_TEST_DSN`, not `NARXNOMA_DSN`, for running tests —
see `docs/deployment/local-postgres.md` for why the two must never point at the same
database.

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
        # ORDER BY id, not observed_at: observed_at defaults to now(), which is the
        # transaction timestamp -- rows written in the same transaction share it, so
        # only id (true insertion order) disambiguates them.
        cur.execute("SELECT price FROM raw_offer WHERE source_key='k1' ORDER BY id")
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
"""The only place that writes offers. Keeps SQL out of the pipeline.

Commit boundary: each function below commits its own transaction
independently. start_run, the data writes (record_raw_offers /
upsert_offers) and finish_run are deliberately *not* one unit of work.
For a long-running crawl that is the right choice -- if a source dies half
way through a sweep, the listings already written should stay written
rather than being rolled back along with everything else, and start_run,
finish_run and the upsert are all idempotent enough that re-running a
failed step is safe.
"""
import functools
import json
from typing import Any, Iterable
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from narxnoma.sources.base import Listing


def _scrub_nuls(value: Any) -> Any:
    """Recursively strip NUL (\\u0000) characters from strings nested in
    dicts, lists and scalars. \\u0000 is valid JSON but PostgreSQL's jsonb
    type rejects it outright with error 22P05, and retailer payloads --
    parsed straight from their API JSON -- occasionally contain it."""
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, dict):
        return {k: _scrub_nuls(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub_nuls(v) for v in value]
    return value


# default=str: a retailer payload can contain a value json.dumps cannot
# serialise on its own (e.g. something that survived parsing as a non-JSON
# type). Rather than raising a TypeError mid-batch and aborting every row,
# such a value is degraded to its str() form.
_dump_json = functools.partial(json.dumps, ensure_ascii=False, default=str)


def store_ids(conn: psycopg.Connection) -> dict[str, UUID]:
    # Every function in this module wraps its body in conn.transaction(),
    # which commits on success and rolls back on error. Without this, a
    # failed statement leaves the connection in psycopg's "aborted
    # transaction" state, and every subsequent call on that connection
    # raises InFailedSqlTransaction -- including the finish_run(ok=False,
    # ...) call a caller makes to record the very failure that just
    # happened. The rollback here is what keeps the connection usable for
    # that call.
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("SELECT slug, id FROM store WHERE is_active")
            return {slug: sid for slug, sid in cur.fetchall()}


def record_raw_offers(conn: psycopg.Connection, store_id: UUID,
                      listings: Iterable[Listing]) -> int:
    """Append one row per observation. Never updates -- this is the permanent
    log price history is later derived from, not a cache of current state."""
    rows = [
        (store_id, listing.source_key, listing.name_raw, listing.price, listing.url,
         listing.availability, listing.image_url,
         Jsonb(_scrub_nuls(listing.raw), dumps=_dump_json))
        for listing in listings
    ]
    if not rows:
        return 0
    with conn.transaction():
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO raw_offer"
                " (store_id, source_key, name_raw, price, url, availability, image_url, payload)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)", rows)
    return len(rows)


def upsert_offers(conn: psycopg.Connection, store_id: UUID,
                  listings: Iterable[Listing]) -> tuple[int, int]:
    """Insert new listings, refresh existing ones. first_seen never moves.

    RETURNING always yields the *new* row version, whether the INSERT or the
    ON CONFLICT DO UPDATE branch fired. Its xmax is 0 (true) when INSERT
    fired -- a brand-new row has never been locked by anyone. It is
    non-zero (false) when DO UPDATE fired instead: Postgres locks the
    conflicting row first while evaluating ON CONFLICT, and that locker's
    transaction id is carried forward onto the new row version's xmax. This
    is an undocumented detail of how ON CONFLICT DO UPDATE is implemented,
    not a guarantee made by the PostgreSQL documentation -- re-verify it
    against the release notes before relying on it across a major version
    upgrade. first_seen is omitted from the DO UPDATE SET list entirely, so
    on conflict it keeps its original DEFAULT now() value from the first
    insert.

    Deliberately not batched into a single multi-row VALUES statement: with
    ON CONFLICT, one statement touching the same conflict key twice raises
    "cannot affect row a second time", which a buggy client sweep could
    trigger. The per-row loop tolerates that; a batched statement would not.
    """
    inserted = updated = 0
    with conn.transaction():
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
    return inserted, updated


def start_run(conn: psycopg.Connection, store_id: UUID) -> int:
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("INSERT INTO harvest_run (store_id) VALUES (%s) RETURNING id", (store_id,))
            run_id = cur.fetchone()[0]
    return run_id


def finish_run(conn: psycopg.Connection, run_id: int, ok: bool,
               seen: int, kept: int, error: str | None = None) -> None:
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE harvest_run SET finished_at = now(), ok = %s,"
                " listings_seen = %s, listings_kept = %s, error = %s WHERE id = %s",
                (ok, seen, kept, error, run_id))
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

### Task 4: olcha client

**Files:**
- Create: `narxnoma-crawler/narxnoma/sources/olcha.py`
- Create: `narxnoma-crawler/tests/fixtures/sources/olcha.json`
- Test: `narxnoma-crawler/tests/sources/test_olcha.py`

**Interfaces:**
- Consumes: `Listing`, `try_build_listing`, `Source`, `polite_session`, `get_json`/`post_json`, `NonJsonResponse` (Task 1).
- Produces: a class `OlchaSource` with `slug`, `can_sweep`, `sweep()`, `search(query)`, and a module-level `parse(payload) -> list[Listing]` that turns one raw API response into listings.

**Endpoint contract and traps (olcha):**

olcha is fetched by **full category pull, not per-query search** — it is the only
source browsed this way, and it is what gives it the best coverage of the
non-uzum sources. `sweep()` GETs the category endpoint once per page, params
`page=<n>`, `per_page=20`, `category=telefony`, looping until `page` exceeds
`data.paginator.last_page` (currently ~22 pages, ~440 phones). olcha's endpoint has
no search parameter, so `search(query)` filters the already-swept catalogue
client-side by name rather than issuing a different call.

Endpoint: `GET https://mobile.olcha.uz/api/v2/products?page=<n>&per_page=20&category=telefony`
— note the `mobile.` host, the mobile-app API. No auth. Headers: `Accept: */*`,
`Accept-Language: ru`, `clientmodel: web` (required), `Origin: https://olcha.uz`,
`Referer: https://olcha.uz/`.

**`per_page` is capped at 20 server-side.** Requesting more (e.g. 100) silently
returns 20 — the page count is fixed by the category size. Don't try to shortcut it.

Response shape:

```json
{
  "data": {
    "products": [
      {
        "name_ru": "Смартфон Samsung Galaxy A27 5G 8/256GB Pink",
        "discount_price": 3290000,
        "total_price": 3590000,
        "alias": "smartfon-samsung-galaxy-a27-5g-8-256gb-pink",
        "quantity": 12
      }
    ],
    "paginator": {"last_page": 22}
  }
}
```

| Field | Meaning |
|---|---|
| `discount_price` | current price, plain SUM — **use this**; fall back to `total_price` when absent or `0` |
| `name_ru` | carries RAM + storage + colour |
| `alias` | URL slug |
| `quantity` | stock, drives `availability` |
| `paginator.last_page` | loop bound for `sweep()` |

Product URL: `https://olcha.uz/ru/product/view/<alias>`. **The `/view/` segment is
required** — the intuitive `https://olcha.uz/ru/product/<alias>` **404s**.

**Steps:**

- [ ] **Step 1: Record a real response into a fixture.** Call
  `GET https://mobile.olcha.uz/api/v2/products?page=1&per_page=20&category=telefony`
  once with the documented headers above, and save the raw JSON to
  `tests/fixtures/sources/olcha.json`. Trim it to at most 20 items so the fixture stays
  readable, but do not otherwise edit it — an edited fixture tests your assumptions
  rather than the retailer's behaviour. Note the exact request you made in a comment at
  the top of the test file.

- [ ] **Step 2: Write the failing parse test** against that fixture, using this exact
  structure. Only the three values marked `# FIXTURE:` are read off the recorded file —
  everything else is literal.

```python
"""Offline parse tests for the olcha client.

Fixture recorded live on YYYY-MM-DD with:
    <the exact URL and headers you used in Step 1>
"""
import json
import pathlib

from narxnoma.sources.olcha import parse
from narxnoma.sources.base import PRICE_MAX, PRICE_MIN

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "sources" / "olcha.json"

# FIXTURE: copy these three from one real item in the recorded file.
KNOWN_SOURCE_KEY = "..."
KNOWN_PRICE = 0            # in SUM, after any unit conversion
KNOWN_URL = "https://..."


def payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_fixture_exists_and_is_not_empty():
    """Guards against the parse tests passing vacuously over an empty file."""
    assert FIXTURE.exists(), f"record the fixture first: {FIXTURE}"
    assert payload()


def test_parse_returns_listings():
    listings = parse(payload())
    assert listings, "parse() found nothing in a real recorded response"


def test_every_listing_has_provenance():
    # A price we cannot attribute to a specific retailer listing is worthless.
    for lst in parse(payload()):
        assert lst.store_slug == "olcha"
        assert lst.source_key
        assert lst.name_raw
        assert lst.url.startswith("http")


def test_every_price_is_an_integer_inside_the_fences():
    for lst in parse(payload()):
        assert isinstance(lst.price, int)
        assert PRICE_MIN <= lst.price <= PRICE_MAX


def test_source_keys_are_unique_within_one_response():
    # source_key is the upsert key; duplicates would silently collapse offers.
    keys = [lst.source_key for lst in parse(payload())]
    assert len(keys) == len(set(keys))


def test_known_product_parses_exactly():
    by_key = {lst.source_key: lst for lst in parse(payload())}
    assert KNOWN_SOURCE_KEY in by_key
    assert by_key[KNOWN_SOURCE_KEY].price == KNOWN_PRICE
    assert by_key[KNOWN_SOURCE_KEY].url == KNOWN_URL


def test_malformed_items_are_dropped_not_raised():
    # One bad item must never kill a sweep of several hundred.
    broken = payload()
    parse(broken)          # must not raise even with the junk item below
```

  Finish `test_malformed_items_are_dropped_not_raised` by injecting a junk item into the
  payload's item list in the shape olcha uses — an entry with a null price, or a
  missing name — and asserting `parse()` returns the other items without raising.

- [ ] **Step 3: Run it and confirm it fails** with `ModuleNotFoundError`.

Run: `cd narxnoma-crawler && python -m pytest tests/sources/test_olcha.py -v`

- [ ] **Step 4: Implement the client.** Read `docs/parsers/olcha.md` for the endpoint
  contract and `narxnoma-seed/sources.py` for the verified request handling —
  `narxnoma-seed/sources.py` holds a verified working implementation of all seven
  clients, exercised live on 2026-07-26; read it alongside the doc, not instead of it.
  `parse()` must be a pure function of the payload so it is testable offline. Build each
  `Listing` with `try_build_listing` (Task 1), never `Listing(...)` directly — a parse
  loop that constructs `Listing` itself is re-implementing the drop-and-count handling
  that `try_build_listing` exists to centralize, one malformed item must not kill a
  sweep, and any item `try_build_listing` returns `None` for is dropped and counted
  rather than raising.

- [ ] **Step 5: Run the parse test and confirm it passes.**

Run: `cd narxnoma-crawler && python -m pytest tests/sources/test_olcha.py -v`
Expected: PASS

- [ ] **Step 6: Add a live contract test** in `tests/sources/test_contract_live.py`,
  marked `@pytest.mark.live`, that calls the real endpoint and asserts the documented
  field names still exist and prices still land inside the fences. This is what catches
  a silent API change before it becomes wrong prices. It is skipped by default via
  `addopts`.

- [ ] **Step 7: Run the live test once manually** to prove it works:
  `python -m pytest tests/sources/test_contract_live.py -m live -k olcha -v`.

- [ ] **Step 8: Commit** with the message
  `feat(sources): add olcha client with recorded-fixture parse tests`.

---

### Task 5: texnomart client

**Files:**
- Create: `narxnoma-crawler/narxnoma/sources/texnomart.py`
- Create: `narxnoma-crawler/tests/fixtures/sources/texnomart.json`
- Test: `narxnoma-crawler/tests/sources/test_texnomart.py`

**Interfaces:**
- Consumes: `Listing`, `try_build_listing`, `Source`, `polite_session`, `get_json`/`post_json`, `NonJsonResponse` (Task 1).
- Produces: a class `TexnomartSource` with `slug`, `can_sweep`, `sweep()`, `search(query)`, and a module-level `parse(payload) -> list[Listing]` that turns one raw API response into listings.

**Endpoint contract and traps (texnomart):**

texnomart is fetched by **generic query sweep**. `sweep()` GETs the search endpoint
with `q=smartfon`, paginating on `data.pagination.total_page` (currently ~25 pages).
`search(query)` issues the same call with the caller's query text.

Endpoint: `GET https://gw.texnomart.uz/api/common/v1/search/result?q=<text>&page=<n>&limit=20`.
No auth. Headers: `Accept: application/json, text/plain, */*`, `accept-device: web`
(required), `accept-language: uz`, `accept-region: 2` (required — selects the
Tashkent price region), `Origin: https://texnomart.uz`, `Referer: https://texnomart.uz/`.

**There are two similar hosts and only one carries prices.**
`gateway.texnomart.uz/api/common/v1/search/header` is autocomplete only — names and
ids, no prices, a dead end. `gw.texnomart.uz/api/common/v1/search/result` is the real
one, with `sale_price`. Do not probe product-detail endpoints off the `gateway.` host
— they 404 for every guessed path.

Response shape:

```json
{
  "data": {
    "products": [
      {"id": 32417, "name": "Honor X9d 12/256GB Midnight Black",
       "sale_price": 5299000, "old_price": 0}
    ],
    "pagination": {"total_page": 2}
  }
}
```

| Field | Meaning |
|---|---|
| `sale_price` | current price, plain SUM — **use this** |
| `old_price` | pre-discount, **frequently `0`** — never use it as a fallback |
| `id` | numeric product id, used to build the URL |
| `name` | carries RAM + storage + colour |

Product URL: `https://texnomart.uz/product/detail/<id>/` — numeric id, no slug to get
wrong, but the trailing slash matters.

**Steps:**

- [ ] **Step 1: Record a real response into a fixture.** Call
  `GET https://gw.texnomart.uz/api/common/v1/search/result?q=smartfon&page=1&limit=20`
  once with the documented headers above, and save the raw JSON to
  `tests/fixtures/sources/texnomart.json`. Trim it to at most 20 items so the fixture
  stays readable, but do not otherwise edit it — an edited fixture tests your
  assumptions rather than the retailer's behaviour. Note the exact request you made in
  a comment at the top of the test file.

- [ ] **Step 2: Write the failing parse test** against that fixture, using this exact
  structure. Only the three values marked `# FIXTURE:` are read off the recorded file —
  everything else is literal.

```python
"""Offline parse tests for the texnomart client.

Fixture recorded live on YYYY-MM-DD with:
    <the exact URL and headers you used in Step 1>
"""
import json
import pathlib

from narxnoma.sources.texnomart import parse
from narxnoma.sources.base import PRICE_MAX, PRICE_MIN

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "sources" / "texnomart.json"

# FIXTURE: copy these three from one real item in the recorded file.
KNOWN_SOURCE_KEY = "..."
KNOWN_PRICE = 0            # in SUM, after any unit conversion
KNOWN_URL = "https://..."


def payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_fixture_exists_and_is_not_empty():
    """Guards against the parse tests passing vacuously over an empty file."""
    assert FIXTURE.exists(), f"record the fixture first: {FIXTURE}"
    assert payload()


def test_parse_returns_listings():
    listings = parse(payload())
    assert listings, "parse() found nothing in a real recorded response"


def test_every_listing_has_provenance():
    # A price we cannot attribute to a specific retailer listing is worthless.
    for lst in parse(payload()):
        assert lst.store_slug == "texnomart"
        assert lst.source_key
        assert lst.name_raw
        assert lst.url.startswith("http")


def test_every_price_is_an_integer_inside_the_fences():
    for lst in parse(payload()):
        assert isinstance(lst.price, int)
        assert PRICE_MIN <= lst.price <= PRICE_MAX


def test_source_keys_are_unique_within_one_response():
    # source_key is the upsert key; duplicates would silently collapse offers.
    keys = [lst.source_key for lst in parse(payload())]
    assert len(keys) == len(set(keys))


def test_known_product_parses_exactly():
    by_key = {lst.source_key: lst for lst in parse(payload())}
    assert KNOWN_SOURCE_KEY in by_key
    assert by_key[KNOWN_SOURCE_KEY].price == KNOWN_PRICE
    assert by_key[KNOWN_SOURCE_KEY].url == KNOWN_URL


def test_malformed_items_are_dropped_not_raised():
    # One bad item must never kill a sweep of several hundred.
    broken = payload()
    parse(broken)          # must not raise even with the junk item below
```

  Finish `test_malformed_items_are_dropped_not_raised` by injecting a junk item into the
  payload's item list in the shape texnomart uses — an entry with a null price, or a
  missing name — and asserting `parse()` returns the other items without raising.

- [ ] **Step 3: Run it and confirm it fails** with `ModuleNotFoundError`.

Run: `cd narxnoma-crawler && python -m pytest tests/sources/test_texnomart.py -v`

- [ ] **Step 4: Implement the client.** Read `docs/parsers/texnomart.md` for the
  endpoint contract and `narxnoma-seed/sources.py` for the verified request handling —
  `narxnoma-seed/sources.py` holds a verified working implementation of all seven
  clients, exercised live on 2026-07-26; read it alongside the doc, not instead of it.
  `parse()` must be a pure function of the payload so it is testable offline. Build each
  `Listing` with `try_build_listing` (Task 1), never `Listing(...)` directly — a parse
  loop that constructs `Listing` itself is re-implementing the drop-and-count handling
  that `try_build_listing` exists to centralize, one malformed item must not kill a
  sweep, and any item `try_build_listing` returns `None` for is dropped and counted
  rather than raising.

- [ ] **Step 5: Run the parse test and confirm it passes.**

Run: `cd narxnoma-crawler && python -m pytest tests/sources/test_texnomart.py -v`
Expected: PASS

- [ ] **Step 6: Add a live contract test** in `tests/sources/test_contract_live.py`,
  marked `@pytest.mark.live`, that calls the real endpoint and asserts the documented
  field names still exist and prices still land inside the fences. This is what catches
  a silent API change before it becomes wrong prices. It is skipped by default via
  `addopts`.

- [ ] **Step 7: Run the live test once manually** to prove it works:
  `python -m pytest tests/sources/test_contract_live.py -m live -k texnomart -v`.

- [ ] **Step 8: Commit** with the message
  `feat(sources): add texnomart client with recorded-fixture parse tests`.

---

### Task 6: idea client

**Files:**
- Create: `narxnoma-crawler/narxnoma/sources/idea.py`
- Create: `narxnoma-crawler/tests/fixtures/sources/idea.json`
- Test: `narxnoma-crawler/tests/sources/test_idea.py`

**Interfaces:**
- Consumes: `Listing`, `try_build_listing`, `Source`, `polite_session`, `get_json`/`post_json`, `NonJsonResponse` (Task 1).
- Produces: a class `IdeaSource` with `slug`, `can_sweep`, `sweep()`, `search(query)`, and a module-level `parse(payload) -> list[Listing]` that turns one raw API response into listings.

**Endpoint contract and traps (idea):**

idea is fetched by **brand queries** — it has no full-catalogue browse, so `sweep()`
loops over a fixed list of brand queries (Samsung, Xiaomi/Redmi, Honor, Apple,
Infinix, Tecno, realme, Nokia, …) and calls the search endpoint once per brand with
`quantity=100`, which the API honours (~94 items per call); there is no pagination.
`search(query)` issues the same call with the caller's query text.

Endpoint: `GET https://api.idea.uz/api/v2/search?search=<text>&quantity=100&type[]=shops&type[]=products`.
No auth. Headers: `Accept: application/json`, `Accept-Language: uz`,
`Origin: https://idea.uz`, `Referer: https://idea.uz/`.

**`type[]` is a repeated parameter, not a comma list.** With `requests`, pass
`params={"type[]": ["shops", "products"], ...}` — `requests` expands a list value
into repeated `type[]=` pairs correctly; a comma-joined string does not work.

Response shape:

```json
{
  "products": [
    {"id": 12345, "name": "Honor X9d 12/256 GB Midnight Black",
     "slug": "honor-x9d-12-256-gb-midnight-black",
     "url": "https://idea.uz/ru/product/honor-x9d-12-256-gb-midnight-black",
     "current_price": 5390000}
  ],
  "shops": [], "brands": [], "categories": []
}
```

| Field | Meaning |
|---|---|
| `current_price` | current price, plain SUM — **use this** |
| `name` | carries RAM + storage + colour |
| `url` | **absolute product URL, ready to use** |

Product URL: take `products[].url` **verbatim** — idea is the only source that
returns a complete absolute URL, so `parse()` must not reconstruct one from `slug`.

**Steps:**

- [ ] **Step 1: Record a real response into a fixture.** Call
  `GET https://api.idea.uz/api/v2/search?search=Samsung&quantity=100&type[]=shops&type[]=products`
  once with the documented headers above, and save the raw JSON to
  `tests/fixtures/sources/idea.json`. Trim it to at most 20 items so the fixture stays
  readable, but do not otherwise edit it — an edited fixture tests your assumptions
  rather than the retailer's behaviour. Note the exact request you made in a comment at
  the top of the test file.

- [ ] **Step 2: Write the failing parse test** against that fixture, using this exact
  structure. Only the three values marked `# FIXTURE:` are read off the recorded file —
  everything else is literal.

```python
"""Offline parse tests for the idea client.

Fixture recorded live on YYYY-MM-DD with:
    <the exact URL and headers you used in Step 1>
"""
import json
import pathlib

from narxnoma.sources.idea import parse
from narxnoma.sources.base import PRICE_MAX, PRICE_MIN

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "sources" / "idea.json"

# FIXTURE: copy these three from one real item in the recorded file.
KNOWN_SOURCE_KEY = "..."
KNOWN_PRICE = 0            # in SUM, after any unit conversion
KNOWN_URL = "https://..."


def payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_fixture_exists_and_is_not_empty():
    """Guards against the parse tests passing vacuously over an empty file."""
    assert FIXTURE.exists(), f"record the fixture first: {FIXTURE}"
    assert payload()


def test_parse_returns_listings():
    listings = parse(payload())
    assert listings, "parse() found nothing in a real recorded response"


def test_every_listing_has_provenance():
    # A price we cannot attribute to a specific retailer listing is worthless.
    for lst in parse(payload()):
        assert lst.store_slug == "idea"
        assert lst.source_key
        assert lst.name_raw
        assert lst.url.startswith("http")


def test_every_price_is_an_integer_inside_the_fences():
    for lst in parse(payload()):
        assert isinstance(lst.price, int)
        assert PRICE_MIN <= lst.price <= PRICE_MAX


def test_source_keys_are_unique_within_one_response():
    # source_key is the upsert key; duplicates would silently collapse offers.
    keys = [lst.source_key for lst in parse(payload())]
    assert len(keys) == len(set(keys))


def test_known_product_parses_exactly():
    by_key = {lst.source_key: lst for lst in parse(payload())}
    assert KNOWN_SOURCE_KEY in by_key
    assert by_key[KNOWN_SOURCE_KEY].price == KNOWN_PRICE
    assert by_key[KNOWN_SOURCE_KEY].url == KNOWN_URL


def test_malformed_items_are_dropped_not_raised():
    # One bad item must never kill a sweep of several hundred.
    broken = payload()
    parse(broken)          # must not raise even with the junk item below


def test_parsed_count_is_pinned_to_the_recording():
    """Pin how many of the recorded items survive parsing.

    Retailer responses mix phones with accessories, and the price fence
    silently drops the accessories -- correctly, but silently. Without this
    assertion a change to PRICE_MIN or coerce_price could turn a 4,000 SUM
    screen protector into a catalogue entry and no test would fail.
    """
    raw_items = ...          # FIXTURE: count the item list in the recorded file
    parsed = parse(payload())
    assert len(parsed) == 0  # FIXTURE: replace with the real parsed count
    # If parsed < raw, name each dropped item and why, so the gap is deliberate.
```

  Finish `test_malformed_items_are_dropped_not_raised` by injecting a junk item into the
  payload's item list in the shape idea uses — an entry with a null price, or a missing
  name — and asserting `parse()` returns the other items without raising.

  Then fill in `test_parsed_count_is_pinned_to_the_recording`: count the items in the
  recorded fixture and the items `parse()` actually returns, identify every item the
  recording drops and say why in a comment — a source quietly discarding items is the
  failure mode this project exists to prevent.

- [ ] **Step 3: Run it and confirm it fails** with `ModuleNotFoundError`.

Run: `cd narxnoma-crawler && python -m pytest tests/sources/test_idea.py -v`

- [ ] **Step 4: Implement the client.** Read `docs/parsers/idea.md` for the endpoint
  contract and `narxnoma-seed/sources.py` for the verified request handling —
  `narxnoma-seed/sources.py` holds a verified working implementation of all seven
  clients, exercised live on 2026-07-26; read it alongside the doc, not instead of it.
  `parse()` must be a pure function of the payload so it is testable offline. Build each
  `Listing` with `try_build_listing` (Task 1), never `Listing(...)` directly — a parse
  loop that constructs `Listing` itself is re-implementing the drop-and-count handling
  that `try_build_listing` exists to centralize, one malformed item must not kill a
  sweep, and any item `try_build_listing` returns `None` for is dropped and counted
  rather than raising.

- [ ] **Step 5: Run the parse test and confirm it passes.**

Run: `cd narxnoma-crawler && python -m pytest tests/sources/test_idea.py -v`
Expected: PASS

- [ ] **Step 6: Add a live contract test** in `tests/sources/test_contract_live.py`,
  marked `@pytest.mark.live`, that calls the real endpoint and asserts the documented
  field names still exist and prices still land inside the fences. This is what catches
  a silent API change before it becomes wrong prices. It is skipped by default via
  `addopts`.

- [ ] **Step 7: Run the live test once manually** to prove it works:
  `python -m pytest tests/sources/test_contract_live.py -m live -k idea -v`.

- [ ] **Step 8: Commit** with the message
  `feat(sources): add idea client with recorded-fixture parse tests`.

---

### Task 7: beemarket client

**Files:**
- Create: `narxnoma-crawler/narxnoma/sources/beemarket.py`
- Create: `narxnoma-crawler/tests/fixtures/sources/beemarket.json`
- Test: `narxnoma-crawler/tests/sources/test_beemarket.py`

**Interfaces:**
- Consumes: `Listing`, `try_build_listing`, `Source`, `polite_session`, `get_json`/`post_json`, `NonJsonResponse` (Task 1).
- Produces: a class `BeemarketSource` with `slug`, `can_sweep`, `sweep()`, `search(query)`, and a module-level `parse(payload) -> list[Listing]` that turns one raw API response into listings.

**Endpoint contract and traps (beemarket):**

beemarket is **fully browsable**. `sweep()` GETs the search endpoint with an **empty
query** (`q=`) and `is_bshop=1`, paginating `page` from 1 (1-based) through
`data.data.last_page` — currently 233 pages. `search(query)` issues the same call
with the caller's query text in `q`.

Endpoint: `GET https://market.beeline.uz/api/web/search?q=<text>&is_bshop=1&page=<n>`.
No auth. Headers: `Accept: */*`, `Accept-Language: ru`,
`Referer: https://market.beeline.uz/`. `is_bshop=1` restricts results to the
BeeMarket shop catalogue — keep it. `page` is **1-based**.

Response has a **doubly-nested `data.data`** — a common source of `KeyError` if
missed:

```json
{
  "code": 200,
  "data": {
    "data": [
      {"name": "Honor X9d, Midnight Black, 12/256 GB",
       "slug": "honor-x9d-point-midnight-black-point-12256-gb",
       "category": {"slug": "smartfony"},
       "actual_price": 5290000, "price": 5990000}
    ],
    "last_page": 233
  }
}
```

| Field | Meaning |
|---|---|
| `actual_price` | current displayed price, plain SUM, discount applied — **use this, not `price`** |
| `price` | struck-through pre-discount list price — do not use |
| `name` | carries RAM + storage + colour, comma-separated |
| `slug` | URL slug — encodes a literal `.` as the token `point`, so use it verbatim rather than generating one |
| `category.slug` | needed for the URL; default to `smartfony` if absent |
| `data.last_page` | loop bound for `sweep()` |

Product URL: `https://market.beeline.uz/<category.slug>/<slug>`.

**Steps:**

- [ ] **Step 1: Record a real response into a fixture.** Call
  `GET https://market.beeline.uz/api/web/search?q=&is_bshop=1&page=1` once with the
  documented headers above, and save the raw JSON to
  `tests/fixtures/sources/beemarket.json`. Trim it to at most 20 items so the fixture
  stays readable, but do not otherwise edit it — an edited fixture tests your
  assumptions rather than the retailer's behaviour. Note the exact request you made in
  a comment at the top of the test file.

- [ ] **Step 2: Write the failing parse test** against that fixture, using this exact
  structure. Only the three values marked `# FIXTURE:` are read off the recorded file —
  everything else is literal.

```python
"""Offline parse tests for the beemarket client.

Fixture recorded live on YYYY-MM-DD with:
    <the exact URL and headers you used in Step 1>
"""
import json
import pathlib

from narxnoma.sources.beemarket import parse
from narxnoma.sources.base import PRICE_MAX, PRICE_MIN

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "sources" / "beemarket.json"

# FIXTURE: copy these three from one real item in the recorded file.
KNOWN_SOURCE_KEY = "..."
KNOWN_PRICE = 0            # in SUM, after any unit conversion
KNOWN_URL = "https://..."


def payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_fixture_exists_and_is_not_empty():
    """Guards against the parse tests passing vacuously over an empty file."""
    assert FIXTURE.exists(), f"record the fixture first: {FIXTURE}"
    assert payload()


def test_parse_returns_listings():
    listings = parse(payload())
    assert listings, "parse() found nothing in a real recorded response"


def test_every_listing_has_provenance():
    # A price we cannot attribute to a specific retailer listing is worthless.
    for lst in parse(payload()):
        assert lst.store_slug == "beemarket"
        assert lst.source_key
        assert lst.name_raw
        assert lst.url.startswith("http")


def test_every_price_is_an_integer_inside_the_fences():
    for lst in parse(payload()):
        assert isinstance(lst.price, int)
        assert PRICE_MIN <= lst.price <= PRICE_MAX


def test_source_keys_are_unique_within_one_response():
    # source_key is the upsert key; duplicates would silently collapse offers.
    keys = [lst.source_key for lst in parse(payload())]
    assert len(keys) == len(set(keys))


def test_known_product_parses_exactly():
    by_key = {lst.source_key: lst for lst in parse(payload())}
    assert KNOWN_SOURCE_KEY in by_key
    assert by_key[KNOWN_SOURCE_KEY].price == KNOWN_PRICE
    assert by_key[KNOWN_SOURCE_KEY].url == KNOWN_URL


def test_malformed_items_are_dropped_not_raised():
    # One bad item must never kill a sweep of several hundred.
    broken = payload()
    parse(broken)          # must not raise even with the junk item below


def test_parsed_count_is_pinned_to_the_recording():
    """Pin how many of the recorded items survive parsing.

    Retailer responses mix phones with accessories, and the price fence
    silently drops the accessories -- correctly, but silently. Without this
    assertion a change to PRICE_MIN or coerce_price could turn a 4,000 SUM
    screen protector into a catalogue entry and no test would fail.
    """
    raw_items = ...          # FIXTURE: count the item list in the recorded file
    parsed = parse(payload())
    assert len(parsed) == 0  # FIXTURE: replace with the real parsed count
    # If parsed < raw, name each dropped item and why, so the gap is deliberate.
```

  Finish `test_malformed_items_are_dropped_not_raised` by injecting a junk item into the
  payload's item list in the shape beemarket uses — an entry with a null price, or a
  missing name — and asserting `parse()` returns the other items without raising.

  Then fill in `test_parsed_count_is_pinned_to_the_recording`: count the items in the
  recorded fixture and the items `parse()` actually returns, identify every item the
  recording drops and say why in a comment — a source quietly discarding items is the
  failure mode this project exists to prevent.

- [ ] **Step 3: Run it and confirm it fails** with `ModuleNotFoundError`.

Run: `cd narxnoma-crawler && python -m pytest tests/sources/test_beemarket.py -v`

- [ ] **Step 4: Implement the client.** Read `docs/parsers/beemarket.md` for the
  endpoint contract and `narxnoma-seed/sources.py` for the verified request handling —
  `narxnoma-seed/sources.py` holds a verified working implementation of all seven
  clients, exercised live on 2026-07-26; read it alongside the doc, not instead of it.
  `parse()` must be a pure function of the payload so it is testable offline. Build each
  `Listing` with `try_build_listing` (Task 1), never `Listing(...)` directly — a parse
  loop that constructs `Listing` itself is re-implementing the drop-and-count handling
  that `try_build_listing` exists to centralize, one malformed item must not kill a
  sweep, and any item `try_build_listing` returns `None` for is dropped and counted
  rather than raising.

- [ ] **Step 5: Run the parse test and confirm it passes.**

Run: `cd narxnoma-crawler && python -m pytest tests/sources/test_beemarket.py -v`
Expected: PASS

- [ ] **Step 6: Add a live contract test** in `tests/sources/test_contract_live.py`,
  marked `@pytest.mark.live`, that calls the real endpoint and asserts the documented
  field names still exist and prices still land inside the fences. This is what catches
  a silent API change before it becomes wrong prices. It is skipped by default via
  `addopts`.

- [ ] **Step 7: Run the live test once manually** to prove it works:
  `python -m pytest tests/sources/test_contract_live.py -m live -k beemarket -v`.

- [ ] **Step 8: Commit** with the message
  `feat(sources): add beemarket client with recorded-fixture parse tests`.

---

### Task 8: alifshop client

**Files:**
- Create: `narxnoma-crawler/narxnoma/sources/alifshop.py`
- Create: `narxnoma-crawler/tests/fixtures/sources/alifshop.json`
- Test: `narxnoma-crawler/tests/sources/test_alifshop.py`

**Interfaces:**
- Consumes: `Listing`, `try_build_listing`, `Source`, `polite_session`, `get_json`/`post_json`, `NonJsonResponse` (Task 1).
- Produces: a class `AlifshopSource` with `slug`, `can_sweep`, `sweep()`, `search(query)`, and a module-level `parse(payload) -> list[Listing]` that turns one raw API response into listings.

**Endpoint contract and traps (alifshop):**

alifshop is a multi-seller marketplace fetched by **per-brand sweep** — the
smartphone category runs to thousands of listings, too many to browse fully, unlike
olcha's. `sweep()` loops over a fixed list of brand queries and calls the search
endpoint once per brand per page, `page` **0-based**, until `page >= n_pages` or a
practical cap (3 pages / 60 listings per brand is what the reference implementation
uses, enough for a stable median). `search(query)` issues the same call with the
caller's query text, `page=0`.

Endpoint: `POST https://gw.alifshop.uz/web/client/search/full-text`, JSON body
`{"query": <text>, "page": <0-based>, "size": 20}`. No auth. Headers:
`Accept: application/json`, `Accept-Language: ru`, `Content-Type: application/json`,
`service-token: service-token-alifshop` (a **fixed public string, not a
credential**), `Origin: https://alifshop.uz`, `Referer: https://alifshop.uz/`.

`page` is **0-based** (unlike beemarket/texnomart, which are 1-based). `size` is
**capped at 20 server-side** — asking for more is silently ignored.

Response shape:

```json
{
  "items": [
    {"price": 259900000,
     "slug": "honor-x9d-12-256-gb-midnight-black-abc123",
     "product": {"name": "Honor X9d 12/256 GB Midnight Black"},
     "partner": {"slug": "some-seller"}}
  ],
  "n_pages": 4
}
```

| Field | Meaning |
|---|---|
| `items[].price` | **TIYIN, not SUM — divide by 100**. `259900000 / 100 = 2,599,000 SUM`. Forgetting the divisor produces prices 100x too large; a *partial* divisor bug is not obvious from the number alone, so assert the converted result also lands in a plausible 500K–50M range |
| `items[].product.name` | the string to carry as `name_raw` |
| `items[].slug` | listing slug, used for the URL |
| `items[].partner.slug` | seller identity, useful for dedupe/diagnostics |
| `n_pages` | total pages for this query |

Product URL: `https://alifshop.uz/moderated-offer/<slug>`. **Not**
`https://alifshop.uz/product/<slug>` — that 404s ("Biz buni topa olmadik"). The slug
from the API is correct; only the path prefix differs.

**Steps:**

- [ ] **Step 1: Record a real response into a fixture.** Call
  `POST https://gw.alifshop.uz/web/client/search/full-text` with body
  `{"query": "Samsung", "page": 0, "size": 20}` once with the documented headers
  above, and save the raw JSON to `tests/fixtures/sources/alifshop.json`. Trim it to
  at most 20 items so the fixture stays readable, but do not otherwise edit it — an
  edited fixture tests your assumptions rather than the retailer's behaviour. Note the
  exact request you made in a comment at the top of the test file.

- [ ] **Step 2: Write the failing parse test** against that fixture, using this exact
  structure. Only the three values marked `# FIXTURE:` are read off the recorded file —
  everything else is literal.

```python
"""Offline parse tests for the alifshop client.

Fixture recorded live on YYYY-MM-DD with:
    <the exact URL and headers you used in Step 1>
"""
import json
import pathlib

from narxnoma.sources.alifshop import parse
from narxnoma.sources.base import PRICE_MAX, PRICE_MIN

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "sources" / "alifshop.json"

# FIXTURE: copy these three from one real item in the recorded file.
KNOWN_SOURCE_KEY = "..."
KNOWN_PRICE = 0            # in SUM, after any unit conversion
KNOWN_URL = "https://..."


def payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_fixture_exists_and_is_not_empty():
    """Guards against the parse tests passing vacuously over an empty file."""
    assert FIXTURE.exists(), f"record the fixture first: {FIXTURE}"
    assert payload()


def test_parse_returns_listings():
    listings = parse(payload())
    assert listings, "parse() found nothing in a real recorded response"


def test_every_listing_has_provenance():
    # A price we cannot attribute to a specific retailer listing is worthless.
    for lst in parse(payload()):
        assert lst.store_slug == "alifshop"
        assert lst.source_key
        assert lst.name_raw
        assert lst.url.startswith("http")


def test_every_price_is_an_integer_inside_the_fences():
    for lst in parse(payload()):
        assert isinstance(lst.price, int)
        assert PRICE_MIN <= lst.price <= PRICE_MAX


def test_source_keys_are_unique_within_one_response():
    # source_key is the upsert key; duplicates would silently collapse offers.
    keys = [lst.source_key for lst in parse(payload())]
    assert len(keys) == len(set(keys))


def test_known_product_parses_exactly():
    by_key = {lst.source_key: lst for lst in parse(payload())}
    assert KNOWN_SOURCE_KEY in by_key
    assert by_key[KNOWN_SOURCE_KEY].price == KNOWN_PRICE
    assert by_key[KNOWN_SOURCE_KEY].url == KNOWN_URL


def test_malformed_items_are_dropped_not_raised():
    # One bad item must never kill a sweep of several hundred.
    broken = payload()
    parse(broken)          # must not raise even with the junk item below


def test_parsed_count_is_pinned_to_the_recording():
    """Pin how many of the recorded items survive parsing.

    Retailer responses mix phones with accessories, and the price fence
    silently drops the accessories -- correctly, but silently. Without this
    assertion a change to PRICE_MIN or coerce_price could turn a 4,000 SUM
    screen protector into a catalogue entry and no test would fail.
    """
    raw_items = ...          # FIXTURE: count the item list in the recorded file
    parsed = parse(payload())
    assert len(parsed) == 0  # FIXTURE: replace with the real parsed count
    # If parsed < raw, name each dropped item and why, so the gap is deliberate.
```

  Finish `test_malformed_items_are_dropped_not_raised` by injecting a junk item into the
  payload's item list in the shape alifshop uses — an entry with a null price, or a
  missing name — and asserting `parse()` returns the other items without raising.

  Then fill in `test_parsed_count_is_pinned_to_the_recording`: count the items in the
  recorded fixture and the items `parse()` actually returns, identify every item the
  recording drops and say why in a comment — a source quietly discarding items is the
  failure mode this project exists to prevent.

  **Add one further test** asserting the tiyin conversion explicitly, by reading the raw
  integer for `KNOWN_SOURCE_KEY` straight out of the fixture and checking
  `parsed.price == raw_price // 100`. Forgetting that divisor produces prices 100× too
  large, and the fences alone would not catch a partial-divisor bug.

- [ ] **Step 3: Run it and confirm it fails** with `ModuleNotFoundError`.

Run: `cd narxnoma-crawler && python -m pytest tests/sources/test_alifshop.py -v`

- [ ] **Step 4: Implement the client.** Read `docs/parsers/alifshop.md` for the
  endpoint contract and `narxnoma-seed/sources.py` for the verified request handling —
  `narxnoma-seed/sources.py` holds a verified working implementation of all seven
  clients, exercised live on 2026-07-26; read it alongside the doc, not instead of it.
  `parse()` must be a pure function of the payload so it is testable offline. Build each
  `Listing` with `try_build_listing` (Task 1), never `Listing(...)` directly — a parse
  loop that constructs `Listing` itself is re-implementing the drop-and-count handling
  that `try_build_listing` exists to centralize, one malformed item must not kill a
  sweep, and any item `try_build_listing` returns `None` for is dropped and counted
  rather than raising.

- [ ] **Step 5: Run the parse test and confirm it passes.**

Run: `cd narxnoma-crawler && python -m pytest tests/sources/test_alifshop.py -v`
Expected: PASS

- [ ] **Step 6: Add a live contract test** in `tests/sources/test_contract_live.py`,
  marked `@pytest.mark.live`, that calls the real endpoint and asserts the documented
  field names still exist and prices still land inside the fences. This is what catches
  a silent API change before it becomes wrong prices. It is skipped by default via
  `addopts`.

- [ ] **Step 7: Run the live test once manually** to prove it works:
  `python -m pytest tests/sources/test_contract_live.py -m live -k alifshop -v`.

- [ ] **Step 8: Commit** with the message
  `feat(sources): add alifshop client with recorded-fixture parse tests`.

---

### Task 9: mediapark client

**Files:**
- Create: `narxnoma-crawler/narxnoma/sources/mediapark.py`
- Create: `narxnoma-crawler/tests/fixtures/sources/mediapark.json`
- Test: `narxnoma-crawler/tests/sources/test_mediapark.py`

**Interfaces:**
- Consumes: `Listing`, `try_build_listing`, `Source`, `polite_session`, `get_json`/`post_json`, `NonJsonResponse` (Task 1).
- Produces: a class `MediaparkSource` with `slug`, `can_sweep`, `sweep()`, `search(query)`, and a module-level `parse(payload) -> list[Listing]` that turns one raw API response into listings.

**Endpoint contract and traps (mediapark):**

mediapark **cannot sweep** — the only endpoint is an autocomplete search with no
full-catalogue browse and no pagination. So `can_sweep = False`, and `sweep()` must
**raise `NotImplementedError`** with a message saying mediapark is search-only.

Raising is deliberate, not a matter of taste. An empty iterator would let a caller
that forgot to check `can_sweep` record a perfectly successful harvest run of zero
listings — silently, and indistinguishably from a source whose catalogue really is
empty. That is the failure this system exists to make impossible. `can_sweep` is the
guard callers must honour; `sweep()` raising is what tells them, loudly, when they
did not. Task 11's harvest stage must therefore check `can_sweep` and skip such a
source rather than calling `sweep()` and catching the error.

Only `search(query)` is implemented for this source. Driving mediapark per-variant
across a harvest cycle is out of scope here — the plan's Self-Review tracks it for
Plan 3.

Endpoint: `GET https://api.v2.mediapark.uz/v1/diginetica/autocomplete?st=<text>&lang=ru`.
Note the query parameter is `st`, not `q` or `search`. No auth. Headers:
`Accept: */*`, `Content-Type: application/json`, `Accept-Language: ru`,
`Origin: https://mediapark.uz`, `Referer: https://mediapark.uz/`, `x-device-id` /
`x-session-id` (required to be **present**, but any value works — they are not
credentials).

Response shape:

```json
{
  "products": [
    {"name": "Смартфон HONOR X9d (8/256) Midnight Black",
     "price": "5299000",
     "linkUrl": "/ru/products/view/honor-x9d-8-128-gb-32417"}
  ],
  "suggestions": [], "categories": []
}
```

| Field | Meaning |
|---|---|
| `price` | plain SUM but delivered as a **string** — cast to `int` |
| `name` | trustworthy: carries RAM, storage and colour |
| `linkUrl` | **relative** path — prefix with `https://mediapark.uz` |

**The slug lies about specs; the trailing id doesn't.** The example above's
`linkUrl` reads `8-128-gb` for a phone whose `name` says `8/256`. The route resolves
by the trailing numeric id, so the link still opens the right product — but the slug
must never be parsed for specs, and never reconstructed. **Match on `name`, use
`linkUrl` verbatim** (prefixed with the host).

**Steps:**

- [ ] **Step 1: Record a real response into a fixture.** Call
  `GET https://api.v2.mediapark.uz/v1/diginetica/autocomplete?st=Samsung&lang=ru`
  once with the documented headers above, and save the raw JSON to
  `tests/fixtures/sources/mediapark.json`. Trim it to at most 20 items so the fixture
  stays readable, but do not otherwise edit it — an edited fixture tests your
  assumptions rather than the retailer's behaviour. Note the exact request you made in
  a comment at the top of the test file.

- [ ] **Step 2: Write the failing parse test** against that fixture, using this exact
  structure. Only the three values marked `# FIXTURE:` are read off the recorded file —
  everything else is literal.

```python
"""Offline parse tests for the mediapark client.

Fixture recorded live on YYYY-MM-DD with:
    <the exact URL and headers you used in Step 1>
"""
import json
import pathlib

from narxnoma.sources.mediapark import parse
from narxnoma.sources.base import PRICE_MAX, PRICE_MIN

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "sources" / "mediapark.json"

# FIXTURE: copy these three from one real item in the recorded file.
KNOWN_SOURCE_KEY = "..."
KNOWN_PRICE = 0            # in SUM, after any unit conversion
KNOWN_URL = "https://..."


def payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_fixture_exists_and_is_not_empty():
    """Guards against the parse tests passing vacuously over an empty file."""
    assert FIXTURE.exists(), f"record the fixture first: {FIXTURE}"
    assert payload()


def test_parse_returns_listings():
    listings = parse(payload())
    assert listings, "parse() found nothing in a real recorded response"


def test_every_listing_has_provenance():
    # A price we cannot attribute to a specific retailer listing is worthless.
    for lst in parse(payload()):
        assert lst.store_slug == "mediapark"
        assert lst.source_key
        assert lst.name_raw
        assert lst.url.startswith("http")


def test_every_price_is_an_integer_inside_the_fences():
    for lst in parse(payload()):
        assert isinstance(lst.price, int)
        assert PRICE_MIN <= lst.price <= PRICE_MAX


def test_source_keys_are_unique_within_one_response():
    # source_key is the upsert key; duplicates would silently collapse offers.
    keys = [lst.source_key for lst in parse(payload())]
    assert len(keys) == len(set(keys))


def test_known_product_parses_exactly():
    by_key = {lst.source_key: lst for lst in parse(payload())}
    assert KNOWN_SOURCE_KEY in by_key
    assert by_key[KNOWN_SOURCE_KEY].price == KNOWN_PRICE
    assert by_key[KNOWN_SOURCE_KEY].url == KNOWN_URL


def test_malformed_items_are_dropped_not_raised():
    # One bad item must never kill a sweep of several hundred.
    broken = payload()
    parse(broken)          # must not raise even with the junk item below


def test_parsed_count_is_pinned_to_the_recording():
    """Pin how many of the recorded items survive parsing.

    Retailer responses mix phones with accessories, and the price fence
    silently drops the accessories -- correctly, but silently. Without this
    assertion a change to PRICE_MIN or coerce_price could turn a 4,000 SUM
    screen protector into a catalogue entry and no test would fail.
    """
    raw_items = ...          # FIXTURE: count the item list in the recorded file
    parsed = parse(payload())
    assert len(parsed) == 0  # FIXTURE: replace with the real parsed count
    # If parsed < raw, name each dropped item and why, so the gap is deliberate.
```

  Finish `test_malformed_items_are_dropped_not_raised` by injecting a junk item into the
  payload's item list in the shape mediapark uses — an entry with a null price, or a
  missing name — and asserting `parse()` returns the other items without raising.

  Then fill in `test_parsed_count_is_pinned_to_the_recording`: count the items in the
  recorded fixture and the items `parse()` actually returns, identify every item the
  recording drops and say why in a comment — a source quietly discarding items is the
  failure mode this project exists to prevent.

- [ ] **Step 3: Run it and confirm it fails** with `ModuleNotFoundError`.

Run: `cd narxnoma-crawler && python -m pytest tests/sources/test_mediapark.py -v`

- [ ] **Step 4: Implement the client.** Read `docs/parsers/mediapark.md` for the
  endpoint contract and `narxnoma-seed/sources.py` for the verified request handling —
  `narxnoma-seed/sources.py` holds a verified working implementation of all seven
  clients, exercised live on 2026-07-26; read it alongside the doc, not instead of it.
  `parse()` must be a pure function of the payload so it is testable offline. Build each
  `Listing` with `try_build_listing` (Task 1), never `Listing(...)` directly — a parse
  loop that constructs `Listing` itself is re-implementing the drop-and-count handling
  that `try_build_listing` exists to centralize, one malformed item must not kill a
  sweep, and any item `try_build_listing` returns `None` for is dropped and counted
  rather than raising.

- [ ] **Step 5: Run the parse test and confirm it passes.**

Run: `cd narxnoma-crawler && python -m pytest tests/sources/test_mediapark.py -v`
Expected: PASS

- [ ] **Step 6: Add a live contract test** in `tests/sources/test_contract_live.py`,
  marked `@pytest.mark.live`, that calls the real endpoint and asserts the documented
  field names still exist and prices still land inside the fences. This is what catches
  a silent API change before it becomes wrong prices. It is skipped by default via
  `addopts`.

- [ ] **Step 7: Run the live test once manually** to prove it works:
  `python -m pytest tests/sources/test_contract_live.py -m live -k mediapark -v`.

- [ ] **Step 8: Commit** with the message
  `feat(sources): add mediapark client with recorded-fixture parse tests`.

---

### Task 10: uzum client

**Files:**
- Create: `narxnoma-crawler/narxnoma/sources/uzum.py`
- Create: `narxnoma-crawler/tests/fixtures/sources/uzum.json`
- Test: `narxnoma-crawler/tests/sources/test_uzum.py`

**Interfaces:**
- Consumes: `Listing`, `try_build_listing`, `Source`, `polite_session`, `get_json`/`post_json`, `NonJsonResponse` (Task 1).
- Produces: a class `UzumSource` with `slug`, `can_sweep`, `sweep()`, `search(query)`, and a module-level `parse(payload) -> list[Listing]` that turns one raw API response into listings.

**Endpoint contract and traps (uzum):**

uzum is fetched by **per-brand GraphQL sweep**. `sweep()` mints a token once
(cached for the process, refreshed ~5 minutes before its 6-hour `exp`), then loops
over a fixed list of brand/query strings, paginating each with
`{"offset": n, "limit": 72}` until the response's `items` comes back empty or
`offset` reaches ~1000. **The offset caps at approximately 1000** — beyond that
`items` is always empty — so sweeping must go brand by brand rather than attempting
one unbounded query. `search(query)` issues one call with the caller's query text and
`offset=0`.

Auth: `POST https://id.uzum.uz/api/auth/token` with `Accept-Language` (any value,
e.g. `ru-RU`) and `Referer` (must be on the `uzum.uz` origin) — both required, or you
get `400 {"baseError":{"code":"insufficient_headers"}}` /
`{"code":"unallowed_app"}` respectively. **`Accept-Language` and `Referer` mint the
token; `Origin` is not required.** The response is `204 No Content` — the token is
**not in the body**, it arrives as a `Set-Cookie: access_token=<JWT>` header. TTL is
6 hours (`exp` in the JWT payload); mint a fresh one per run.

Endpoint: `POST https://graphql.uzum.uz/` with `Authorization: Bearer <token>`,
`Content-Type: application/json`, `apollographql-client-name: web-customers`,
`x-iid: <any UUID>` — all four required, or you get a bare `401` (missing
`Authorization`).

**GraphQL signals failure as HTTP 200 with an `errors` key, not an HTTP error
status.** Drop `apollographql-client-name` or `x-iid` and the request still returns
`200 OK` with `data: null` and an `errors` array (e.g.
`{"errors": [{"message": "HTTP fetch failed from 'search-gateway': 4.."}]}`).
`get_json`/`post_json` (Task 1) only raise on transport failure, so `parse()` and the
client must check `payload.get("errors")` explicitly rather than trusting a 200
status code.

The `makeSearch` query returns cards; the smartphone-relevant ones are
`SkuGroupCard`s with a `skuList`. Response shape (abbreviated):

```json
{"data": {"makeSearch": {"total": 262, "items": [
  {"catalogCard": {
    "__typename": "SkuGroupCard",
    "productId": 1983388,
    "title": "IPhone 17 Pro/Pro Max, 256, 512, 1 ТБ, 2 ТБ",
    "category": {"id": 15272, "title": "Смартфоны Apple iPhone (iOS)"},
    "skuList": [
      {"id": 7028608, "sellPrice": 20789010, "fullPrice": 31000000,
       "availableAmount": 27,
       "characteristicValues": [
         {"title": "17 Pro Max 256 GB", "characteristic": {"title": "Модель"}}]}
    ]}}
]}}}
```

| Field | Meaning |
|---|---|
| `skuList[].sellPrice` | current price, plain SUM, discount applied — **use this** |
| `skuList[].fullPrice` | pre-discount, often fantasy — never use |
| `skuList[].availableAmount` | filter to `> 0` |
| `catalogCard.category.id` | filter to `15271` (Android) / `15272` (iPhone) — relevance search mixes in accessories |

**Match at SKU level — `minSellPrice` understates by millions.** A card bundles
several models and storage tiers under one `minSellPrice`/`minFullPrice` (e.g. an
iPhone 17 Pro/Pro Max card's `minSellPrice` is the cheapest variant on the card, not
the 256GB Pro Max variant you actually want). Build `name_raw`/`source_key` from the
SKU's own `id` and `characteristicValues`, never the card-level min-price fields.

Product URL: `https://uzum.uz/ru/product/<productId>?skuId=<skuId>` —
302-redirects to the canonical slug, so no slug construction is needed.

**Steps:**

- [ ] **Step 1: Record a real response into a fixture.** Mint a token as described
  above, then call `POST https://graphql.uzum.uz/` with the `makeSearch` query and
  variables `{"text": "Samsung", "showAdultContent": "TRUE", "filters": [], "sort":
  "BY_RELEVANCE_DESC", "pagination": {"offset": 0, "limit": 72}}`, and save the raw
  JSON to `tests/fixtures/sources/uzum.json`. Trim it to at most 20 items so the
  fixture stays readable, but do not otherwise edit it — an edited fixture tests your
  assumptions rather than the retailer's behaviour. Note the exact request you made in
  a comment at the top of the test file.

- [ ] **Step 2: Write the failing parse test** against that fixture, using this exact
  structure. Only the three values marked `# FIXTURE:` are read off the recorded file —
  everything else is literal.

```python
"""Offline parse tests for the uzum client.

Fixture recorded live on YYYY-MM-DD with:
    <the exact URL and headers you used in Step 1>
"""
import json
import pathlib

from narxnoma.sources.uzum import parse
from narxnoma.sources.base import PRICE_MAX, PRICE_MIN

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "sources" / "uzum.json"

# FIXTURE: copy these three from one real item in the recorded file.
KNOWN_SOURCE_KEY = "..."
KNOWN_PRICE = 0            # in SUM, after any unit conversion
KNOWN_URL = "https://..."


def payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_fixture_exists_and_is_not_empty():
    """Guards against the parse tests passing vacuously over an empty file."""
    assert FIXTURE.exists(), f"record the fixture first: {FIXTURE}"
    assert payload()


def test_parse_returns_listings():
    listings = parse(payload())
    assert listings, "parse() found nothing in a real recorded response"


def test_every_listing_has_provenance():
    # A price we cannot attribute to a specific retailer listing is worthless.
    for lst in parse(payload()):
        assert lst.store_slug == "uzum"
        assert lst.source_key
        assert lst.name_raw
        assert lst.url.startswith("http")


def test_every_price_is_an_integer_inside_the_fences():
    for lst in parse(payload()):
        assert isinstance(lst.price, int)
        assert PRICE_MIN <= lst.price <= PRICE_MAX


def test_source_keys_are_unique_within_one_response():
    # source_key is the upsert key; duplicates would silently collapse offers.
    keys = [lst.source_key for lst in parse(payload())]
    assert len(keys) == len(set(keys))


def test_known_product_parses_exactly():
    by_key = {lst.source_key: lst for lst in parse(payload())}
    assert KNOWN_SOURCE_KEY in by_key
    assert by_key[KNOWN_SOURCE_KEY].price == KNOWN_PRICE
    assert by_key[KNOWN_SOURCE_KEY].url == KNOWN_URL


def test_malformed_items_are_dropped_not_raised():
    # One bad item must never kill a sweep of several hundred.
    broken = payload()
    parse(broken)          # must not raise even with the junk item below


def test_parsed_count_is_pinned_to_the_recording():
    """Pin how many of the recorded items survive parsing.

    Retailer responses mix phones with accessories, and the price fence
    silently drops the accessories -- correctly, but silently. Without this
    assertion a change to PRICE_MIN or coerce_price could turn a 4,000 SUM
    screen protector into a catalogue entry and no test would fail.
    """
    raw_items = ...          # FIXTURE: count the item list in the recorded file
    parsed = parse(payload())
    assert len(parsed) == 0  # FIXTURE: replace with the real parsed count
    # If parsed < raw, name each dropped item and why, so the gap is deliberate.
```

  Finish `test_malformed_items_are_dropped_not_raised` by injecting a junk item into the
  payload's item list in the shape uzum uses — an entry with a null price, or a missing
  name — and asserting `parse()` returns the other items without raising. Also cover the
  `errors`-key failure mode: construct a payload shaped like
  `{"data": null, "errors": [{"message": "..."}]}` and assert `parse()` returns `[]`
  rather than raising or silently returning garbage.

  Then fill in `test_parsed_count_is_pinned_to_the_recording`: count the items in the
  recorded fixture and the items `parse()` actually returns, identify every item the
  recording drops and say why in a comment — a source quietly discarding items is the
  failure mode this project exists to prevent.

- [ ] **Step 3: Run it and confirm it fails** with `ModuleNotFoundError`.

Run: `cd narxnoma-crawler && python -m pytest tests/sources/test_uzum.py -v`

- [ ] **Step 4: Implement the client.** Read `docs/parsers/uzum.md` for the endpoint
  contract and `narxnoma-seed/sources.py` for the verified request handling —
  `narxnoma-seed/sources.py` holds a verified working implementation of all seven
  clients, exercised live on 2026-07-26; read it alongside the doc, not instead of it.
  `parse()` must be a pure function of the payload so it is testable offline. Build each
  `Listing` with `try_build_listing` (Task 1), never `Listing(...)` directly — a parse
  loop that constructs `Listing` itself is re-implementing the drop-and-count handling
  that `try_build_listing` exists to centralize, one malformed item must not kill a
  sweep, and any item `try_build_listing` returns `None` for is dropped and counted
  rather than raising.

- [ ] **Step 5: Run the parse test and confirm it passes.**

Run: `cd narxnoma-crawler && python -m pytest tests/sources/test_uzum.py -v`
Expected: PASS

- [ ] **Step 6: Add a live contract test** in `tests/sources/test_contract_live.py`,
  marked `@pytest.mark.live`, that calls the real endpoint and asserts the documented
  field names still exist and prices still land inside the fences. This is what catches
  a silent API change before it becomes wrong prices. It is skipped by default via
  `addopts`.

- [ ] **Step 7: Run the live test once manually** to prove it works:
  `python -m pytest tests/sources/test_contract_live.py -m live -k uzum -v`.

- [ ] **Step 8: Commit** with the message
  `feat(sources): add uzum client with recorded-fixture parse tests`.

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
        # A search-only source (mediapark) has no catalogue to browse. Skip it
        # explicitly rather than calling sweep() -- sweep() raises for those, and
        # honouring can_sweep is the caller's job.
        if not source.can_sweep:
            logger.info("skipping %s: search-only source, nothing to sweep", source.slug)
            results.append(HarvestResult(source.slug, ok=True, error="search-only, skipped"))
            continue
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
- Produces: `coverage_report(conn) -> list[SourceCoverage]` with `slug, offers, median_price, oldest_seen, newest_seen, last_run_ok, expected_min, is_suspicious`; and `EXPECTED_MIN_OFFERS: dict[str, int]`.

This task exists because a source can fail silently by returning fewer rows rather than
by raising. The incumbent has a store dead since April still flagged healthy.

### The silent-shrinkage guard — added after Task 7's review

Every source built so far shares one blind spot, and it must be closed here rather than
in each client. All of them raise loudly when an endpoint 404s or returns non-JSON. None
of them notice a retailer that starts answering **HTTP 200 with an empty item list**. In
that case `sweep()` exits cleanly after page one, the harvest records `ok = True` with
zero listings, and the catalogue quietly empties while every check stays green.

This is not hypothetical. beemarket's sweep now uses an endpoint discovered by watching
the retailer's own frontend, which the retailer does not document and could rescope
without warning — and the same failure shape applies to alifshop's and uzum's per-brand
queries, and to any category id or slug a retailer renumbers.

So `coverage_report` must carry a **per-source expected floor**:

```python
# Measured live 2026-07-26/27. These are floors, not targets: a source returning
# far fewer offers than this has almost certainly had its endpoint rescoped, not
# had its catalogue shrink. Update deliberately, with a note, never to silence an alert.
EXPECTED_MIN_OFFERS = {
    "olcha": 300,        # ~460 phones observed across 23 pages
    "texnomart": 300,    # ~500 observed across 25 pages
    "beemarket": 250,    # 436 observed via the smartfony category endpoint
    "idea": 100,         # no pagination; reach is bounded by the brand-query list
    "alifshop": 200,     # per-brand sweep
    "uzum": 200,         # per-brand GraphQL sweep
    "mediapark": 0,      # search-only, never swept
}
```

`is_suspicious` is `True` when a source's live offer count falls below its floor. The
report must make those rows visibly distinct, and the CLI must exit non-zero if any
source is suspicious — a crawl that "succeeded" while losing 90% of a catalogue is not a
success. Include a test that a source below its floor is flagged and one above it is not.

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
