import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.adapters.zetaris import DataAccessAdapter, ZetarisError


class FakeTransport:
    def __init__(self, fail_first_run=False):
        self.calls, self.fail = [], fail_first_run

    def __call__(self, url, body, headers):
        self.calls.append((url, body, headers))
        if url.endswith("/auth/login"):
            return {"idToken": f"tok{len(self.calls)}", "orgId": 7}
        if self.fail:
            self.fail = False
            raise ZetarisError("HTTP 401 from run: expired")
        return {"headers": ["a", "b"], "data": [["1", "x"], ["2", "y"]]}


def _adapter(t):
    return DataAccessAdapter(rest_url="http://r/api/v1.0", login_url="http://l/api", user="u", password="p", transport=t)


def test_query_returns_dict_rows_and_sends_required_headers():
    t = FakeTransport()
    rows = _adapter(t).query("select a, b from s.t;", limit=5)
    assert rows == [{"a": "1", "b": "x"}, {"a": "2", "b": "y"}]
    _, body, headers = t.calls[-1]
    assert body["sql"] == "select a, b from s.t" and body["limit"] == 5
    assert headers["X-Org-ID"] == "7" and headers["Authorization"].startswith("Bearer ")
    assert len(headers["X-Request-ID"]) == 36


def test_query_rejects_writes_and_multiple_statements():
    a = _adapter(FakeTransport())
    for bad in ("drop table x", "CREATE DATASOURCE d OPTIONS ()", "select 1; select 2"):
        with pytest.raises(ZetarisError):
            a.query(bad, limit=1)


def test_relogin_once_on_401():
    t = FakeTransport(fail_first_run=True)
    assert _adapter(t).query("select 1", limit=1)
    assert sum(u.endswith("/auth/login") for u, *_ in t.calls) == 2


def test_failed_login_is_reported():
    a = _adapter(lambda url, body, h: {"msg": "bad credentials"})
    with pytest.raises(ZetarisError, match="bad credentials"):
        a.query("select 1", limit=1)
