# Glossary

Domain language for ServiceWhy. One term, one meaning; if a term is missing or wrong, fix it here
first. No implementation detail in this file.

| Term | Meaning |
|---|---|
| **ServiceWhy** | The product: an agent that explains why a restaurant's service or revenue changed. |
| **Investigation** | One run of the question loop (question → hypotheses → evidence → verification → answer). Has a stable id used across trace, report and UI. |
| **Question** | What the manager asks in one sentence; the input of an investigation. |
| **Hypothesis** | A candidate cause the agent considers for a question; it is supported, rejected or blocked during verification — never assumed. |
| **Evidence Item** | One unit of support for a hypothesis: which source, which query, which measured value, on how many cases. |
| **Finding** | The output unit: a supported cause with its evidence, confidence, uncertainty and a recommended action, subject to approval. |
| **Confidence** | How strongly the evidence supports a finding: high, medium or low — always backed by effect sizes, never a bare percentage. |
| **Contrast** | The comparison that makes a causal claim legitimate: before/after, cross-section, or dose-response across staffing buckets. |
| **Verifier block** | The act of rejecting a claim the data does not support; the investigation is sent back or answered with "insufficient evidence". |
| **Insufficient evidence** | The honest terminal answer when no hypothesis survives verification within the retry budget. |
| **Period** | The reporting window of the report: one week. |
| **Service segment** | Lunch or dinner of a business day; the finest normal slicing for comparisons. |
| **Baseline** | The comparison values for a period: the previous period and the same weekday across the last four weeks. |
| **Incident** | A cause injected into the simulated restaurant on purpose (e.g. a section running short-staffed at peak). |
| **Decoy** | An injected external cause (e.g. a rainy day cutting walk-ins) that tempts the agent toward a non-service explanation. |
| **Ground truth** | The non-public record of everything injected; used only to score the agent, never readable by it. |
| **Scorecard** | The published measurement of the agent against ground truth across a fixed question set. |
| **Drill-down** | Running an investigation that starts from one finding of a report. |
| **Approval** | The manager's explicit accept or reject of a finding's recommended action. |
| **Staffing condition** | The allowed way to name a cause: a role, section and time window — never an individual person. |
| **Trace** | The append-only record of everything an investigation did, in order, including blocks and retries. |
| **Sample mode** | Serving a previously recorded run so the system demonstrates full behaviour with no credentials or network. |
| **Model adapter** | The single seam through which every model call is made, provider-agnostic. |
| **Data access adapter** | The single seam through which every data query is made — federated SQL across both stores. |
| **World model** | The shared, provenance-carrying state of hypotheses and evidence that all agent roles read and write. |
