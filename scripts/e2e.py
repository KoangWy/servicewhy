"""End-to-end proof: fresh seed -> demo question through POST /run -> trace has every role.

  python scripts/e2e.py          # keyless: local seeded store + cassettes (or the fake model if none yet)
  python scripts/e2e.py --full   # QA machine: loader + Zetaris registration, then the keyed FULL run
  python scripts/e2e.py --record # QA machine: local store + live model; records only the cassettes still missing
                                 # (MODEL_MODE=record-missing), so existing ones, including the planner's, are kept

Exit code 0 only when the run succeeds and the trace holds planner, investigator, verifier and writer
events with at least one federated query and one verifier verdict.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import load_dotenv  # noqa: E402

DEMO = "Why did Saturday dinner revenue drop 18%?"


def main() -> int:
    load_dotenv()
    ap = argparse.ArgumentParser()
    kind = ap.add_mutually_exclusive_group()
    kind.add_argument("--full", action="store_true", help="seed the real stores and run against Zetaris + the model")
    kind.add_argument("--record", action="store_true",
                      help="local store + live model: record the missing cassettes the keyless run replays")
    ap.add_argument("--question", default=DEMO)
    args = ap.parse_args()
    if args.full:
        os.environ["DATA_BACKEND"], os.environ["SAMPLE_MODE"] = "zetaris", "false"
        os.environ.setdefault("MODEL_MODE", "live")
        from app.sim.load import main as seed
        if seed([]) != 0:
            return 1
    else:
        os.environ["DATA_BACKEND"], os.environ["SAMPLE_MODE"] = "local", "false"
        if args.record:
            os.environ["MODEL_MODE"] = "record-missing"
        elif os.environ.get("MODEL_MODE") not in ("replay", "fake"):
            has_cassettes = any((ROOT / "cassettes").rglob("*.json"))
            os.environ["MODEL_MODE"] = "replay" if has_cassettes else "fake"
    print(f"e2e: DATA_BACKEND={os.environ['DATA_BACKEND']} MODEL_MODE={os.environ['MODEL_MODE']}")

    from fastapi.testclient import TestClient
    from app.logging.trace import read_trace
    from app.main import create_app
    from app.config import Settings

    settings = Settings.from_env()
    client = TestClient(create_app(settings))
    assert client.get("/health").json()["status"] == "ok"
    resp = client.post("/run", json={"run_id": "e2e-demo", "input": {"query": args.question}}).json()
    if resp["status"] != "success":
        print("e2e FAILED:", resp.get("error"))
        return 1
    events = read_trace(settings.logs_dir / "trace-e2e-demo.jsonl")
    agents = {e["agent_name"] for e in events}
    checks = {
        "planner events": any(e["event"] == "plan" for e in events),
        "investigator federated queries": any(e["event"] == "query" and e["agent_name"] == "Investigator" for e in events),
        "investigator evidence": any(e["event"] == "evidence" for e in events),
        "verifier verdicts": any(e["event"] in ("verify", "block") and e["agent_name"] == "Verifier" for e in events),
        "writer answer": any(e["event"] == "answer" and e["agent_name"] == "Writer" for e in events),
        "world model mutations": any(e["event"] == "wm_mutation" for e in events),
    }
    for k, ok in checks.items():
        print(f"  [{'ok' if ok else 'FAIL'}] {k}")
    print(f"e2e: {len(events)} trace events from {sorted(agents)}; answer: {resp['output']['summary'][:200]}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
