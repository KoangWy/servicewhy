import { render, screen, waitFor, fireEvent, cleanup } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import App from "./App";
import { summariseVerifier } from "./components/VerifierNote";
import type { TraceEvent } from "./types";

const finding = {
  id: "fnd_1", cause_hypothesis: "Section B ran 7 tables per server", confidence: "medium", status: "proposed",
  effect_size: { metric: "order_to_delivery_min", delta: "+4.7 min", relative: "+23%", evidence_id: "evd_1" },
  uncertainty: "u", recommended_action: "Add one server", library_id: "H_SERVER_LOAD", family: "staffing", run_id: "r1",
  evidence: [{ evidence_id: "evd_1", source: "s", query: "WITH ...", metric: "order_to_delivery_min", contrast: "c",
               group: "7", value: 25.2, baseline: 20.4, n: 31, n_baseline: 45, supports: true }],
};
const routes: Record<string, unknown> = {
  "/api/health": { status: "ok", zetaris: "sample", model: "sample-replay", sample_mode: true, sample_questions: ["Why?"] },
  "/api/reports": [{ report_id: "rep-1" }],
  "/api/reports/rep-1": { report_id: "rep-1", period: { start: "2026-09-28", end: "2026-10-04" }, summary: "Week summary [evd_1].",
    findings: [finding], revenue_split: null, not_causes: [], insufficient: [],
    provenance: { data: "synthetic", channel: "c", model: "m", runs: [] } },
  "/api/findings/fnd_1": finding,
  "/api/findings/fnd_1/approve": { ...finding, status: "approved" },
  "/api/traces/r1": { run_id: "r1", events: [
    { event: "block", agent_name: "Verifier", action: "block_claim", input_summary: "", output_summary: "V2: n=6 < 15", retry_count: 0, status: "blocked", verdict: "block", timestamp: "" },
    { event: "retry", agent_name: "Orchestrator", action: "widen_and_retry", input_summary: "", output_summary: "retry 1", retry_count: 1, status: "success", timestamp: "" },
  ] },
};

beforeEach(() => {
  window.location.hash = "";
  vi.stubGlobal("fetch", vi.fn(async (url: string) => ({ ok: true, status: 200, json: async () => routes[url] })));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

test("report screen lists findings with confidence and the synthetic label", async () => {
  render(<App />);
  expect(screen.getByTestId("synthetic-label").textContent).toMatch(/Synthetic data/);
  await waitFor(() => expect(screen.getByText("Section B ran 7 tables per server")).toBeTruthy());
  expect(screen.getByText("medium confidence")).toBeTruthy();
});

test("finding detail shows evidence and approve flips status", async () => {
  window.location.hash = "/finding/fnd_1";
  render(<App />);
  await waitFor(() => expect(screen.getByText("Add one server")).toBeTruthy());
  expect(screen.getByTestId("synthetic-label")).toBeTruthy();
  fireEvent.click(screen.getByText("Approve"));
  await waitFor(() => expect(screen.getByText("approved")).toBeTruthy());
});

test("trace panel shows blocks and the retry chain", async () => {
  window.location.hash = "/trace/r1";
  render(<App />);
  await waitFor(() => expect(screen.getByText("V2: n=6 < 15")).toBeTruthy());
  expect(screen.getByText("retry 1", { selector: ".badge" })).toBeTruthy();
  expect(screen.getByTestId("synthetic-label")).toBeTruthy();
});

// Stands in for a route's body to make fetch answer with a non-2xx status.
class Failure {
  constructor(public status: number, public body: unknown) {}
}
const stubFetch = (over: Record<string, unknown> = {}) =>
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    const r = url in over ? over[url] : routes[url];
    return r instanceof Failure
      ? { ok: false, status: r.status, statusText: "error", json: async () => r.body }
      : { ok: true, status: 200, json: async () => r };
  }));
const clickAskWhy = () => fireEvent.click(screen.getByRole("button", { name: "Ask why" }));

test("drill-down in SAMPLE mode says the live stack is needed instead of doing nothing", async () => {
  stubFetch({ "/api/findings/fnd_1/drilldown": new Failure(404, { status: "error", error: { type: "SampleModeMiss", message: "no recorded drill-down for this finding in the sample bundle" } }) });
  window.location.hash = "/finding/fnd_1";
  render(<App />);
  await waitFor(() => expect(screen.getByText("Add one server")).toBeTruthy());
  await waitFor(() => expect((screen.getByLabelText("drill-down question") as HTMLInputElement).disabled).toBe(true));
  clickAskWhy();
  expect(await screen.findByText(/Drill-down needs the live stack; SAMPLE mode replays recorded runs/)).toBeTruthy();
  expect(screen.getByText(/SampleModeMiss: no recorded drill-down/)).toBeTruthy();
});

test("a failing drill-down shows the real error", async () => {
  stubFetch({ "/api/findings/fnd_1/drilldown": new Failure(500, { detail: "boom" }) });
  window.location.hash = "/finding/fnd_1";
  render(<App />);
  await waitFor(() => expect(screen.getByText("Add one server")).toBeTruthy());
  clickAskWhy();
  expect(await screen.findByText("The drill-down failed.")).toBeTruthy();
  expect(screen.getByText("boom")).toBeTruthy();
});

test("a recorded drill-down renders its answer", async () => {
  stubFetch({ "/api/findings/fnd_1/drilldown": { parent_finding: "fnd_1", run: { run_id: "d1", status: "success", question: "q",
    output: { summary: "Drill summary.", answer_type: "answer", findings: [], not_causes: [], insufficient: [], revenue_split: null } } } });
  window.location.hash = "/finding/fnd_1";
  render(<App />);
  await waitFor(() => expect(screen.getByText("Add one server")).toBeTruthy());
  clickAskWhy();
  expect(await screen.findByText("Drill summary.")).toBeTruthy();
});

test("a failed approve shows an inline error and leaves the finding proposed", async () => {
  stubFetch({ "/api/findings/fnd_1/approve": new Failure(500, { detail: "boom" }) });
  window.location.hash = "/finding/fnd_1";
  render(<App />);
  await waitFor(() => expect(screen.getByText("Add one server")).toBeTruthy());
  fireEvent.click(screen.getByText("Approve"));
  expect(await screen.findByText("Could not approve this finding: boom")).toBeTruthy();
  expect(screen.getByText("proposed")).toBeTruthy();
  expect((screen.getByText("Approve") as HTMLButtonElement).disabled).toBe(false);
});

test("the trace link stays after a decision even though the response has no run_id", async () => {
  stubFetch({ "/api/findings/fnd_1/approve": { ...finding, status: "approved", run_id: undefined } });
  window.location.hash = "/finding/fnd_1";
  render(<App />);
  await waitFor(() => expect(screen.getByText("Add one server")).toBeTruthy());
  fireEvent.click(screen.getByText("Approve"));
  await waitFor(() => expect(screen.getByText("approved")).toBeTruthy());
  expect(screen.getByText(/Full evidence & trace/).closest("a")?.getAttribute("href")).toBe("#/trace/r1");
});

test("the finding view surfaces the verifier block and the widened retry", async () => {
  window.location.hash = "/finding/fnd_1";
  render(<App />);
  const note = await screen.findByTestId("verifier-note");
  expect(note.textContent).toMatch(/Blocked 1 hypothesis, then retried on a wider window\./);
  expect(note.textContent).toMatch(/V2: n=6 < 15/);
  expect(note.querySelector("a")?.getAttribute("href")).toBe("#/trace/r1");
});

const ev = (e: Partial<TraceEvent>): TraceEvent => ({ timestamp: "", event: "x", agent_name: "Verifier", action: "", input_summary: "", output_summary: "", retry_count: 0, status: "success", ...e });

test("summariseVerifier reads the block, its widened retry and the later verdict", () => {
  const events = [
    ev({ event: "block", action: "block_claim", input_summary: "hyp_1", output_summary: "V2: n=10 < 15; V2: n=6 < 15", verdict: "block" }),
    ev({ event: "retry", agent_name: "Orchestrator", input_summary: "hyp_1", output_summary: "retry 1: at dinner on Sat 03 Oct -> at dinner on Sat 03 Oct, Sat 26 Sep" }),
    ev({ event: "verify", action: "verdict", input_summary: "hyp_1", verdict: "pass" }),
  ];
  expect(summariseVerifier(events)).toEqual([{
    reasons: "V2: n=10 < 15; V2: n=6 < 15", why: "sample too small",
    retry: "at dinner on Sat 03 Oct → at dinner on Sat 03 Oct, Sat 26 Sep", outcome: "pass",
  }]);
  expect(summariseVerifier([ev({ event: "verify", verdict: "block" })])).toEqual([]);
});

test("the footer names Zetaris and Meterless and says SAMPLE mode is a recorded replay", async () => {
  render(<App />);
  expect(await screen.findByText(/Recorded replay: no Zetaris query and no model call/)).toBeTruthy();
  expect(screen.getByText("Powered by Zetaris")).toBeTruthy();
  expect(screen.getByText("Powered by Meterless")).toBeTruthy();
  expect(screen.getByTestId("mode-label").textContent).toMatch(/sample mode/);
});

test("outside SAMPLE mode the footer reports the health check and makes no replay claim", async () => {
  stubFetch({ "/api/health": { status: "ok", zetaris: "up", model: "live-model", sample_mode: false, sample_questions: null } });
  render(<App />);
  expect(await screen.findByText("Zetaris answered the health check. Model: live-model.")).toBeTruthy();
  expect(screen.queryByText(/Recorded replay: no Zetaris query/)).toBeNull();
  expect(screen.getByTestId("mode-label").textContent).toBe("data: up · model: live-model");
});

test("an unreachable /health is shown as an unknown mode, not as live", async () => {
  stubFetch({ "/api/health": new Failure(500, { detail: "down" }) });
  render(<App />);
  expect(await screen.findByText(/did not answer \/health, so nothing is claimed/)).toBeTruthy();
  expect(screen.getByTestId("mode-label").textContent).toMatch(/mode unknown/);
  expect(screen.getByTestId("synthetic-label")).toBeTruthy();
});
