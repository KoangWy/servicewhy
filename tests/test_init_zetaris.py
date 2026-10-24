from app.config import Settings
from init_zetaris import plan, run

ENV = {"POSTGRES_PASSWORD": "pgsecret", "MINIO_ROOT_PASSWORD": "miniosecret", "MINIO_BUCKET": "servicewhy"}


class FakeZetaris:
    """Holds registration state like the bundle does; SHOW reflects earlier CREATE/REGISTER calls."""

    def __init__(self):
        self.sources, self.pg_tables, self.dbs, self.fs_tables, self.calls = set(), set(), set(), set(), []

    def __call__(self, sql):
        self.calls.append(sql)
        w = sql.split()
        if sql == "SHOW DATASOURCES":
            return [{"name": s} for s in self.sources]
        if sql.startswith("SHOW DATASOURCE TABLES"):
            return [{"tableName": t} for t in self.pg_tables]
        if sql == "SHOW LIGHTNING DATABASES":
            return [{"name": d} for d in self.dbs]
        if sql.startswith("SHOW LIGHTNING TABLES"):
            return [{"name": t} for t in self.fs_tables]
        if sql.startswith("CREATE DATASOURCE"):
            self.sources.add(w[2])
        elif sql.startswith("REGISTER DATASOURCE TABLE"):
            self.pg_tables.add(w[3].strip('"'))
        elif sql.startswith("CREATE LIGHTNING DATABASE"):
            self.dbs.add(w[3])
        elif sql.startswith("CREATE LIGHTNING FILESTORE TABLE"):
            self.fs_tables.add(w[4])
        return []


def test_first_run_registers_both_stores_second_run_is_noop():
    z, s = FakeZetaris(), Settings.from_env()
    first = run(z, ENV, s, log=lambda _: None)
    assert len(first) == 1 + 3 + 1 + 3
    assert z.sources == {"svc_pg"} and z.dbs == {"svc_fs"}
    assert z.pg_tables == {"pos_tickets", "ticket_items", "table_events"}
    assert z.fs_tables == {"shifts", "plate_returns", "reviews"}
    assert run(z, ENV, s, log=lambda _: None) == []


def test_statements_follow_documented_syntax_and_mask_secrets():
    p = plan(ENV, Settings.from_env())
    assert p["datasource"].startswith("CREATE DATASOURCE svc_pg DESCRIBE BY")
    assert 'jdbcdriver "org.postgresql.Driver"' in p["datasource"]
    assert all(q.startswith('REGISTER DATASOURCE TABLE "') and q.endswith("FROM svc_pg") for q in p["pg_tables"])
    fs = p["fs_tables"][0]
    assert "FORMAT PARQUET" in fs and 's3a://servicewhy/filestore/shifts/shifts.parquet' in fs
    assert 'useS3PathStyleAccess "true"' in fs and "s3Endpoint" in fs
    executed = run(FakeZetaris(), ENV, Settings.from_env(), log=lambda _: None)
    assert not any("pgsecret" in q or "miniosecret" in q for q in executed)
    assert all(";" not in q for q in executed)


def test_refresh_uncaches_existing_filestore_tables_only():
    z, s = FakeZetaris(), Settings.from_env()
    run(z, ENV, s, log=lambda _: None)
    again = run(z, ENV, s, refresh=True, log=lambda _: None)
    assert again == [f"UNCACHE LIGHTNING FILESTORE TABLE {t} FROM svc_fs" for t in ("shifts", "plate_returns", "reviews")]
