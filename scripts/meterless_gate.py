"""Meterless gate: World Model skeleton + generator roundtrip.

  python scripts/meterless_gate.py --fake   # offline, deterministic generator
  python scripts/meterless_gate.py          # live: needs MODEL_API_KEY/MODEL_BASE_URL/MODEL_ID (from .env)
"""
from __future__ import annotations

import json
import os
import re
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.worldmodel.context_builder import ContextBuilderService  # noqa: E402
from app.worldmodel.ingest import IngestPipelineService  # noqa: E402
from app.worldmodel.store import WorldStoreService  # noqa: E402


def load_dotenv(path: Path) -> None:
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip() and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def fake_generator(prompt, attachments=None, system_prompt=None, on_stream=None, abort_signal=None):
    ids = re.findall(r"evd_[0-9a-f]{12}", prompt)
    return {"text": f"Section B tickets rise with tables per server [{ids[0]}].", "session": "fake"}


def run(generator, run_id: str, log_path: Path) -> dict:
    store = WorldStoreService(log_path)
    ingest = IngestPipelineService(store, run_id=run_id)
    hid = ingest.ingest_hypothesis("Complaints rise when servers handle more tables", agent_id="planner")
    eid = ingest.ingest_evidence(hid, source="gate_pg", query="select ...", metric="tickets_per_100_covers",
                                 value=7.4, contrast="tables_per_server 5-6 vs 3-4", n=412, agent_id="investigator")
    ctx = ContextBuilderService(store).build(intent="write_finding", hypothesis_id=hid)
    out = generator(
        "Write ONE sentence finding from this context. Cite evidence ids in square brackets. "
        "Do not invent numbers.\n" + json.dumps(ctx),
        system_prompt="You are the Writer. Use only the supplied evidence.")
    cited = re.findall(r"evd_[0-9a-f]{12}", out["text"])
    fid = ingest.ingest_finding(hid, text=out["text"].strip(), evidence_ids=cited, agent_id="writer")
    return {"hypothesis": hid, "evidence": eid, "finding": fid, "text": out["text"].strip(),
            "cited": cited, "context_trace": ctx["trace"], "session": out.get("session")}


def main() -> int:
    load_dotenv(ROOT / ".env")
    if "--fake" in sys.argv:
        gen = fake_generator
    else:
        from app.adapters.model import make_generator
        gen = make_generator()
    run_id = str(uuid.uuid4())
    result = run(gen, run_id, ROOT / "logs" / f"worldmodel-gate-{run_id[:8]}.jsonl")
    print(json.dumps(result, indent=2))
    return 0 if result["cited"] else 1


if __name__ == "__main__":
    sys.exit(main())
