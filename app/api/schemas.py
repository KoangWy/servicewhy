"""Request contracts (Technical Execution Guide JSON shapes). Responses are the documented dicts."""
from __future__ import annotations

from pydantic import BaseModel, Field


class RunInput(BaseModel):
    query: str = Field(..., min_length=3, max_length=500, examples=["Why did Saturday dinner revenue drop 18%?"])
    context: str | None = Field(None, max_length=500, description="Earlier question this one follows up on")


class RunOptions(BaseModel):
    sample_mode: bool = False


class RunRequest(BaseModel):
    run_id: str | None = Field(None, max_length=200)  # shape is checked in the route: a file name is built from it
    input: RunInput
    options: RunOptions = RunOptions()


class Period(BaseModel):
    start: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    end: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")


class ReportRequest(BaseModel):
    period: Period | None = None


class DrilldownRequest(BaseModel):
    question: str | None = Field(None, max_length=500)


class DecisionRequest(BaseModel):
    role: str = Field("manager", max_length=40)
    note: str | None = Field(None, max_length=500)
