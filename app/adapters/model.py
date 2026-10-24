"""ModelAdapter: single seam for model calls. Meterless engines receive this as the injected generator.

Modes (env `MODEL_MODE`):
  live    OpenAI-compatible provider (OpenCode Go), failover to the backup provider (DeepInfra)
  record  live call, response stored as a cassette (secrets masked) — run only on the QA machine
  replay  answer from cassettes keyed by (role, system prompt, prompt); a miss raises CassetteMiss
  fake    deterministic offline responder (tests and keyless development only)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable

Generator = Callable[..., dict[str, Any]]

MODES = ("live", "record", "replay", "fake")
_SECRET_ENV = re.compile(r"(KEY|PASSWORD|TOKEN|SECRET)$")


class CassetteMiss(RuntimeError):
    """Replay mode found no recorded response: a hard failure, never a silent live call."""


class ModelBudgetExceeded(RuntimeError):
    pass


def make_generator(*, session_id: str | None = None, timeout: float = 60.0, prefix: str = "MODEL") -> Generator:
    """OpenAI-compatible chat generator. Config from {prefix}_API_KEY / {prefix}_BASE_URL / {prefix}_ID."""
    key, base = os.environ[f"{prefix}_API_KEY"], os.environ[f"{prefix}_BASE_URL"].rstrip("/")
    model = os.environ[f"{prefix}_ID"]
    session = session_id or str(uuid.uuid4())

    def generator(prompt: str, attachments=None, system_prompt: str | None = None,
                  on_stream=None, abort_signal=None) -> dict[str, Any]:
        messages = ([{"role": "system", "content": system_prompt}] if system_prompt else [])
        messages.append({"role": "user", "content": prompt})
        req = urllib.request.Request(
            f"{base}/chat/completions",
            json.dumps({"model": model, "messages": messages, "temperature": 0}).encode(),
            {"Content-Type": "application/json", "Authorization": f"Bearer {key}",
             "x-opencode-session": session,
             # Cloudflare in front of the endpoint rejects urllib's default UA (error 1010)
             "User-Agent": "servicewhy/0.1"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as res:
            body = json.load(res)
        return {"text": body["choices"][0]["message"]["content"], "usage": body.get("usage"), "session": session,
                "model": model}

    return generator


def cassette_key(role: str, system_prompt: str | None, prompt: str) -> str:
    return hashlib.sha256("\x1f".join((role, system_prompt or "", prompt)).encode()).hexdigest()[:24]


def mask_secrets(text: str, env: dict[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    for k, v in env.items():
        if _SECRET_ENV.search(k) and v and len(v) >= 6:
            text = text.replace(v, "…redacted")
    return text


def extract_json(text: str) -> dict[str, Any]:
    """Models wrap JSON in prose or code fences; take the outermost object."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError(f"no JSON object in model output: {text[:120]!r}")
    return json.loads(text[start:end + 1])


class ModelAdapter:
    def __init__(self, mode: str = "live", *, session_id: str | None = None, cassette_dir: str | Path = "cassettes",
                 max_calls: int = 40, live: Generator | None = None, backup: Generator | None = None,
                 fake: Callable[[str, str | None, str], str] | None = None):
        if mode not in MODES:
            raise ValueError(f"MODEL_MODE must be one of {MODES}, got {mode!r}")
        self.mode, self.session_id = mode, session_id or str(uuid.uuid4())
        self.cassette_dir, self.max_calls, self.calls = Path(cassette_dir), max_calls, 0
        self._live, self._backup, self._fake = live, backup, fake

    @classmethod
    def from_env(cls, *, session_id: str, cassette_dir: str | Path) -> "ModelAdapter":
        return cls(os.environ.get("MODEL_MODE", "live").strip().lower(), session_id=session_id,
                   cassette_dir=cassette_dir, max_calls=int(os.environ.get("MODEL_MAX_CALLS", "40")))

    @property
    def model_id(self) -> str:
        return {"fake": "fake-offline", "replay": "cassette-replay"}.get(self.mode, os.environ.get("MODEL_ID", "?"))

    # ---- providers -------------------------------------------------------------------------------
    def _live_call(self, prompt: str, system_prompt: str | None) -> dict[str, Any]:
        if self._live is None:
            self._live = make_generator(session_id=self.session_id)
        if self._backup is None and os.environ.get("MODEL_BACKUP_API_KEY"):
            self._backup = make_generator(session_id=self.session_id, prefix="MODEL_BACKUP")
        last: Exception | None = None
        for gen in [g for g in (self._live, self._live, self._backup) if g is not None]:
            try:
                return gen(prompt, system_prompt=system_prompt)
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:  # transport only
                last = e
                time.sleep(0.5)
        raise RuntimeError(f"model providers unavailable: {last}")

    def _path(self, role: str, key: str) -> Path:
        return self.cassette_dir / role / f"{key}.json"

    # ---- public ----------------------------------------------------------------------------------
    def complete(self, role: str, prompt: str, system_prompt: str | None = None) -> dict[str, Any]:
        self.calls += 1
        if self.calls > self.max_calls:
            raise ModelBudgetExceeded(f"model call budget of {self.max_calls} per run exhausted")
        key = cassette_key(role, system_prompt, prompt)
        if self.mode == "fake":
            if self._fake is None:
                from app.adapters.fake_model import respond
                self._fake = respond
            return {"text": self._fake(role, system_prompt, prompt), "session": self.session_id, "source": "fake"}
        if self.mode == "replay":
            path = self._path(role, key)
            if not path.exists():
                raise CassetteMiss(f"no cassette for role={role} key={key} in {self.cassette_dir}")
            rec = json.loads(path.read_text(encoding="utf-8"))
            return {"text": rec["response"]["text"], "session": self.session_id, "source": f"cassette:{key}"}
        out = self._live_call(prompt, system_prompt)
        if self.mode == "record":
            path = self._path(role, key)
            path.parent.mkdir(parents=True, exist_ok=True)
            rec = {"role": role, "key": key, "model": out.get("model"), "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "system_prompt": mask_secrets(system_prompt or ""), "prompt": mask_secrets(prompt),
                   "response": {"text": mask_secrets(out["text"])}}
            path.write_text(json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8")
        return {"text": out["text"], "session": self.session_id, "source": self.mode, "usage": out.get("usage")}

    def complete_json(self, role: str, prompt: str, system_prompt: str | None = None) -> tuple[dict[str, Any], dict]:
        out = self.complete(role, prompt, system_prompt)
        return extract_json(out["text"]), out

    def generator(self, role: str) -> Generator:
        """Meterless-style injected generator bound to one role."""
        def gen(prompt: str, attachments=None, system_prompt: str | None = None, on_stream=None, abort_signal=None):
            return self.complete(role, prompt, system_prompt)
        return gen
