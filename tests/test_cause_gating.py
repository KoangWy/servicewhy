"""A published cause never says more than the evidence that supports it (Writer._causes + hypothesis library).

The Verifier's model judgment may pass a compound claim on partial support because the Writer narrows the finding
to what its supporting items measure; these tests pin that guarantee.
"""
from app.agent.planner import load_library
from app.agent.writer import _causes, fill

LIB = load_library()
FOCUS = {"focus": "on Sat 03 Oct"}


def cause(hid: str, supported: set[str], found: dict[str, str] | None = None) -> str:
    return fill(_causes(LIB[hid]["cause"], supported), {**FOCUS, **(found or {})}, "FALLBACK")


def test_list_when_needs_every_item():
    templates = [{"when": ["a", "b"], "text": "both"}, {"when": "a", "text": "only a"}, "plain"]
    assert _causes(templates, {"a"}) == ["only a", "plain"]
    assert _causes(templates, {"a", "b"}) == ["both", "only a", "plain"]
    assert _causes([{"text": "no guard"}], {"a"}) == []  # a dict template without `when` is never used


def test_server_load_names_only_the_slowdowns_that_were_measured():
    d, g = "order_to_delivery_min@cross_section", "greet_min@cross_section"
    found = {"section": "B", "tables_per_server": "7"}
    both = cause("H_SERVER_LOAD", {d, g}, found)
    assert "order-to-delivery and greeting slowed" in both
    delivery_only = cause("H_SERVER_LOAD", {d}, found)
    assert "order-to-delivery slowed" in delivery_only and "greeting" not in delivery_only
    greeting_only = cause("H_SERVER_LOAD", {g}, found)
    assert "greeting slowed" in greeting_only and "order-to-delivery" not in greeting_only


def test_server_load_dose_response_alone_does_not_blame_a_section_or_greeting():
    text = cause("H_SERVER_LOAD", {"order_to_delivery_min@dose_response"}, {"tables_per_server": "7"})
    assert text == "Parties served at 7 tables per server waited longer for food on Sat 03 Oct"


def test_server_load_section_evidence_alone_never_falls_back_to_the_compound_claim():
    assert "slowed greeting and delivery" not in cause("H_SERVER_LOAD", {"order_to_delivery_min@cross_section"},
                                                       {"section": "B"})
    assert cause("H_SERVER_LOAD", {"greet_min@cross_section"}, {"section": "B"}) == \
        "Greeting was slower in section B on Sat 03 Oct"


def test_spend_names_comps_only_when_comp_rate_supports_it():
    spend = "net_revenue_per_party@period_vs_baseline"
    assert cause("H_SPEND", {spend}) == "Revenue per party fell on Sat 03 Oct"
    both = cause("H_SPEND", {spend, "comp_rate@period_vs_baseline"})
    assert "guests spent less and more tickets were comped" in both
    assert cause("H_SPEND", {"comp_rate@period_vs_baseline"}) == "More tickets were comped on Sat 03 Oct than in the baseline"
    assert cause("H_SPEND", {spend}, {"section": "C"}) == "Revenue per party fell on Sat 03 Oct, concentrated in section C"


def test_demand_cause_does_not_assert_an_unmeasured_reason():
    text = cause("H_DEMAND", set())
    assert text.startswith("Fewer parties came in on Sat 03 Oct than the baseline")
    assert "demand-side" not in text and "does not show why" in text
