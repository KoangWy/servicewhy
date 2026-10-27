"""What the Writer is given and what it prints: the checked-result sentence reaches the model, and the section a
question named is not lost when the evidence found no section."""
from app.adapters.fake_model import respond
from app.adapters.model import ModelAdapter
from app.agent.planner import load_library
from app.agent.writer import Writer
from app.orchestrator import Orchestrator
from app.runtime import data_adapter

LIB = load_library()


class _Ingest:
    def ingest_finding(self, hypothesis_id, *, text, evidence_ids, agent_id, **extra):
        return "fnd_test"


class _Trace:
    def emit(self, *args, **kwargs):
        pass


def _dose_response_only() -> tuple[dict, dict, list[dict]]:
    ev = {"id": "evd_1", "metric": "order_to_delivery_min", "contrast_type": "dose_response",
          "spec": {"dim": "tables_per_server"}, "group": "7", "supports": True, "descriptive": False,
          "value": 25.2, "baseline": 20.4, "n": 17, "n_baseline": 45, "rel": 0.24, "delta": 4.8,
          "source": "s", "query": "q", "contrast": "c"}
    verdict = {"passed_ids": ["evd_1"], "supporting_ids": ["evd_1"], "confidence": "low"}
    return {**LIB["H_SERVER_LOAD"], "wm_id": "hyp_1"}, verdict, [ev]


def test_a_named_section_survives_when_the_evidence_found_no_section():
    hyp, verdict, evidence = _dose_response_only()
    writer = Writer(None, _Ingest(), None, _Trace())
    f = writer.finding(hyp, verdict, evidence, "at dinner in section B on Fri 02 Oct", None,
                       focus_plain="at dinner on Fri 02 Oct", section="B")
    assert f["recommended_action"].startswith("Add one server to section B at dinner on Fri 02 Oct")
    assert "section B" not in f["cause_hypothesis"]  # the dose-response contrast is not filtered to a section
    assert f["cause_hypothesis"] == "Parties served at 7 tables per server waited longer for food at dinner on Fri 02 Oct"


def test_without_a_named_section_the_action_does_not_invent_one():
    hyp, verdict, evidence = _dose_response_only()
    f = Writer(None, _Ingest(), None, _Trace()).finding(hyp, verdict, evidence, "at dinner on Fri 02 Oct", None)
    assert f["recommended_action"].startswith("Add one server to the affected section at dinner")
    assert "section the affected" not in f["recommended_action"] + f["uncertainty"]


def test_the_checked_result_sentence_reaches_the_writer_prompt(client, settings):
    prompts: list[str] = []

    def spy(role, system, prompt):
        if role == "writer":
            prompts.append(prompt)
        return respond(role, system, prompt)

    client.app.state.svc.orchestrator = Orchestrator(settings, lambda: data_adapter(settings),
                                                     lambda s: ModelAdapter("fake", session_id=s, fake=spy))
    out = client.post("/run", json={"run_id": "writer-input", "input": {"query": "Is the kitchen slow on Saturdays?"}}).json()
    assert out["output"]["not_causes"]
    assert prompts and "The kitchen was not slow" in prompts[0] and '"negative"' in prompts[0]
    # figures handed to the model are rounded like finding evidence (no 10-decimal floats)
    assert not any(len(tok.split(".")[-1]) > 4 for tok in prompts[0].replace(",", " ").split() if tok.replace(".", "").isdigit())


def test_the_revenue_split_is_in_the_answer_even_when_the_model_text_omits_it(client, settings):
    def model_that_forgets_the_split(role, system, prompt):
        if role == "writer":
            return '{"answer": "Revenue per party fell."}'
        return respond(role, system, prompt)

    client.app.state.svc.orchestrator = Orchestrator(
        settings, lambda: data_adapter(settings),
        lambda s: ModelAdapter("fake", session_id=s, fake=model_that_forgets_the_split))
    out = client.post("/run", json={"run_id": "split-forced", "input": {"query": "Why did Saturday dinner revenue drop 18%?"}}).json()["output"]
    assert out["revenue_split"]
    assert out["summary"].startswith("Revenue per party fell.")
    assert "fewer parties explain" in out["summary"] and out["summary"].count("fewer parties explain") == 1


def test_the_split_is_not_repeated_when_the_deterministic_template_already_has_it(demo):
    assert demo["output"]["summary"].count("fewer parties explain") == 1


def test_number_guard_accepts_a_long_decimal_that_the_evidence_states_verbatim():
    payload = {"findings": [{"cause_hypothesis": "Resets took longer", "value": 5.401}]}
    assert Writer.unsupported_numbers("Resets took 5.401 min.", "Why?", payload) == []
