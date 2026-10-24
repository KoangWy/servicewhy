import { render, screen, waitFor, fireEvent, cleanup } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import App from "./App";

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
