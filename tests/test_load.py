import json

import pyarrow.parquet as pq

from app.sim.load import FS_TABLES, PG_TABLES, generate, insert_statements, write_files
from app.sim.simulator import content_manifest


def test_same_seed_same_manifest_small_dataset():
    a = generate(seed=11, days=7)[2]
    b = generate(seed=11, days=7)[2]
    assert a == b
    assert generate(seed=12, days=7)[2]["tables"] != a["tables"]


def test_manifest_is_a_content_hash_independent_of_row_order():
    rows = [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]
    assert content_manifest({"t": rows}) == content_manifest({"t": list(reversed(rows))})
    assert content_manifest({"t": rows}) != content_manifest({"t": rows[:1]})


def test_files_written_for_filestore_and_scorecard(tmp_path):
    tables, gt, manifest = generate(seed=3, days=7)
    paths = write_files(tmp_path, tables, gt, manifest)
    assert set(paths) == set(FS_TABLES)
    for name, path in paths.items():
        t = pq.read_table(path)
        assert t.num_rows == len(tables[name])
        assert t.column_names == list(tables[name][0].keys())
    assert json.loads((tmp_path / "run_manifest.json").read_text())["tables"] == manifest["tables"]
    assert (tmp_path / "ground_truth.json").exists()
    # the federated stores never receive ground truth: it is a file next to the data, nothing more
    assert not any("ground_truth" in str(p) for p in paths.values())


def test_postgres_inserts_cover_every_row_and_column():
    tables, _, _ = generate(seed=3, days=7)
    for name in PG_TABLES:
        sql, params = insert_statements(name, tables[name])
        assert sql.startswith(f"INSERT INTO {name} (") and len(params) == len(tables[name])
        assert sql.count("%s") == len(tables[name][0])
