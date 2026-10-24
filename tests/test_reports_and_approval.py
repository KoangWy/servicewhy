"""Report, approval and drill-down endpoints."""
import json

from conftest import DEMO


def test_report_has_summary_findings_and_provenance(client):
    r = client.post("/reports", json={})
    assert r.status_code == 200
    rid = r.json()["report_id"]
    rep = client.get(f"/reports/{rid}").json()
    assert rep["summary"] and 1 <= len(rep["findings"]) <= 5
    assert rep["provenance"]["thresholds"]["V1_tolerance"] == 0.02
    assert {r["run_id"] for r in rep["provenance"]["runs"]} == {f"{rid}-1", f"{rid}-2"}
    assert "synthetic" in rep["provenance"]["data"].lower()
    assert all(client.get(f"/findings/{f['id']}").status_code == 200 for f in rep["findings"])


def test_explicit_period(client):
    rid = client.post("/reports", json={"period": {"start": "2026-09-21", "end": "2026-09-27"}}).json()["report_id"]
    rep = client.get(f"/reports/{rid}").json()
    assert rep["period"] == {"start": "2026-09-21", "end": "2026-09-27"}


def test_approve_and_reject_flip_status_and_log_role_and_time(client, demo, settings):
    fid = demo["output"]["findings"][0]["id"]
    assert client.get(f"/findings/{fid}").json()["status"] == "proposed"
    a = client.post(f"/findings/{fid}/approve", json={"role": "manager"}).json()
    assert a["status"] == "approved"
    other = demo["output"]["findings"][-1]["id"]
    assert client.post(f"/findings/{other}/reject").json()["status"] == "rejected"
    log = [json.loads(line) for line in (settings.logs_dir / "approvals.jsonl").read_text().splitlines()]
    assert log[0]["finding_id"] == fid and log[0]["role"] == "manager" and log[0]["decision"] == "approved"
    assert log[0]["timestamp"].endswith("Z")
    assert client.post("/findings/fnd_000000000000/approve").status_code == 404


def test_drilldown_runs_a_nested_investigation_with_the_same_core(client, demo):
    f = demo["output"]["findings"][0]
    r = client.post(f"/findings/{f['id']}/drilldown", json={}).json()
    assert r["parent_finding"] == f["id"]
    run = r["run"]
    assert run["status"] == "success" and run["output"]["parent_finding"] == f["id"]
    assert run["output"]["plan"]["hypotheses"] == [f["library_id"]]
    assert client.get(f"/traces/{run['run_id']}").json()["events"]


def test_trace_endpoint_serves_json_and_jsonl(client, demo):
    j = client.get("/traces/demo-001").json()
    assert j["run_id"] == "demo-001" and j["events"][0]["event"] == "run_start"
    raw = client.get("/traces/demo-001?format=jsonl").text
    assert len(raw.splitlines()) == len(j["events"])
    assert client.get("/traces/nope").status_code == 404
