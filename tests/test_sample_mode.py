"""SAMPLE_MODE: same endpoints, recorded runs, zero network and zero services."""
import socket
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from conftest import DEMO
from seed_sample import record


@pytest.fixture(scope="module")
def bundle_dir(tmp_path_factory):
    from app.config import Settings
    tmp = tmp_path_factory.mktemp("rec")
    s = replace(Settings.from_env(), sample_mode=False, data_backend="local", model_mode="fake", seed=20261024,
                sim_days=35, logs_dir=tmp / "logs", sample_dir=tmp / "examples", cassette_dir=tmp / "c")
    record(s, tmp / "examples")
    return tmp / "examples"


@pytest.fixture
def sample(bundle_dir, tmp_path, monkeypatch):
    real_connect = socket.socket.connect

    def no_network(sock, addr):  # loopback stays open: the event loop's self-pipe uses it on Windows
        if isinstance(addr, tuple) and addr[0] not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError(f"SAMPLE_MODE must not open network connections ({addr})")
        return real_connect(sock, addr)
    monkeypatch.setattr(socket.socket, "connect", no_network)
    from app.config import Settings
    s = replace(Settings.from_env(), sample_mode=True, data_backend="zetaris", model_mode="live",
                logs_dir=tmp_path / "logs", sample_dir=bundle_dir)
    return TestClient(create_app(s))


def test_health_says_sample(sample):
    h = sample.get("/health").json()
    assert h["zetaris"] == "sample" and h["sample_mode"] is True and DEMO in h["sample_questions"]


def test_recorded_run_replays_through_the_same_endpoint(sample):
    r = sample.post("/run", json={"input": {"query": DEMO.lower()}}).json()
    assert r["status"] == "success" and r["output"]["mode"]["sample_mode"] is True
    assert r["output"]["mode"]["recorded_with"]["data"].startswith("local-sqlite")
    events = sample.get(f"/traces/{r['run_id']}").json()["events"]
    assert any(e["event"] == "block" for e in events) and any(e["event"] == "retry" for e in events)


def test_unrecorded_question_is_a_structured_miss(sample):
    r = sample.post("/run", json={"input": {"query": "Why is the sky blue?"}})
    assert r.status_code == 404 and r.json()["error"]["type"] == "SampleModeMiss"
    assert DEMO in r.json()["error"]["available_questions"]


def test_report_findings_approval_and_drilldown_work_offline(sample):
    rid = sample.post("/reports", json={}).json()["report_id"]
    rep = sample.get(f"/reports/{rid}").json()
    assert rep["findings"]
    demo = sample.post("/run", json={"input": {"query": DEMO}}).json()
    fid = demo["output"]["findings"][0]["id"]
    assert sample.post(f"/findings/{fid}/approve").json()["status"] == "approved"
    dd = sample.post(f"/findings/{fid}/drilldown", json={}).json()
    assert dd["parent_finding"] == fid and dd["run"]["status"] == "success"
