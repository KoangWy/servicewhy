"""GET /activity: what the agent is doing right now (in-memory, bounded; see app/activity.py)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/activity")
def activity(request: Request) -> dict[str, Any]:
    return request.app.state.svc.activity.snapshot()
