"""Scorecard harness: canned questions, ground-truth join, schema refusal, import ban."""
import json
import re
from pathlib import Path

import pytest

from app.logging.trace import TraceError, read_trace
from app.scorecard import harness

ROOT = Path(__file__).resolve().parent.parent
AGENT_SIDE = ["app/agent", "app/adapters", "app/worldmodel", "app/api", "app/report", "app/orchestrator.py",
              "app/metrics.py", "app/registry.py", "app/sample.py"]


def test_all_ten_spec_questions_are_encoded_with_grading():
    qs = harness.load_questions()
    assert [q["id"] for q in qs] == [f"Q{i}" for i in range(1, 11)]
    kinds = [q["kind"] for q in qs]
    assert kinds.count("incident_direct") == 2 and "decoy_trap" in kinds and "refuse_ranking" in kinds
    assert all(q["expect"].get("answer_type") for q in qs)


def test_harness_emits_markdown_table_from_runs(settings):
    res = harness.run(settings)
    md = res["markdown"]
    assert "| Root-cause hit rate" in md and "| Q10 |" in md
    assert (settings.logs_dir / "scorecard.md").exists()
    s = res["summary"]
    assert s["abstention_correct"] == (2, 2) and s["questions_passed"][1] == 10
    saved = json.loads((settings.logs_dir / "scorecard.json").read_text())
    assert saved["summary"]["root_cause_hit"][1] == 3


def test_harness_refuses_unknown_schema_version(tmp_path):
    p = tmp_path / "trace-x.jsonl"
    p.write_text(json.dumps({"schema_version": 99, "event": "run_start"}) + "\n")
    with pytest.raises(TraceError, match="schema_version"):
        read_trace(p)


def test_agent_side_code_never_references_ground_truth():
    banned = re.compile(r"ground_truth|scorecard\.harness|from app\.scorecard")
    files = [f for target in AGENT_SIDE for f in ([ROOT / target] if target.endswith(".py")
                                                  else (ROOT / target).glob("**/*.py"))]
    assert len(files) > 15
    for f in files:
        assert not banned.search(f.read_text(encoding="utf-8")), f"{f} references ground truth"
