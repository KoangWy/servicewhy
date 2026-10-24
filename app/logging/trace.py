"""Run trace: one JSONL file per investigation (`logs/trace-<run_id>.jsonl`) plus readable stdout lines.

If it is not in the trace, it did not happen (project rule 4). The event set is closed and versioned;
the scorecard harness refuses traces with an unknown `schema_version`.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

from app.adapters.model import mask_secrets

SCHEMA_VERSION = 1
EVENTS = ("run_start", "plan", "query", "evidence", "verify", "block", "retry", "answer", "run_end",
          "wm_mutation")


class TraceError(ValueError):
    pass


class Trace:
    def __init__(self, run_id: str, logs_dir: str | Path, *, echo: bool = True):
        self.run_id = run_id
        self.path = Path(logs_dir) / f"trace-{run_id}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8", newline="\n")
        self.echo, self.events = echo, []

    def emit(self, event: str, agent_name: str, action: str, *, input_summary: str = "", output_summary: str = "",
             query: str | None = None, rows_used: int | None = None, verdict: str | None = None,
             retry_count: int = 0, status: str = "success", data: dict[str, Any] | None = None) -> dict[str, Any]:
        if event not in EVENTS:
            raise TraceError(f"unknown trace event {event!r}")
        rec = {"schema_version": SCHEMA_VERSION, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "run_id": self.run_id, "event": event, "agent_name": agent_name, "action": action,
               "input_summary": mask_secrets(input_summary), "output_summary": mask_secrets(output_summary),
               "retry_count": retry_count, "status": status}
        if query is not None:
            rec["query"] = mask_secrets(query)
        if rows_used is not None:
            rec["rows_used"] = rows_used
        if verdict is not None:
            rec["verdict"] = verdict
        if data:
            rec["data"] = json.loads(mask_secrets(json.dumps(data, default=str)))
        with self.path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")
        self.events.append(rec)
        if self.echo and event != "wm_mutation":
            level = "WARN" if event == "block" or status != "success" else "INFO"
            text = output_summary or input_summary
            line = f"[{level}] run_id={self.run_id} {agent_name} {action}: {text[:160]}"
            try:
                print(line, file=sys.stdout, flush=True)
            except UnicodeEncodeError:  # legacy Windows consoles
                print(line.encode("ascii", "replace").decode(), file=sys.stdout, flush=True)
        return rec


def read_trace(path: str | Path) -> list[dict[str, Any]]:
    events = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    for e in events:
        if e.get("schema_version") != SCHEMA_VERSION:
            raise TraceError(f"unsupported trace schema_version {e.get('schema_version')!r} in {path}")
        if e.get("event") not in EVENTS:
            raise TraceError(f"unknown trace event {e.get('event')!r} in {path}")
    return events
