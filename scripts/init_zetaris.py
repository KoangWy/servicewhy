"""Idempotent Zetaris init job: register both ServiceWhy stores on the federated surface.

  python scripts/init_zetaris.py            # register what is missing; re-running is a no-op
  python scripts/init_zetaris.py --dry-run  # print the statements without connecting
  python scripts/init_zetaris.py --refresh  # also UNCACHE filestore tables after a re-seed

Never runs during a request. Statement syntax follows the Zetaris Lightning SQL command guide
(zetaris/getting-started, docs/guides/zetaris-lightning-sql-commands.md, retrieved 2026-10-24):
CREATE DATASOURCE / REGISTER DATASOURCE TABLE for PostgreSQL, CREATE LIGHTNING DATABASE /
CREATE LIGHTNING FILESTORE TABLE for Parquet on MinIO (s3Endpoint + useS3PathStyleAccess, as in the
Zetaris kbase MinIO how-to). UNVERIFIED until Huy's FULL smoke: the MinIO filestore options.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.adapters.zetaris import DataAccessAdapter  # noqa: E402
from app.config import Settings, load_dotenv  # noqa: E402
from app.sim.load import FS_TABLES, PG_TABLES  # noqa: E402

Exec = Callable[[str], list[dict]]


def _q(v: str) -> str:
    return '"' + v.replace('"', '\\"') + '"'


def _listed(rows: list[dict], name: str) -> bool:
    """SHOW output column names vary by version; match the name against any cell."""
    want = name.lower()
    return any(str(v).lower() == want for r in rows for v in r.values())


def plan(env: dict, settings: Settings) -> dict[str, list[str] | str]:
    pg, fs, bucket = settings.pg_source, settings.fs_database, env.get("MINIO_BUCKET", "servicewhy")
    jdbc = (f"jdbc:postgresql://{env.get('ZETARIS_PG_HOST', env.get('POSTGRES_HOST', 'postgres'))}:"
            f"{env.get('POSTGRES_PORT', '5432')}/{env.get('POSTGRES_DB', 'servicewhy')}")
    return {
        "datasource": (f"CREATE DATASOURCE {pg} DESCRIBE BY \"ServiceWhy POS and table events\" OPTIONS ("
                       f"jdbcdriver \"org.postgresql.Driver\", jdbcurl {_q(jdbc)}, "
                       f"username {_q(env.get('POSTGRES_USER', 'svcwhy'))}, "
                       f"password {_q(env.get('POSTGRES_PASSWORD', ''))}, fetchsize \"1000\")"),
        "pg_tables": [f"REGISTER DATASOURCE TABLE \"{t}\" FROM {pg}" for t in PG_TABLES],
        "database": f"CREATE LIGHTNING DATABASE {fs} DESCRIBE BY \"ServiceWhy rosters, plate returns, reviews\"",
        "fs_tables": [
            (f"CREATE LIGHTNING FILESTORE TABLE {t} FROM {fs} FORMAT PARQUET OPTIONS ("
             f"PATH \"s3a://{bucket}/filestore/{t}/{t}.parquet\", inferSchema \"true\", "
             f"awsAccessKeyId {_q(env.get('MINIO_ROOT_USER', 'svcwhy'))}, "
             f"awsSecretAccessKey {_q(env.get('MINIO_ROOT_PASSWORD', ''))}, "
             f"s3Endpoint {_q(env.get('ZETARIS_S3_ENDPOINT', 'http://minio:9000'))}, "
             f"useS3PathStyleAccess \"true\")")
            for t in FS_TABLES],
    }


def run(execute: Exec, env: dict, settings: Settings, *, refresh: bool = False,
        log: Callable[[str], None] = print) -> list[str]:
    """Apply only the missing registrations. Returns the statements actually executed (masked)."""
    p, done = plan(env, settings), []

    def do(sql: str) -> None:
        execute(sql)
        done.append(_mask(sql, env))
        log("zetaris: " + done[-1])

    pg, fs = settings.pg_source, settings.fs_database
    if not _listed(execute("SHOW DATASOURCES"), pg):
        do(p["datasource"])
    registered = execute(f"SHOW DATASOURCE TABLES {pg}")
    for t, sql in zip(PG_TABLES, p["pg_tables"]):
        if not _listed(registered, t):
            do(sql)
    if not _listed(execute("SHOW LIGHTNING DATABASES"), fs):
        do(p["database"])
    fs_tables = execute(f"SHOW LIGHTNING TABLES {fs}")
    for t, sql in zip(FS_TABLES, p["fs_tables"]):
        if not _listed(fs_tables, t):
            do(sql)
        elif refresh:
            do(f"UNCACHE LIGHTNING FILESTORE TABLE {t} FROM {fs}")
    if not done:
        log("zetaris: all sources already registered (no-op)")
    return done


def _mask(sql: str, env: dict) -> str:
    for k in ("POSTGRES_PASSWORD", "MINIO_ROOT_PASSWORD"):
        if env.get(k):
            sql = sql.replace(env[k], "…redacted")
    return sql


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    ap = argparse.ArgumentParser(description="Idempotent Zetaris registration for ServiceWhy")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args(argv)
    settings, env = Settings.from_env(), dict(os.environ)
    if args.dry_run:
        p = plan(env, settings)
        for sql in [p["datasource"], *p["pg_tables"], p["database"], *p["fs_tables"]]:
            print(_mask(sql, env))
        return 0
    run(DataAccessAdapter.from_env().execute, env, settings, refresh=args.refresh)
    return 0


if __name__ == "__main__":
    sys.exit(main())
