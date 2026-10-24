"""IngestPipelineService: validate -> derive stable id -> idempotent write, with provenance."""
from __future__ import annotations

from typing import Any

from .store import WorldStoreService, stable_id


HYPOTHESIS_STATUSES = ("proposed", "supported", "rejected", "blocked")


class IngestError(ValueError):
    pass


class IngestPipelineService:
    def __init__(self, store: WorldStoreService, *, run_id: str):
        self.store = store
        self.run_id = run_id

    def ingest_hypothesis(self, statement: str, *, agent_id: str, **extra: Any) -> str:
        if not statement.strip():
            raise IngestError("hypothesis statement is empty")
        hid = stable_id("hyp", statement)
        self.store.put("hypothesis", hid, {"statement": statement, "status": "proposed", **extra},
                       agent_id=agent_id, run_id=self.run_id)
        return hid

    def set_status(self, hypothesis_id: str, status: str, *, reason: str, agent_id: str) -> None:
        if status not in HYPOTHESIS_STATUSES:
            raise IngestError(f"unknown hypothesis status {status!r}")
        if self.store.get(hypothesis_id) is None:
            raise IngestError(f"unknown hypothesis {hypothesis_id}")
        self.store.put("hypothesis", hypothesis_id, {"status": status, "status_reason": reason},
                       agent_id=agent_id, run_id=self.run_id)

    def ingest_evidence(self, hypothesis_id: str, *, source: str, query: str, metric: str,
                        value: Any, contrast: str, n: int, agent_id: str, **extra: Any) -> str:
        if self.store.get(hypothesis_id) is None:
            raise IngestError(f"unknown hypothesis {hypothesis_id}")
        eid = stable_id("evd", hypothesis_id, source, query, metric)
        self.store.put("evidence", eid, {"hypothesis_id": hypothesis_id, "source": source, "query": query,
                                         "metric": metric, "value": value, "contrast": contrast, "n": n,
                                         "produced_by": agent_id, **extra}, agent_id=agent_id, run_id=self.run_id)
        return eid

    def ingest_finding(self, hypothesis_id: str, *, text: str, evidence_ids: list[str], agent_id: str,
                       **extra: Any) -> str:
        missing = [e for e in evidence_ids if (self.store.get(e) or {}).get("kind") != "evidence"]
        if missing:
            raise IngestError(f"finding cites unknown evidence: {missing}")
        fid = stable_id("fnd", hypothesis_id, text)
        self.store.put("finding", fid, {"hypothesis_id": hypothesis_id, "text": text,
                                        "evidence_ids": sorted(evidence_ids), **extra},
                       agent_id=agent_id, run_id=self.run_id)
        return fid
