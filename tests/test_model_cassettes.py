import json
from pathlib import Path

import pytest

from app.adapters.model import CassetteMiss, ModelAdapter, ModelBudgetExceeded, cassette_key, extract_json
from app.worldmodel.store import WorldStoreService
from meterless_gate import fake_generator, run

FIXTURES = Path(__file__).parent / "fixtures" / "cassettes"


def test_world_model_gate_runs_green_in_replay_mode_against_fixture_cassette(tmp_path):
    adapter = ModelAdapter("replay", cassette_dir=FIXTURES)
    out = run(adapter.generator("writer"), "r1", tmp_path / "wm.jsonl")
    assert out["cited"] == [out["evidence"]]
    assert WorldStoreService(tmp_path / "wm.jsonl").get(out["finding"])["evidence_ids"] == [out["evidence"]]
    assert out["session"] == adapter.session_id


def test_cassette_miss_is_a_named_hard_failure_never_a_live_call(tmp_path):
    def live(*a, **k):
        raise AssertionError("replay mode must never reach the network")
    adapter = ModelAdapter("replay", cassette_dir=tmp_path, live=live)
    with pytest.raises(CassetteMiss, match="role=planner"):
        adapter.complete("planner", "an unrecorded prompt")


def test_record_masks_secrets_and_replay_returns_the_recording(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "sk-very-secret-123")
    def live(prompt, system_prompt=None, **_):
        return {"text": "answer mentioning sk-very-secret-123", "model": "m"}
    rec = ModelAdapter("record", cassette_dir=tmp_path, live=live)
    rec.complete("writer", "prompt with sk-very-secret-123", "sys")
    files = list(tmp_path.rglob("*.json"))
    assert len(files) == 1 and "sk-very-secret-123" not in files[0].read_text()
    assert files[0].stem == cassette_key("writer", "sys", "prompt with sk-very-secret-123")
    replay = ModelAdapter("replay", cassette_dir=tmp_path)
    assert replay.complete("writer", "prompt with sk-very-secret-123", "sys")["text"] == "answer mentioning …redacted"


def test_record_missing_replays_what_exists_and_records_only_what_is_missing(tmp_path):
    calls = []

    def live(prompt, system_prompt=None, **_):
        calls.append(prompt)
        return {"text": f"live:{prompt}", "model": "m"}

    first = ModelAdapter("record-missing", cassette_dir=tmp_path, live=live)
    assert first.complete("writer", "p1")["text"] == "live:p1"          # missing: live call, stored
    again = ModelAdapter("record-missing", cassette_dir=tmp_path, live=live)
    out = again.complete("writer", "p1")
    assert out["text"] == "live:p1" and out["source"].startswith("cassette:") and calls == ["p1"]  # exists: no call
    assert again.complete("writer", "p2")["text"] == "live:p2" and calls == ["p1", "p2"]
    assert len(list(tmp_path.rglob("*.json"))) == 2
    path = next(tmp_path.rglob("*.json"))
    rec = json.loads(path.read_text(encoding="utf-8"))
    rec["response"]["text"] = "edited"
    path.write_text(json.dumps(rec), encoding="utf-8")
    assert ModelAdapter("record-missing", cassette_dir=tmp_path, live=live).complete(rec["role"], rec["prompt"], rec["system_prompt"] or None)["text"] == "edited"


def test_keys_depend_on_role_and_prompt():
    assert cassette_key("planner", None, "p") != cassette_key("writer", None, "p")
    assert cassette_key("planner", None, "p") != cassette_key("planner", None, "p2")


def test_live_fails_over_to_backup_on_transport_errors():
    import urllib.error
    def primary(*a, **k):
        raise urllib.error.URLError("down")
    def backup(prompt, system_prompt=None, **_):
        return {"text": "from backup", "model": "b"}
    a = ModelAdapter("live", live=primary, backup=backup)
    assert a.complete("writer", "p")["text"] == "from backup"


def test_call_budget_is_bounded():
    a = ModelAdapter("fake", max_calls=1, fake=lambda role, sys, prompt: "{}")
    a.complete("planner", "p")
    with pytest.raises(ModelBudgetExceeded):
        a.complete("planner", "p")


def test_extract_json_from_fenced_output():
    assert extract_json('Sure:\n```json\n{"verdict": "pass", "reason": "ok"}\n```') == {"verdict": "pass", "reason": "ok"}
