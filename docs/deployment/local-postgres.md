# Local PostgreSQL for development

The development machine has no Docker and no system PostgreSQL, and no administrator
rights. So the `db`-marked tests run against a **portable PostgreSQL cluster** living
entirely inside `.local/`, which is git-ignored.

This is a development convenience only. Production uses the `docker-compose.yml` in
`narxnoma-crawler/`, or whatever PostgreSQL 16 the server provides.

## What is installed

| | |
|---|---|
| Binaries | PostgreSQL **16.14** x86-64, from the official EnterpriseDB binary archive |
| Location | `.local/pgsql/` (binaries), `.local/pgdata/` (cluster) |
| Port | **55432** — deliberately not 5432, so it cannot collide with anything else |
| Superuser | `narxnoma`, `trust` authentication |
| Databases | `narxnoma` (production-shaped, has real crawled data) and `narxnoma_test` (disposable) |
| Log | `.local/pg.log` |

Nothing was installed system-wide. No service was registered, no registry key written, no
PATH entry added. Deleting `.local/` removes every trace.

## Two databases, two variables — never mix them up

There are **two separate databases and two separate environment variables**, and they must
never point at the same database:

| Variable | Database | Read by | Purpose |
|---|---|---|---|
| `NARXNOMA_DSN` | `narxnoma` | `narxnoma/config.py` (`load_settings()`) | The **production/runtime** setting. This is what the deployed crawler and web app use on the server, and what a real harvest writes to locally. |
| `NARXNOMA_TEST_DSN` | `narxnoma_test` | `tests/conftest.py` (`dsn` fixture) | The **test** setting. Disposable, truncated on every run. |

**Why this matters:** every `db`-marked test depends on the `db_conn` fixture in
`tests/conftest.py`, and that fixture runs `TRUNCATE raw_offer, offer, harvest_run
RESTART IDENTITY CASCADE` **unconditionally, before every single `db` test**. If the test
suite ever read the same variable the production app reads, running `pytest` on a machine
where that variable is exported — for example the deployed server — would silently wipe
whatever the live crawler had collected. This actually happened once in development: an
earlier version of `db_conn` read `NARXNOMA_DSN`, and running the suite locally wiped 448
real olcha offers that had been harvested minutes before.

Two independent guards now prevent that:

1. **Different variable names.** `tests/conftest.py` reads only `NARXNOMA_TEST_DSN`. It
   never falls back to `NARXNOMA_DSN` — if `NARXNOMA_TEST_DSN` is unset, `db`-marked tests
   skip, exactly as they did before when `NARXNOMA_DSN` was unset.
2. **A database-name check.** Before truncating anything, `db_conn` calls
   `require_disposable_test_database(dsn)`, which parses the database name out of the DSN
   and raises `RuntimeError` unless it contains `test`. This catches the case where
   `NARXNOMA_TEST_DSN` itself gets pointed at the wrong database — belt and braces.

Create `narxnoma_test` once, alongside `narxnoma`:

```bash
.local/pgsql/bin/createdb.exe -h 127.0.0.1 -p 55432 -U narxnoma narxnoma_test
```

## Daily use

```bash
# start
.local/pgsql/bin/pg_ctl.exe -D .local/pgdata -l .local/pg.log -o "-p 55432" start

# check
.local/pgsql/bin/pg_isready.exe -h 127.0.0.1 -p 55432

# stop
.local/pgsql/bin/pg_ctl.exe -D .local/pgdata -m fast stop
```

`pg_ctl ... -w start` blocks under Git Bash — omit `-w` and check with `pg_isready`
instead.

Then export the **test** DSN and run the suite:

```bash
export NARXNOMA_TEST_DSN="postgresql://narxnoma@127.0.0.1:55432/narxnoma_test"
cd narxnoma-crawler && python -m pytest tests/ -q
```

Do **not** export `NARXNOMA_DSN` for this — that is the production variable, and pointing
it at `narxnoma_test` (or vice versa) defeats the whole point of having two of them. If you
also want to exercise the crawler for real against the `narxnoma` database (e.g. `python -m
narxnoma.cli harvest`), export `NARXNOMA_DSN` separately for that command only.

Without `NARXNOMA_TEST_DSN` the `db`-marked tests skip rather than fail, so the suite still
passes on a machine with no database — it just verifies less. **A green run with the
variable unset is not evidence the storage layer works.**

## Recreating it from scratch

```bash
mkdir -p .local && cd .local
curl -sSL -o pg.zip "https://sbp.enterprisedb.com/getfile.jsp?fileid=1260308"
python -c "import zipfile; zipfile.ZipFile('pg.zip').extractall('.')"
rm pg.zip
./pgsql/bin/initdb.exe -D ./pgdata -U narxnoma --auth=trust --encoding=UTF8 --locale=C
./pgsql/bin/pg_ctl.exe -D ./pgdata -l ./pg.log -o "-p 55432" start
./pgsql/bin/createdb.exe -h 127.0.0.1 -p 55432 -U narxnoma narxnoma
./pgsql/bin/createdb.exe -h 127.0.0.1 -p 55432 -U narxnoma narxnoma_test
```

The file id in that URL pins PostgreSQL 16.14 and will change when EDB publishes a new
16.x. The current list is at <https://www.enterprisedb.com/download-postgresql-binaries>.

## Why this matters

Tasks 2 and 3 built the entire storage layer — schema, migration and repository — on a
machine that could not execute a single line of their SQL. They were reviewed by reading
alone, and the reviews were unusually productive precisely because reading was all anyone
had: they caught an aborted-transaction bug that would have made a dead crawler source
indistinguishable from a running one, and a `CREATE EXTENSION` that would have failed on
first run against managed PostgreSQL.

Running them for real afterwards confirmed all eight tests pass, including the
`RETURNING (xmax = 0)` insert-versus-update idiom, which depends on an undocumented
PostgreSQL implementation detail and was the thing least safe to take on trust.

Keep the cluster running while working on Tasks 4–12. A skipped test proves nothing.
