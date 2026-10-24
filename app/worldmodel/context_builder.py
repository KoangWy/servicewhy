"""ContextBuilderService: structured payloads (not pre-rendered strings) with trace metadata."""
from __future__ import annotations

from typing import Any

from .store import WorldStoreService


class ContextBuilderService:
    def __init__(self, store: WorldStoreService):
        self.store = store

    def build(self, *, intent: str, hypothesis_id: str, max_items: int = 20) -> dict[str, Any]:
        hyp = self.store.get(hypothesis_id)
        if hyp is None:
            raise KeyError(hypothesis_id)
        evidence = sorted(self.store.query("evidence", hypothesis_id=hypothesis_id),
                          key=lambda e: (-int(e.get("n", 0)), e["id"]))
        chosen = evidence[:max_items]
        return {
            "intent": intent,
            "hypothesis": {k: hyp[k] for k in ("id", "statement", "status")},
            "evidence": [{**e, "relevance": 1.0 if i == 0 else round(1 / (i + 1), 3)} for i, e in enumerate(chosen)],
            "trace": {
                "strategy": "evidence-by-sample-size",
                "selection_reason": f"{len(chosen)} of {len(evidence)} evidence items for {hypothesis_id}, "
                                    f"ordered by n desc",
                "truncated": len(evidence) > len(chosen),
            },
        }
