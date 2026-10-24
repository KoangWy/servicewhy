"""ModelAdapter: single seam for model calls. Meterless engines receive this as the injected generator."""
from __future__ import annotations

import json
import os
import urllib.request
import uuid
from typing import Any, Callable

Generator = Callable[..., dict[str, Any]]


def make_generator(*, session_id: str | None = None, timeout: float = 60.0) -> Generator:
    """OpenAI-compatible chat generator. Config from MODEL_API_KEY / MODEL_BASE_URL / MODEL_ID."""
    key, base, model = os.environ["MODEL_API_KEY"], os.environ["MODEL_BASE_URL"].rstrip("/"), os.environ["MODEL_ID"]
    session = session_id or str(uuid.uuid4())

    def generator(prompt: str, attachments=None, system_prompt: str | None = None,
                  on_stream=None, abort_signal=None) -> dict[str, Any]:
        messages = ([{"role": "system", "content": system_prompt}] if system_prompt else [])
        messages.append({"role": "user", "content": prompt})
        req = urllib.request.Request(
            f"{base}/chat/completions",
            json.dumps({"model": model, "messages": messages}).encode(),
            {"Content-Type": "application/json", "Authorization": f"Bearer {key}",
             "x-opencode-session": session,
             # Cloudflare in front of the endpoint rejects urllib's default UA (error 1010)
             "User-Agent": "servicewhy/0.1"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as res:
            body = json.load(res)
        return {"text": body["choices"][0]["message"]["content"], "usage": body.get("usage"), "session": session}

    return generator
