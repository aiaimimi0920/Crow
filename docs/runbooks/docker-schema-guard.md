# Docker DB schema guard

> Data-root compatibility: `CrowData` is the new-install default. Existing populated
> `FPFData` stays in place and explicit paths keep priority; do not move or copy data.
> See [the compatibility guide](crow-data-root-compatibility.md).

The Docker entrypoint runs a read-only database schema guard before starting seed,
detail, API, or legacy collection workers.

## What it checks

When `FAPAI_DB_URL` is set and `FAPAI_DB_SCHEMA_GUARD` is not disabled, the
entrypoint compares:

- the live database tables and columns, inspected through SQLAlchemy; and
- the current SQLAlchemy model metadata from `src/storage/models.py`.

If the database already contains any current application table but is missing a
required table or column, the entrypoint exits with status `1` before launching a
worker subprocess.

Example failure:

```text
[docker-entrypoint] startup check failed: database schema is not compatible with current application models.
Run database migrations before starting workers, for example: python -m alembic upgrade head
```

This is a fail-fast protection for long-running collectors. In particular, it
prevents the detail worker from spending browser and LLM work before failing on a
late database write because the live DB is still on an older schema.

## Empty databases

Completely empty databases are allowed through the guard. This preserves the
existing `FAPAI_DB_AUTO_CREATE=1` first-run path.

Once any current application table exists, the database must match the current
model table/column set before workers start.

## Migration command

Revision `20260922_0013` converts only system/instant columns from legacy
UTC-naive values to PostgreSQL `timestamp with time zone`. It leaves the three
civil/business dates (`auction_date`, `auction_start_time`, and
`appraisal_benchmark_date`) unchanged. The conversion interprets every stored
naive value as UTC; it does not guess or repair historical local-time values.
Before applying it, verify that the deployed schema and UTC-naive data match this
contract and keep a verified PostgreSQL backup.

This revision requires a maintenance window: stop API and worker writers before
the schema upgrade, then start only the matching code that binds UTC-aware
PostgreSQL values. The old application can interpret writes to the new columns
using the PostgreSQL session timezone. If rollback is needed, stop writers,
restore the old code, then downgrade to `20260921_0012` so stored instants are
converted back to UTC-naive values.

For local host-side migrations, use the host-visible PostgreSQL port:

```powershell
$env:FAPAI_DB_URL = "postgresql+psycopg://fapaifang:fapaifang@127.0.0.1:55432/fapaifang"
.\venv\Scripts\python.exe -m pip install -r requirements.txt -r tools\requirements-postgres.txt
.\venv\Scripts\python.exe -m alembic upgrade head
```

Inside Docker, `docker.local.env` can keep using `host.docker.internal`:

```env
FAPAI_DB_URL=postgresql+psycopg://fapaifang:fapaifang@host.docker.internal:55432/fapaifang
```

## Temporary bypass

Only use this for short troubleshooting windows:

```env
FAPAI_DB_SCHEMA_GUARD=0
```

Disabling the guard does not fix the database. It only allows workers to start
and leaves them exposed to later DB write failures.

## Read-only preflight

From the host:

```powershell
@'
import os
from tools.docker_entrypoint import guard_database_schema

os.environ["FAPAI_DB_URL"] = "postgresql+psycopg://fapaifang:fapaifang@127.0.0.1:55432/fapaifang"
guard_database_schema(os.environ)
print("schema_guard=passed")
'@ | .\venv\Scripts\python.exe -
```

From the collector image, without starting a long-running worker:

```powershell
docker compose --env-file docker.local.env -f docker-compose.collection.yml run --rm --no-deps `
  -e FAPAI_RUN_MODE=sleep `
  fapaifang-seed-collector `
  python -c "from tools.docker_entrypoint import guard_database_schema; import os; guard_database_schema(os.environ); print('container_schema_guard=passed')"
```

## PostgreSQL backup and restore-list probe

Use the host data root for operator-owned PostgreSQL dumps:

```text
.\CrowData
```

Create a verified custom-format dump and keep recent copies:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\backup-postgres-to-host.ps1
```

The backup script copies the dump out of the PostgreSQL container and runs a
`pg_restore -l` style restore-list probe before treating the host copy as valid.

Install the periodic backup task when the host should maintain independent
database restore points:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\register-postgres-backup-task.ps1
```

The scheduled task name is `FapaiFangPostgresBackup`.

Use the health check to catch missing, stale, too-small, or invalid backups:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\check-postgres-backup-health.ps1
```

For periodic health verification, register `FapaiFangPostgresBackupHealth`:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\register-postgres-backup-health-task.ps1
```
