"""SAMPLE_MODE: serve a recorded run through the same endpoints, with zero network and zero services.

The bundle (`logs/examples/sample_bundle.json`) is produced by `scripts/seed_sample.py` from real
runs; traces are replayed from `logs/examples/trace-<run_id>.jsonl`. `recorded_with` says which data
channel and model produced it, so a keyless recording is never mistaken for a FULL-mode one.
"""
from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path
from typing import Any

BUNDLE = "sample_bundle.json"


def normalise(question: str) -> str:
    return re.sub(r"[^a-z0-9% ]+", "", question.lower()).strip()


class SampleMiss(LookupError):
    pass


class SampleStore:
    def __init__(self, sample_dir: Path):
        self.dir = Path(sample_dir)
        path = self.dir / BUNDLE
        self.bundle = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"runs": []}
        self.by_question = {normalise(r["question"]): r for r in self.bundle["runs"]}

    @property
    def available(self) -> bool:
        return bool(self.bundle["runs"])

    @property
    def questions(self) -> list[str]:
        return [r["question"] for r in self.bundle["runs"]]

    def trace_path(self, run_id: str) -> Path:
        return self.dir / f"trace-{run_id}.jsonl"

    def _mark(self, response: dict[str, Any]) -> dict[str, Any]:
        out = copy.deepcopy(response)
        if out.get("output"):
            out["output"].setdefault("mode", {})["sample_mode"] = True
            out["output"]["mode"]["recorded_with"] = self.bundle.get("recorded_with")
        out["log_file"] = f"logs/examples/trace-{out['run_id']}.jsonl"
        return out

    def run(self, question: str, *, echo: bool = True) -> dict[str, Any]:
        rec = self.by_question.get(normalise(question))
        if rec is None:
            raise SampleMiss(question)
        resp = self._mark(rec["response"])
        if echo:  # replay the recorded trace on stdout, like a live run
            path = self.trace_path(resp["run_id"])
            if path.exists():
                for line in path.read_text(encoding="utf-8").splitlines():
                    e = json.loads(line)
                    if e["event"] != "wm_mutation":
                        text = f"[REPLAY] run_id={e['run_id']} {e['agent_name']} {e['action']}: " \
                               f"{(e.get('output_summary') or e.get('input_summary') or '')[:160]}"
                        print(text.encode("ascii", "replace").decode(), file=sys.stdout, flush=True)
        return resp

    def report(self) -> dict[str, Any] | None:
        rep = self.bundle.get("report")
        return copy.deepcopy(rep) if rep else None

    def drilldown(self, finding_id: str) -> dict[str, Any] | None:
        rec = (self.bundle.get("drilldowns") or {}).get(finding_id)
        return self._mark(rec) if rec else None

    def responses(self) -> list[dict[str, Any]]:
        return [self._mark(r["response"]) for r in self.bundle["runs"]]
