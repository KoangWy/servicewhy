"""DataAccessAdapter over the Zetaris local bundle (REST first; JDBC stays a config-switchable fallback).

Verified flow (2026-10-24, local bundle): POST {login}/auth/login -> idToken + orgId, then
POST {rest}/sql-editor/sqls/run with Bearer idToken, X-Org-ID, X-Request-ID (uuid).
One statement per call, no trailing semicolon, all filestore columns come back as strings.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
import uuid
from typing import Any, Callable

Transport = Callable[[str, dict | None, dict], dict]

_READ_ONLY = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)


class ZetarisError(RuntimeError):
    pass


def _http(url: str, body: dict | None, headers: dict) -> dict:
    req = urllib.request.Request(url, json.dumps(body).encode() if body is not None else None,
                                 {"Content-Type": "application/json", "User-Agent": "servicewhy/0.1", **headers})
    try:
        with urllib.request.urlopen(req, timeout=600) as res:
            return json.load(res)
    except urllib.error.HTTPError as e:
        raise ZetarisError(f"HTTP {e.code} from {url}: {e.read()[:300].decode(errors='replace')}") from e


class DataAccessAdapter:
    dialect = "spark"
    channel = "Zetaris federated SQL (REST)"

    def __init__(self, *, rest_url: str, login_url: str, user: str, password: str,
                 transport: Transport = _http):
        self.rest_url, self.login_url = rest_url.rstrip("/"), login_url.rstrip("/")
        self._user, self._password, self._transport = user, password, transport
        self._token: str | None = None
        self._org: str | None = None

    @classmethod
    def from_env(cls) -> "DataAccessAdapter":
        return cls(rest_url=os.environ.get("ZETARIS_REST_URL", "http://localhost:8888/api/v1.0"),
                   login_url=os.environ.get("ZETARIS_LOGIN_URL", "http://localhost:3000/api"),
                   user=os.environ.get("ZETARIS_USER", "admin@zetaris.com"),
                   password=os.environ["ZETARIS_PASSWORD"])

    def _login(self) -> None:
        res = self._transport(f"{self.login_url}/auth/login", {"username": self._user, "password": self._password}, {})
        if "idToken" not in res or "orgId" not in res:
            raise ZetarisError(f"login failed: {res.get('msg', 'no token in response')}")
        self._token, self._org = res["idToken"], str(res["orgId"])

    def _run(self, sql: str, limit: int) -> dict:
        for attempt in (0, 1):
            if self._token is None:
                self._login()
            headers = {"Authorization": f"Bearer {self._token}", "X-Org-ID": self._org,
                       "X-Request-ID": str(uuid.uuid4())}
            try:
                return self._transport(f"{self.rest_url}/sql-editor/sqls/run",
                                       {"queryId": str(uuid.uuid4()), "sql": sql, "source": "SqlEditor",
                                        "limit": limit}, headers)
            except ZetarisError as e:
                if attempt == 0 and "HTTP 401" in str(e):
                    self._token = None  # expired token: log in once more
                    continue
                raise
        raise AssertionError("unreachable")

    @staticmethod
    def _one_statement(sql: str) -> str:
        sql = sql.strip().rstrip(";").strip()
        if ";" in sql:
            raise ZetarisError("one SQL statement per call")
        return sql

    def query(self, sql: str, *, limit: int) -> list[dict[str, Any]]:
        """Read-only entry point for the Investigator. Row limit is explicit: Zetaris limits are client-side."""
        sql = self._one_statement(sql)
        if not _READ_ONLY.match(sql):
            raise ZetarisError("query() accepts SELECT/WITH only; use execute() for management statements")
        res = self._run(sql, limit)
        return [dict(zip(res["headers"], row)) for row in res["data"]]

    def execute(self, sql: str) -> list[dict[str, Any]]:
        """Management statements (CREATE DATASOURCE, REGISTER ..., SHOW ...). Used by init scripts only."""
        res = self._run(self._one_statement(sql), 1000)
        return [dict(zip(res.get("headers", []), row)) for row in res.get("data", [])]
