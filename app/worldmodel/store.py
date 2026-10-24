"""WorldStoreService: canonical entity store rebuilt from an append-only JSONL log.

Meterless World Model engine (reference architecture, implemented in-repo): one write path,
content-hash stable ids, every mutation appended to the log, canon derived by replay.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable, Iterator

SCHEMA_VERSION = 1


def stable_id(kind: str, *parts: str) -> str:
    """Content-hash id: independent agents derive the same id for the same content."""
    digest = hashlib.sha256("\x1f".join(p.strip().lower() for p in parts).encode()).hexdigest()
    return f"{kind}_{digest[:12]}"


class WorldStoreService:
    def __init__(self, log_path: str | Path, *, on_mutation: Callable[[dict[str, Any]], None] | None = None):
        self.log_path = Path(log_path)
        self.on_mutation = on_mutation
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._entities: dict[str, dict[str, Any]] = {}
        self._replay()

    def _replay(self) -> None:
        if not self.log_path.exists():
            return
        for line in self.log_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue  # torn final line from a crashed run: ignore, ingest re-applies it
            self._apply(rec)

    def _apply(self, rec: dict[str, Any]) -> None:
        if rec["op"] == "put":
            current = self._entities.get(rec["id"], {})
            self._entities[rec["id"]] = {**current, **rec["data"], "id": rec["id"], "kind": rec["kind"]}

    def put(self, kind: str, entity_id: str, data: dict[str, Any], *, agent_id: str, run_id: str) -> bool:
        """Upsert. Returns False (and writes nothing) when the content is unchanged: idempotent."""
        merged = {**self._entities.get(entity_id, {}), **data, "id": entity_id, "kind": kind}
        if self._entities.get(entity_id) == merged:
            return False
        rec = {"v": SCHEMA_VERSION, "ts": time.time(), "op": "put", "kind": kind, "id": entity_id,
               "data": data, "agent_id": agent_id, "run_id": run_id}
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, sort_keys=True, default=str) + "\n")
            fh.flush()
        self._apply(rec)
        if self.on_mutation:
            self.on_mutation(rec)
        return True

    def get(self, entity_id: str) -> dict[str, Any] | None:
        return self._entities.get(entity_id)

    def query(self, kind: str, **where: Any) -> Iterator[dict[str, Any]]:
        for e in self._entities.values():
            if e["kind"] == kind and all(e.get(k) == v for k, v in where.items()):
                yield e
