"""Verifier rules observed through the run endpoint and the trace (V1-V5)."""
import pytest
from fastapi.testclient import TestClient

from app.logging.trace import read_trace
from app.main import create_app
from app.orchestrator import MAX_STEPS, Orchestrator
from app.runtime import data_adapter
from conftest import DEMO


class SkewedReQuery:
    """Same data, but the Verifier's independent re-query sees values 10% off: V1 must block."""

    def __init__(self, inner):
        self.inner, self.dialect, self.channel = inner, inner.dialect, inner.channel

    def query(self, sql, *, limit):
        rows = self.inner.query(sql, limit=limit)
        if " AS v FROM base" in sql:
            rows = [{**r, "v": None if r["v"] is None else r["v"] * 1.10} for r in rows]
        return rows


@pytest.fixture
def skewed(settings):
    app = create_app(settings)
    app.state.svc.orchestrator = Orchestrator(settings, lambda: SkewedReQuery(data_adapter(settings)))
    return TestClient(app)


def test_v1_mismatch_blocks_with_machine_readable_reason(skewed, settings):
    r = skewed.post("/run", json={"run_id": "skew", "input": {"query": DEMO}}).json()
    events = read_trace(settings.logs_dir / "trace-skew.jsonl")
    v1 = [e for e in events if e["event"] == "verify" and e["verdict"] == "block"]
    assert v1 and all(any(x.startswith("V1:") for x in e["data"]["reasons"]) for e in v1[:3])
    assert all("query" in e for e in v1)  # the re-query itself is in the trace


def test_v5_every_claim_blocked_ends_in_insufficient_evidence_within_bounds(skewed, settings):
    r = skewed.post("/run", json={"run_id": "skew5", "input": {"query": DEMO}}).json()
    out = r["output"]
    # party counts are recounted, not re-summed, so only the value-based claims are blocked
    assert out["findings"] == [] and len(out["insufficient"]) == 2
    assert "Blocked for insufficient evidence" in out["summary"]
    assert out["steps"] <= MAX_STEPS
    events = read_trace(settings.logs_dir / "trace-skew5.jsonl")
    assert [e for e in events if e["action"] == "V5_insufficient_evidence"]
    assert max(e["retry_count"] for e in events if e["event"] == "retry") == 2


def test_v2_small_sample_blocks_then_widening_retries(demo, settings):
    events = read_trace(settings.logs_dir / "trace-demo-001.jsonl")
    v2 = [e for e in events if e["event"] == "verify" and any("V2" in x for x in (e.get("data") or {}).get("reasons", []))]
    assert v2
    retry = next(e for e in events if e["event"] == "retry")
    assert len(retry["data"]["to"]["focus"]) > len(retry["data"]["from"]["focus"])


def test_v1_re_queries_go_through_the_data_adapter(demo, settings):
    events = read_trace(settings.logs_dir / "trace-demo-001.jsonl")
    requery = [e for e in events if e["event"] == "query" and e["agent_name"] == "Verifier"]
    assert requery and all("re-query" in e["input_summary"] for e in requery)


def test_model_judgment_can_block(settings):
    app = create_app(settings)
    def stubborn(role, system, prompt):
        from app.adapters.fake_model import respond
        return '{"verdict": "block", "reason": "contrast does not test the claim"}' if role == "verifier" \
            else respond(role, system, prompt)
    from app.adapters.model import ModelAdapter
    app.state.svc.orchestrator = Orchestrator(settings, lambda: data_adapter(settings),
                                              lambda s: ModelAdapter("fake", session_id=s, fake=stubborn))
    r = TestClient(app).post("/run", json={"run_id": "stub", "input": {"query": "Is the kitchen slow on Saturdays?"}}).json()
    assert r["output"]["answer_type"] == "insufficient_evidence"
    events = read_trace(settings.logs_dir / "trace-stub.jsonl")
    assert any("model: contrast does not test the claim" in e["output_summary"] for e in events if e["event"] == "block")


def test_hypothesis_library_is_data(tmp_path):
    import yaml
    from app.agent.planner import LIBRARY_PATH, load_library, normalise
    entries = yaml.safe_load(LIBRARY_PATH.read_text(encoding="utf-8"))
    entries.append({"id": "H_NEW", "family": "staffing", "statement": "A new cause", "keywords": ["x"],
                    "cause": ["A new cause {focus}"], "action": "Act", "plans": [{"metric": "greet_min", "contrast": "compare"}]})
    path = tmp_path / "lib.yaml"
    path.write_text(yaml.safe_dump(entries), encoding="utf-8")
    plan = normalise({"intent": "explain", "hypotheses": ["H_NEW", "H_UNKNOWN"], "slots": {}}, load_library(path))
    assert plan["hypotheses"] == ["H_NEW"]


class _FlatInvestigator:
    """Re-query reproduces the reported value exactly, and neither side has a baseline group."""

    def sql_for(self, spec, *, raw, independent):
        return "SELECT 1"

    def _query(self, sql, *, purpose, agent, retry):
        return []

    def compute(self, spec, rows, *, raw):
        return {"value": 12.0, "baseline": None}


class _RecordingTrace:
    def __init__(self):
        self.events = []

    def emit(self, event, agent, action, **fields):
        self.events.append((event, action, fields))


def test_v3_causal_claim_without_a_baseline_group_is_blocked():
    from app.agent.verifier import Verifier
    trace = _RecordingTrace()
    evidence = {"id": "evd_flat", "spec": {}, "value": 12.0, "baseline": None, "n": 40, "n_baseline": 0,
                "descriptive": False, "supports": True}
    verdict = Verifier(_FlatInvestigator(), None, None, trace).verify(
        {"wm_id": "hyp_flat", "statement": "A cause with nothing to compare against"}, [evidence], retry=0)
    assert verdict["blocked"] and verdict["reasons"] == ["V3: no contrast (baseline group missing) for a causal claim"]
    blocks = [fields for event, _, fields in trace.events if event == "block"]
    assert blocks and "V3" in blocks[0]["output_summary"]
