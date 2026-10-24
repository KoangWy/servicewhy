"""Behaviour through the REST API (the single high seam): run, trace, world model, findings."""
import json
import re

from app.logging.trace import EVENTS, SCHEMA_VERSION, read_trace
from conftest import DEMO


def test_health_reports_modes(client):
    h = client.get("/health").json()
    assert h == {"status": "ok", "zetaris": "local", "model": "fake", "sample_mode": False, "sample_questions": None}


def test_run_returns_the_technical_execution_guide_shape(demo):
    assert demo["run_id"] == "demo-001" and demo["status"] == "success"
    assert demo["trace_id"] == "trace-demo-001" and demo["log_file"].endswith("trace-demo-001.jsonl")
    assert {a["name"] for a in demo["agents"]} == {"Planner", "Investigator", "Verifier", "Writer"}
    assert isinstance(demo["execution_time_seconds"], float)
    out = demo["output"]
    assert out["summary"] and out["answer_type"] == "answer"
    assert out["recommendations"] == [f["recommended_action"] for f in out["findings"]]


def test_trace_is_versioned_enumerated_and_shows_every_role(demo, settings):
    events = read_trace(settings.logs_dir / "trace-demo-001.jsonl")
    assert all(e["schema_version"] == SCHEMA_VERSION and e["event"] in EVENTS for e in events)
    kinds = {e["event"] for e in events}
    assert {"run_start", "plan", "query", "evidence", "verify", "answer", "run_end", "wm_mutation"} <= kinds
    agents = {e["agent_name"] for e in events}
    assert {"Planner", "Investigator", "Verifier", "Writer"} <= agents
    queries = [e for e in events if e["event"] == "query"]
    assert all(e["rows_used"] >= 0 and e["query"].upper().startswith(("WITH", "SELECT")) for e in queries)


def test_planner_proposes_at_most_three_hypotheses_with_provenance(demo, settings):
    plan = demo["output"]["plan"]
    assert 1 <= len(plan["hypotheses"]) <= 3 and {"H_DEMAND", "H_SPEND"} <= set(plan["hypotheses"])
    wm = [json.loads(line) for line in (settings.logs_dir / "worldmodel-demo-001.jsonl").read_text().splitlines()]
    hyps = [r for r in wm if r["kind"] == "hypothesis" and r["data"].get("library_id")]
    assert len(hyps) == len(plan["hypotheses"]) and all(r["agent_id"] == "planner" for r in hyps)
    events = read_trace(settings.logs_dir / "trace-demo-001.jsonl")
    plan_ids = {e["data"]["hypothesis_id"] for e in events if e["action"] == "propose_hypothesis"}
    assert plan_ids == {r["id"] for r in hyps}


def test_evidence_items_carry_provenance_and_contrast(demo, settings):
    wm = [json.loads(line) for line in (settings.logs_dir / "worldmodel-demo-001.jsonl").read_text().splitlines()]
    evidence = [r for r in wm if r["kind"] == "evidence"]
    assert evidence
    for r in evidence:
        d = r["data"]
        assert {"source", "query", "metric", "value", "contrast", "n", "baseline", "rows_used"} <= set(d)
        assert r["agent_id"] == "investigator" and d["query"].startswith("WITH")


def test_findings_follow_the_spec_contract_and_cite_real_evidence(demo, settings):
    wm_ids = {json.loads(line)["id"] for line in (settings.logs_dir / "worldmodel-demo-001.jsonl").read_text().splitlines()}
    findings = demo["output"]["findings"]
    assert findings
    for f in findings:
        assert {"id", "cause_hypothesis", "evidence", "confidence", "effect_size", "uncertainty",
                "recommended_action", "status"} <= set(f)
        assert f["confidence"] in ("high", "medium", "low") and f["status"] == "proposed"
        assert f["evidence"] and all(e["evidence_id"] in wm_ids for e in f["evidence"])
        assert f["effect_size"]["evidence_id"] in {e["evidence_id"] for e in f["evidence"]}
    for eid in re.findall(r"evd_[0-9a-f]{12}", demo["output"]["summary"]):
        assert eid in wm_ids


def test_revenue_question_carries_the_decoy_split(demo):
    split = demo["output"]["revenue_split"]
    assert split and 0 <= split["volume_share"] <= 1
    assert abs(split["volume_effect"] + split["spend_effect"] - split["change"]) < 0.05
    assert "fewer parties explain" in demo["output"]["summary"]


def test_verifier_block_and_retry_are_visible_in_the_demo_trace(demo, settings):
    events = read_trace(settings.logs_dir / "trace-demo-001.jsonl")
    blocks = [e for e in events if e["event"] == "block"]
    retries = [e for e in events if e["event"] == "retry"]
    assert blocks and retries
    assert any("V2" in e["output_summary"] for e in blocks)
    assert all(e["retry_count"] >= 1 for e in retries)


def test_no_data_question_abstains(client):
    r = client.post("/run", json={"input": {"query": "Did the new menu cause the drop?", "context": DEMO}}).json()
    assert r["output"]["answer_type"] == "insufficient_evidence" and r["output"]["findings"] == []
    assert "menu" in r["output"]["summary"]


def test_ranking_request_is_reframed_without_naming_staff(client):
    r = client.post("/run", json={"input": {"query": "Who is our worst server?"}}).json()
    assert r["output"]["answer_type"] == "reframed"
    assert "does not rank individual staff" in r["output"]["summary"]
    blob = json.dumps(r["output"])
    assert not re.search(r"\bS[1-4]\b|\bB[12]\b", blob.replace("section B", ""))


def test_non_cause_probe_answers_no(client):
    r = client.post("/run", json={"input": {"query": "Is the kitchen slow on Saturdays?"}}).json()
    assert r["output"]["summary"].startswith("No.")
    assert r["output"]["not_causes"] and not r["output"]["findings"]


def test_bad_input_is_a_structured_validation_error(client):
    assert client.post("/run", json={"input": {"query": ""}}).status_code == 422


def test_cassette_miss_returns_structured_error(settings):
    from dataclasses import replace
    from fastapi.testclient import TestClient
    from app.main import create_app
    c = TestClient(create_app(replace(settings, model_mode="replay")))
    r = c.post("/run", json={"input": {"query": DEMO}})
    assert r.status_code == 502
    err = r.json()
    assert err["status"] == "error" and err["error"]["type"] == "CassetteMiss" and err["error"]["recoverable"]
