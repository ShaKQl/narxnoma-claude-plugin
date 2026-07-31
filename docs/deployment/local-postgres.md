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
| Database | `narxnoma` |
| Log | `.local/pg.log` |

Nothing was installed system-wide. No service was registered, no registry key written, no
PATH entry added. Deleting `.local/` removes every trace.

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

Then export the DSN and run the suite:

```bash
export NARXNOMA_DSN="postgresql://narxnoma@127.0.0.1:55432/narxnoma"
cd narxnoma-crawler && python -m pytest tests/ -q
```

Without `NARXNOMA_DSN` the `db`-marked tests skip rather than fail, so the suite still
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
