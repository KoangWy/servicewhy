"""Manager-facing wording: no repeated section, no "section the affected section", and a number guard that
does not reject the dates and times the evidence itself contains."""
from app.agent.scope import resolve
from app.agent.writer import Writer

Q4 = "Why are greeting times long in section B on Friday nights?"


def texts(finding: dict) -> list[str]:
    return [finding["cause_hypothesis"], finding["recommended_action"], finding["uncertainty"]]


def test_a_named_section_is_not_repeated_in_a_finding(client):
    out = client.post("/run", json={"run_id": "text-q4", "input": {"query": Q4}}).json()["output"]
    assert out["findings"]
    for f in out["findings"]:
        for text in texts(f):
            assert text.lower().count("section b") <= 1, text
    assert out["summary"].lower().count("in section b") <= 1, out["summary"]


def test_no_text_says_section_the_affected_section(demo, client):
    out = demo["output"]
    assert out["findings"]
    for f in out["findings"]:
        assert not any("section the affected section" in t for t in texts(f)), texts(f)
    assert "section the affected section" not in out["summary"]
    report = client.post("/reports", json={}).json()
    assert "section the affected section" not in str(report)


def test_scope_label_without_section_drops_only_the_section():
    scope = resolve({"weekday": "fri", "service": "dinner", "section": "B", "compare_previous": True},
                    "2026-10-04", "2026-08-31", 0)
    assert "in section B" in scope.label
    assert scope.label_without_section == scope.label.replace(" in section B", "")


def test_number_guard_accepts_dates_and_times_the_evidence_contains():
    payload = {"findings": [{"cause_hypothesis": "Resets slowed at dinner 21:00-23:00 on Sat 03 Oct", "value": 25.2}]}
    ok = "Resets slowed at dinner 21:00-23:00 on Sat 03 Oct, 25.2 min."
    assert Writer.unsupported_numbers(ok, "Why?", payload) == []


def test_number_guard_still_rejects_a_figure_the_evidence_does_not_contain():
    payload = {"findings": [{"cause_hypothesis": "Resets slowed on Sat 03 Oct", "value": 25.2}]}
    assert Writer.unsupported_numbers("Resets slowed on Sat 03 Oct by 47.9 min.", "Why?", payload) == ["47.9"]
    assert Writer.unsupported_numbers("Resets slowed on Sat 04 Oct.", "Why?", payload) == ["04"]
