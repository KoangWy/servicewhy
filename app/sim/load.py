"""Loader: run the seeded simulator, write Postgres rows + Parquet files, upload Parquet to MinIO.

  python -m app.sim.load                 # full seed: files, Postgres, MinIO, then Zetaris registration
  python -m app.sim.load --files-only    # write data/generated only (no services needed)

Store split (SPEC D9): PostgreSQL {pos_tickets, ticket_items, table_events};
Parquet-on-MinIO {shifts, plate_returns, reviews}. Ground truth is written next to the data for the
scorecard harness only; it is never loaded into a federated store.
Timestamps are stored as TIMESTAMP (venue-local wall clock, no zone): the data is single-venue and a
zone-aware column would shift hour-of-day windows through the federation layer.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from app.config import Settings, load_dotenv
from app.sim.simulator import Simulator

PG_TABLES = ("pos_tickets", "ticket_items", "table_events")
FS_TABLES = ("shifts", "plate_returns", "reviews")

PG_DDL = {
    "pos_tickets": """CREATE TABLE pos_tickets (
  ticket_id TEXT PRIMARY KEY, business_date DATE NOT NULL,
  service TEXT NOT NULL CHECK (service IN ('lunch','dinner')), table_id TEXT NOT NULL,
  party_id TEXT NOT NULL, server_id TEXT NOT NULL, covers INT NOT NULL,
  opened_at TIMESTAMP NOT NULL, closed_at TIMESTAMP NOT NULL,
  total NUMERIC(10,2) NOT NULL, comp_total NUMERIC(10,2) NOT NULL DEFAULT 0)""",
    "ticket_items": """CREATE TABLE ticket_items (
  line_id TEXT PRIMARY KEY, ticket_id TEXT NOT NULL REFERENCES pos_tickets,
  item_name TEXT NOT NULL, category TEXT NOT NULL, qty INT NOT NULL, unit_price NUMERIC(8,2) NOT NULL,
  fired_at TIMESTAMP NOT NULL, bumped_at TIMESTAMP NOT NULL, delivered_at TIMESTAMP NOT NULL,
  comp_reason TEXT)""",
    "table_events": """CREATE TABLE table_events (
  event_id TEXT PRIMARY KEY, business_date DATE NOT NULL, table_id TEXT NOT NULL, party_id TEXT,
  event_type TEXT NOT NULL CHECK (event_type IN
    ('seated','greeted','ordered','fired','bumped','delivered','paid','left','reset')),
  occurred_at TIMESTAMP NOT NULL, server_id TEXT)""",
}

# Parquet column types; everything not listed is a string
FS_TYPES = {"shifts": {"tables_assigned": "int32"},
            "plate_returns": {"leftover_share": "float64"},
            "reviews": {"rating": "int32"}}


def generate(seed: int, days: int) -> tuple[dict[str, list[dict]], dict[str, Any], dict[str, Any]]:
    return Simulator(seed=seed, days=days).run()


def write_files(out_dir: Path, tables: dict, ground_truth: dict, manifest: dict) -> dict[str, Path]:
    """Parquet for the filestore tables, JSON for ground truth and the run manifest."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name in FS_TABLES:
        rows = tables[name]
        cols = list(rows[0].keys())
        types = FS_TYPES.get(name, {})
        arrays = {c: pa.array([r[c] for r in rows], type=getattr(pa, types.get(c, "string"))()) for c in cols}
        path = out_dir / f"{name}.parquet"
        pq.write_table(pa.table(arrays), path)
        paths[name] = path
    (out_dir / "ground_truth.json").write_text(json.dumps(ground_truth, indent=2))
    (out_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2))
    return paths


def insert_statements(name: str, rows: list[dict]) -> tuple[str, list[tuple]]:
    cols = list(rows[0].keys())
    sql = f"INSERT INTO {name} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})"
    return sql, [tuple(r[c] for c in cols) for r in rows]


def write_postgres(tables: dict, dsn: str) -> None:
    """Drop + recreate: a seed always reflects exactly one simulator run."""
    import psycopg

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        for name in reversed(PG_TABLES):
            cur.execute(f"DROP TABLE IF EXISTS {name} CASCADE")
        for name in PG_TABLES:
            cur.execute(PG_DDL[name])
            sql, params = insert_statements(name, tables[name])
            cur.executemany(sql, params)
        conn.commit()


def upload_minio(paths: dict[str, Path], *, endpoint: str, access_key: str, secret_key: str, bucket: str,
                 secure: bool = False) -> list[str]:
    from minio import Minio

    client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
    keys = []
    for name, path in paths.items():
        key = f"filestore/{name}/{name}.parquet"
        client.fput_object(bucket, key, str(path))
        keys.append(f"s3a://{bucket}/{key}")
    return keys


def pg_dsn() -> str:
    e = os.environ
    return (f"host={e.get('POSTGRES_HOST', 'localhost')} port={e.get('POSTGRES_PORT', '5432')} "
            f"user={e.get('POSTGRES_USER', 'svcwhy')} password={e['POSTGRES_PASSWORD']} "
            f"dbname={e.get('POSTGRES_DB', 'servicewhy')}")


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    s = Settings.from_env()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, default=s.seed)
    ap.add_argument("--days", type=int, default=s.sim_days)
    ap.add_argument("--files-only", action="store_true", help="write data/generated only")
    ap.add_argument("--skip-zetaris", action="store_true", help="do not run the Zetaris init job")
    args = ap.parse_args(argv)

    tables, gt, manifest = generate(args.seed, args.days)
    paths = write_files(s.data_dir, tables, gt, manifest)
    print(json.dumps({"seed": args.seed, "days": args.days, "out": str(s.data_dir),
                      "tables": {k: v["rows"] for k, v in manifest["tables"].items()}}))
    if args.files_only:
        return 0
    write_postgres(tables, pg_dsn())
    print("postgres: wrote", ", ".join(PG_TABLES))
    e = os.environ
    keys = upload_minio(paths, endpoint=e.get("MINIO_ENDPOINT", "localhost:9000"),
                        access_key=e.get("MINIO_ROOT_USER", "svcwhy"), secret_key=e["MINIO_ROOT_PASSWORD"],
                        bucket=e.get("MINIO_BUCKET", "servicewhy"))
    print("minio: uploaded", ", ".join(keys))
    if not args.skip_zetaris:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
        from init_zetaris import main as init_zetaris
        return init_zetaris([])
    return 0


if __name__ == "__main__":
    sys.exit(main())
