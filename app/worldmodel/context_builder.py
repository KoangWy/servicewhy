"""ContextBuilderService: structured payloads (not pre-rendered strings) with trace metadata."""
from __future__ import annotations

from typing import Any

from .store import WorldStoreService


class ContextBuilderService:
    def __init__(self, store: WorldStoreService):
        self.store = store

    def build(self, *, intent: str, hypothesis_id: str, max_items: int = 20,
              evidence_ids: list[str] | None = None) -> dict[str, Any]:
        """Evidence for one hypothesis, largest samples first; `evidence_ids` narrows it to one attempt."""
        hyp = self.store.get(hypothesis_id)
        if hyp is None:
            raise KeyError(hypothesis_id)
        evidence = [e for e in self.store.query("evidence", hypothesis_id=hypothesis_id)
                    if evidence_ids is None or e["id"] in evidence_ids]
        evidence.sort(key=lambda e: (-int(e.get("n", 0)), e["id"]))
        chosen = evidence[:max_items]
        scope = "" if evidence_ids is None else f" (current attempt: {len(evidence_ids)} ids)"
        return {
            "intent": intent,
            "hypothesis": {k: hyp.get(k) for k in ("id", "statement", "status", "library_id", "family")},
            "evidence": [{**e, "relevance": 1.0 if i == 0 else round(1 / (i + 1), 3)} for i, e in enumerate(chosen)],
            "trace": {
                "strategy": "evidence-by-sample-size",
                "selection_reason": f"{len(chosen)} of {len(evidence)} evidence items for {hypothesis_id}, "
                                    f"ordered by n desc{scope}",
                "truncated": len(evidence) > len(chosen),
            },
        }
