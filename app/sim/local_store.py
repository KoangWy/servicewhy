"""Keyless stand-in for the Zetaris federated surface: the seeded simulator's tables in SQLite.

Same contract as `DataAccessAdapter.query` (read-only, one statement, explicit limit) and the same
two-part names (`<pg source>.<table>`, `<fs database>.<table>`) via ATTACHed in-memory databases, so
agent SQL runs unchanged apart from the dialect. For tests and keyless development only: the judged
FULL path always goes through Zetaris (SPEC D10). Ground truth is never loaded here.
"""
from __future__ import annotations

import re
import sqlite3
from typing import Any

from app.sim.load import FS_TABLES, PG_TABLES
from app.sim.simulator import Simulator

_READ_ONLY = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)


class LocalStoreError(RuntimeError):
    pass


class LocalDataAccessAdapter:
    dialect = "sqlite"
    channel = "local-sqlite (keyless dev/test stand-in for Zetaris)"

    def __init__(self, *, seed: int, days: int = 35, pg_source: str = "svc_pg", fs_database: str = "svc_fs"):
        tables, _ground_truth_not_loaded, self.manifest = Simulator(seed=seed, days=days).run()
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        for schema, names in ((pg_source, PG_TABLES), (fs_database, FS_TABLES)):
            self.db.execute(f"ATTACH DATABASE ':memory:' AS {schema}")
            for name in names:
                rows = tables[name]
                cols = list(rows[0].keys())
                self.db.execute(f"CREATE TABLE {schema}.{name} ({', '.join(cols)})")
                self.db.executemany(f"INSERT INTO {schema}.{name} VALUES ({', '.join('?' * len(cols))})",
                                    [tuple(r[c] for c in cols) for r in rows])
        self.db.execute(f"CREATE INDEX {pg_source}.ev_party ON table_events (party_id)")
        self.db.execute(f"CREATE INDEX {fs_database}.sh_date ON shifts (business_date, role)")
        self.queries = 0

    def query(self, sql: str, *, limit: int) -> list[dict[str, Any]]:
        sql = sql.strip().rstrip(";").strip()
        if ";" in sql:
            raise LocalStoreError("one SQL statement per call")
        if not _READ_ONLY.match(sql):
            raise LocalStoreError("query() accepts SELECT/WITH only")
        self.queries += 1
        cur = self.db.execute(sql)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchmany(limit)]
