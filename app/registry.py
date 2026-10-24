"""In-process registry of runs, reports and findings, plus the append-only approval log.

Findings carry the SPEC §6 status: proposed -> approved | rejected. Every decision is appended to
`logs/approvals.jsonl` with timestamp and role before the status flips.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

DECISIONS = {"approve": "approved", "reject": "rejected"}


class Registry:
    def __init__(self, logs_dir: Path):
        self.logs_dir = Path(logs_dir)
        self.runs: dict[str, dict] = {}
        self.reports: dict[str, dict] = {}
        self.findings: dict[str, dict] = {}
        self.finding_run: dict[str, str] = {}
        self._lock = threading.Lock()

    def add_run(self, response: dict[str, Any]) -> None:
        with self._lock:
            self.runs[response["run_id"]] = response
            for f in (response.get("output") or {}).get("findings", []):
                self.findings[f["id"]] = f
                self.finding_run[f["id"]] = response["run_id"]

    def add_report(self, report: dict[str, Any]) -> None:
        with self._lock:
            self.reports[report["report_id"]] = report
            for f in report.get("findings", []):
                self.findings.setdefault(f["id"], f)
                self.finding_run.setdefault(f["id"], f.get("run_id", ""))

    def decide(self, finding_id: str, decision: str, *, role: str, note: str | None) -> dict[str, Any]:
        with self._lock:
            f = self.findings[finding_id]
            rec = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "finding_id": finding_id,
                   "decision": DECISIONS[decision], "role": role, "note": note,
                   "recommended_action": f.get("recommended_action")}
            self.logs_dir.mkdir(parents=True, exist_ok=True)
            with (self.logs_dir / "approvals.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec) + "\n")
            f["status"] = rec["decision"]
            f.setdefault("approvals", []).append(rec)
            return f
