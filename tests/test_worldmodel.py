import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from app.worldmodel.context_builder import ContextBuilderService
from app.worldmodel.ingest import IngestError, IngestPipelineService
from app.worldmodel.store import WorldStoreService, stable_id
from meterless_gate import fake_generator, run


def _ingest(tmp_path, run_id="r1"):
    store = WorldStoreService(tmp_path / "wm.jsonl")
    return store, IngestPipelineService(store, run_id=run_id)


def test_stable_ids_are_content_derived():
    assert stable_id("hyp", "Foo ") == stable_id("hyp", "foo")
    assert stable_id("hyp", "a") != stable_id("hyp", "b")


def test_ingest_is_idempotent(tmp_path):
    store, ing = _ingest(tmp_path)
    a = ing.ingest_hypothesis("h", agent_id="planner")
    b = ing.ingest_hypothesis("h", agent_id="planner")
    assert a == b
    assert len((tmp_path / "wm.jsonl").read_text().splitlines()) == 1


def test_resume_after_crash_replays_log_and_ignores_torn_line(tmp_path):
    store, ing = _ingest(tmp_path)
    hid = ing.ingest_hypothesis("h", agent_id="planner")
    with (tmp_path / "wm.jsonl").open("a") as fh:
        fh.write('{"v": 1, "op": "put", "ki')  # torn write
    store2, ing2 = _ingest(tmp_path, run_id="r2")
    assert store2.get(hid)["statement"] == "h"
    assert ing2.ingest_hypothesis("h", agent_id="planner") == hid


def test_every_mutation_is_attributed(tmp_path):
    _, ing = _ingest(tmp_path)
    ing.ingest_hypothesis("h", agent_id="planner")
    rec = json.loads((tmp_path / "wm.jsonl").read_text().splitlines()[0])
    assert rec["agent_id"] == "planner" and rec["run_id"] == "r1"


def test_finding_must_cite_real_evidence(tmp_path):
    _, ing = _ingest(tmp_path)
    hid = ing.ingest_hypothesis("h", agent_id="planner")
    with pytest.raises(IngestError):
        ing.ingest_finding(hid, text="claim", evidence_ids=["evd_000000000000"], agent_id="writer")
    with pytest.raises(IngestError):
        ing.ingest_evidence("hyp_unknown", source="s", query="q", metric="m", value=1, contrast="c", n=1, agent_id="x")


def test_context_is_structured_with_trace(tmp_path):
    store, ing = _ingest(tmp_path)
    hid = ing.ingest_hypothesis("h", agent_id="planner")
    for n, m in ((10, "a"), (99, "b")):
        ing.ingest_evidence(hid, source="s", query="q", metric=m, value=1, contrast="c", n=n, agent_id="inv")
    ctx = ContextBuilderService(store).build(intent="verify", hypothesis_id=hid)
    assert isinstance(ctx, dict) and [e["n"] for e in ctx["evidence"]] == [99, 10]
    assert ctx["trace"]["strategy"] and ctx["trace"]["selection_reason"]


def test_generator_roundtrip_with_injected_fake(tmp_path):
    out = run(fake_generator, "r1", tmp_path / "wm.jsonl")
    assert out["cited"] == [out["evidence"]]
    assert WorldStoreService(tmp_path / "wm.jsonl").get(out["finding"])["evidence_ids"] == [out["evidence"]]
