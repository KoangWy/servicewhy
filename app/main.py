"""FastAPI application: wires settings, backends, registry and sample store into the routes."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.api.settings import router as settings_router
from app.config import Settings, load_dotenv
from app.registry import Registry
from app.sample import SampleStore


DEFAULT_CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"


@dataclass
class Services:
    settings: Settings
    registry: Registry
    sample: SampleStore
    data: Callable[[], Any]
    orchestrator: Any


def create_app(settings: Settings | None = None) -> FastAPI:
    load_dotenv()
    settings = settings or Settings.from_env()
    app = FastAPI(title="ServiceWhy API", version="0.1.0",
                  description="Explains why a (synthetic) restaurant's service or revenue changed, with a verifier "
                              "that blocks unsupported claims. All data is synthetic.")
    sample = SampleStore(settings.sample_dir)
    if settings.sample_mode:
        data, orch = (lambda: None), None
        # SAMPLE mode never touches stores or the model: replayed findings must still be approvable
        registry = Registry(settings.logs_dir)
        for resp in sample.responses():
            registry.add_run(resp)
        rep = sample.report()
        if rep:
            registry.add_report(rep)
    else:
        from app import runtime
        data, orch = (lambda: runtime.data_adapter(settings)), runtime.orchestrator(settings)
        registry = Registry(settings.logs_dir)
    app.state.svc = Services(settings=settings, registry=registry, sample=sample, data=data, orchestrator=orch)
    # An endpoint that accepts a token must not be callable cross-site; the UI reaches the API same-origin via /api
    origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", DEFAULT_CORS_ORIGINS).split(",") if o.strip()]
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])
    app.include_router(router)
    app.include_router(settings_router)
    return app
